"""P9 M2 (ADR-0069): table and stories presets, Spanish EARS, Spanish Gherkin, short titles."""

from __future__ import annotations

import pytest

from ad2v import ir
from ad2v.extract.spec import gherkin, markdown, presets, team, titles
from ad2v.manifest import from_data

from helpers import write_tree


def test_split_row_keeps_escaped_and_code_pipes():
    assert team.split_row("| a | b \\| c | `x|y` |") == ["a", "b | c", "`x|y`"]
    assert team.split_row("| a<br>b |") == ["a b"]
    assert team.split_row("not a row") is None


def test_headers_ignore_case_accents_and_markup():
    cols = team._columns(["**Código**", "DESCRIPCIÓN", "Título", "Módulo", "Prioridad", "Tipo"])
    assert cols == {"id": 0, "text": 1, "title": 2, "component": 3, "priority": 4, "type": 5}
    assert team._columns(["Nombre", "Descripción"]) is None  # no id column: not a requirement table


def test_detection_order_keeps_earlier_presets():
    table = "| ID | Descripción |\n|---|---|\n| RF-001 | El sistema deberá x. |\n"
    assert presets.detect("docs/r.md", table) == "table"
    assert presets.detect("docs/r.md", "- [REQ-001] The api shall x.\n\n" + table) == "ad2v"
    assert presets.detect("docs/r.md", "| ID | Descripción |\n|---|---|\n| nada | x |\n") is None
    stories = "## HU-001: X\n\nComo cliente, quiero pagar, para irme.\n"
    assert presets.detect("docs/h.md", stories) == "stories"
    assert presets.detect("docs/h.md", "## HU-001: X\n\nTexto libre.\n") is None


@pytest.mark.parametrize(
    "text,pattern,response",
    [
        ("Cuando llega un extracto, el sistema deberá conciliarlo.", "event", "conciliarlo"),
        ("Mientras el banco no responda, el sistema debe reintentar.", "state", "reintentar"),
        ("Si falta el monto, entonces el sistema deberá rechazar la fila.", "unwanted", "rechazar la fila"),
        ("Si falta el monto, el sistema deberá rechazar la fila.", "unwanted", "rechazar la fila"),
        ("Donde haya exportación, la plataforma tendrá que generar un CSV.", "optional", "generar un CSV"),
        ("El sistema deberá registrar cada acceso.", "ubiquitous", "registrar cada acceso"),
        ("Los reportes deben incluir el total.", "ubiquitous", "incluir el total"),
        ("Mientras haya red, cuando llegue un pago, el sistema deberá aplicarlo.", "event", "aplicarlo"),
    ],
)
def test_spanish_ears(text, pattern, response):
    got = markdown.parse_ears(text)
    assert got["ears"] == pattern and got["response"] == response


def test_non_ears_text_stays_raw():
    assert markdown.parse_ears("La conciliación se hace de noche.") == {"ears": None}


def test_convention_title_syntax():
    g = ir.Graph()
    markdown.extract(
        g,
        "s.md",
        "## Component: Pagos {#CMP-001}\n\n"
        "- [REQ-001] (Cobro único) Cuando llega un pago, el sistema deberá cobrarlo.\n",
    )
    titles.apply_titles(g)
    req = next(n for n in g.nodes.values() if n.kind == "requirement")
    assert req.attrs["title"] == "Cobro único"
    assert req.attrs["text"].startswith("Cuando") and req.attrs["ears"] == "event"


@pytest.mark.parametrize(
    "text,title",
    [
        (
            "The api shall start a reconciliation run for the given accounts.",
            "Start a reconciliation run for",
        ),
        (
            "El sistema deberá emparejar cada movimiento con un asiento.",
            "Emparejar cada movimiento con un asiento",
        ),
        ("System MUST retry a timed-out charge [NEEDS CLARIFICATION: how many]", "Retry a timed-out charge"),
        ("Pagar   rápido.", "Pagar rápido"),
    ],
)
def test_short_titles(text, title):
    got = titles.short(text)
    assert got == title or (
        got.split() == title.split()[: len(got.split())] and len(got.split()) <= titles.WORDS
    )


def test_story_parts_and_actor_normalization():
    es = team.story_parts("Como **la Analista** de Finanzas, quiero exportar todo, para cerrar el mes.")
    assert es == {"actor": "analista de finanzas", "action": "exportar todo", "benefit": "cerrar el mes"}
    en = team.story_parts("As an auditor, I want to read runs so that I can sign them.")
    assert en["actor"] == "auditor" and en["action"] == "read runs" and en["benefit"] == "I can sign them"
    assert team.story_parts("Texto libre") == {}


def test_gwt_parts():
    assert team.gwt("Dado un pago, Cuando lo apruebo, Entonces se registra y se notifica") == {
        "given": "un pago",
        "when": "lo apruebo",
        "then": "se registra y se notifica",
    }
    assert team.gwt("solo texto") == {}


def test_nonfunctional_prefixes_are_configurable(tmp_path):
    from ad2v import pipeline

    write_tree(
        tmp_path / "r",
        {
            "specs/r.md": "| ID | Descripción |\n|---|---|\n"
            "| Q-1 | El sistema deberá ser rápido. |\n| RNF-1 | x |\n",
            "app.py": "x = 1\n",
        },
    )
    res = pipeline.build(tmp_path / "r")
    assert res.stats["nonfunctional_requirements"] == 1  # RNF by default
    (tmp_path / "r" / "ad2v.yaml").write_text("spec_ids:\n  nonfunctional_prefixes: [Q]\n", encoding="utf-8")
    res = pipeline.build(tmp_path / "r")
    nf = sorted(
        n.qualified_name
        for n in res.graph.nodes.values()
        if n.attrs.get("requirement_type") == "nonfunctional"
    )
    assert nf == ["Q-1"]
    assert from_data({"spec_ids": {"nonfunctional_prefixes": ["x"]}}, None).nonfunctional_prefixes == ("X",)


ES = """# language: es
@CMP-001
Característica: Conciliación
  Antecedentes:
    Dado un banco
  @RF-001
  Escenario: Conciliar
    Dado un extracto
    Cuando concilio
    Entonces veo el resultado
    Y nada más
    Pero sin errores
"""
EN = """@CMP-001
Feature: Conciliación
  Background:
    Given un banco
  @RF-001
  Scenario: Conciliar
    Given un extracto
    When concilio
    Then veo el resultado
    And nada más
    But sin errores
"""


def test_spanish_gherkin_gives_the_same_nodes_as_english():
    def shape(text: str) -> list[tuple[str, str, list[str], str | None]]:
        g = ir.Graph()
        gherkin.extract(g, "f.feature", text)
        return sorted(
            (n.kind, n.qualified_name.split("::", 1)[-1], n.spec_ref, n.attrs.get("keyword_type"))
            for n in g.nodes.values()
            if n.kind != "spec_doc"
        )

    es, en = shape(ES), shape(EN)
    assert [x[0] for x in es] == [x[0] for x in en]
    assert [x[2] for x in es] == [x[2] for x in en]
    assert [x[3] for x in es] == [x[3] for x in en]  # Context / Action / Outcome / Conjunction
    assert sum(1 for x in es if x[0] == "scenario_step") == 6
