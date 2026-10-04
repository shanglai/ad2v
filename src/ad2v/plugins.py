"""Extractor and framework-pack plug-ins: discovery, opt-in, identity, rules and isolated runs.

ADR-0063 (the API and its compatibility policy), ADR-0064 (discovery, opt-in and trust), ADR-0065
(plug-in identity in the epoch, additive within format v0.5).

- Discovery: entry points in the groups `ad2v.extractors` and `ad2v.frameworks`
  (`importlib.metadata`), plus an internal registry of the built-ins so source checkouts and
  editable installs work without installed metadata.
- Opt-in: only the built-ins are active by default. Others must be named in `ad2v.yaml`
  (`extractors.enabled`) or with `--extractor`. Disabled plug-ins are never imported by
  `extract`/`history`; `ad2v extractors list` reads their metadata without importing them unless
  asked to (`--inspect`).
- Identity: every active plug-in (kind, name, version, api_version, the canonical hash of its own
  rules files, and the hash of the effective rules it ran with) enters the epoch rules under the
  key `plugins`, so it is covered by `rules_hash` and therefore by the epoch id.
- Runs: each extractor writes into its own graph, which the core merges in name order. A
  third-party plug-in that raises or exceeds its timeout is reported and skipped (its output is
  discarded) unless `strict`; the built-ins are part of the core and fail the run.
"""

from __future__ import annotations

import copy
import fnmatch
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from ad2v import ir
from ad2v import rules as rules_mod
from ad2v.api import (
    API_VERSION,
    EXTRACTOR_GROUP,
    FRAMEWORK_GROUP,
    NAME_RE,
    ExtractContext,
    ExtractOutput,
    FileAccessor,
    FrameworkContext,
    PluginError,
    api_compatible,
)
from ad2v.extract.code.base import CodeFacts, Layout
from ad2v.extract.files import SourceFile
from ad2v.manifest import Config

DEFAULT_TIMEOUT_S = 600.0
KINDS = {"extractor": EXTRACTOR_GROUP, "framework": FRAMEWORK_GROUP}
EXTRACTOR_ATTRS = (
    "api_version",
    "name",
    "version",
    "languages",
    "file_patterns",
    "rules_files",
    "node_kinds",
    "edge_kinds",
    "extract",
)
FRAMEWORK_ATTRS = (
    "api_version",
    "name",
    "version",
    "attaches_to",
    "frameworks",
    "file_patterns",
    "rules_files",
    "node_kinds",
    "edge_kinds",
    "post_extract",
)


def _builtin_extractors() -> dict[str, Callable[[], Any]]:
    from ad2v.extract.code.plugin import PythonPlugin

    return {"python": PythonPlugin}


def _builtin_frameworks() -> dict[str, Callable[[], Any]]:
    from ad2v.extract.code.plugin import PythonFrameworksPack

    return {"python-frameworks": PythonFrameworksPack}


BUILTIN_DIST = "ad2v"


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    """A file belongs to a plug-in if its name or its repo-relative path matches a pattern."""
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(path, p) for p in patterns)


# ---------------------------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------------------------


@dataclass
class Discovered:
    kind: str  # extractor | framework
    name: str
    builtin: bool
    dist: str | None = None
    dist_version: str | None = None
    target: str | None = None  # "module:attr" of the entry point
    loader: Callable[[], Any] | None = None
    error: str | None = None  # discovery problem (shadowing a built-in, duplicate name)
    obj: Any | None = None
    load_error: str | None = None

    def load(self) -> Any:
        """Import and instantiate the plug-in, then check it (attributes, name, api_version)."""
        if self.obj is not None:
            return self.obj
        if self.error:
            raise PluginError(f"{self.kind} {self.name!r}: {self.error}")
        try:
            assert self.loader is not None
            target = self.loader()
            obj = target() if callable(target) and isinstance(target, type) else target
            if callable(obj) and not hasattr(obj, "api_version"):
                obj = obj()  # a factory function
        except Exception as e:  # noqa: BLE001 - third-party import failures are reported, not raised
            self.load_error = f"failed to load: {type(e).__name__}: {e}"
            raise PluginError(f"{self.kind} {self.name!r} {self.load_error}") from e
        problem = check_plugin(obj, self.kind, self.name)
        if problem:
            self.load_error = problem
            raise PluginError(f"{self.kind} {self.name!r}: {problem}")
        self.obj = obj
        return obj


