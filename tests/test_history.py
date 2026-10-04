"""P3 history: lineage, stale, diff, view equivalence, determinism, prune/GC, CLI (needs git)."""

import re
import shutil

import pytest
import yaml
from history_scenario import REQ3_FP, Scenario, git_available

from ad2v import admin, diff, dump, gitsource, ids, materialize, pipeline, store
from ad2v.cli import main
from ad2v.validate import validate

from helpers import FIXTURE

pytestmark = pytest.mark.skipif(not git_available(), reason="git is not installed; history tests need it")
EXPECTED = yaml.safe_load((FIXTURE / "expected-history.yaml").read_text(encoding="utf-8"))
SPEC, JUNIT = "specs", ["test-results/junit.xml"]


def _history(sc: Scenario, out):
    """Two calls: the first commit alone, then the rest (a range excludes its start)."""
    first = sc.commits[0][1]
    res = gitsource.run_history(sc.repo, f"{first}^!", out, SPEC, JUNIT)
    res += gitsource.run_history(sc.repo, f"{first}..HEAD", out, SPEC, JUNIT)
    return res


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    root = tmp_path_factory.mktemp("history")
    sc = Scenario(root).build()
    out = root / "h.ad2v"
    results = _history(sc, out)
    return sc, out, results


def _status(res, side, kind, qname):
    return res.pairing.statuses[ids.node_id(side, kind, qname)].status


def _links(res):
    g = res.graph
    out = {}
    for lk in res.pairing.links:
        if lk.spec_node_id and lk.code_node_id:
            hist = [e["kind"] for e in lk.evidence if e["kind"] in diff.HISTORY_KINDS]
            out[(g.nodes[lk.spec_node_id].qualified_name, g.nodes[lk.code_node_id].qualified_name)] = (
                lk.status,
                hist,
            )
    return out


def test_epoch_by_epoch(scenario):
    sc, _out, results = scenario
    assert [label for label, _ in sc.commits] == [e["commit"] for e in EXPECTED["epochs"]]
    assert len(results) == len(EXPECTED["epochs"])
    for (commit, res), want in zip(results, EXPECTED["epochs"], strict=True):
        assert not res.unchanged
        assert res.epoch.repo_commit == commit
        assert res.epoch.change_kind == want["change_kind"], want["commit"]
        lineage = [
            [res.lineage_names[o], res.graph.nodes[n].qualified_name, m]
            for o, n, m, _ in res.lineage.rows
            if m != "ambiguous"
        ]
        assert lineage == want["lineage"], want["commit"]
        for side, kind, qname, status in want["statuses"]:
            assert _status(res, side, kind, qname) == status, (want["commit"], qname)
        links = _links(res)
        for spec_q, code_q, status, hist in want.get("links", []):
            assert links[(spec_q, code_q)] == (status, hist), (want["commit"], spec_q, code_q)


def test_fingerprint_is_the_spec_content_hash(scenario):
    _sc, _out, results = scenario
    res = results[-1][1]
    req3 = res.graph.nodes[ids.node_id("spec", "requirement", "REQ-003")]
    assert req3.content_hash[:8] == REQ3_FP


def test_fingerprint_mismatch_makes_stale_immediately(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURE, repo)
    m = repo / "api" / "recon_api" / "matching.py"
    m.write_text(
        m.read_text(encoding="utf-8").replace("# ad2v: REQ-003\n", "# ad2v: REQ-003@00000000\n"),
        encoding="utf-8",
        newline="\n",
    )
    res = pipeline.build(repo, repo / "specs", test_results=[repo / "test-results" / "junit.xml"])
    links = _links(res)
    assert links[("REQ-003", "api/recon_api/matching.py::amounts_match")] == (
        "stale",
        ["fingerprint_mismatch"],
    )


