"""Pairing and status rules (format spec §6), one test per rule."""

import textwrap

import pytest

from ad2v import ids, ir, pairing, pipeline

from helpers import write_tree

FASTAPI_HEAD = "from fastapi import FastAPI\napp = FastAPI()\n\n"

OPENAPI = """
openapi: 3.0.0
info: {title: t, version: "1"}
servers: [{url: "https://x.example.com/api"}]
paths:
  /items/{item_id}:
    get:
      parameters:
        - {name: item_id, in: path, required: true}
        - {name: page, in: query, required: true}
      responses: {"200": {description: ok}}
  /orders:
    post:
      responses: {"200": {description: ok}}
  /missing:
    delete:
      responses: {"200": {description: ok}}
"""


def _build(tmp_path, files, junit=None, **kw):
    write_tree(tmp_path, files)
    tr = []
    if junit is not None:
        (tmp_path / "junit.xml").write_text(textwrap.dedent(junit).lstrip(), encoding="utf-8")
        tr = [tmp_path / "junit.xml"]
    return pipeline.build(tmp_path, tmp_path / "specs", test_results=tr, **kw)


def _status(res, side, kind, qname):
    return res.pairing.statuses[ids.node_id(side, kind, qname)]


def _links(res, spec_q=None, code_q=None):
    g = res.graph
    q = lambda n: g.nodes[n].qualified_name if n else None  # noqa: E731
    return [
        lk
        for lk in res.pairing.links
        if (spec_q is None or q(lk.spec_node_id) == spec_q)
        and (code_q is None or q(lk.code_node_id) == code_q)
    ]


@pytest.mark.parametrize(
    ("path", "base", "prefix_map", "ci", "expected"),
    [
        ("/items/{item_id}", "/api", None, False, ("/api/items/{}", ["item_id"])),
        ("items//{id}/", "", None, False, ("/items/{}", ["id"])),
        ("/", "", None, False, ("/", [])),
        ("/v1/Items", "", {"/v1": "/api"}, False, ("/api/Items", [])),
        ("/v1/Items", "", {"/v1": "/api"}, True, ("/api/items", [])),
        ("/v10/items", "", {"/v1": ""}, False, ("/v10/items", [])),  # prefix only on a segment boundary
        ("/v1", "", {"/v1": ""}, False, ("/", [])),
    ],
)
def test_normalize_path(path, base, prefix_map, ci, expected):
    assert pairing.normalize_path(path, base, prefix_map, ci) == expected


def test_slug():
    assert pairing.slug("Billing  Service!") == "billing-service"
    assert pairing.slug("--API--") == "api"


def test_route_match_drift_mismatch_and_missing(tmp_path):
    res = _build(
        tmp_path,
        {
            "specs/openapi.yaml": OPENAPI,
            "app/pyproject.toml": "[project]\nname='app'\n",
            "app/web.py": """
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/items/{id}/")
            def get_item(id: int):
                return id

            @app.post("/api/orders")
            def create_order(**kwargs):
                return 1
        """,
        },
    )
    get = _links(res, "GET /items/{item_id}")[0]
    assert get.method == "route_match" and get.status == "drift"
    kinds = {e["kind"] for e in get.evidence}
    assert {"param_name_mismatch", "required_query_param_missing"} <= kinds
    post = _links(res, "POST /orders")[0]
    assert post.status == "implemented"  # **kwargs may absorb query params: no drift claim
    assert post.confidence == 1.0 and post.provenance == "deterministic"
    missing = _links(res, "DELETE /missing")[0]
    assert (missing.status, missing.method, missing.code_node_id) == ("missing", "none", None)
    assert _status(res, "spec", "spec_endpoint", "DELETE /missing").status == "missing"


def test_path_param_count_drift(tmp_path):
    spec = """
    openapi: 3.0.0
    info: {title: t, version: "1"}
    paths:
      /a/{x}:
        get:
          parameters:
            - {name: x, in: path, required: true}
            - {name: y, in: path, required: true}
          responses: {"200": {description: ok}}
    """
    res = _build(
        tmp_path,
        {
            "specs/openapi.yaml": spec,
            "web.py": FASTAPI_HEAD + '@app.get("/a/{x}")\ndef a(x, y):\n    pass\n',
        },
    )
    lk = _links(res, "GET /a/{x}")[0]
    assert lk.status == "drift"
    assert {"kind": "path_param_count", "spec": 2, "code": 1} in lk.evidence


