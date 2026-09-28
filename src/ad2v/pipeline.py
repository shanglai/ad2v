"""End-to-end extraction: repo + specs -> IR -> .ad2v file."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ad2v import glyphs, ids, ir, store, workflows
from ad2v.extract import files as filewalk
from ad2v.extract.code.base import CodeFacts, Layout
from ad2v.extract.code.python import PythonExtractor, load_rules
from ad2v.extract.spec import extract_specs
from ad2v.manifest import Config
from ad2v.manifest import load as load_manifest


@dataclass
class Result:
    graph: ir.Graph
    facts: CodeFacts
    workflows: list[ir.Workflow]
    glyphs: list[ir.Glyph]
    epoch: store.Epoch
    config: Config
    meta: dict[str, str]
    elapsed_s: float = 0.0
    stats: dict[str, int] = field(default_factory=dict)


def read_git_head(repo: Path) -> str | None:
    """Read HEAD's commit from <repo>/.git without running git. Never raises."""
    try:
        git = repo / ".git"
        if not git.is_dir():
            return None
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head[4:].strip()
        ref_file = git / ref
        if ref_file.is_file():
            return ref_file.read_text(encoding="utf-8").strip() or None
        packed = git / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        return None
    return None


def rules_hash(rules_files: dict[str, str]) -> str:
    """Tree hash over {rules file name: content_hash of its normalized text} (format spec §2)."""
    return ids.tree_hash(rules_files)


def build(
    repo: Path, spec: Path | None = None, manifest: Path | None = None, rules_path: Path | None = None
) -> Result:
    t0 = time.perf_counter()
    repo = Path(repo).resolve()
    config = load_manifest(repo, manifest)
    rules = load_rules(rules_path)
    r_hash = rules_hash({"python.yaml": rules["_hash"]})
    graph = ir.Graph()
    system_name = config.system_name or repo.name
    layout = Layout(graph, config, repo, system_name)

    extractor = PythonExtractor(config, rules)
    rel = filewalk.walk(repo, config.exclude, extractor.suffixes)
    spec_root = Path(spec).resolve() if spec is not None else None
    if spec_root is not None and spec_root != repo and spec_root.is_relative_to(repo):
        spec_rel = spec_root.relative_to(repo).as_posix()
        rel = [p for p in rel if not p.startswith(spec_rel + "/")]
    facts = extractor.extract(graph, layout, filewalk.load(repo, rel))

    spec_files: dict[str, str] = {}
    if spec_root is not None:
        spec_files = extract_specs(graph, spec_root, config.exclude)

    resolve_spec_refs(graph)
    graph.link_contains()
    graph.compute_subtree_hashes()

    wfs = workflows.build_all(graph, facts, config)
    gl = glyphs.compute(graph)

    repo_tree = ids.tree_hash(facts.files_read)
    spec_tree = ids.tree_hash(spec_files)
    epoch = store.Epoch(
        epoch_id=ids.epoch_id(None, repo_tree, spec_tree, r_hash),
        repo_tree_hash=repo_tree,
        spec_tree_hash=spec_tree,
        rules_hash=r_hash,
        repo_commit=read_git_head(repo),
        attrs={**config.echo(), "rules_version": str(rules["rules_version"])},
    )
    meta = {
        "repo_root_name": repo.name,
        "rules_version": str(rules["rules_version"]),
        "system_name": system_name,
    }
    res = Result(graph, facts, wfs, gl, epoch, config, meta)
    res.elapsed_s = time.perf_counter() - t0
    res.stats = {
        "files_code": len(facts.files_read),
        "files_spec": len(spec_files),
        "loc_code": sum(
            (n.span_end_line or 0) for n in graph.nodes.values() if n.kind == "module" and n.side == "code"
        ),
    }
    return res


def resolve_spec_refs(graph: ir.Graph) -> None:
    """Turn explicit spec IDs into `annotated_as` edges or `unresolved_refs` rows."""
    by_qname: dict[str, list[str]] = {}
    for nid, n in sorted(graph.nodes.items()):
        if n.side == "spec":
            by_qname.setdefault(n.qualified_name, []).append(nid)
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        for ref in sorted(set(n.spec_ref)):
            targets = [t for t in by_qname.get(ref, []) if t != nid]
            if targets:
                for t in targets:
                    graph.add_edge(nid, t, "annotated_as", attrs={"ref": ref})
            elif ref not in by_qname:
                graph.unresolved.append(ir.UnresolvedRef(nid, ref, "spec_id", "not_found"))


def extract_to_file(
    repo: Path, spec: Path | None, out: Path, manifest: Path | None = None, rules_path: Path | None = None
) -> Result:
    res = build(repo, spec, manifest, rules_path)
    t0 = time.perf_counter()
    store.write(out, res.graph, res.epoch, res.glyphs, res.workflows, res.meta)
    res.elapsed_s += time.perf_counter() - t0
    return res