def test_diffs(scenario):
    _sc, out, _results = scenario
    conn = store.open_readonly(out)
    try:
        rows = store.epoch_rows(conn)
        eid = {r["seq"]: r["epoch_id"] for r in rows}
        for key, want in EXPECTED["diffs"].items():
            a, b = (int(x) for x in key.split("->"))
            d = diff.diff(conn, eid[a], eid[b])
            if "counts" in want:
                assert d["status_transitions"]["counts"] == want["counts"], key
            if "spec_changed" in want:
                assert d["spec"]["changed"] == want["spec_changed"], key
            if "new_risks" in want:
                assert len(d["risk"]["new"]) == want["new_risks"], key
            if "modified" in want:
                assert sorted(x["qualified_name"] for x in d["nodes"]["modified"]) == want["modified"], key
            if "renamed" in want:
                got = [[r["from"], r["to"], r["method"]] for r in d["nodes"]["renamed"]]
                assert got == want["renamed"], key
            if "added_contains" in want:
                added = {x["qualified_name"] for x in d["nodes"]["added"]}
                assert set(want["added_contains"]) <= added, key
            md = diff.to_markdown(d)
            assert len(md.splitlines()) <= diff.MD_MAX_LINES
            assert md.startswith("### ad2v: epoch #")
    finally:
        conn.close()


def _base_rows(path, epoch):
    """Base facts of one epoch through the views, epoch_id stripped."""
    conn = store.connect(path)
    out = {}
    for view, order in dump.VIEW_ORDER.items():
        cols = [c for c in store.columns(conn, view) if c != "epoch_id"]
        out[view] = conn.execute(
            f"SELECT {', '.join(cols)} FROM {view} WHERE epoch_id = ? ORDER BY {', '.join(order[1:])}",
            (epoch,),
        ).fetchall()
        out[view] = [tuple(r) for r in out[view]]
    conn.close()
    return out


def test_views_equal_fresh_single_epoch_extraction(scenario, tmp_path):
    sc, out, results = scenario
    for i, (commit, res) in enumerate(results):
        tree = tmp_path / f"t{i}"
        tree.mkdir()
        gitsource.export(sc.repo, commit, tree)
        fresh = tmp_path / f"fresh{i}.ad2v"
        f = pipeline.extract_to_file(
            tree,
            tree / SPEC,
            fresh,
            test_results=[tree / JUNIT[0]],
            name_hint="payments-recon",
            repo_commit=commit,
        )
        assert _base_rows(fresh, f.epoch.epoch_id) == _base_rows(out, res.epoch.epoch_id), sc.commits[i][0]


def test_materialize_on_demand_equals_extraction(scenario, tmp_path):
    _sc, out, results = scenario
    copy = tmp_path / "m.ad2v"
    shutil.copyfile(out, copy)
    conn = store.connect(copy)
    try:
        head = store.head_epoch(conn)
        before = store.derived_rows(head, materialize.derive(conn, head))
        stored = {
            t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} WHERE epoch_id = ?", (head,))]
            for t in store.DERIVED_TABLES
        }
        for t, rows in before.items():  # stored rows == rows recomputed from base facts
            keys = sorted(rows[0]) if rows else []
            norm = lambda rs, keys=keys: sorted(tuple(str(r.get(k)) for k in keys) for r in rs)  # noqa: E731
            assert norm(rows) == norm(stored[t]), t
        # a middle epoch is not materialized; materializing it writes exactly derive()'s rows
        mid = results[3][1].epoch.epoch_id
        assert not store.is_materialized(conn, mid)
        with conn:
            assert materialize.materialize(conn, mid)
        assert store.is_materialized(conn, mid)
    finally:
        conn.close()
    assert validate(copy) == []


def _mask_commits(text: str) -> str:
    return re.sub(r'"repo_commit":"[0-9a-f]{40}"', '"repo_commit":"<sha>"', text)


def test_history_deterministic_and_crlf_bom_equivalent(scenario, tmp_path):
    _sc, out, _results = scenario
    reference = dump.canonical_dump(out, normative_only=True, epoch="all")
    again = Scenario(tmp_path / "again").build()
    out2 = tmp_path / "again.ad2v"
    _history(again, out2)
    assert dump.canonical_dump(out2, normative_only=True, epoch="all") == reference  # same SHAs, too
    crlf = Scenario(tmp_path / "crlf", crlf=True, bom=True).build()
    out3 = tmp_path / "crlf.ad2v"
    _history(crlf, out3)
    assert b"\r\n" in (crlf.repo / "api" / "recon_api" / "matching.py").read_bytes()
    # file bytes differ, so commit SHAs differ; everything else is identical
    assert _mask_commits(dump.canonical_dump(out3, normative_only=True, epoch="all")) == _mask_commits(
        reference
    )


