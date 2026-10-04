"""End-to-end extraction: repo + specs -> IR -> an epoch in a .ad2v file.

`build()` computes one epoch in memory (optionally against a parent epoch for lineage and
history). `extract_to_file()` writes it: a fresh file (`--out`) or a new head epoch appended to
an existing file (`--into`), reusing that file's parse cache.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v import (
    glyphs,
    history,
    ids,
    ir,
    junit,
    layout,
    materialize,
    pairing,
    severity,
    specroots,
    store,
    workflows,
)
from ad2v import rules as rules_mod
from ad2v.extract import files as filewalk
from ad2v.extract.code import schema_digest
from ad2v.extract.code.base import CodeFacts, Layout
from ad2v.extract.code.python import PythonExtractor
from ad2v.extract.code.python_local import LOCAL_EXTRACTOR_VERSION
from ad2v.extract.spec import extract_specs, spec_tree_hash
from ad2v.manifest import Config
from ad2v.manifest import load as load_manifest

CacheLoader = Callable[[str], dict[tuple[str, str], Any]]


@dataclass
class Parent:
    """What a new epoch needs from its parent (loaded from the file)."""

    epoch: store.Epoch
    graph: ir.Graph
    link_state: dict[str, dict[str, Any]]
    tests: dict[str, ir.TestResult]


@dataclass
class Result:
    graph: ir.Graph
    facts: CodeFacts
    workflows: list[ir.Workflow]
    glyphs: list[ir.Glyph]
    epoch: store.Epoch
    config: Config
    meta: dict[str, str]
    pairing: pairing.PairingResult
    tests: junit.Ingested
    ranked_behaviors: list[str]
    rules: dict[str, Any] = field(default_factory=dict)
    lineage: history.Lineage = field(default_factory=history.Lineage)
    link_state: list[dict[str, Any]] = field(default_factory=list)
    cache_entries: dict[str, tuple[str, Any]] = field(default_factory=dict)
    elapsed_s: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    unchanged: bool = False  # inputs identical to the parent: no epoch was built
    lineage_names: dict[str, str] = field(default_factory=dict)  # old id -> parent qualified name
    sources: dict[str, str] = field(default_factory=dict)  # content_hash -> normalized file text
    spec_roots: specroots.SpecRoots = field(
        default_factory=specroots.SpecRoots
    )  # P6.1: where specs came from

    @property
    def derived(self) -> store.Derived:
        return store.Derived(self.glyphs, self.workflows, self.pairing)


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


def resolve_spec_refs(graph: ir.Graph) -> None:
    """Turn explicit spec IDs into `annotated_as` edges or `unresolved_refs` rows."""
    by_qname: dict[str, list[str]] = {}
    for nid, n in sorted(graph.nodes.items()):
        if n.side == "spec":
            by_qname.setdefault(n.qualified_name, []).append(nid)
    namespaced: dict[str, list[str]] = {}  # bare id -> ids of namespaced spec items (`ns:FR-001`)
    for q, nids in by_qname.items():
        if ":" in q and not q.startswith(("http", "cli:", "mcp:")) and ".md::" not in q:
            namespaced.setdefault(q.split(":", 1)[1], []).extend(nids)
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        hints = n.attrs.get("spec_ref_hints", {})
        for ref in sorted(set(n.spec_ref)):
            targets = [t for t in by_qname.get(ref, []) if t != nid]
            if not targets and ":" not in ref and ref in namespaced:
                # a bare `FR-001`: resolves only if exactly one namespace has it (after a test-name hint);
                # otherwise every candidate is linked as needs_review, never guessed (ADR-0048)
                cands = sorted(t for t in namespaced[ref] if t != nid)
                hint = hints.get(ref)
                if hint:
                    hinted = [t for t in cands if _namespace_matches(graph.nodes[t].qualified_name, hint)]
                    cands = hinted or cands
                if len(cands) == 1:
                    graph.add_edge(nid, cands[0], "annotated_as", attrs={"ref": ref})
                else:
                    names = sorted(graph.nodes[t].qualified_name for t in cands)
                    for t in cands:
                        graph.add_edge(nid, t, "annotated_as", attrs={"ref": ref, "ambiguous": names})
                continue
            if targets:
                for t in targets:
                    graph.add_edge(nid, t, "annotated_as", attrs={"ref": ref})
            elif ref not in by_qname:
                graph.unresolved.append(ir.UnresolvedRef(nid, ref, "spec_id", "not_found"))


def _namespace_matches(qname: str, hint: str) -> bool:
    """`003-payments:FR-001` matches the test-name hint `payments` (or `003_payments`)."""
    ns = qname.split(":", 1)[0]
    base = re.sub(r"^[0-9]+(?:-[0-9]+)*-", "", ns)
    return hint in (ns.replace("-", "_"), base.replace("-", "_"))


def _carry_tests(parent: Parent, graph: ir.Graph, lineage: history.Lineage) -> dict[str, ir.TestResult]:
    """Test results carry forward when none are given (mapped through lineage, dropped if gone)."""
    out = {}
    for tid, t in sorted(parent.tests.items()):
        nid = lineage.forward.get(tid, tid)
        if nid in graph.nodes:
            out[nid] = ir.TestResult(nid, t.outcome, t.source_file, t.duration_ms)
    return out


def build(
    repo: Path,
    spec: Path | list[Path] | None = None,
    manifest: Path | None = None,
    rules_path: Path | None = None,
    test_results: list[Path] | None = None,
    *,
    parent: Parent | None = None,
    cache_loader: CacheLoader | None = None,
    name_hint: str | None = None,
    repo_commit: str | None = None,
    seq: int = 1,
    spec_autodetect: bool = True,
) -> Result:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = timings.get(name, 0.0) + now - since
        return now

    repo = Path(repo).resolve()
    config = load_manifest(repo, manifest)
    rules = rules_mod.load(rules_path, config.rules_overlay)
    system_name = config.system_name or name_hint or repo.name
    extractor = PythonExtractor(config, rules)
    rel = filewalk.walk(repo, config.exclude, extractor.suffixes)
    cli_specs = None if spec is None else [Path(spec)] if isinstance(spec, (str, Path)) else list(spec)
    sroots = specroots.resolve(
        repo, cli_specs, list(config.spec_roots), config.exclude, spec_autodetect, config.spec_markdown
    )
    for root in sroots.roots:  # spec files inside the repo never count as code
        if root.is_dir() and root != repo and root.is_relative_to(repo):
            spec_rel = root.relative_to(repo).as_posix()
            rel = [p for p in rel if not p.startswith(spec_rel + "/")]
    files = filewalk.load(repo, rel)
    # P7 (ADR-0059): SQL DDL feeds the datastore schema digests, so it is an epoch input
    spec_prefixes = tuple(
        r.relative_to(repo).as_posix() + "/"
        for r in sroots.roots
        if r.is_dir() and r != repo and r.is_relative_to(repo)
    )
    sql_rel = [
        p
        for p in filewalk.walk(repo, config.exclude, (".sql",))
        if not (spec_prefixes and p.startswith(spec_prefixes))
    ]
    sql_files = filewalk.load(repo, sql_rel)
    specs = specroots.collect(sroots, config.exclude, config.spec_markdown)
    config.effective_spec_roots = tuple(sroots.labels)
    config.spec_presets = {p: ch.preset for p, ch in sroots.choices.items()}
    tests_given = bool(test_results)
    tr_paths = [Path(t) for t in test_results or []]
    repo_tree = ids.tree_hash({f.path: f.content_hash for f in [*files, *sql_files]})
    spec_tree = spec_tree_hash(specs)
    if tests_given:
        tests_hash = junit.files_hash(tr_paths, repo)
    else:
        tests_hash = parent.epoch.test_results_hash if parent else ids.tree_hash({})
    t = lap("read_inputs", t0)
    hashes = (repo_tree, spec_tree, rules["_hash"], config.config_hash, tests_hash)
    epoch = store.Epoch(
        epoch_id=ids.epoch_id(parent.epoch.epoch_id if parent else None, *hashes),
        repo_tree_hash=repo_tree,
        spec_tree_hash=spec_tree,
        rules_hash=rules["_hash"],
        config_hash=config.config_hash,
        test_results_hash=tests_hash,
        parent_epoch_id=parent.epoch.epoch_id if parent else None,
        repo_commit=repo_commit if repo_commit is not None else read_git_head(repo),
        seq=seq,
    )
    epoch.change_kind = store.change_kind(parent.epoch if parent else None, epoch)
    if parent is not None and epoch.input_hashes == parent.epoch.input_hashes:
        res = Result(
            ir.Graph(),
            CodeFacts(),
            [],
            [],
            epoch,
            config,
            {},
            pairing.PairingResult([], {}, {}),
            junit.Ingested(),
            [],
            rules=rules,
            unchanged=True,
            spec_roots=sroots,
        )
        res.elapsed_s = time.perf_counter() - t0
        return res

    graph = ir.Graph()
    layout = Layout(graph, config, repo, system_name)
    cache = cache_loader(rules["_hash"]) if cache_loader is not None else None
    facts = extractor.extract(graph, layout, files, cache)
    schema_digest.apply(graph, files, sql_files)
    t = lap("code_extraction", t)
    timings.update({f"code.{k}": v for k, v in extractor.timings.items()})
    if sroots.roots:
        extract_specs(
            graph, sroots.roots[0], config.exclude, root_name=system_name, files=specs, choices=sroots.choices
        )
    resolve_spec_refs(graph)
    graph.link_contains()
    graph.compute_subtree_hashes()
    t = lap("specs_refs_hashes", t)
    wfs = workflows.build_all(graph, facts, config)
    ranked = severity.apply(graph, wfs, rules)
    t = lap("workflows_severity", t)
    lineage = history.compute_lineage(parent.graph, graph) if parent is not None else history.Lineage()
    if tests_given:
        tests = junit.ingest(tr_paths, repo, graph)
    else:
        tests = junit.Ingested(results=_carry_tests(parent, graph, lineage) if parent else {})
    tests_fresh = tests_given and (parent is None or tests_hash != parent.epoch.test_results_hash)
    links, warnings = pairing.pair_links(graph, config, tests.results)
    link_state = history.apply_history(
        graph,
        links,
        epoch.epoch_id,
        parent.graph if parent else None,
        parent.link_state if parent else None,
        lineage if parent else None,
        tests_fresh,
    )
    paired = pairing.finalize(graph, links, warnings, lineage.ambiguous_reasons())
    gl = glyphs.compute(graph)
    t = lap("lineage_pairing_status", t)
    coverage = pairing.spec_coverage(graph)
    epoch.attrs = {
        **config.echo(),
        "pairing_warnings": paired.warnings,
        "rules_version": str(rules["rules_version"]),
        "spec_coverage": coverage,
        "test_cases": tests.cases,
        "tests_carried": parent is not None and not tests_given,
        "tests_fresh": tests_fresh,
        "unmatched_tests": tests.unmatched,
    }
    meta = {
        "repo_root_name": repo.name,
        "rules_version": str(rules["rules_version"]),
        "spec_coverage": coverage,
        "system_name": system_name,
    }
    res = Result(
        graph,
        facts,
        wfs,
        gl,
        epoch,
        config,
        meta,
        paired,
        tests,
        ranked,
        rules,
        lineage,
        link_state,
        dict(extractor.new_cache_entries),
    )
    res.timings = timings
    res.spec_roots = sroots
    res.sources = {f.content_hash: f.text for f in files} | {ids.content_hash(t): t for _, _, t in specs}
    if parent is not None:
        res.lineage_names = {o: parent.graph.nodes[o].qualified_name for o, _, _, _ in lineage.rows}
    res.elapsed_s = time.perf_counter() - t0
    res.stats = {
        "files_code": len(facts.files_read),
        "files_spec": len(specs),
        "loc_code": sum(
            (n.span_end_line or 0) for n in graph.nodes.values() if n.kind == "module" and n.side == "code"
        ),
        "cache_hits": extractor.cache_hits,
        "cache_misses": extractor.cache_misses,
    }
    return res


def load_parent(conn: sqlite3.Connection) -> Parent | None:
    head = store.head_epoch(conn)
    if head is None:
        return None
    return Parent(
        epoch=store.get_epoch(conn, head),
        graph=store.load_graph(conn, head),
        link_state=store.load_link_state(conn, head),
        tests=store.load_tests(conn, head),
    )


def write_epoch(conn: sqlite3.Connection, res: Result, parent: Parent | None) -> None:
    """Write a built epoch as the new head; keep derived rows only for head and pinned epochs."""
    store.insert_epoch(conn, res.epoch, res.rules, res.config.config_json)
    res.stats.update(
        store.write_base(
            conn,
            res.epoch.epoch_id,
            res.graph,
            res.facts,
            res.tests.results.values(),
            res.lineage.rows,
            res.link_state,
        )
    )
    if parent is not None:  # drop first: the freed pages are reused by the new rows
        pinned = conn.execute(
            "SELECT pinned FROM epochs WHERE epoch_id = ?", (parent.epoch.epoch_id,)
        ).fetchone()
        if not (pinned and pinned[0]):
            store.drop_derived(conn, parent.epoch.epoch_id)
    store.write_derived(conn, res.epoch.epoch_id, res.derived)
    store.write_parse_cache(conn, res.cache_entries, res.rules["_hash"], LOCAL_EXTRACTOR_VERSION)
    store.write_sources(conn, res.sources)
    store.set_meta(conn, {**res.meta, "head_epoch": res.epoch.epoch_id})


def extract_to_file(
    repo: Path,
    spec: Path | list[Path] | None,
    out: Path,
    manifest: Path | None = None,
    rules_path: Path | None = None,
    test_results: list[Path] | None = None,
    *,
    into: bool = False,
    use_cache: bool = True,
    name_hint: str | None = None,
    repo_commit: str | None = None,
    spec_autodetect: bool = True,
) -> Result:
    """`--out` (into=False): fresh single-epoch file. `--into`: append an epoch if inputs changed."""
    out = Path(out)
    t0 = time.perf_counter()
    conn = store.open_rw(out) if into and out.exists() else store.create(out)
    try:
        t_parent = time.perf_counter()
        parent = load_parent(conn)
        t_parent = time.perf_counter() - t_parent
        seq_row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM epochs").fetchone()
        loader: CacheLoader | None = None
        if use_cache:

            def loader(rules_hash: str) -> dict[tuple[str, str], Any]:
                return store.load_parse_cache(conn, rules_hash, LOCAL_EXTRACTOR_VERSION)

        res = build(
            repo,
            spec,
            manifest,
            rules_path,
            test_results,
            parent=parent,
            cache_loader=loader,
            name_hint=name_hint,
            repo_commit=repo_commit,
            seq=int(seq_row[0]) + 1,
            spec_autodetect=spec_autodetect,
        )
        res.timings["load_parent"] = t_parent
        if res.unchanged:
            return res
        t1 = time.perf_counter()
        with conn:
            conn.execute("PRAGMA defer_foreign_keys = ON")
            write_epoch(conn, res, parent)
        res.timings["write"] = time.perf_counter() - t1
        t2 = time.perf_counter()
        with conn:  # deterministic layout of the new epoch (inherits the parent's grid slots)
            layout.ensure(conn, [res.epoch.epoch_id])
        res.timings["layout"] = time.perf_counter() - t2
        if into and conn.execute("SELECT 1 FROM llm_results LIMIT 1").fetchone():
            from ad2v.llm import api as llm_api  # informative rows of the new head, from the cache only
            from ad2v.llm.config import from_data as llm_config

            with conn:
                res.stats["llm_rebuild"] = llm_api.rebuild(
                    conn, res.epoch.epoch_id, llm_config(res.config.llm_data)
                )
    finally:
        conn.close()
    res.elapsed_s = time.perf_counter() - t0
    return res


def materialize_epoch(path: Path, epoch_ref: str) -> tuple[str, bool]:
    conn = store.open_rw(Path(path))
    try:
        e = store.resolve_epoch(conn, epoch_ref)
        with conn:
            did = materialize.materialize(conn, e)
            laid = layout.ensure(conn, [e])  # the viewer needs a layout for every materialized epoch
        return e, did or bool(laid)
    finally:
        conn.close()
