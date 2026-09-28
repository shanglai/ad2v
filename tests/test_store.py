import json
import sqlite3

import pytest

from ad2v import dump, ids, ir, pairing, store
from ad2v.extract.code.base import CodeFacts

# Column lists of the v0.2 base tables: the v0.3 views must keep exactly this shape.
V02_COLUMNS = {
    "nodes": [
        "epoch_id",
        "id",
        "side",
        "kind",
        "name",
        "qualified_name",
        "parent_id",
        "path",
        "span_start_line",
        "span_end_line",
        "content_hash",
        "subtree_hash",
        "level_hint",
        "attrs_json",
        "spec_ref_json",
    ],
    "edges": [
        "epoch_id",
        "src",
        "dst",
        "kind",
        "weight",
        "attrs_json",
        "provenance",
        "model",
        "model_version",
        "prompt_hash",
        "input_hash",
        "confidence",
    ],
    "unresolved_refs": ["epoch_id", "src", "ref", "ref_kind", "reason"],
    "test_results": ["epoch_id", "test_node_id", "outcome", "source_file", "duration_ms"],
}


def _graph(extra: bool = False) -> ir.Graph:
    g = ir.Graph()
    sysn = g.add_node(ir.Node("code", "system", "s", "s", content_hash=ids.sha256_hex("s")))
    mod = g.add_node(
        ir.Node(
            "code",
            "module",
            "m.py",
            "m.py",
            parent_id=sysn.id,
            path="m.py",
            content_hash=ids.sha256_hex("m"),
            span_start_line=1,
            span_end_line=9,
        )
    )
    fn = g.add_node(
        ir.Node(
            "code",
            "function",
            "f",
            "m.py::f",
            parent_id=mod.id,
            content_hash=ids.sha256_hex("f"),
            attrs={"async": False},
            spec_ref=["REQ-2", "REQ-1"],
            span_start_line=2 + extra,
            span_end_line=3 + extra,
        )
    )
    if extra:
        g.add_node(
            ir.Node("code", "function", "g", "m.py::g", parent_id=mod.id, content_hash=ids.sha256_hex("g"))
        )
    g.add_edge(mod.id, fn.id, "calls", lines=[3 + extra])
    g.add_edge(mod.id, fn.id, "calls", lines=[1, 3 + extra])
    g.unresolved.append(ir.UnresolvedRef(fn.id, "REQ-9", "spec_id", "not_found"))
    g.link_contains()
    g.compute_subtree_hashes()
    return g


def _write_epoch(conn, g, seq, parent=None):
    e = store.Epoch(
        epoch_id=ids.epoch_id(parent, f"r{seq}", "s", "x", "c", "t"),
        repo_tree_hash=f"r{seq}",
        spec_tree_hash="s",
        rules_hash="x",
        parent_epoch_id=parent,
        seq=seq,
        change_kind="initial" if parent is None else "code",
    )
    with conn:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        store.insert_epoch(conn, e, {"rules_version": "t"}, {"manifest": {}})
        stats = store.write_base(conn, e.epoch_id, g, CodeFacts(), [], [], [])
        wf = ir.Workflow(
            "w", "code", sorted(g.nodes)[0], "static", [ir.WorkflowStep(0, [sorted(g.nodes)[0]], 0)]
        )
        glyphs = [ir.Glyph(n, "rounded_box", "module", {"ports": 0}, 1, False) for n in g.nodes]
        store.write_derived(conn, e.epoch_id, store.Derived(glyphs, [wf], pairing.finalize(g, [])))
        if parent is not None:
            store.drop_derived(conn, parent)
        store.set_meta(conn, {"head_epoch": e.epoch_id, "system_name": "s", "repo_root_name": "x"})
    return e.epoch_id, stats


def _file(path, epochs=1):
    conn = store.create(path)
    ids_, parent = [], None
    for i in range(epochs):
        parent, _ = _write_epoch(conn, _graph(extra=i > 0), i + 1, parent)
        ids_.append(parent)
    conn.close()
    return ids_


def test_edge_merge_weights_and_lines():
    g = _graph()
    calls = [e for e in g.edges.values() if e.kind == "calls"]
    assert len(calls) == 1 and calls[0].weight == 2 and calls[0].attrs["lines"] == [1, 3]


def test_unknown_kinds_rejected():
    g = ir.Graph()
    with pytest.raises(ValueError):
        g.add_node(ir.Node("code", "widget", "x", "x"))
    with pytest.raises(ValueError):
        g.add_edge("a", "b", "likes")


def test_views_keep_the_v02_shape(tmp_path):
    p = tmp_path / "a.ad2v"
    _file(p)
    conn = store.connect(p)
    for view, cols in V02_COLUMNS.items():
        assert store.columns(conn, view) == cols, view
    # a P2-era query runs unchanged against the views
    row = conn.execute(
        "SELECT id, qualified_name, span_start_line FROM nodes WHERE qualified_name = 'm.py::f'"
    ).fetchone()
    assert row[1] == "m.py::f" and row[2] == 2
    attrs = json.loads(conn.execute("SELECT attrs_json FROM edges WHERE kind = 'calls'").fetchone()[0])
    assert attrs["lines"] == [1, 3]  # volatile lines re-attached by the view
    assert conn.execute("SELECT ref FROM unresolved_refs").fetchone()[0] == "REQ-9"