def test_rerun_is_a_no_op(scenario, tmp_path):
    sc, out, _results = scenario
    copy = tmp_path / "again.ad2v"
    shutil.copyfile(out, copy)
    res = gitsource.run_history(sc.repo, f"{sc.commits[-2][1]}..HEAD", copy, SPEC, JUNIT)
    assert [r.unchanged for _, r in res] == [True]


def test_parse_cache_hits(scenario):
    _sc, _out, results = scenario
    first, later = results[0][1], results[1][1]
    assert first.stats["cache_hits"] == 0
    assert later.stats["cache_misses"] == 2 and later.stats["cache_hits"] == later.stats["files_code"] - 2


def test_prune_and_gc(scenario, tmp_path):
    _sc, out, _results = scenario
    copy = tmp_path / "p.ad2v"
    shutil.copyfile(out, copy)
    head_before = dump.canonical_dump(copy, normative_only=True)
    conn = store.connect(copy)
    third = store.epoch_rows(conn)[2]["epoch_id"]
    with conn:
        admin.pin(conn, third, "v0.3.0")
    conn.close()
    stats = admin.prune_file(copy, keep_last=3, keep_pinned=True)
    assert stats["epochs_removed"] == 4
    assert validate(copy) == []
    assert dump.canonical_dump(copy, normative_only=True) == head_before  # head unchanged
    conn = store.connect(copy)
    try:
        rows = store.epoch_rows(conn)
        assert [r["seq"] for r in rows] == [3, 6, 7, 8]
        assert rows[0]["parent_epoch_id"] is None and rows[1]["parent_epoch_id"] == third
        assert store.is_materialized(conn, third)  # pinned epochs stay materialized
        for versions, members in (
            ("node_versions", "epoch_nodes"),
            ("edge_versions", "epoch_edges"),
            ("code_fact_versions", "epoch_code_facts"),
        ):
            n = conn.execute(
                f"SELECT COUNT(*) FROM {versions} WHERE version_key NOT IN "
                f"(SELECT version_key FROM {members})"
            ).fetchone()[0]
            assert n == 0, versions
        # P8 (ADR-0065): cache rows are keyed by the extractor's effective rules hash, which the
        # epoch rules record per plug-in
        orphan_cache = conn.execute(
            "SELECT COUNT(*) FROM parse_cache WHERE NOT EXISTS (SELECT 1 FROM nodes n JOIN epochs e ON"
            " e.epoch_id = n.epoch_id JOIN rules_versions rv ON rv.rules_hash = e.rules_hash"
            " WHERE n.kind = 'module' AND n.path = parse_cache.path"
            " AND n.content_hash = parse_cache.content_hash AND EXISTS (SELECT 1 FROM"
            " json_each(rv.rules_json, '$.plugins') p"
            " WHERE json_extract(p.value, '$.effective_rules_hash') = parse_cache.rules_hash))"
        ).fetchone()[0]
        assert orphan_cache == 0
        # history across the pruned gap still diffs (lineage composes only along existing epochs)
        d = diff.diff(conn, third, rows[-1]["epoch_id"])
        assert "summary" in d
    finally:
        conn.close()
    stats = admin.prune_file(copy, keep_last=1, keep_pinned=False)
    assert validate(copy) == []