def test_ambiguous_route_is_needs_review(tmp_path):
    res = _build(
        tmp_path,
        {
            "specs/openapi.yaml": OPENAPI.replace('servers: [{url: "https://x.example.com/api"}]\n', ""),
            "a/pyproject.toml": "",
            "b/pyproject.toml": "",
            "a/web.py": FASTAPI_HEAD + '@app.post("/orders")\ndef o():\n    pass\n',
            "b/web.py": FASTAPI_HEAD + '@app.post("/orders")\ndef o():\n    pass\n',
        },
    )
    links = _links(res, "POST /orders")
    assert len(links) == 2 and {lk.status for lk in links} == {"needs_review"}
    assert _status(res, "spec", "spec_endpoint", "POST /orders").status == "needs_review"
    assert _status(res, "code", "http_route", "http:a:POST /orders").status == "needs_review"


def test_manifest_name_match_and_specified(tmp_path):
    res = _build(
        tmp_path,
        {
            "ad2v.yaml": "pairing:\n  components: {CMP-1: api, CMP-9: nowhere, CMP-404: api}\n",
            "api/pyproject.toml": "",
            "billing/pyproject.toml": "",
            "api/x.py": "def f():\n    pass\n",
            "billing/y.py": "def g():\n    pass\n",
            "specs/c.md": textwrap.dedent("""
            ## Component: Public API {#CMP-1}
            ## Component: Ghost {#CMP-9}
            ## Component: Billing {#CMP-2}
            ## Component: Payments {#CMP-3}
            - [REQ-1] The billing shall bill.
        """).lstrip(),
        },
    )
    assert _links(res, "CMP-1", "container:api")[0].method == "manifest"
    assert _status(res, "spec", "spec_component", "CMP-1").status == "implemented"
    ghost = _links(res, "CMP-9")[0]
    assert (ghost.status, ghost.method, ghost.evidence[0]["kind"]) == (
        "missing",
        "manifest",
        "target_not_found",
    )
    assert _links(res, "CMP-2", "container:billing")[0].method == "name_match"
    assert _status(res, "spec", "spec_component", "CMP-3").status == "specified"  # no rule covers it
    assert _status(res, "spec", "requirement", "REQ-1").status == "specified"
    assert {"kind": "manifest_spec_id_not_found", "spec_id": "CMP-404"} in res.pairing.warnings
    # a function inside a linked container inherits implemented; never orphan
    assert _status(res, "code", "function", "api/x.py::f").status == "implemented"


def test_name_match_ambiguous(tmp_path):
    res = _build(
        tmp_path,
        {
            "ad2v.yaml": "containers:\n  - {name: core, paths: [core]}\n  - {name: other, paths: [other]}\n",
            "core/x.py": "",
            "other/core/y.py": "",
            "specs/c.md": "## Component: Core {#CMP-1}\n",
        },
    )
    links = _links(res, "CMP-1")
    assert len(links) == 2 and {lk.status for lk in links} == {"needs_review"}


def test_orphan_scope(tmp_path):
    res = _build(
        tmp_path,
        {
            "specs/c.md": "- [REQ-1] The api shall ping.\n",
            "svc/pyproject.toml": "",
            "svc/web.py": """
            from fastapi import FastAPI
            import typer
            app = FastAPI()
            cli = typer.Typer()

            @app.get("/ping")
            def ping():
                # ad2v: REQ-1
                return "pong"

            @app.get("/debug")
            def debug():
                return 1

            @cli.command()
            def run():
                helper()

            def helper():
                pass
        """,
        },
    )
    assert _status(res, "code", "http_route", "http:svc:GET /debug").status == "orphan"
    assert _status(res, "code", "cli_command", "cli:svc:run").status == "orphan"
    assert _status(res, "code", "container", "container:svc").status == "orphan"
    ping = _status(res, "code", "http_route", "http:svc:GET /ping")
    assert ping.status == "implemented" and ping.reasons[0]["kind"] == "via_handler"
    for fn in ("svc/web.py::debug", "svc/web.py::helper", "svc/web.py::run"):
        assert _status(res, "code", "function", fn).status == "none"  # never orphan
    assert _status(res, "code", "module", "svc/web.py").status == "none"
    assert not [
        lk
        for lk in res.pairing.links
        if lk.status == "orphan" and res.graph.nodes[lk.code_node_id].kind in ("function", "class", "module")
    ]