def check_plugin(obj: Any, kind: str, expected_name: str | None = None) -> str | None:
    """None if `obj` satisfies the interface for `kind`, else the first problem."""
    attrs = EXTRACTOR_ATTRS if kind == "extractor" else FRAMEWORK_ATTRS
    missing = [a for a in attrs if not hasattr(obj, a)]
    if missing:
        return f"missing attribute(s): {', '.join(missing)}"
    name = getattr(obj, "name", "")
    if not isinstance(name, str) or not NAME_RE.match(name):
        return f"invalid name {name!r} (lowercase letters, digits and '-')"
    if expected_name is not None and name != expected_name:
        return f"entry point name {expected_name!r} differs from the plug-in name {name!r}"
    ok, why = api_compatible(str(obj.api_version))
    if not ok:
        return why
    if not str(obj.version or "").strip():
        return "empty version"
    if kind == "extractor" and not tuple(obj.file_patterns):
        return "an extractor must claim at least one file pattern"
    if kind == "framework" and not tuple(obj.attaches_to):
        return "a framework pack must attach to at least one extractor"
    bad_n = sorted(set(obj.node_kinds) - set(ir.NODE_KINDS))
    bad_e = sorted(set(obj.edge_kinds) - set(ir.EDGE_KINDS))
    if bad_n or bad_e:
        return f"declares unknown kinds: {', '.join(bad_n + bad_e)} (see ad2v.api.NODE_KINDS / EDGE_KINDS)"
    for p in obj.rules_files:
        if not Path(p).is_file():
            return f"rules file not found: {p}"
    return None


def _entry_points(group: str) -> list[metadata.EntryPoint]:
    try:
        return sorted(metadata.entry_points(group=group), key=lambda ep: (ep.name, ep.value))
    except Exception:  # noqa: BLE001 - broken metadata must not break extraction
        return []


def discover() -> list[Discovered]:
    """Every plug-in known to this interpreter, built-ins first, then entry points by name."""
    out: list[Discovered] = []
    builtins = {"extractor": _builtin_extractors(), "framework": _builtin_frameworks()}
    version = _ad2v_version()
    for kind, reg in builtins.items():
        for name, factory in sorted(reg.items()):
            out.append(
                Discovered(
                    kind,
                    name,
                    True,
                    BUILTIN_DIST,
                    version,
                    f"{factory.__module__}:{factory.__name__}",
                    factory,
                )
            )
    for kind, group in KINDS.items():
        seen: dict[str, Discovered] = {}
        for ep in _entry_points(group):
            dist = getattr(ep, "dist", None)
            dname = getattr(dist, "name", None) if dist is not None else None
            dver = getattr(dist, "version", None) if dist is not None else None
            if ep.name in builtins[kind]:
                if (dname or "").lower() == BUILTIN_DIST:
                    continue  # the built-in's own entry point (pyproject.toml)
                out.append(
                    Discovered(
                        kind,
                        ep.name,
                        False,
                        dname,
                        dver,
                        ep.value,
                        ep.load,
                        error="shadows a built-in plug-in name; ignored",
                    )
                )
                continue
            d = Discovered(kind, ep.name, False, dname, dver, ep.value, ep.load)
            if ep.name in seen:
                prev = seen[ep.name]
                prev.error = d.error = f"name registered by several distributions ({prev.dist}, {dname})"
            seen[ep.name] = d
            out.append(d)
    return out


def _ad2v_version() -> str:
    from ad2v import __version__  # not the installed metadata, which an editable install may freeze

    return __version__


# ---------------------------------------------------------------------------------------------
# the active set
# ---------------------------------------------------------------------------------------------


def own_rules(obj: Any) -> dict[str, Any]:
    """A plug-in's own rules: its rules files deep-merged in order (empty if none)."""
    merged: dict[str, Any] = {}
    for p in obj.rules_files:
        merged = rules_mod.deep_merge(merged, rules_mod.load_yaml(Path(p)))
    return merged


