from ad2v import glyphs, ids, ir


def _node(g, kind, qname, parent=None, **kw):
    n = ir.Node(
        ir.side_of(kind),
        kind,
        qname,
        qname,
        parent_id=parent.id if parent else None,
        content_hash=ids.sha256_hex(qname),
        **kw,
    )
    return g.add_node(n)


def test_every_kind_has_a_shape_from_the_closed_set():
    assert set(glyphs.KIND_SHAPES) == set(ir.NODE_KINDS)
    assert {s for s, _ in glyphs.KIND_SHAPES.values()} <= set(glyphs.BASE_SHAPES)
    assert len(glyphs.BASE_SHAPES) == 10


def test_modifiers_roll_up_and_ports():
    g = ir.Graph()
    sysn = _node(g, "system", "s")
    c = _node(g, "container", "container:api", sysn, attrs={"replicas": 2, "container_kind": "service"})
    m = _node(g, "module", "a.py", c, span_start_line=1, span_end_line=10)
    f = _node(g, "function", "a.py::f", m, span_start_line=2, span_end_line=5)
    loop = _node(
        g, "loop", "a.py::f@loop#1", f, span_start_line=3, span_end_line=4, attrs={"risk": ["io_in_loop"]}
    )
    route = _node(g, "http_route", "http:api:GET /x", c)
    llm = _node(g, "llm_endpoint", "llm_endpoint:x")
    db = _node(g, "datastore", "datastore:x")
    g.add_edge(c.id, route.id, "exposes")
    g.add_edge(f.id, llm.id, "invokes_llm")
    g.add_edge(f.id, db.id, "reads", weight=3)
    g.link_contains()
    by = {gl.node_id: gl for gl in glyphs.compute(g)}
    assert len(by) == len(g.nodes)
    assert by[c.id].modifiers == {
        "ports": 1,
        "replicas": 2,
        "has_loop_risk": True,
        "has_llm": True,
        "external": False,
    }
    assert by[loop.id].base_shape == "ring"
    assert by[m.id].modifiers["has_loop_risk"] and not by[route.id].modifiers["has_loop_risk"]
    assert by[route.id].base_shape == "port_notch"
    assert by[db.id].size_weight == 3 and by[db.id].base_shape == "cylinder"
    assert by[f.id].size_weight == 4
    assert by[sysn.id].size_weight == 10 and by[sysn.id].has_interior
    assert not by[loop.id].has_interior


def test_gateway_container_is_trapezoid():
    n = ir.Node("code", "container", "gw", "container:gw", attrs={"container_kind": "gateway"})
    assert glyphs.shape_for(n) == ("trapezoid", "gateway")
    n2 = ir.Node("code", "function", "f", "a::f")
    assert glyphs.shape_for(n2) == ("rounded_box", "function")
