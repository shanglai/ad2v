"""Severity scoring, rules overlays, JUnit ingestion and the normative-only dump."""

import pytest

from ad2v import dump, ids, ir, junit, pipeline, severity
from ad2v import rules as rules_mod

from helpers import FIXTURE, JUNIT, write_tree

W = rules_mod.load()["severity"]


@pytest.mark.parametrize(
    ("risk", "reach", "expected"),
    [
        (["io_in_loop"], 0, 3.0),
        (["io_in_loop"], 1, 4.5),
        (["io_in_loop"], 3, 5.1),  # 1.5 + 0.2
        (["io_in_loop", "nested_loop_io"], 1, 7.5),  # (3 + 2) x 1.5
        (["llm_in_loop"], 50, 12.5),  # reach factor capped at 2.5
        (["fan_out", "unbounded_retry"], 0, 4.0),  # max over flags, not sum
        ([], 4, 0.0),
    ],
)
def test_severity_formula(risk, reach, expected):
    assert severity.score(risk, reach, W) == expected


def test_severity_rank_ties_broken_by_id():
    g = ir.Graph()
    a = g.add_node(ir.Node("code", "loop", "a", "m::f@loop#aaaa", attrs={"risk": ["io_in_loop"]}))
    b = g.add_node(ir.Node("code", "loop", "b", "m::f@loop#bbbb", attrs={"risk": ["io_in_loop"]}))
    c = g.add_node(ir.Node("code", "retry", "c", "m::f@retry#cccc", attrs={"risk": ["unbounded_retry"]}))
    ranked = severity.apply(g, [], {"severity": W})
    assert ranked[0] == c.id and ranked[1:] == sorted([a.id, b.id])
    assert [g.nodes[n].attrs["severity_rank"] for n in ranked] == [1, 2, 3]


def test_deep_merge_semantics():
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    over = {"a": {"y": [9], "z": 3}, "c": 2}
    assert rules_mod.deep_merge(base, over) == {"a": {"x": 1, "y": [9], "z": 3}, "b": 1, "c": 2}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 1}  # inputs untouched


def test_rules_overlay_changes_hash_and_weights(tmp_path):
    overlay = tmp_path / "o.yaml"
    overlay.write_text("severity:\n  base:\n    fan_out: 9\n", encoding="utf-8")
    merged = rules_mod.load(None, overlay)
    assert merged["severity"]["base"]["fan_out"] == 9
    assert merged["severity"]["base"]["io_in_loop"] == 3  # untouched keys survive
    assert merged["_hash"] != rules_mod.load()["_hash"]
    assert merged["_overlay"] == "o.yaml"
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(rules_mod.RulesError):
        rules_mod.load(None, bad)
    with pytest.raises(rules_mod.RulesError):
        rules_mod.load(None, tmp_path / "missing.yaml")


def test_manifest_overlay_must_exist(tmp_path):
    from ad2v.manifest import ManifestError, load

    (tmp_path / "ad2v.yaml").write_text("rules_overlay: nope.yaml\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load(tmp_path)


def test_junit_matching_rules(tmp_path):
    write_tree(
        tmp_path,
        {
            "svc/tests/test_a.py": """
            class TestThing:
                def test_method(self):
                    pass

            def test_plain():
                pass
        """,
            "other/tests/test_a.py": "def test_plain():\n    pass\n",
        },
    )
    res = pipeline.build(tmp_path)
    g = res.graph
    m = lambda c, n, f=None: junit.match_case(c, n, f, g)  # noqa: E731
    fn = lambda q: ids.node_id("code", "function", q)  # noqa: E731
    assert m("svc.tests.test_a.TestThing", "test_method") == (
        fn("svc/tests/test_a.py::TestThing.test_method"),
        "matched",
    )
    assert m("svc.tests.test_a", "test_plain[param-1]") == (fn("svc/tests/test_a.py::test_plain"), "matched")
    assert m("tests.test_a", "test_plain") == (None, "ambiguous")  # rootdir-relative, two candidates
    assert m("tests.test_a", "test_plain", "other/tests/test_a.py")[1] == "matched"  # `file` disambiguates
    assert m("nope.mod", "test_x") == (None, "not_found")


def test_junit_outcomes_worst_wins_and_errors(tmp_path):
    write_tree(tmp_path, {"tests/test_a.py": "def test_x():\n    pass\n\ndef test_s():\n    pass\n"})
    g = pipeline.build(tmp_path).graph
    (tmp_path / "r1.xml").write_text(
        '<testsuite><testcase classname="tests.test_a" name="test_x" time="0.5"/>'
        '<testcase classname="tests.test_a" name="test_s"><skipped/></testcase></testsuite>',
        encoding="utf-8",
    )
    (tmp_path / "r2.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_a" name="test_x" time="bad">'
        '<error message="boom"/></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    got = junit.ingest([tmp_path / "r2.xml", tmp_path / "r1.xml"], tmp_path, g)
    x = got.results[ids.node_id("code", "function", "tests/test_a.py::test_x")]
    assert (x.outcome, x.source_file) == ("failed", "r2.xml")
    assert got.results[ids.node_id("code", "function", "tests/test_a.py::test_s")].outcome == "skipped"
    assert set(got.files) == {"r1.xml", "r2.xml"} and got.cases == 3
    (tmp_path / "broken.xml").write_text("<testsuite>", encoding="utf-8")
    with pytest.raises(junit.JUnitError):
        junit.ingest([tmp_path / "broken.xml"], tmp_path, g)
    with pytest.raises(junit.JUnitError):
        junit.ingest([tmp_path / "absent.xml"], tmp_path, g)


def test_test_results_move_the_epoch(tmp_path):
    a = pipeline.build(FIXTURE, FIXTURE / "specs")
    b = pipeline.build(FIXTURE, FIXTURE / "specs", test_results=[JUNIT])
    assert a.epoch.test_results_hash != b.epoch.test_results_hash
    assert a.epoch.epoch_id != b.epoch.epoch_id


def test_normative_only_dump_drops_informative_rows(tmp_path):
    import sqlite3

    out = tmp_path / "p.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, test_results=[JUNIT])
    conn = sqlite3.connect(out)
    e = conn.execute("SELECT epoch_id FROM epochs").fetchone()[0]
    nid = conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO summaries VALUES (?,?,?,?,?,?,?,?,?,?)",
        (e, nid, "card", "an llm summary", "m", "1", "p", "i", 0.8, None),
    )
    conn.execute(
        "INSERT INTO links(epoch_id, link_id, spec_node_id, method, status, provenance, confidence, model,"
        " model_version, prompt_hash, input_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (e, "l_llm", nid, "llm", "drift", "llm", 0.6, "m", "1", "p", "i"),
    )
    conn.commit()
    conn.close()
    full = dump.canonical_dump(out)
    normative = dump.canonical_dump(out, normative_only=True)
    assert "an llm summary" in full and "l_llm" in full
    assert "an llm summary" not in normative and "l_llm" not in normative
    assert '"model"' not in normative and '"generator"' not in full and '"class":"N"' in normative