def test_verified_needs_passing_linked_test(tmp_path):
    files = {
        "specs/c.md": "- [REQ-1] The api shall ping.\n- [REQ-2] The api shall pong.\n",
        "app.py": "def ping():\n    # ad2v: REQ-1\n    pass\n\ndef pong():\n    # ad2v: REQ-2\n    pass\n",
        "tests/test_app.py": "def test_req_1_ping():\n    pass\n\ndef test_req_2_pong():\n    pass\n",
    }
    junit = """
    <testsuite>
      <testcase classname="tests.test_app" name="test_req_1_ping" time="0.01"/>
      <testcase classname="tests.test_app" name="test_req_2_pong" time="0.01"><failure/></testcase>
    </testsuite>
    """
    res = _build(tmp_path / "with", files, junit)
    assert _status(res, "spec", "requirement", "REQ-1").status == "verified"
    assert _status(res, "code", "function", "app.py::ping").status == "verified"
    r2 = _status(res, "spec", "requirement", "REQ-2")
    assert r2.status == "implemented"
    pong = _links(res, "REQ-2", "app.py::pong")[0]
    assert {"kind": "tests_failed", "tests": ["tests/test_app.py::test_req_2_pong"]} in pong.evidence
    # without a results file, nothing is verified
    res_none = _build(tmp_path / "without", files)
    assert "verified" not in {s.status for s in res_none.pairing.statuses.values()}


def test_unresolved_ref_is_needs_review_and_precedence(tmp_path):
    res = _build(
        tmp_path,
        {
            "specs/c.md": "- [REQ-1] The api shall ping.\n",
            "app.py": "def f():\n    # ad2v: REQ-1, REQ-77\n    pass\n",
        },
    )
    st = _status(res, "code", "function", "app.py::f")
    assert st.status == "needs_review"  # needs_review outranks implemented
    assert {r["kind"] for r in st.reasons} == {"link", "unresolved_ref"}


def test_precedence_order_is_the_documented_one():
    order = [s for s in ir.STATUS_PRECEDENCE if s not in ("stale", "none")]
    assert order == [
        "drift",
        "needs_review",
        "missing",
        "orphan",
        "verified",
        "implemented",
        "not_evaluable",
        "specified",
    ]  # P8.1: not_evaluable (ADR-0066)
    assert ir.STATUS_PRECEDENCE[-1] == "none"


def test_precedence_on_constructed_links():
    g = ir.Graph()
    s = g.add_node(ir.Node("spec", "spec_endpoint", "GET /a", "GET /a", content_hash="0" * 64))
    c = g.add_node(ir.Node("code", "http_route", "GET /a", "http:x:GET /a", content_hash="0" * 64))
    links = [
        ir.Link(s.id, c.id, "implemented", "route_match"),
        ir.Link(s.id, c.id, "drift", "annotation"),
        ir.Link(s.id, None, "missing", "none"),
    ]
    st = pairing._node_statuses(g, links, pairing._ancestors(g))
    assert st[s.id].status == "drift" and st[c.id].status == "drift"


def test_rollup_counts_descendants(tmp_path):
    res = _build(
        tmp_path,
        {
            "ad2v.yaml": "pairing:\n  components: {CMP-1: svc}\n",
            "svc/pyproject.toml": "",
            "svc/a.py": "def f():\n    pass\n",
            "specs/c.md": "## Component: S {#CMP-1}\n",
        },
    )
    cont = ids.node_id("code", "container", "container:svc")
    assert res.pairing.rollup[cont] == {"implemented": 2}  # module + function
    assert cont not in [n for n, r in res.pairing.rollup.items() if not r]