def test_cli_history_commands(scenario, tmp_path, capsysbinary):
    sc, out, _results = scenario
    copy = tmp_path / "c.ad2v"
    shutil.copyfile(out, copy)
    assert main(["log", str(copy)]) == 0
    text = capsysbinary.readouterr().out.decode("utf-8")
    assert "tests_only" in text and "8*" in text
    assert main(["pin", str(copy), sc.commits[2][1][:10], "--label", "rc1"]) == 0
    capsysbinary.readouterr()
    assert main(["diff", str(copy), "--from", "rc1", "--to", "head", "--format", "md"]) == 0
    md = capsysbinary.readouterr().out.decode("utf-8")
    assert md.startswith("### ad2v: epoch #3") and len(md.splitlines()) <= 60
    assert main(["diff", str(copy), "--format", "json"]) == 0
    assert b'"summary"' in capsysbinary.readouterr().out
    assert main(["diff", str(copy)]) == 0
    assert b"[status transitions]" in capsysbinary.readouterr().out
    assert main(["status", str(copy), "--epoch", "rc1", "--status", "stale"]) == 0
    assert b"REQ-003" in capsysbinary.readouterr().out
    assert main(["materialize", str(copy), "--epoch", "parent"]) == 0
    assert b"materialized" in capsysbinary.readouterr().out
    assert main(["unpin", str(copy), "rc1"]) == 0
    capsysbinary.readouterr()
    assert main(["dump", str(copy), "--epoch", "all", "--normative-only"]) == 0
    assert capsysbinary.readouterr().out.count(b'"table":"epochs"') == 8
    assert main(["prune", str(copy), "--keep-last", "2"]) == 0
    assert b"removed 6 epoch(s)" in capsysbinary.readouterr().out
    assert main(["validate", str(copy)]) == 0
    capsysbinary.readouterr()
    assert main(["diff", str(copy), "--from", "nope"]) == 2
    assert (
        main(["history", "--repo", str(tmp_path), "--commits", "HEAD", "--into", str(copy)]) == 2
    )  # not a repo


def test_extract_into_cli_and_no_changes(tmp_path, capsysbinary):
    out = tmp_path / "x.ad2v"
    args = ["extract", "--repo", str(FIXTURE), "--spec", str(FIXTURE / "specs"), "--into", str(out)]
    assert main(args) == 0
    assert b"epoch #1" in capsysbinary.readouterr().out
    assert main([*args, "--no-cache"]) == 0
    assert b"no changes" in capsysbinary.readouterr().out


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_incremental_export_equals_full_export(tmp_path):
    from history_scenario import _git

    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", date="2024-01-01T00:00:00Z")

    def commit(files: dict, delete=(), n=1):
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text, encoding="utf-8", newline="\n")
        for rel in delete:
            _git(repo, "rm", "-q", "-r", rel, date="2024-01-01T00:00:00Z")
        _git(repo, "add", "-A", date="2024-01-01T00:00:00Z")
        _git(repo, "commit", "-q", "-m", f"c{n}", date=f"2024-01-0{n}T00:00:00Z")
        return _git(repo, "rev-parse", "HEAD", date="2024-01-01T00:00:00Z")

    c1 = commit({"a/x.py": "x = 1\n", "b/deep/y.py": "y = 1\n", "keep.py": "k = 1\n"})
    # a glob-like name, a modified file, and a whole directory deleted
    c2 = commit({"a/x.py": "x = 2\n", "c/[x].py": "z = 1\n"}, delete=["b"], n=2)
    tree, full = tmp_path / "tree", tmp_path / "full"
    tree.mkdir()
    full.mkdir()
    gitsource.export(repo, c1, tree)
    assert gitsource.update(repo, c1, c2, tree) == 3
    gitsource.export(repo, c2, full)
    assert _files(tree) == _files(full)
    assert not (tree / "b").exists()  # emptied directories are removed, like a fresh export
    assert not gitsource._export_ignore(repo, c2)
    c3 = commit({".gitattributes": "keep.py export-ignore\n"}, n=3)
    assert gitsource._export_ignore(repo, c3)  # run_history falls back to a full export
    res = gitsource.run_history(repo, f"{c1}..{c3}", tmp_path / "h.ad2v")
    assert [r.unchanged for _, r in res] == [False, False]
    conn = store.open_readonly(tmp_path / "h.ad2v")
    try:
        head = store.load_graph(conn, store.head_epoch(conn))
    finally:
        conn.close()
    assert "keep.py" not in {n.qualified_name for n in head.nodes.values() if n.kind == "module"}
