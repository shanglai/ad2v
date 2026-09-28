import hashlib

from ad2v import ids


def test_normalize_bytes_bom_and_line_endings():
    assert ids.normalize_bytes(b"\xef\xbb\xbfa\r\nb\rc\n") == "a\nb\nc\n"
    assert ids.normalize_bytes(b"a\r\n") == ids.normalize_bytes(b"a\n")


def test_normalize_text_strips_single_bom():
    assert ids.normalize_text("﻿x\r\n") == "x\n"


def test_invalid_utf8_is_deterministic():
    assert ids.normalize_bytes(b"\xff\xfe") == ids.normalize_bytes(b"\xff\xfe")


def test_node_id_formula():
    expected = "n_" + hashlib.sha256(b"code|function|a/b.py::f").hexdigest()[:20]
    assert ids.node_id("code", "function", "a/b.py::f") == expected
    assert len(expected) == 22


def test_node_id_depends_on_side_kind_and_name():
    base = ids.node_id("code", "function", "x")
    assert base != ids.node_id("spec", "function", "x")
    assert base != ids.node_id("code", "class", "x")
    assert base != ids.node_id("code", "function", "y")


def test_content_hash_ignores_line_endings():
    assert ids.content_hash("a\r\nb") == ids.content_hash("a\nb")


def test_canonical_json_sorted_compact_unicode():
    assert ids.canonical_json({"b": 1, "a": ["é"]}) == '{"a":["é"],"b":1}'


def test_subtree_hash_order_independent():
    a = ids.subtree_hash("h", [("n_2", "x"), ("n_1", "y")])
    b = ids.subtree_hash("h", [("n_1", "y"), ("n_2", "x")])
    assert a == b
    assert a != ids.subtree_hash("h", [("n_1", "y")])
    assert ids.subtree_hash("h", []) == ids.sha256_hex("h")


def test_tree_hash_sorted():
    assert ids.tree_hash({"b": "1", "a": "2"}) == ids.tree_hash({"a": "2", "b": "1"})


def test_rel_posix(tmp_path):
    f = tmp_path / "a" / "b.py"
    f.parent.mkdir()
    f.write_text("")
    assert ids.rel_posix(f, tmp_path) == "a/b.py"
    assert ids.rel_posix(tmp_path, tmp_path) == ""


def test_workflow_and_epoch_ids():
    assert ids.workflow_id("code", "n_x", "static").startswith("w_")
    base = ids.epoch_id(None, "a", "b", "r", "c", "t")
    assert base == ids.epoch_id("", "a", "b", "r", "c", "t")
    assert ids.epoch_id("e_1", "a", "b", "r", "c", "t") != base
    for i in range(1, 6):  # every input moves the epoch id
        args = ["", "a", "b", "r", "c", "t"]
        args[i] += "x"
        assert ids.epoch_id(*args) != base


def test_link_id():
    assert ids.link_id("n_a", None, "none") == ids.link_id("n_a", "", "none")
    assert ids.link_id("n_a", "n_b", "annotation") != ids.link_id("n_a", "n_b", "route_match")
    assert ids.link_id("n_a", "n_b", "annotation").startswith("l_")
