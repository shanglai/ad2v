"""Conformance kit for extractor and framework-pack plug-ins (ADR-0063, docs/plugins.md).

Plain functions, no pytest at runtime. Run it from code:

    from ad2v.testing.conformance import check
    result = check("routes-dsl", Path("tests/fixture"))
    assert result["passed"], result

or from the CLI: `ad2v extractor check <name> --fixture <dir> [--json]`.

Checks (each one returns {"id", "passed", "detail"}):

api_handshake   the plug-in loads, has every interface attribute, a valid name and version, and an
                api_version this ad2v accepts (current major, or the previous one);
determinism     two runs give the same canonical output, and so does a copy of the fixture with
                CRLF line endings and a UTF-8 BOM on every text file;
id_stability    every node id survives an unrelated insertion: blank lines prepended to each of
                the plug-in's files plus one new empty file matching its first pattern;
schema          a full `extract` with the plug-in enabled validates (`ad2v validate`: IR JSON
                schema, ids, subtree hashes, references);
file_access     while the plug-in's code runs it opens no file outside its file set (Python audit
                hook on `open`; files under sys.path entries are imports and are ignored) and asks
                the accessor for nothing outside the set;
side_effects    while the plug-in's code runs: no network (socket connect / resolve / bind), no
                subprocess, no file opened for writing (audit hook);
declared_kinds  every node and edge kind it emitted was declared (`node_kinds` / `edge_kinds`;
                system / container / component and `contains` come from the core's Layout);
runs_clean      the plug-in neither raised nor timed out on the fixture.

The fixture is a small repository directory (code, optional specs and ad2v.yaml). A framework pack
is checked through the extractor(s) it attaches to: its output is that extractor's graph.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from ad2v import ids, ir, pipeline, plugins, validate
from ad2v.api import API_VERSION, LAYOUT_EDGE_KINDS, LAYOUT_NODE_KINDS

_AUDIT_INSTALLED = False
_OPENS: list[tuple[str, str]] = []  # (plug-in, absolute path) recorded while a plug-in runs
_RECORDING = [False]


_EFFECTS: list[tuple[str, str]] = []  # (plug-in, "network: …" / "process: …" / "write: …")
_NET_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.bind", "urllib.Request", "http.client.connect")
_PROC_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile")


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if not _RECORDING[0]:
        return
    who = plugins.current_plugin()
    if who is None:
        return
    if event.startswith(_NET_EVENTS):
        _EFFECTS.append((who, f"network: {event}"))
        return
    if event.startswith(_PROC_EVENTS):
        _EFFECTS.append((who, f"process: {event}"))
        return
    if event != "open" or not args:
        return
    path = args[0]
    if isinstance(path, int):  # an already-open file descriptor
        return
    try:
        p = os.fspath(path)
    except TypeError:
        return
    mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
    flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
    if any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
        _EFFECTS.append((who, f"write: {Path(p).name}"))
    _OPENS.append((who, p))


def _install_audit_hook() -> None:
    global _AUDIT_INSTALLED
    if not _AUDIT_INSTALLED:
        sys.addaudithook(_audit)  # cannot be removed; it is a no-op unless recording
        _AUDIT_INSTALLED = True


def _import_roots() -> list[Path]:
    roots = {Path(sys.prefix), Path(sys.base_prefix), Path(sys.exec_prefix)}
    for p in sys.path:
        if p and Path(p).is_dir():
            roots.add(Path(p))
    return sorted({r.resolve() for r in roots})


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == r or path.is_relative_to(r) for r in roots)


def _find(name: str) -> plugins.Discovered:
    cands = [d for d in plugins.discover() if d.name == name]
    if not cands:
        raise plugins.PluginError(f"no plug-in named {name!r} is installed")
    usable = [d for d in cands if not d.error]
    return usable[0] if usable else cands[0]


def _canonical(graph: ir.Graph) -> list[str]:
    rows = [
        ids.canonical_json({"node": n.to_dict(), "spec_ref": sorted(n.spec_ref)})
        for n in graph.nodes.values()
    ]
    rows += [ids.canonical_json({"edge": e.to_dict()}) for e in graph.edges.values()]
    rows += [
        ids.canonical_json({"unresolved": [u.src, u.ref, u.ref_kind, u.reason]}) for u in graph.unresolved
    ]
    return sorted(rows)


def _copy(src: Path, dst: Path, transform: str | None = None, patterns: tuple[str, ...] = ()) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.ad2v", ".git"))
    if transform is None:
        return
    for p in sorted(dst.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(dst).as_posix()
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        if transform == "crlf_bom":
            p.write_bytes(b"\xef\xbb\xbf" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
        elif transform == "insert" and plugins.matches(rel, patterns):
            p.write_bytes(("\n\n\n" + text).encode("utf-8"))
    if transform == "insert":
        for pat in patterns:
            if pat.startswith("*.") and "/" not in pat and "*" not in pat[2:]:
                (dst / f"ad2v_conformance_extra{pat[1:]}").write_bytes(b"")
                break


def _run(repo: Path, enable: list[str], target: str) -> tuple[pipeline.Result, list[tuple[str, str]]]:
    """One build with the audit hook recording; `_EFFECTS` holds side effects afterwards."""
    _OPENS.clear()
    _EFFECTS.clear()
    _RECORDING[0] = True
    try:
        res = pipeline.build(repo, extractors=enable, name_hint="fixture", strict=False)
    finally:
        _RECORDING[0] = False
    return res, list(_OPENS)


def check(name: str, fixture: Path) -> dict[str, Any]:
    """Run every check for plug-in `name` on `fixture`; return a JSON-serializable result."""
    fixture = Path(fixture)
    result: dict[str, Any] = {
        "kit": "ad2v.testing.conformance",
        "core_api_version": API_VERSION,
        "plugin": name,
        "fixture": fixture.name,
        "checks": [],
    }
    checks: list[dict[str, Any]] = result["checks"]

    def add(cid: str, ok: bool, detail: Any) -> None:
        checks.append({"id": cid, "passed": bool(ok), "detail": detail})

    try:
        d = _find(name)
        obj = d.load()
    except plugins.PluginError as e:
        add("api_handshake", False, str(e))
        result["passed"] = False
        return result
    result.update(kind=d.kind, version=str(obj.version), api_version=str(obj.api_version), builtin=d.builtin)
    ok, why = plugins.api_compatible(str(obj.api_version))
    add("api_handshake", ok, why)
    if not fixture.is_dir():
        add("fixture", False, "fixture directory not found")
        result["passed"] = False
        return result
    _install_audit_hook()
    # the extractor(s) whose graphs carry the plug-in's output
    targets = [name] if d.kind == "extractor" else list(obj.attaches_to)
    enable = sorted({name, *targets} - {x.name for x in plugins.discover() if x.builtin})
    patterns: tuple[str, ...] = tuple(obj.file_patterns)
    if d.kind == "framework":
        for t in targets:
            patterns += tuple(_find(t).load().file_patterns)
    tmp = Path(tempfile.mkdtemp(prefix="ad2v-conformance-"))
    try:
        base_repo = tmp / "a" / "fixture"
        _copy(fixture, base_repo)
        r1, opens = _run(base_repo, enable, name)
        effects = sorted({e for who, e in _EFFECTS if who in {name, *targets}})
        failures = [r for r in r1.plugin_runs if not r.ok and r.name in {name, *targets}]
        add("runs_clean", not failures, [f"{r.name}: {r.error}" for r in failures] or "ok")

        def out(res: pipeline.Result) -> list[str]:
            rows: list[str] = []
            for t in targets:
                g = res.plugin_graphs.get(t)
                rows += _canonical(g) if g is not None else [f"<no output from {t}>"]
            return rows

        o1 = out(r1)
        r2, _ = _run(base_repo, enable, name)
        crlf_repo = tmp / "b" / "fixture"
        _copy(fixture, crlf_repo, "crlf_bom")
        r3, _ = _run(crlf_repo, enable, name)
        same2, same3 = out(r2) == o1, out(r3) == o1
        add(
            "determinism",
            same2 and same3,
            {"rows": len(o1), "second_run_identical": same2, "crlf_bom_identical": same3},
        )
        ins_repo = tmp / "c" / "fixture"
        _copy(fixture, ins_repo, "insert", patterns)
        r4, _ = _run(ins_repo, enable, name)
        before = {nid for t in targets for nid in (r1.plugin_graphs.get(t) or ir.Graph()).nodes}
        after = {nid for t in targets for nid in (r4.plugin_graphs.get(t) or ir.Graph()).nodes}
        lost = sorted(before - after)
        add("id_stability", not lost and bool(before), {"ids": len(before), "lost": len(lost)})
        # schema: a real extract with the plug-in enabled, then validate
        out_file = tmp / "check.ad2v"
        pipeline.extract_to_file(base_repo, None, out_file, name_hint="fixture", extractors=enable)
        problems = validate.validate(out_file)
        add("schema", not problems, problems[:10] or "ok")
        # file access
        own = _file_set(base_repo, targets, enable)
        roots = _import_roots()
        bad = sorted(
            {
                path
                for who, path in opens
                if who in {name, *targets}
                and Path(path).resolve() not in own
                and not _under(Path(path).resolve(), roots)
            }
        )
        acc_bad = sorted({v for r in r1.plugin_runs if r.name in {name, *targets} for v in r.violations})
        add(
            "file_access",
            not bad and not acc_bad,
            {
                "opens_outside_file_set": [_redact(p, base_repo) for p in bad][:10],
                "accessor_violations": acc_bad[:10],
            },
        )
        add("side_effects", not effects, effects[:10] or "none (no network, subprocess or file write)")
        # declared kinds
        declared_n = set(LAYOUT_NODE_KINDS) | set(obj.node_kinds)
        declared_e = set(LAYOUT_EDGE_KINDS) | set(obj.edge_kinds)
        for t in targets:
            tobj = _find(t).load()
            declared_n |= set(tobj.node_kinds)
            declared_e |= set(tobj.edge_kinds)
        emitted_n, emitted_e = set(), set()
        for t in targets:
            g = r1.plugin_graphs.get(t) or ir.Graph()
            emitted_n |= {n.kind for n in g.nodes.values()}
            emitted_e |= {e.kind for e in g.edges.values()}
        add(
            "declared_kinds",
            emitted_n <= declared_n and emitted_e <= declared_e,
            {
                "undeclared_node_kinds": sorted(emitted_n - declared_n),
                "undeclared_edge_kinds": sorted(emitted_e - declared_e),
                "declared_not_emitted": sorted(set(obj.node_kinds) - emitted_n),
            },
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    result["passed"] = all(c["passed"] for c in checks)
    return result


def _file_set(repo: Path, targets: list[str], enable: list[str]) -> set[Path]:
    """Every file the target extractors and their active packs may read in `repo`."""
    from ad2v.manifest import load as load_manifest

    act = plugins.resolve(load_manifest(repo, None), tuple(enable))
    pats: list[str] = []
    for ex in act.extractors:
        if ex.name in targets:
            pats += list(ex.file_patterns)
            for pk in act.packs_for(ex.name):
                pats += list(pk.file_patterns)
    out = set()
    for p in repo.rglob("*"):
        if p.is_file() and plugins.matches(p.relative_to(repo).as_posix(), tuple(pats)):
            out.add(p.resolve())
    return out


def _redact(path: str, repo: Path) -> str:
    """Never print absolute local paths: show fixture-relative paths, else only the file name."""
    p = Path(path).resolve()
    try:
        return "<fixture>/" + p.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return "<outside>/" + p.name


def format_text(result: dict[str, Any]) -> str:
    lines = [
        f"{result.get('kind', 'plug-in')} {result['plugin']} {result.get('version', '?')}"
        f" (api {result.get('api_version', '?')}) on {result['fixture']}:"
        f" {'PASS' if result.get('passed') else 'FAIL'}"
    ]
    for c in result["checks"]:
        detail = c["detail"] if isinstance(c["detail"], str) else json.dumps(c["detail"], sort_keys=True)
        lines.append(f"  {'ok  ' if c['passed'] else 'FAIL'} {c['id']:15s} {detail}")
    return "\n".join(lines) + "\n"