def identity(obj: Any, kind: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "api_version": str(obj.api_version),
        "kind": kind,
        "name": obj.name,
        "rules_hash": rules_mod.rules_hash(rules if rules is not None else own_rules(obj)),
        "version": str(obj.version),
    }
    if kind == "framework":
        rec["attaches_to"] = sorted(obj.attaches_to)
    return rec


@dataclass
class ActiveSet:
    extractors: list[Any]
    packs: list[Any]
    builtin: frozenset[str]
    epoch_rules: dict[str, Any] = field(default_factory=dict)  # stored in rules_versions
    effective: dict[str, dict[str, Any]] = field(default_factory=dict)  # extractor -> its rules
    effective_hash: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [p.name for p in [*self.extractors, *self.packs]]

    def packs_for(self, extractor: str) -> list[Any]:
        return [p for p in self.packs if extractor in p.attaches_to]

    def patterns(self, obj: Any) -> tuple[str, ...]:
        return tuple(obj.file_patterns)

    def all_patterns(self) -> tuple[str, ...]:
        pats: list[str] = []
        for p in [*self.extractors, *self.packs]:
            pats.extend(x for x in p.file_patterns if x not in pats)
        return tuple(pats)

    def cache_version(self, ex: Any) -> str:
        """The parse-cache `extractor_version` key: name, version and any internal cache version."""
        inner = getattr(ex, "cache_version", None)
        return f"{ex.name}@{ex.version}" + (f":{inner}" if inner else "")

    def is_builtin(self, obj: Any) -> bool:
        return obj.name in self.builtin


def resolve(
    config: Config,
    cli_enabled: tuple[str, ...] | list[str] = (),
    base_rules_path: Path | None = None,
    discovered: list[Discovered] | None = None,
) -> ActiveSet:
    """The plug-ins active for one run and the epoch rules they imply."""
    found = discovered if discovered is not None else discover()
    wanted = sorted(set(config.extractors_enabled) | set(cli_enabled))
    extractors: list[Any] = []
    packs: list[Any] = []
    builtin: set[str] = set()
    for d in found:
        if d.builtin:
            (extractors if d.kind == "extractor" else packs).append(d.load())
            builtin.add(d.name)
    for name in wanted:
        if name in builtin:
            continue
        cands = [d for d in found if d.name == name and not d.builtin]
        if not cands:
            raise PluginError(f"plug-in {name!r} is enabled but not installed (see `ad2v extractors list`)")
        d = cands[0]
        obj = d.load()
        (extractors if d.kind == "extractor" else packs).append(obj)
    extractors.sort(key=lambda o: o.name)
    packs.sort(key=lambda o: o.name)
    ex_names = {e.name for e in extractors}
    for p in packs:
        missing = [a for a in p.attaches_to if a not in ex_names]
        if missing:
            raise PluginError(
                f"framework pack {p.name!r} attaches to {', '.join(missing)}, which is not active"
            )
    act = ActiveSet(extractors, packs, frozenset(builtin))
    _compute_rules(act, config, base_rules_path)
    return act


def _compute_rules(act: ActiveSet, config: Config, base_rules_path: Path | None) -> None:
    records: list[dict[str, Any]] = []
    plugin_rules: dict[str, Any] = {}
    for ex in act.extractors:
        if ex.name == "python" and base_rules_path is not None:
            base = rules_mod.load_yaml(Path(base_rules_path))
        else:
            base = own_rules(ex)
        eff = base
        for p in act.packs_for(ex.name):
            eff = rules_mod.pack_merge(eff, own_rules(p))
        if ex.name == "python" and config.rules_overlay is not None:
            eff = rules_mod.deep_merge(eff, rules_mod.load_yaml(config.rules_overlay))
        act.effective[ex.name] = eff
        act.effective_hash[ex.name] = rules_mod.rules_hash(eff)
        rec = identity(ex, "extractor", base)
        rec["effective_rules_hash"] = act.effective_hash[ex.name]
        records.append(rec)
        if ex.name != "python":
            plugin_rules[ex.name] = eff
    for p in act.packs:
        records.append(identity(p, "framework"))
    records.sort(key=lambda r: (r["kind"], r["name"]))
    # the built-in Python extractor's effective rules stay at the top level (pre-P8 layout: the
    # severity and retrieval sections live there, ADR-0065)
    top = copy.deepcopy(act.effective.get("python", {}))
    top["plugins"] = records
    if plugin_rules:
        top["plugin_rules"] = plugin_rules
    top["_hash"] = rules_mod.rules_hash(top)
    top["_overlay"] = config.rules_overlay.name if config.rules_overlay is not None else None
    act.epoch_rules = top


