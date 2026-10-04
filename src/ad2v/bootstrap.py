"""`ad2v specs bootstrap / review / approve`: a guided wrapper around P4's `extract-prose` (P6.1, ADR-0049).

No new LLM logic. `bootstrap` takes any Markdown / text files or folders (also outside the spec
root: `docs/`, `NOTES.md`), keeps those that qualify (enough free prose, not parsed by a preset),
extracts them into a small workspace file (default `<repo>/.ad2v/bootstrap.ad2v`, which holds the
LLM cache), and runs `extract-prose` there:

- `--plan`: the qualifying files and the offline cost estimate (chars/4). No calls.
- `--yes --max-cost-usd X`: writes proposals to `<spec-root>/.ad2v-extracted/<slug>.md` in the
  ad2v convention with reserved `-X` ids (continuing after the -X ids already in the spec tree).

`index.json` next to the proposals records each proposal's source (repo-relative path and
content hash), so `review` can flag stale proposals and `approve` can refuse them. `approve`
moves a proposal into the spec tree: the human approval act, CLI-only, never overwriting.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ad2v import ids, ir, pipeline, specroots, store
from ad2v.extract.spec import markdown, presets
from ad2v.llm import prose
from ad2v.llm.suggest import tokens

INDEX = "index.json"
TEXT_SUFFIXES = (".md", ".markdown", ".txt")
X_ID_RE = re.compile(r"\b(REQ|CMP)-X([0-9]+)\b")


class BootstrapError(ValueError):
    pass


@dataclass
class Candidate:
    path: Path  # absolute
    rel: str  # repo-relative POSIX
    qualifies: bool
    reason: str
    prose_chars: int


def _rel(repo: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def spec_root_of(repo: Path, given: str | None, manifest: Path | None = None) -> Path:
    """`--spec-root`, else the first resolved spec root directory, else `<repo>/specs`."""
    if given:
        p = Path(given)
        return (p if p.is_absolute() else repo / p).resolve()
    from ad2v.manifest import load as load_manifest

    cfg = load_manifest(repo, manifest)
    sr = specroots.resolve(repo, None, list(cfg.spec_roots), cfg.exclude, True, cfg.spec_markdown)
    dirs = [r for r in sr.roots if r.is_dir()]
    return dirs[0] if dirs else (repo / "specs").resolve()


def candidates(repo: Path, sources: list[Path], rules: list[dict[str, Any]] | None = None) -> list[Candidate]:
    files: list[Path] = []
    root = repo.resolve()
    for s in sources:
        # relative to the repository, like --spec-root (ADR-0052); proposals must track a repo path
        s = Path(s) if Path(s).is_absolute() else root / s
        if s.exists() and not s.resolve().is_relative_to(root):
            raise BootstrapError(f"--from must be inside the repository: {s}")
        if s.is_dir():
            files += sorted(
                p
                for p in s.rglob("*")
                if p.is_file() and p.suffix in TEXT_SUFFIXES and prose.EXTRACTED_DIR not in p.parts
            )
        elif s.is_file():
            files.append(s)
        else:
            raise BootstrapError(f"--from not found: {s}")
    out: list[Candidate] = []
    for p in sorted(set(f.resolve() for f in files)):
        rel = _rel(repo, p)
        text = ids.read_normalized(p)
        if p.suffix not in TEXT_SUFFIXES:
            out.append(Candidate(p, rel, False, "not a Markdown or text file", 0))
            continue
        ch = presets.choose(rel, text, rules or [])
        g = ir.Graph()
        markdown.extract(g, rel, text)
        doc = g.nodes[ids.node_id("spec", "spec_doc", rel)]
        chars = len((doc.attrs.get("prose") or "").strip())
        if ch is not None:
            out.append(Candidate(p, rel, False, f"already parsed by the {ch.preset} preset", chars))
        elif chars < prose.MIN_PROSE_CHARS:
            out.append(Candidate(p, rel, False, f"too little prose ({chars} chars)", chars))
        else:
            out.append(Candidate(p, rel, True, "free prose", chars))
    return out


def _next_x(spec_root: Path) -> tuple[int, int]:
    """The next free REQ-X / CMP-X numbers: after every -X id in the spec tree and its proposals."""
    req = cmp = 0
    if spec_root.is_dir():
        for p in spec_root.rglob("*"):
            if p.is_file() and p.suffix in TEXT_SUFFIXES:
                for kind, n in X_ID_RE.findall(p.read_text(encoding="utf-8", errors="replace")):
                    if kind == "REQ":
                        req = max(req, int(n))
                    else:
                        cmp = max(cmp, int(n))
    return req + 1, cmp + 1


def _workspace(repo: Path, qualifying: list[Candidate], cache: Path) -> Path:
    cache.parent.mkdir(parents=True, exist_ok=True)
    pipeline.extract_to_file(
        repo, [c.path for c in qualifying], cache, into=cache.exists(), spec_autodetect=False
    )
    return cache


def bootstrap(
    repo: Path,
    sources: list[Path],
    cfg: Any,
    *,
    spec_root: Path,
    cache: Path | None = None,
    plan_only: bool = True,
    max_cost_usd: float | None = None,
    provider: Any = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from ad2v.llm import api as llm_api

    repo = Path(repo).resolve()
    cands = candidates(repo, sources, rules)
    qual = [c for c in cands if c.qualifies]
    report: dict[str, Any] = {
        "files": [
            {"path": c.rel, "qualifies": c.qualifies, "reason": c.reason, "prose_chars": c.prose_chars}
            for c in cands
        ],
        "spec_root": _rel(repo, spec_root),
    }
    if not qual:
        report["note"] = "no file qualifies"
        return report
    cache = Path(cache) if cache else repo / ".ad2v" / "bootstrap.ad2v"
    _workspace(repo, qual, cache)
    first_req, first_cmp = _next_x(spec_root)
    opts = {"spec_root": str(spec_root), "first_req": first_req, "first_cmp": first_cmp}
    if plan_only:
        r = llm_api.plan(cache, cfg, ["extract-prose"], provider=provider, opts=opts)
        report["plan"] = {
            k: r["tasks"]["extract-prose"][k]
            for k in ("jobs", "hits", "misses", "est_input_tokens", "est_output_tokens", "est_cost_usd")
        }
        report["priced"] = r["priced"]
        return report
    if max_cost_usd is None:
        raise BootstrapError("a run needs --max-cost-usd and --yes")
    r = llm_api.run(cache, cfg, ["extract-prose"], max_cost_usd, provider=provider, opts=opts)
    report["run"] = {"calls": r["totals"]["calls"], "spent_usd": r["spent_usd"], "aborted": r["aborted"]}
    report["proposals"] = _index_run(repo, cache, qual, spec_root)
    return report


def _index_run(repo: Path, cache: Path, qual: list[Candidate], spec_root: Path) -> list[dict[str, Any]]:
    """Record source path + hash of each proposal written by this run in index.json."""
    by_doc: dict[str, Candidate] = {}
    for c in qual:
        by_doc[c.path.name] = c  # single file root: the doc is named by the file name
        by_doc[c.rel] = c
    conn = store.open_readonly(cache)
    try:
        head = store.head_epoch(conn)
        rows = conn.execute(
            "SELECT e.output_path, e.state, n.qualified_name, x.model, x.model_version FROM "
            "spec_extractions e"
            " JOIN nodes n ON n.id = e.spec_doc_node_id AND n.epoch_id = e.epoch_id"
            " JOIN llm_results x ON x.result_id = e.result_id WHERE e.epoch_id = ? ORDER BY e.output_path",
            (head,),
        ).fetchall()
    finally:
        conn.close()
    idx_path = spec_root / prose.EXTRACTED_DIR / INDEX
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.is_file() else {}
    out = []
    for target, state, qn, model, version in rows:
        c = by_doc.get(qn) or by_doc.get(qn.rsplit("/", 1)[-1])
        if c is None or state != "written":
            continue
        name = Path(target).name
        entry = {
            "source": c.rel,
            "source_hash": ids.content_hash(ids.read_normalized(c.path)),
            "model": model,
            "model_version": version,
        }
        idx[name] = entry
        out.append({"proposal": f"{prose.EXTRACTED_DIR}/{name}", **entry})
    if out:
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(
            json.dumps(dict(sorted(idx.items())), indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    return out


# -- review / approve -------------------------------------------------------------------------------
def _existing_specs(repo: Path, spec_root: Path) -> list[tuple[str, str]]:
    """(id, text) of the spec items already in the tree (any preset), for overlap checks."""
    if not spec_root.is_dir():
        return []
    from ad2v.manifest import DEFAULT_EXCLUDES

    sr = specroots.SpecRoots([spec_root], [specroots.label(repo, spec_root)], "cli")
    files = specroots.collect(sr, DEFAULT_EXCLUDES)  # never the proposals themselves
    g = ir.Graph()
    from ad2v.extract.spec import extract_specs

    extract_specs(g, spec_root, DEFAULT_EXCLUDES, files=files, choices=sr.choices)
    return sorted(
        (n.qualified_name, str(n.attrs.get("text") or n.name))
        for n in g.nodes.values()
        if n.kind in ("requirement", "spec_component")
    )


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def review(repo: Path, spec_root: Path, overlap_min: float = 0.5) -> list[dict[str, Any]]:
    repo = Path(repo).resolve()
    xdir = spec_root / prose.EXTRACTED_DIR
    idx = json.loads((xdir / INDEX).read_text(encoding="utf-8")) if (xdir / INDEX).is_file() else {}
    existing = [(q, tokens(t)) for q, t in _existing_specs(repo, spec_root)]
    out = []
    for p in sorted(xdir.glob("*.md")) if xdir.is_dir() else []:
        text = ids.read_normalized(p)
        g = ir.Graph()
        markdown.extract(g, p.name, text)
        reqs = [n for n in g.nodes.values() if n.kind == "requirement"]
        comps = [n for n in g.nodes.values() if n.kind == "spec_component"]
        overlaps = []
        for r in sorted(reqs, key=lambda n: n.qualified_name):
            rt = tokens(str(r.attrs.get("text", "")))
            best = max(((round(_jaccard(rt, et), 2), q) for q, et in existing), default=(0.0, None))
            if best[0] >= overlap_min:
                overlaps.append({"proposed": r.qualified_name, "existing": best[1], "overlap": best[0]})
        ent = idx.get(p.name, {})
        src = repo / ent["source"] if ent.get("source") else None
        if not ent:
            stale = None
        elif src is None or not src.is_file():
            stale = True
        else:
            stale = ids.content_hash(ids.read_normalized(src)) != ent.get("source_hash")
        clash = sorted({n.qualified_name for n in reqs + comps} & {q for q, _ in existing})
        out.append(
            {
                "proposal": f"{prose.EXTRACTED_DIR}/{p.name}",
                "source": ent.get("source"),
                "source_hash": (ent.get("source_hash") or "")[:12] or None,
                "model": ent.get("model"),
                "components": len(comps),
                "requirements": len(reqs),
                "overlaps": overlaps,
                "id_clashes": clash,
                "stale": stale,
            }
        )
    return out


def approve(
    repo: Path, spec_root: Path, proposal: str, to: Path | None = None, force_stale: bool = False
) -> Path:
    repo = Path(repo).resolve()
    xdir = spec_root / prose.EXTRACTED_DIR
    src = Path(proposal)
    if not src.is_absolute():
        src = xdir / src.name if (xdir / src.name).is_file() else (repo / proposal)
    if not src.is_file() or src.parent.resolve() != xdir.resolve():
        raise BootstrapError(f"no proposal {proposal!r} in {_rel(repo, xdir)}")
    info = next((r for r in review(repo, spec_root) if Path(r["proposal"]).name == src.name), None)
    if info and info["stale"] and not force_stale:
        raise BootstrapError(
            f"{src.name}: the source {info['source']} changed since extraction (re-run bootstrap, or "
            f"--force-stale)"
        )
    if info and info["id_clashes"]:
        raise BootstrapError(f"{src.name}: ids already in the spec tree: {', '.join(info['id_clashes'])}")
    dest_dir = Path(to) if to else spec_root
    dest_dir = dest_dir if dest_dir.is_absolute() else (repo / dest_dir)
    if not dest_dir.resolve().is_relative_to(repo):  # P8 (docs/security.md §7)
        raise BootstrapError(f"--to must be inside the repository: {to}")
    dest = dest_dir / src.name
    if dest.exists():
        raise BootstrapError(f"refusing to overwrite {_rel(repo, dest)}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    idx_path = xdir / INDEX
    if idx_path.is_file():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        idx.pop(src.name, None)
        idx_path.write_text(
            json.dumps(dict(sorted(idx.items())), indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    return dest
