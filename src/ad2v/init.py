"""`ad2v init`: deterministic onboarding of an existing repository (P9, ADR-0071).

Scans a repository without executing anything and proposes an `ad2v.yaml`:

- spec roots by content: the usual folder names (specs/, spec/, docs/specs/, .kiro/specs/, sdd/,
  docs/sdd/, requirements/, docs/requirements/, specification(s)/) and any other folder whose files
  a reader recognizes (ad2v convention, spec-kit, Kiro, requirement tables, user stories, Gherkin,
  OpenAPI); each candidate is scored, with the evidence (files per format);
- the format of every spec file, and the prose files no preset reads (candidates for
  `ad2v specs bootstrap`);
- containers from project manifests (pyproject.toml, setup.py, package.json, Dockerfile, go.mod,
  Cargo.toml, pom.xml, build.gradle*), their language, and whether an active extractor reads it;
- the vendored or generated folders present, and how many code files each one keeps out;
- SQL files (and whether an exclude would drop them), infrastructure-as-code (reported only,
  mapped in P10), test results or a pytest configuration;
- route prefixes the Python extractor cannot resolve, as `pairing.path_constants` entries with
  empty values for a human to fill in (an empty value is ignored; ad2v never guesses one).

The proposal is a complete, commented YAML with sorted keys, stable comments and no timestamps.
Nothing is written unless `--write` is given.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids, ir, plugins, scope
from ad2v.extract import files as filewalk
from ad2v.manifest import CODE_ONLY_EXCLUDES, DEFAULT_EXCLUDES, Config, code_excluded
from ad2v.specroots import AUTO_DIRS

NAMED_SPEC_DIRS = (
    *AUTO_DIRS,
    "requirements",
    "docs/requirements",
    "specification",
    "specifications",
    "docs/specification",
    "docs/specifications",
)
CONTAINER_FILES = (
    "pyproject.toml",
    "setup.py",
    "package.json",
    "Dockerfile",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)
VCS = (".git", ".hg", ".svn")
GENERATED_DIRS = ("generated", "__generated__", "gen-client", "openapi-client", "api-client")
PROSE_SKIP = re.compile(
    r"^(readme|changelog|contributing|license|code_of_conduct|security)(\.[a-z]+)?$", re.I
)
MAX_MARKDOWN = 2000  # files read for content sniffing (sorted); reported when the cap is hit
DEFAULT_TEST_PREFIXES = ("REQ", "CMP", "FR")
INFRA_KINDS = ("terraform", "pulumi", "cloudformation", "kubernetes", "helm")


@dataclass
class Findings:
    repo_label: str
    system_name: str = ""
    existing_manifest: str | None = None
    spec_candidates: list[dict[str, Any]] = field(default_factory=list)
    spec_roots: list[str] = field(default_factory=list)
    spec_files: list[dict[str, Any]] = field(default_factory=list)
    prose: list[str] = field(default_factory=list)
    spec_id_prefixes: list[str] = field(default_factory=list)
    nonfunctional_prefixes: list[str] = field(default_factory=list)
    containers: list[dict[str, Any]] = field(default_factory=list)
    excludes: list[dict[str, Any]] = field(default_factory=list)
    extra_excludes: list[str] = field(default_factory=list)
    sql: list[dict[str, Any]] = field(default_factory=list)
    infra: dict[str, list[str]] = field(default_factory=dict)
    test_results: dict[str, list[str]] = field(default_factory=dict)
    path_constants: list[str] = field(default_factory=list)
    unresolved_routes: int = 0
    spec_components: list[dict[str, Any]] = field(default_factory=list)
    capped: bool = False
    # P10 (ADR-0081): infra roots (Terraform root modules) and how deployment units map to containers
    infra_roots: list[str] = field(default_factory=list)
    infra_matches: dict[str, list[str]] = field(default_factory=dict)  # container -> unit addresses
    infra_ambiguous: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _walk_all(repo: Path) -> list[str]:
    """Every regular file (sorted, POSIX, repo-relative), VCS folders aside; never follows links."""
    out = []
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in VCS and not (Path(dirpath) / d).is_symlink())
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        for f in sorted(filenames):
            full = Path(dirpath) / f
            if full.is_symlink() or not full.is_file():
                continue
            out.append(f if rel_dir == "." else f"{rel_dir}/{f}")
    return sorted(out)


def _excluded_by(rel: str, patterns: tuple[str, ...]) -> str | None:
    """The first default exclude pattern that drops this path (a folder on the way, or the file)."""
    parts = rel.split("/")
    for i, part in enumerate(parts):
        sub = "/".join(parts[: i + 1])
        for p in patterns:
            if fnmatch.fnmatchcase(part, p) or fnmatch.fnmatchcase(sub, p):
                return p
    return None


def _language_of_dir(files: list[str], d: str, marker: str) -> str:
    inside = [f for f in files if f.startswith(d + "/") or d == "."]
    counts = Counter(scope.language(f) or ("python" if f.endswith(".py") else None) for f in inside)
    counts.pop(None, None)
    if marker in ("pyproject.toml", "setup.py"):
        return "python"
    if marker == "package.json":
        return (
            "typescript"
            if counts.get("typescript", 0) or any(f.endswith("tsconfig.json") for f in inside)
            else "javascript"
        )
    if marker == "go.mod":
        return "go"
    if marker == "Cargo.toml":
        return "rust"
    if marker in ("pom.xml", "build.gradle", "build.gradle.kts"):
        return "kotlin" if counts.get("kotlin", 0) > counts.get("java", 0) else "java"
    return counts.most_common(1)[0][0] if counts else "unknown"


def _infra(files: list[str], read: Any) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {k: set() for k in INFRA_KINDS}
    for f in files:
        name = f.rsplit("/", 1)[-1]
        d = f.rsplit("/", 1)[0] if "/" in f else "."
        if f.endswith(".tf") or name == ".terraform.lock.hcl":
            out["terraform"].add(d)
        elif name in ("Pulumi.yaml", "Pulumi.yml"):
            out["pulumi"].add(d)
        elif name == "Chart.yaml":
            out["helm"].add(d)
        elif f.endswith((".yaml", ".yml", ".json", ".template")):
            text = read(f)
            if "AWSTemplateFormatVersion" in text:
                out["cloudformation"].add(d)
            elif re.search(r"^apiVersion:\s*\S+", text, re.M) and re.search(r"^kind:\s*\S+", text, re.M):
                out["kubernetes"].add(d)
    return {k: sorted(v) for k, v in out.items() if v}


def scan(repo: Path, repo_label: str | None = None) -> Findings:
    """Everything `init` reports. Reads files; never executes anything."""
    from ad2v.extract.spec import gherkin, openapi, presets
    from ad2v.extract.spec import titles as spec_titles

    repo = Path(repo).resolve()
    fd = Findings(repo_label or repo.name, system_name=repo.name)
    if (repo / "ad2v.yaml").is_file():
        fd.existing_manifest = "ad2v.yaml"
    every = _walk_all(repo)
    cache: dict[str, str] = {}

    def read(rel: str) -> str:
        if rel not in cache:
            try:
                cache[rel] = ids.read_normalized(repo / rel)
            except (OSError, UnicodeDecodeError, ValueError):
                cache[rel] = ""
        return cache[rel]

    # excludes ------------------------------------------------------------------------------------
    kept: list[str] = []
    dropped: Counter[str] = Counter()
    dropped_code: Counter[str] = Counter()
    for f in every:
        p = _excluded_by(f, DEFAULT_EXCLUDES)
        if p is None:
            kept.append(f)
        else:
            dropped[p] += 1
            if scope.language(f) or f.endswith(".py"):
                dropped_code[p] += 1
    fd.excludes = [
        {"pattern": p, "files": dropped[p], "code_files": dropped_code[p], "default": True}
        for p in sorted(dropped)
        if p not in VCS
    ]
    gen_dirs = sorted({part for f in kept for part in f.split("/")[:-1] if part in GENERATED_DIRS})
    for g in gen_dirs:
        n = sum(1 for f in kept if g in f.split("/")[:-1])
        nc = sum(1 for f in kept if g in f.split("/")[:-1] and (scope.language(f) or f.endswith(".py")))
        fd.excludes.append({"pattern": g, "files": n, "code_files": nc, "default": False})
    fd.extra_excludes = gen_dirs
    files = [f for f in kept if not any(g in f.split("/")[:-1] for g in gen_dirs)]

    # spec files and roots ------------------------------------------------------------------------
    spec_like: dict[str, str] = {}  # path -> format
    md = [f for f in files if f.endswith((".md", ".markdown"))]
    fd.capped = len(md) > MAX_MARKDOWN
    for f in md[:MAX_MARKDOWN]:
        ch = presets.detect(f, read(f))
        spec_like[f] = ch if ch else "prose"
    for f in files:
        if f.endswith(".feature"):
            spec_like[f] = "gherkin"
        elif f.endswith((".yaml", ".yml", ".json")) and openapi.is_openapi(read(f)):
            spec_like[f] = "openapi"
    by_dir: dict[str, Counter[str]] = {}
    for f, fmt in spec_like.items():
        d = f.rsplit("/", 1)[0] if "/" in f else "."
        by_dir.setdefault(d, Counter())[fmt] += 1

    def named_root(d: str) -> str | None:
        for n in sorted(NAMED_SPEC_DIRS, key=len, reverse=True):
            if d == n or d.startswith(n + "/"):
                return n
        return None

    cands: dict[str, Counter[str]] = {}
    for d, c in by_dir.items():
        recognized = sum(v for k, v in c.items() if k != "prose")
        root = named_root(d)
        if root is None and recognized == 0:
            continue
        if root is None:
            root = d
        cands.setdefault(root, Counter()).update(c)
    # nested candidates fold into the outermost one
    for c in sorted(cands, key=len, reverse=True):
        parent = next((o for o in cands if o != c and o != "." and c.startswith(o + "/")), None)
        if parent is not None:
            cands[parent].update(cands.pop(c))
    for root, c in cands.items():
        recognized = sum(v for k, v in c.items() if k != "prose")
        score = 3 * recognized + (2 if named_root(root) == root else 0) + (1 if c.get("prose") else 0)
        fd.spec_candidates.append(
            {
                "path": root,
                "score": score,
                "evidence": dict(sorted(c.items())),
                "named": named_root(root) == root,
            }
        )
    fd.spec_candidates.sort(key=lambda x: (-x["score"], x["path"]))
    chosen = [c for c in fd.spec_candidates if sum(v for k, v in c["evidence"].items() if k != "prose") > 0]
    roots = []
    for c in chosen:
        if c["path"] == ".":  # spec files at the repo root: name them one by one
            roots += sorted(f for f, fmt in spec_like.items() if "/" not in f and fmt != "prose")
        else:
            roots.append(c["path"])
    fd.spec_roots = sorted(set(roots))
    if not fd.spec_roots:  # only prose: still worth reporting the named folders for bootstrap
        named_prose = [c["path"] for c in fd.spec_candidates if c["named"]]
        fd.prose = sorted(
            f
            for f, fmt in spec_like.items()
            if fmt == "prose" and any(f.startswith(n + "/") for n in named_prose)
        )
    in_roots = sorted(f for f in spec_like if any(f == r or f.startswith(r + "/") for r in fd.spec_roots))
    fd.spec_files = [{"path": f, "format": spec_like[f]} for f in in_roots]
    if fd.spec_roots:
        fd.prose = [
            f for f in in_roots if spec_like[f] == "prose" and not PROSE_SKIP.match(f.rsplit("/", 1)[-1])
        ]

    # spec ids: the prefixes test names would use, and the non-functional ones
    g = ir.Graph()
    for f in in_roots:
        fmt = spec_like[f]
        if fmt == "gherkin":
            gherkin.extract(g, f, read(f))
        elif fmt == "openapi":
            continue
        elif fmt != "prose":
            presets.extract(g, f, read(f), presets.choose(f, read(f), []))
    spec_ids = sorted(
        {n.qualified_name for n in g.nodes.values() if n.kind in ("requirement", "spec_component")}
    )
    spec_ids += sorted({r for n in g.nodes.values() for r in n.spec_ref})
    prefixes = sorted(
        {spec_titles.prefix(x) for x in spec_ids if re.match(r"^[A-Za-z]", x.split(":", 1)[-1])}
    )
    fd.spec_id_prefixes = [p for p in prefixes if re.fullmatch(r"[A-Z][A-Z0-9]*", p)]
    fd.nonfunctional_prefixes = [
        p for p in fd.spec_id_prefixes if p in spec_titles.DEFAULT_NONFUNCTIONAL_PREFIXES
    ] + sorted(
        {
            spec_titles.prefix(n.qualified_name)
            for n in g.nodes.values()
            if n.attrs.get("requirement_type") == "nonfunctional"
        }
        - set(spec_titles.DEFAULT_NONFUNCTIONAL_PREFIXES)
    )

    comps = [n for n in g.nodes.values() if n.kind == "spec_component"]
    # containers ------------------------------------------------------------------------------------
    # languages an active extractor reads (the built-ins: python; P11 adds typescript)
    read_by_extractor = {lang for ex in plugins.resolve(Config()).extractors for lang in ex.languages}
    markers: dict[str, str] = {}
    for f in files:
        name = f.rsplit("/", 1)[-1]
        d = f.rsplit("/", 1)[0] if "/" in f else "."
        if name in CONTAINER_FILES and d != "." and d.count("/") <= 2:
            if any(d.startswith(s + "/") or d == s for s in fd.spec_roots):
                continue
            markers.setdefault(d, name)
    tops = [d for d in sorted(markers) if not any(o != d and d.startswith(o + "/") for o in markers)]
    for d in tops:
        lang = _language_of_dir(files, d, markers[d])
        name = d.rsplit("/", 1)[-1]
        fd.containers.append(
            {
                "name": name,
                "path": d,
                "marker": markers[d],
                "language": lang,
                "read": lang in read_by_extractor,
                "status_if_unread": None if lang in read_by_extractor else "not_evaluable",
            }
        )

    # spec components: by id (a pairing.components key) or by a name that pairs with a container
    from ad2v.pairing import slug

    cnames = {slug(c["name"]): c["name"] for c in fd.containers}
    for n in sorted(comps, key=lambda n: n.qualified_name):
        sid = n.attrs.get("spec_id") or (n.qualified_name if "::" not in n.qualified_name else None)
        fd.spec_components.append({"id": sid, "name": n.name, "pairs_by_name_with": cnames.get(slug(n.name))})

    # SQL, infra, tests -------------------------------------------------------------------------------
    for f in every:
        if f.endswith(".sql"):
            p = _excluded_by(f, DEFAULT_EXCLUDES)
            migration = any(part in CODE_ONLY_EXCLUDES for part in f.split("/")[:-1])
            fd.sql.append({"path": f, "dropped_by": p, "migration": migration})
    fd.infra = _infra(files, read)
    fd.infra_roots = [d for d in fd.infra.get("terraform", []) if "modules" not in d.split("/")]
    if fd.infra_roots:
        _infra_matches(fd, repo, read)
    junit = sorted(f for f in files if f.endswith(".xml") and "<testsuite" in read(f)[:4000])
    pytest_cfg = sorted(
        f
        for f in files
        if f.rsplit("/", 1)[-1] in ("pytest.ini", "conftest.py")
        or (
            f.endswith(("pyproject.toml", "setup.cfg", "tox.ini"))
            and re.search(r"\[(tool[.:])?pytest", read(f))
        )
    )
    fd.test_results = {"junit": junit, "pytest_config": pytest_cfg}

    # route prefixes the Python extractor cannot resolve --------------------------------------------
    py = [f for f in files if f.endswith(".py") and not code_excluded(f)]
    py = [f for f in py if not any(f.startswith(r + "/") for r in fd.spec_roots)]
    if py:
        from ad2v.extract.code.base import Layout
        from ad2v.extract.code.python import PythonExtractor
        from ad2v.manifest import ContainerDecl

        cfg = Config()  # with the proposed containers, so imports resolve from each project root
        cfg.containers = [ContainerDecl(c["name"], (c["path"],), kind="service") for c in fd.containers]
        graph = ir.Graph()
        ex = PythonExtractor(cfg)
        ex.extract(graph, Layout(graph, cfg, repo, fd.repo_label), filewalk.load(repo, py))
        fd.path_constants = sorted(ex.unresolved_prefix_exprs)
        fd.unresolved_routes = sum(
            1 for n in graph.nodes.values() if n.kind == "http_route" and n.attrs.get("path_unresolved")
        )
    return fd


def _infra_matches(fd: Findings, repo: Path, read: Any) -> None:
    """Which static deployment units (or website buckets) match each proposed container by name
    (the bridge's rule (b)); several candidates with different images are ambiguous."""
    from ad2v.infra import bridge, static

    names = static.env_names(fd.infra_roots)
    hosts = []
    for root in fd.infra_roots:
        for r in static.read_root(repo, root, names[root], read).resources:
            if r.kind == "deployment_unit" or (r.kind == "bucket" and r.attrs.get("website")):
                hosts.append(
                    ir.Node("infra", r.kind, r.address, r.address, attrs={**r.attrs, "address": r.address})
                )
    for c in fd.containers:
        cname = bridge._slug(c["name"])
        cands = [u for u in hosts if bridge._name_match(bridge._unit_names(u), cname)]
        images = {u.attrs.get("image") for u in cands}
        if len(cands) == 1 or (len(cands) > 1 and len(images) == 1 and None not in images):
            fd.infra_matches[c["name"]] = sorted(u.qualified_name for u in cands)
        elif len(cands) > 1:
            fd.infra_ambiguous[c["name"]] = sorted(u.qualified_name for u in cands)


PLAN_COMMAND = (
    "terraform init && terraform plan -refresh=false -out tfplan && terraform show -json tfplan > plan.json"
)


# -- the proposal ----------------------------------------------------------------------------------
def proposal(fd: Findings) -> dict[str, Any]:
    """The proposed manifest as data (sorted keys)."""
    out: dict[str, Any] = {"system": fd.system_name}
    if fd.containers:
        out["containers"] = [
            {"kind": "service", "name": c["name"], "paths": [c["path"]]} for c in fd.containers
        ]
    if fd.extra_excludes:
        out["exclude"] = list(fd.extra_excludes)
    pairing: dict[str, Any] = {"orphan_policy": "auto"}
    if fd.path_constants:
        pairing["path_constants"] = {k: "" for k in fd.path_constants}
    out["pairing"] = pairing
    spec_ids: dict[str, Any] = {
        "test_name_prefixes": sorted(set(DEFAULT_TEST_PREFIXES) | set(fd.spec_id_prefixes))
    }
    if fd.nonfunctional_prefixes:
        spec_ids["nonfunctional_prefixes"] = sorted(set(fd.nonfunctional_prefixes))
    out["spec_ids"] = spec_ids
    rules = [
        {"glob": f["path"], "preset": f["format"]}
        for f in fd.spec_files
        if f["format"] in ("table", "stories")
    ]
    if rules:
        out["spec_markdown"] = rules
    if fd.spec_roots:
        out["spec_root"] = list(fd.spec_roots)
    if fd.infra_roots:
        out["infra_root"] = list(fd.infra_roots)
    if fd.infra_ambiguous:  # placeholders: an empty value is ignored until a human picks
        out["infra"] = {"deploys": {a: "" for c in sorted(fd.infra_ambiguous) for a in fd.infra_ambiguous[c]}}
    return dict(sorted(out.items()))


def _flow(v: Any) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid YAML scalar
    return yaml.safe_dump(v, default_flow_style=True, allow_unicode=True, sort_keys=True, width=1000).strip()


def render_yaml(fd: Findings, manifest: dict[str, Any]) -> str:
    """The proposal with comments. Keys sorted; comments fixed; no timestamps."""
    lines = [
        "# ad2v.yaml proposed by `ad2v init` (review it; nothing here is guessed).",
        "# Keep it outside the repository while you try it: `ad2v extract --manifest <this file>`.",
    ]
    for key, value in manifest.items():
        if key == "containers":
            lines.append("# one container per project manifest found (language: read by an extractor?)")
            lines.append("containers:")
            for c, info in zip(value, fd.containers, strict=True):
                note = "read" if info["read"] else "not read: shown as not_evaluable"
                lines.append(f"  - {_flow(c)}  # {info['language']}, {info['marker']}; {note}")
        elif key == "exclude":
            lines.append("# generated folders found (the defaults already drop node_modules, dist, build, …)")
            lines.append(f"exclude: {_flow(value)}")
        elif key == "pairing":
            lines.append("pairing:")
            lines.append(f"  orphan_policy: {value['orphan_policy']}  # auto | strict | off")
            unmapped = [c for c in fd.spec_components if c["id"] and not c["pairs_by_name_with"]]
            if unmapped and fd.containers:
                lines.append("  # spec components to map onto containers (uncomment and choose):")
                lines.append("  # components:")
                for c in unmapped:
                    opts = " | ".join(x["name"] for x in fd.containers)
                    lines.append(f"  #   {c['id']}: {opts}  # {c['name']}")
            if "path_constants" in value:
                lines.append(
                    "  # route prefixes the extractor cannot resolve: fill in the values (empty = ignored)"
                )
                lines.append("  path_constants:")
                for k in value["path_constants"]:
                    lines.append(f'    {_flow(k)}: ""')
        elif key == "spec_ids":
            lines.append("spec_ids:")
            lines.append(
                f"  test_name_prefixes: {_flow(value['test_name_prefixes'])}  # test_rf_001_… links to RF-001"
            )
            if "nonfunctional_prefixes" in value:
                lines.append(f"  nonfunctional_prefixes: {_flow(value['nonfunctional_prefixes'])}")
        elif key == "spec_markdown":
            lines.append(
                "# team formats found (they are auto-detected too; listed to keep the choice stable)"
            )
            lines.append("spec_markdown:")
            for r in value:
                lines.append(f"  - {_flow(r)}")
        elif key == "spec_root":
            lines.append(f"spec_root: {_flow(value)}")
        elif key == "infra_root":
            lines.append(
                "# Terraform root modules, read statically every epoch (pass --infra-plan for the plan)"
            )
            lines.append(f"infra_root: {_flow(value)}")
        elif key == "infra":
            lines.append(
                "# several deployment units match a container by name: keep the right one (empty = ignored)"
            )
            lines.append("infra:")
            lines.append("  deploys:")
            for addr in value["deploys"]:
                who = next(c for c, a in fd.infra_ambiguous.items() if addr in a)
                lines.append(f'    {_flow(addr)}: ""  # {who}?')
        elif key == "system":
            lines.append(f"system: {_flow(value)}")
    for kind, dirs in fd.infra.items():
        if kind != "terraform":
            lines.append(f"# infra: {kind} in {', '.join(dirs)} (detected; only Terraform is read)")
    return "\n".join(lines) + "\n"


def render_report(fd: Findings, manifest_path: str | None) -> str:
    r = fd.repo_label
    out = [f"ad2v init: {r}", ""]
    if fd.existing_manifest:
        out.append(
            f"The repository has an {fd.existing_manifest}; compare with:"
            f" ad2v init --repo {r} --check {r}/ad2v.yaml"
        )
        out.append("")
    out.append("Spec folders (score; evidence = files per format):")
    if fd.spec_candidates:
        for c in fd.spec_candidates:
            ev = ", ".join(f"{k} {v}" for k, v in c["evidence"].items())
            pick = (
                "proposed"
                if c["path"] in fd.spec_roots or (c["path"] == "." and fd.spec_roots)
                else "not used"
            )
            out.append(f"  {c['path']}/  score {c['score']}  ({ev})  {pick}")
    else:
        out.append("  none recognized")
    if fd.spec_files:
        out.append("Spec files:")
        for f in fd.spec_files:
            out.append(f"  {f['path']}: {f['format']}")
    if fd.prose:
        out.append("Prose no preset reads (candidates for `ad2v specs bootstrap`):")
        out += [f"  {p}" for p in fd.prose]
    if fd.spec_id_prefixes:
        out.append("Spec id prefixes: " + ", ".join(fd.spec_id_prefixes))
    out.append("Containers:")
    if fd.containers:
        for c in fd.containers:
            how = "read by the python extractor" if c["read"] else "no active extractor: not_evaluable"
            out.append(f"  {c['name']} ({c['path']}/, {c['marker']}): {c['language']}, {how}")
    else:
        out.append("  none found below the root (the whole repository is one container)")
    if fd.excludes:
        out.append("Excluded folders (files dropped; code files of them):")
        for e in fd.excludes:
            tag = "default" if e["default"] else "proposed"
            out.append(f"  {e['pattern']}: {e['files']} ({e['code_files']} code)  [{tag}]")
    if fd.sql:
        out.append("SQL files (schema digests):")
        for s in fd.sql:
            warn = f"  WARNING: dropped by the exclude {s['dropped_by']!r}" if s["dropped_by"] else ""
            out.append(f"  {s['path']}{warn}")
    if fd.infra:
        out.append("Infrastructure as code:")
        for k, dirs in fd.infra.items():
            tag = "proposed infra_root" if k == "terraform" and fd.infra_roots else "detected; not read"
            out.append(f"  {k}: {', '.join(d + '/' for d in dirs)}  ({tag})")
        for c, units in sorted(fd.infra_matches.items()):
            out.append(f"  {c} is deployed by {', '.join(units)} (name match)")
        for c, units in sorted(fd.infra_ambiguous.items()):
            out.append(f"  {c}: several deployment units match ({', '.join(units)}); choose in infra.deploys")
        if fd.infra_roots:
            out.append("  For deployment facts per environment, produce a plan JSON yourself:")
            out.append(f"    {PLAN_COMMAND}")
            out.append(
                "  That runs the providers and needs credentials and state. ad2v never runs it; it only"
            )
            out.append(
                "  reads plan.json (--infra-plan prod=plan.json). Keep plan.json out of the repository."
            )
    tr = fd.test_results
    if tr.get("junit") or tr.get("pytest_config"):
        out.append("Test results:")
        if tr.get("junit"):
            out.append("  JUnit XML: " + ", ".join(tr["junit"]))
        if tr.get("pytest_config"):
            out.append(
                "  pytest config: " + ", ".join(tr["pytest_config"]) + " (run `pytest --junitxml <file>`)"
            )
    if fd.path_constants:
        out.append(
            f"Route prefixes the extractor cannot resolve ({fd.unresolved_routes} route(s)): "
            + ", ".join(fd.path_constants)
            + "; fill in pairing.path_constants"
        )
    if fd.capped:
        out.append(f"(read the first {MAX_MARKDOWN} Markdown files only)")
    if not fd.spec_roots:
        out.append("")
        out.append("No spec format recognized. If the specs are prose, propose spec files from them:")
        folder = fd.prose[0].rsplit("/", 1)[0] if fd.prose else "docs"
        out.append(f"  ad2v specs bootstrap --repo {r} --from {folder} --plan")
    out.append("")
    out.append("Next:")
    manifest = manifest_path or "<a file outside the repo>"
    if manifest_path is None:
        out.append(f"  ad2v init --repo {r} --write {manifest}")
    tests = f" --test-results {r}/{tr['junit'][0]}" if tr.get("junit") else ""
    out.append(f"  ad2v extract --repo {r} --manifest {manifest}{tests} --out {Path(r).name}.ad2v")
    if fd.prose and fd.spec_roots:
        out.append(f"  ad2v specs bootstrap --repo {r} --from {' --from '.join(fd.prose)} --plan")
    out.append(f"  ad2v view {Path(r).name}.ad2v")
    return "\n".join(out) + "\n"


def check(fd: Findings, existing: dict[str, Any]) -> list[str]:
    """Differences between an existing manifest and what `init` proposes today."""
    want = proposal(fd)
    diffs: list[str] = []
    have_roots = existing.get("spec_root") or []
    have_roots = [have_roots] if isinstance(have_roots, str) else list(have_roots)
    if have_roots:  # without spec_root the manifest relies on auto-detection: nothing to compare
        for r in want.get("spec_root", []):
            if r not in have_roots:
                diffs.append(f"new spec folder: {r}")
        for r in have_roots:
            if r not in want.get("spec_root", []):
                diffs.append(f"spec folder no longer recognized: {r}")
    have_c = {c.get("name"): c for c in existing.get("containers") or [] if isinstance(c, dict)}
    for c in want.get("containers", []):
        if c["name"] not in have_c:
            diffs.append(f"new container: {c['name']} ({c['paths'][0]})")
    for name in sorted(have_c):
        if name not in {c["name"] for c in want.get("containers", [])}:
            diffs.append(f"container not found any more: {name}")
    present = {e["pattern"] for e in fd.excludes}
    for e in existing.get("exclude") or []:
        if str(e) not in present and str(e) not in DEFAULT_EXCLUDES:
            diffs.append(f"stale exclude (matches nothing): {e}")
    have_prefixes = {
        str(x).upper()
        for x in (existing.get("spec_ids") or {}).get("test_name_prefixes") or DEFAULT_TEST_PREFIXES
    }
    missing = sorted(set(fd.spec_id_prefixes) - have_prefixes)
    if missing:
        diffs.append("test-name prefixes not listed: " + ", ".join(missing))
    have_pc = {  # an empty value is a placeholder, not an entry
        k
        for k, v in ((existing.get("pairing") or {}).get("path_constants") or {}).items()
        if v not in (None, "")
    }
    for k in fd.path_constants:
        if k not in have_pc:
            diffs.append(f"unresolved route prefix without a path_constants entry: {k}")
    have_ir = existing.get("infra_root") or []
    have_ir = [have_ir] if isinstance(have_ir, str) else list(have_ir)
    for r in fd.infra_roots:
        if r not in have_ir:
            diffs.append(f"Terraform folder not in infra_root: {r}")
    chosen = {  # an empty value is a placeholder
        k for k, v in ((existing.get("infra") or {}).get("deploys") or {}).items() if v not in (None, "", [])
    }
    for c, units in sorted(fd.infra_ambiguous.items()):
        if not chosen & set(units):
            diffs.append(f"ambiguous deployment for container {c}: {', '.join(units)} (set infra.deploys)")
    return diffs


def to_json(fd: Findings, manifest: dict[str, Any]) -> str:
    return json.dumps(
        {"findings": fd.to_dict(), "proposal": manifest}, indent=2, sort_keys=True, ensure_ascii=False
    )
