import textwrap

from ad2v import ir
from ad2v.extract.spec import extract_specs, gherkin, markdown, openapi

from helpers import node, qnames, write_tree


def _md(text):
    g = ir.Graph()
    markdown.extract(g, "spec.md", textwrap.dedent(text).lstrip("\n"))
    return g


def test_markdown_components_requirements_and_prose():
    g = _md("""
        # Title

        Intro prose.

        ## Component: Billing API {#CMP-010}

        Handles invoices.

        - [REQ-100] When a customer pays, the billing API shall mark the invoice as paid.
        - [REQ-101] The billing API shall log every request.
        - [REQ-102] Not really EARS at all.

        ## Other section

        - [REQ-103] If the card is declined, then the billing API shall notify the customer.
        - [REQ-104] While in maintenance mode, the billing API shall reject writes.
        - [REQ-105] Where multi-currency is enabled, the billing API shall convert amounts.
        - [REQ-106] While offline, when a payment arrives, the queue shall buffer it.

        ```
        ## Component: Not a component {#CMP-999}
        - [REQ-999] When x, the y shall z.
        ```

        ## Component: Unnumbered
        text
    """)
    assert qnames(g, "spec_component") == ["CMP-010", "spec.md::Unnumbered"]
    assert qnames(g, "requirement") == [f"REQ-10{i}" for i in range(7)]
    comp = node(g, "spec_component", "CMP-010")
    assert comp.attrs["text"] == "Handles invoices."
    assert (comp.span_start_line, comp.span_end_line) == (5, 11)
    r = {n.qualified_name: n.attrs for n in g.nodes.values() if n.kind == "requirement"}
    assert r["REQ-100"]["ears"] == "event"
    assert r["REQ-100"]["trigger"] == "a customer pays"
    assert r["REQ-100"]["system"] == "billing API"
    assert r["REQ-100"]["response"] == "mark the invoice as paid"
    assert r["REQ-101"]["ears"] == "ubiquitous"
    assert r["REQ-102"]["ears"] is None
    assert r["REQ-103"]["ears"] == "unwanted"
    assert r["REQ-104"]["ears"] == "state"
    assert r["REQ-105"]["ears"] == "optional"
    assert r["REQ-106"]["ears"] == "event" and r["REQ-106"]["precondition"] == "offline"
    assert node(g, "requirement", "REQ-100").parent_id == comp.id
    doc = node(g, "spec_doc", "spec.md")
    assert node(g, "requirement", "REQ-103").parent_id == doc.id
    assert "Intro prose." in doc.attrs["prose"] and "REQ-999" in doc.attrs["prose"]


def test_gherkin_feature_background_outline_rule_and_tags():
    g = ir.Graph()
    text = textwrap.dedent("""
        @CMP-1 @smoke
        Feature: Payments
          Background:
            Given a user

          @REQ-1
          Scenario: Pay
            When they pay
            Then it works
              | a | b |
              | 1 | 2 |

          Scenario Outline: Many
            When <x>
            Examples:
              | x |
              | 1 |
              | 2 |

          Rule: Refunds
            Scenario: Pay
              Then refund
          Scenario: Pay
            Then again
    """).lstrip("\n")
    scenarios = gherkin.extract(g, "f/pay.feature", text)
    assert len(scenarios) == 5
    feat = node(g, "spec_component", "f/pay.feature::Payments")
    assert feat.spec_ref == ["CMP-1"] and feat.attrs["tags"] == ["@CMP-1", "@smoke"]
    assert feat.span_start_line == 1
    assert qnames(g, "scenario") == [
        "f/pay.feature::Payments::Background",
        "f/pay.feature::Payments::Many",
        "f/pay.feature::Payments::Pay",
        "f/pay.feature::Payments::Refunds::Pay",
        "f/pay.feature::Payments::Refunds::Pay#2",
    ]
    pay = node(g, "scenario", "f/pay.feature::Payments::Pay")
    assert pay.spec_ref == ["REQ-1"] and pay.span_start_line == 6
    step = node(g, "scenario_step", "f/pay.feature::Payments::Pay::step[2]")
    assert step.attrs["keyword"] == "Then" and (step.span_start_line, step.span_end_line) == (9, 11)
    assert node(g, "scenario", "f/pay.feature::Payments::Many").attrs["examples"] == 2
    assert node(g, "scenario", "f/pay.feature::Payments::Background").attrs["background"] is True


def test_openapi_operations_lines_and_refs():
    g = ir.Graph()
    text = textwrap.dedent("""
        openapi: 3.1.0
        info: {title: T, version: 1}
        paths:
          /a:
            get:
              operationId: getA
              x-ad2v-refs: [REQ-1]
              responses: {"200": {description: ok}}

            post:
              operationId: postA
              responses: {"200": {description: ok}}
            parameters: []
          /b/{id}:
            delete:
              responses: {"204": {description: gone}}
    """).lstrip("\n")
    assert openapi.is_openapi(text)
    openapi.extract(g, "api.yaml", text)
    assert qnames(g, "spec_endpoint") == ["DELETE /b/{id}", "GET /a", "POST /a"]
    get_a = node(g, "spec_endpoint", "GET /a")
    assert (get_a.span_start_line, get_a.span_end_line) == (5, 8)
    assert get_a.spec_ref == ["REQ-1"] and get_a.attrs["operation_id"] == "getA"
    post_a = node(g, "spec_endpoint", "POST /a")
    assert (post_a.span_start_line, post_a.span_end_line) == (10, 12)
    assert not openapi.is_openapi("swagger: '2.0'\n")
    assert not openapi.is_openapi(": : :\n")


def test_extract_specs_dispatch_and_skip(tmp_path):
    write_tree(
        tmp_path,
        {
            "a.md": "- [REQ-1] The system shall work.\n",
            "b.feature": "Feature: F\n  Scenario: S\n    Given x\n",
            "openapi.json": '{"openapi": "3.0.0", "info": {"title": "t", "version": "1"},'
            ' "paths": {"/x": {"get": {}}}}',
            "config.yaml": "not: openapi\n",
        },
    )
    g = ir.Graph()
    read = extract_specs(g, tmp_path, ())
    assert sorted(read) == ["a.md", "b.feature", "openapi.json"]
    assert qnames(g, "spec_endpoint") == ["GET /x"]
    assert qnames(g, "requirement") == ["REQ-1"]
