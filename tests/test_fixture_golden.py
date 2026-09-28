"""Golden test: the payments-recon fixture must satisfy fixtures/payments-recon/expected.yaml."""

from collections import Counter

import pytest
import yaml

from ad2v import ids, ir, pipeline
from ad2v import rules as rules_mod

from helpers import FIXTURE, JUNIT, node

EXPECTED = yaml.safe_load((FIXTURE / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result():
    return pipeline.build(FIXTURE, FIXTURE / "specs", test_results=[JUNIT])


def _q(g, nid):
    return g.nodes[nid].qualified_name if nid else None


def test_counts_per_kind(result):
    counts = Counter(n.kind for n in result.graph.nodes.values())
    assert {k: counts.get(k, 0) for k in EXPECTED["counts"]} == EXPECTED["counts"]
    assert set(counts) <= set(EXPECTED["counts"])


def test_containers(result):
    for qname, attrs in EXPECTED["containers"].items():
        n = node(result.graph, "container", qname)
        for k, v in attrs.items():
            assert n.attrs[k] == v


def test_named_nodes(result):
    for kind, names in EXPECTED["nodes"].items():
        for q in names:
            node(result.graph, kind, q)


def test_risks(result):
    got = {n.qualified_name: n.attrs["risk"] for n in result.graph.nodes.values() if n.attrs.get("risk")}
    assert got == EXPECTED["risks"]


def test_ports_and_handlers(result):
    g = result.graph
    for kind, ports in EXPECTED["ports"].items():
        got = {n.qualified_name: n.attrs["handler"] for n in g.nodes.values() if n.kind == kind}
        assert got == ports
        for port_q, handler_q in ports.items():
            p = node(g, kind, port_q)
            assert (p.id, "calls", node(g, "function", handler_q).id) in g.edges
            assert g.nodes[p.parent_id].kind == "container"
            assert (p.parent_id, "exposes", p.id) in g.edges


def test_edges(result):
    g = result.graph
    have = {(k, _q(g, s), _q(g, d)) for (s, k, d) in g.edges}
    for kind, src, dst in EXPECTED["edges"]:
        assert (kind, src, dst) in have


def test_annotations_and_dangling_ref(result):
    g = result.graph
    for code_q, refs in EXPECTED["annotations"].items():
        n = node(g, "function", code_q)
        linked = sorted(_q(g, d) for (s, k, d) in g.edges if s == n.id and k == "annotated_as")
        assert linked == refs
    dangling = [{"src": _q(g, u.src), "ref": u.ref} for u in g.unresolved]
    assert dangling == EXPECTED["dangling_refs"]


def test_workflows(result):
    g = result.graph
    by_side = Counter(w.side for w in result.workflows)
    assert by_side["code"] == EXPECTED["workflows"]["code"]
    assert by_side["spec"] == EXPECTED["workflows"]["spec"]
    for entry, sequence in EXPECTED["workflows"]["traces"].items():
        wf = next(w for w in result.workflows if _q(g, w.entry_node_id) == entry)
        flat = [_q(g, nid) for s in wf.steps for nid in s.node_ids]
        it = iter(flat)
        missing = [q for q in sequence if q not in it]  # subsequence check
        assert not missing, f"{entry}: {missing} not found in order in {flat}"
        assert not wf.attrs.get("truncated")


def test_spec_root_hierarchy(result):
    g = result.graph
    root = node(g, "spec_root", "payments-recon")
    docs = [n for n in g.nodes.values() if n.kind == "spec_doc"]
    assert docs and all(d.parent_id == root.id for d in docs)
    assert root.parent_id is None


def test_statuses(result):
    g, st = result.graph, result.pairing.statuses
    for side in ("spec", "code"):
        for kind, qname, status in EXPECTED["statuses"][side]:
            nid = ids.node_id(side, kind, qname)
            assert nid in g.nodes, (kind, qname)
            assert st[nid].status == status, (qname, st[nid])
    assert set(st) == set(g.nodes)
    # functions, classes and modules are never orphan
    assert not [
        n
        for n, s in st.items()
        if s.status == "orphan" and g.nodes[n].kind in ("function", "class", "module")
    ]


def test_link_evidence(result):
    g = result.graph
    have = {
        (_q(g, lk.spec_node_id), _q(g, lk.code_node_id), e["kind"])
        for lk in result.pairing.links
        for e in lk.evidence
    }
    for spec_q, code_q, kind in EXPECTED["link_evidence"]:
        assert (spec_q, code_q, kind) in have


def test_rollups(result):
    for qname, counts in EXPECTED["rollups"].items():
        assert result.pairing.rollup[ids.node_id("code", "container", qname)] == counts


def test_severity_top3(result):
    g = result.graph
    top = [[_q(g, n), g.nodes[n].attrs["severity"]] for n in result.ranked_behaviors[:3]]
    assert top == EXPECTED["severity_top3"]
    assert [g.nodes[n].attrs["severity_rank"] for n in result.ranked_behaviors[:3]] == [1, 2, 3]


def test_test_results_matching(result):
    g = result.graph
    got = {_q(g, t.test_node_id): t.outcome for t in result.tests.results.values()}
    assert got == EXPECTED["test_results"]["matched"]
    unmatched = [{k: u[k] for k in ("classname", "name", "reason")} for u in result.tests.unmatched]
    assert unmatched == EXPECTED["test_results"]["unmatched"]


def test_rules_overlay_in_rules_hash(result):
    overlay = FIXTURE / EXPECTED["rules"]["overlay"]
    assert result.epoch.rules_hash == rules_mod.load(None, overlay)["_hash"]
    assert result.epoch.rules_hash != rules_mod.load()["_hash"]


def test_every_node_is_well_formed(result):
    g = result.graph
    for nid, n in g.nodes.items():
        assert nid == ids.node_id(n.side, n.kind, n.qualified_name)
        assert len(n.content_hash) == 64 and len(n.subtree_hash) == 64
        assert n.side == ir.side_of(n.kind)
        if n.path is not None:
            assert "\\" not in n.path
        if n.parent_id is not None:
            assert n.parent_id in g.nodes
