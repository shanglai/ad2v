"""Golden test: the payments-recon fixture must satisfy fixtures/payments-recon/expected.yaml."""

from collections import Counter

import pytest
import yaml

from ad2v import ids, ir, pipeline

from helpers import FIXTURE, node

EXPECTED = yaml.safe_load((FIXTURE / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result():
    return pipeline.build(FIXTURE, FIXTURE / "specs")


def _q(g, nid):
    return g.nodes[nid].qualified_name


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
    g = result.graph
    got = {n.qualified_name: n.attrs["risk"] for n in g.nodes.values() if n.attrs.get("risk")}
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
    for name, sequence in EXPECTED["workflows"]["traces"].items():
        wf = next(w for w in result.workflows if w.name == name)
        flat = [_q(g, nid) for s in wf.steps for nid in s.node_ids]
        it = iter(flat)
        missing = [q for q in sequence if q not in it]  # subsequence check
        assert not missing, f"{name}: {missing} not found in order in {flat}"
        assert not wf.attrs.get("truncated")


def test_p2_candidates(result):
    g = result.graph
    routes = {
        (n.attrs["method"], n.attrs["path"]): n.qualified_name
        for n in g.nodes.values()
        if n.kind == "http_route"
    }
    endpoints = {
        (n.attrs["method"], n.attrs["path"]): n.qualified_name
        for n in g.nodes.values()
        if n.kind == "spec_endpoint"
    }
    assert (
        sorted(endpoints[k] for k in endpoints.keys() - routes.keys()) == EXPECTED["p2_candidates"]["missing"]
    )
    assert sorted(routes[k] for k in routes.keys() - endpoints.keys()) == EXPECTED["p2_candidates"]["orphan"]


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