def test_dedup_across_epochs(tmp_path):
    p = tmp_path / "a.ad2v"
    conn = store.create(p)
    e1, s1 = _write_epoch(conn, _graph(), 1)
    e2, s2 = _write_epoch(conn, _graph(extra=True), 2, e1)
    assert s1["node_versions_new"] == 3
    # epoch 2 adds g, changes the module's subtree hash (and so the system's); f's lines move but f is shared
    assert s2["node_versions_new"] == 3
    shared = conn.execute(
        "SELECT COUNT(*) FROM epoch_nodes a JOIN epoch_nodes b ON a.vid = b.vid"
        " WHERE a.seq = ? AND b.seq = ?",
        (store.epoch_seq(conn, e1), store.epoch_seq(conn, e2)),
    ).fetchone()[0]
    assert shared == 1  # m.py::f
    spans = dict(conn.execute("SELECT epoch_id, span_start_line FROM nodes WHERE qualified_name = 'm.py::f'"))
    assert spans == {e1: 2, e2: 3}  # volatile spans stay per epoch
    assert store.is_materialized(conn, e2) and not store.is_materialized(conn, e1)
    assert conn.execute("SELECT COUNT(*) FROM glyphs WHERE epoch_id = ?", (e1,)).fetchone()[0] == 0


def test_roundtrip_and_dump_deterministic(tmp_path):
    a, b = tmp_path / "a.ad2v", tmp_path / "b.ad2v"
    _file(a, 2)
    _file(b, 2)
    for which in ("head", "all"):
        da, db = dump.canonical_dump(a, epoch=which), dump.canonical_dump(b, epoch=which)
        assert da == db
    da = dump.canonical_dump(a, epoch="all")
    assert "created_at" not in da and '"generator"' not in da
    assert '"spec_ref_json":["REQ-1","REQ-2"]' in da
    assert '"table":"node_versions"' not in da and '"table":"epoch_nodes"' not in da  # dedup invisible
    assert da.count('"table":"epochs"') == 2
    normative = dump.canonical_dump(a, normative_only=True, epoch="all")
    assert '"pinned"' not in normative and '"materialized"' not in normative


def test_create_replaces_file(tmp_path):
    p = tmp_path / "x.ad2v"
    _file(p, 2)
    _file(p, 1)
    conn = store.connect(p)
    assert conn.execute("SELECT count(*) FROM epochs").fetchone()[0] == 1


def test_llm_rows_require_provenance(tmp_path):
    p = tmp_path / "x.ad2v"
    _file(p)
    conn = store.connect(p)
    nid = conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0]
    e = conn.execute("SELECT epoch_id FROM epochs").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO links(epoch_id, link_id, spec_node_id, method, status, provenance, confidence)"
            " VALUES (?,?,?,?,?,?,?)",
            (e, "l_1", nid, "llm", "drift", "llm", 0.5),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO summaries(epoch_id, node_id, length, text) VALUES (?,?,?,?)", (e, nid, "card", "x")
        )
    with pytest.raises(sqlite3.IntegrityError):  # narrations are keyed by projection mode too
        conn.execute(
            "INSERT INTO narrations(epoch_id, workflow_id, mode, detail_level, span_start, span_end, text,"
            " model, model_version, prompt_hash, input_hash, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (e, "w_x", "zoom", 1, 0, 0, "t", "m", "1", "p", "i", 0.5),
        )
    conn.execute(
        "INSERT INTO links(epoch_id, link_id, spec_node_id, method, status, provenance, evidence_json,"
        " confidence, model, model_version, prompt_hash, input_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (e, "l_2", nid, "llm", "drift", "llm", "[]", 0.7, "m", "1", "p", "i"),
    )


def test_foreign_keys_enforced(tmp_path):
    p = tmp_path / "x.ad2v"
    _file(p)
    conn = store.connect(p)
    e = conn.execute("SELECT epoch_id FROM epochs").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):  # no such edge version
        conn.execute("INSERT INTO epoch_edges(seq, vid) VALUES (1, 999999)")
    with pytest.raises(sqlite3.IntegrityError):  # no such epoch
        conn.execute("INSERT INTO epoch_nodes(seq, vid) VALUES (99, (SELECT MIN(vid) FROM node_versions))")
    with pytest.raises(sqlite3.OperationalError):  # views are read-only
        conn.execute("INSERT INTO nodes(epoch_id, id) VALUES (?, ?)", (e, "n_x"))


def test_change_kind():
    base = store.Epoch("e", "r", "s", "x", "c", "t")
    assert store.change_kind(None, base) == "initial"
    cases = {
        ("r2", "s", "x", "c", "t"): "code",
        ("r", "s2", "x", "c", "t"): "spec",
        ("r2", "s2", "x", "c", "t"): "code+spec",
        ("r", "s", "x2", "c", "t"): "rules",
        ("r", "s", "x", "c2", "t"): "config",
        ("r", "s", "x", "c", "t2"): "tests_only",
        ("r2", "s", "x", "c", "t2"): "mixed",
    }
    for (r, s, x, c, t), want in cases.items():
        assert store.change_kind(base, store.Epoch("e2", r, s, x, c, t)) == want


def test_open_rw_refuses_other_formats(tmp_path):
    p = tmp_path / "x.ad2v"
    _file(p)
    conn = store.connect(p)
    conn.execute("UPDATE meta SET value = '0.2' WHERE key = 'format_version'")
    conn.commit()
    conn.close()
    with pytest.raises(store.NotAnAd2vFile):
        store.open_rw(p)
    with pytest.raises(store.NotAnAd2vFile):
        store.open_rw(tmp_path / "missing.ad2v")