# ---------------------------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------------------------


@dataclass
class PluginRun:
    name: str
    kind: str
    version: str
    ok: bool = True
    error: str | None = None
    elapsed_s: float = 0.0
    warnings: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


@dataclass
class RunOutput:
    graph: ir.Graph
    facts: CodeFacts
    runs: list[PluginRun]
    cache_entries: dict[tuple[str, str], dict[str, tuple[str, Any]]]  # (cache version, rules hash) -> entries
    timings: dict[str, float]
    stats: dict[str, int]
    graphs: dict[str, ir.Graph] = field(default_factory=dict)  # per extractor, before the merge

    @property
    def failures(self) -> list[dict[str, str]]:
        return [
            {"name": r.name, "kind": r.kind, "version": r.version, "error": r.error or ""}
            for r in self.runs
            if not r.ok
        ]


_CURRENT: list[str] = []  # plug-in whose code runs now (read by the conformance kit's audit hook)


def current_plugin() -> str | None:
    return _CURRENT[-1] if _CURRENT else None


def _invoke(name: str, fn: Callable[[], Any], threaded: bool, timeout_s: float | None) -> Any:
    _CURRENT.append(name)
    try:
        return _call(fn, timeout_s) if threaded else fn()
    finally:
        _CURRENT.pop()


