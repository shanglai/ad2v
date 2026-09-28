import sqlite3

import pytest

from ad2v import dump, ids, ir, store


def _graph() -> ir.Graph:
    g = ir.Graph()
    sysn = g.add_node(ir.Node("code", "system", "s", "s", content_hash=ids.sha256_hex("s")))
    mod = g.add_node(
        ir.Node(
            "code", "module", "m.py", "m.py", parent_id=sysn.id, path="m.py", content_hash=ids.sha256_hex("m")
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
        )
    )
    g.add_edge(mod.id, fn.id, "calls", lines=[3])
    g.add_edge(mod.id, fn.id, "calls", lines=[1, 3])
    g.link_contains()
    g.compute_subtree_hashes()
    return g


def _write(path, g):
    epoch = store.Epoch(
        epoch_id=ids.epoch_id(None, "r", "s", "x"), repo_tree_hash="r", spec_tree_hash="s", rules_hash="x"
    )
    wf = ir.Workflow("w", "code", sorted(g.nodes)[0], "static", [ir.WorkflowStep(0, [sorted(g.nodes)[0]], 0)])
    glyphs = [ir.Glyph(n, "rounded_box", "module", {"ports": 0}, 1, False) for n in g.nodes]
    store.write(path, g, epoch, glyphs, [wf], {"repo_root_name": "x", "system_name": "s"})


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


def test_roundtrip_and_dump_deterministic(tmp_path):
    a, b = tmp_path / "a.ad2v", tmp_path / "b.ad2v"
    _write(a, _graph())
    _write(b, _graph())
    da, db = dump.canonical_dump(a), dump.canonical_dump(b)
    assert da == db
    assert "created_at" not in da
    assert '"generator"' not in da
    assert '"spec_ref_json":["REQ-1","REQ-2"]' in da


def test_rewrite_replaces_file(tmp_path):
    p = tmp_path / "x.ad2v"
    _write(p, _graph())
    _write(p, _graph())
    conn = store.connect(p)
    assert conn.execute("SELECT count(*) FROM nodes").fetchone()[0] == 3


def test_llm_rows_require_provenance(tmp_path):
    p = tmp_path / "x.ad2v"
    _write(p, _graph())
    conn = store.connect(p)
    nid = conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0]
    e = conn.execute("SELECT epoch_id FROM epochs").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO links(epoch_id, link_id, spec_node_id, status, provenance) VALUES (?,?,?,?,?)",
            (e, "l_1", nid, "drift", "llm"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO summaries(epoch_id, node_id, length, text) VALUES (?,?,?,?)",
            (e, nid, "card", "x"),
        )
    conn.execute(
        "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (e, "l_2", nid, None, "drift", "llm", "[]", 0.7, "m", "1", "p", "i", None),
    )


def test_foreign_keys_enforced(tmp_path):
    p = tmp_path / "x.ad2v"
    _write(p, _graph())
    conn = store.connect(p)
    e = conn.execute("SELECT epoch_id FROM epochs").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO edges(epoch_id, src, dst, kind) VALUES (?,?,?,?)", (e, "n_x", "n_y", "calls")
        )