def _call(fn: Callable[[], Any], timeout_s: float | None) -> Any:
    """Run `fn` in a daemon thread; raise PluginError on timeout (the thread is abandoned)."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e

    t = threading.Thread(target=target, name="ad2v-plugin", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise PluginError(f"timed out after {timeout_s:g} s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def merge_graph(main: ir.Graph, part: ir.Graph) -> None:
    """Union `part` into `main`: first node wins (spec refs are unioned), edges merge like add_edge."""
    for nid, n in part.nodes.items():
        cur = main.nodes.get(nid)
        if cur is None:
            main.nodes[nid] = n
        elif cur is not n:
            cur.spec_ref = sorted(set(cur.spec_ref) | set(n.spec_ref))
    for key, e in part.edges.items():
        if key not in main.edges:
            main.edges[key] = e
        else:
            main.add_edge(e.src, e.dst, e.kind, e.weight, e.attrs, e.attrs.get("lines"))
    main.unresolved.extend(part.unresolved)


def merge_facts(main: CodeFacts, part: CodeFacts) -> None:
    for k, v in part.events.items():
        main.events.setdefault(k, []).extend(v)
    for k, w in part.wrappers.items():
        main.wrappers.setdefault(k, []).extend(w)
    main.entry_ports = sorted(set(main.entry_ports) | set(part.entry_ports))
    main.files_read.update(part.files_read)


def run(
    act: ActiveSet,
    *,
    graph: ir.Graph,
    repo: Path,
    config: Config,
    system_name: str,
    files: list[SourceFile],
    cache_loader: Callable[[str, str], dict[tuple[str, str], Any]] | None = None,
    strict: bool = False,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> RunOutput:
    """Run every active extractor (and its packs' hooks) on `files`; merge into `graph`."""
    facts = CodeFacts()
    runs: list[PluginRun] = []
    cache_out: dict[tuple[str, str], dict[str, tuple[str, Any]]] = {}
    timings: dict[str, float] = {}
    stats = {"cache_hits": 0, "cache_misses": 0}
    graphs: dict[str, ir.Graph] = {}
    for ex in act.extractors:
        builtin = act.is_builtin(ex)
        rules = act.effective[ex.name]
        rh = act.effective_hash[ex.name]
        cver = act.cache_version(ex)
        sub = ir.Graph()
        lay = Layout(sub, config, repo, system_name)
        acc = FileAccessor([f for f in files if matches(f.path, tuple(ex.file_patterns))])
        cache = cache_loader(rh, cver) if cache_loader is not None else {}
        ctx = ExtractContext(sub, lay, acc, config, rules, cache)
        rec = PluginRun(ex.name, "extractor", str(ex.version))
        t0 = time.perf_counter()
        try:
            out = _invoke(ex.name, lambda ex=ex, ctx=ctx: ex.extract(ctx), not builtin, timeout_s)
            if not isinstance(out, ExtractOutput):
                raise PluginError(f"extract() returned {type(out).__name__}, not ExtractOutput")
        except Exception as e:
            if builtin or strict:
                raise
            rec.ok, rec.error = False, f"{type(e).__name__}: {e}"
            rec.elapsed_s = time.perf_counter() - t0
            rec.violations = list(acc.violations)
            runs.append(rec)
            continue
        rec.elapsed_s = time.perf_counter() - t0
        rec.warnings, rec.violations = ctx.warnings, list(acc.violations)
        runs.append(rec)
        for pack in act.packs_for(ex.name):
            pbuiltin = act.is_builtin(pack)
            extra = [f for f in files if matches(f.path, tuple(pack.file_patterns)) and f.path not in acc]
            pacc = FileAccessor([*acc, *extra])
            target = sub if pbuiltin else copy.deepcopy(sub)
            fctx = FrameworkContext(ex.name, target, pacc, config, rules, out.facts)
            prec = PluginRun(pack.name, "framework", str(pack.version))
            t1 = time.perf_counter()
            try:
                _invoke(
                    pack.name, lambda pack=pack, fctx=fctx: pack.post_extract(fctx), not pbuiltin, timeout_s
                )
                sub = target
            except Exception as e:
                if pbuiltin or strict:
                    raise
                prec.ok, prec.error = False, f"{type(e).__name__}: {e}"
            prec.elapsed_s = time.perf_counter() - t1
            prec.warnings, prec.violations = fctx.warnings, list(pacc.violations)
            runs.append(prec)
            timings[f"plugin.{pack.name}"] = prec.elapsed_s
        graphs[ex.name] = sub
        merge_graph(graph, sub)
        merge_facts(facts, out.facts)
        if out.cache_entries:
            cache_out.setdefault((cver, rh), {}).update(out.cache_entries)
        for k, v in out.timings.items():
            timings[f"code.{k}" if builtin and ex.name == "python" else f"{ex.name}.{k}"] = v
        for k in ("cache_hits", "cache_misses"):
            stats[k] += int(out.stats.get(k, 0))
        timings[f"plugin.{ex.name}"] = rec.elapsed_s
    return RunOutput(graph, facts, runs, cache_out, timings, stats, graphs)


def describe(act: ActiveSet) -> list[str]:
    """One line per active plug-in, for `extract` / `history` output."""
    lines = []
    for rec in act.epoch_rules.get("plugins", []):
        extra = f" -> {', '.join(rec['attaches_to'])}" if rec["kind"] == "framework" else ""
        src = "built-in" if rec["name"] in act.builtin else "enabled"
        lines.append(
            f"{rec['kind']} {rec['name']} {rec['version']} (api {rec['api_version']}, {src}{extra})"
            f" rules {rec['rules_hash'][:12]}"
        )
    return lines


def default_epoch_rules(base_path: Path | None = None, overlay_path: Path | None = None) -> dict[str, Any]:
    """The epoch rules of a run with only the built-ins active (what `rules.load()` returns)."""
    cfg = Config()
    cfg.rules_overlay = overlay_path
    found = [d for d in discover() if d.builtin]
    return resolve(cfg, (), base_path, found).epoch_rules


__all__ = [
    "API_VERSION",
    "ActiveSet",
    "Discovered",
    "PluginError",
    "default_epoch_rules",
    "describe",
    "discover",
    "matches",
    "resolve",
    "run",
]
