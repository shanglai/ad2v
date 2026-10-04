"""P7 M2 retrieval v2 (ADR-0054): link propagation with a spec intent, status ordering, resource
words, spec ids (namespaced, synthesized, sub-ids), test code de-weighted; the preset eval set."""

from __future__ import annotations

from pathlib import Path

import pytest

from ad2v import pipeline
from ad2v.mcp import evaluate, locate
from ad2v.mcp.files import FileSet
from ad2v.mcp.protocol import Request
from ad2v.mcp.tools import Ctx, status_rank, t_status

REPO = Path(__file__).resolve().parent.parent
PRESETS = REPO / "fixtures" / "sdd-presets"


@pytest.fixture(scope="module")
def preset_maps(tmp_path_factory) -> dict[str, Path]:
    tmp = tmp_path_factory.mktemp("presets")
    out = {}
    for name in ("spec-kit", "kiro", "custom"):
        out[name] = tmp / f"{name}.ad2v"
        pipeline.extract_to_file(PRESETS / name, None, out[name], name_hint=name)
    return out


def _loc(path: Path):
    ctx = Ctx(FileSet(single=path))
    ix, conn = ctx.index({})
    return ix, locate.build(conn, ix), ctx


def _top(ix, loc, q: str, k: int = 3) -> list[str]:
    return [ix.nodes[r["id"]]["qname"] for r in loc.rank(q, k, ix=ix)]


def test_query_ids_and_matching():
    ids, subs = locate.query_ids("is 003-Payments:fr-001 the same as FR-001 or criterion 1.2?")
    assert ids == {"003-payments:FR-001", "FR-001"} and subs == {"1.2"}
    assert locate.id_matches("001-payments:FR-001", {"FR-001"}, set())  # bare id finds namespaced items
    assert locate.id_matches("001-payments:FR-001", {"001-payments:FR-001"}, set())
    assert not locate.id_matches("002-refunds:FR-001", {"001-payments:FR-001"}, set())
    assert locate.id_matches("ORDEREXPORT-1.2", set(), {"1.2"})
    assert not locate.id_matches("ORDEREXPORT-1.2", set(), {"2.1"})
    assert locate.query_ids("version 3.12 of python") == (set(), {"3.12"})  # harmless: no -3.12 id


def test_ids_are_searchable_bare_full_and_sub(preset_maps):
    ix, loc, _ = _loc(preset_maps["spec-kit"])
    assert set(_top(ix, loc, "FR-001", 2)) == {"001-payments:FR-001", "002-refunds:FR-001"}
    assert _top(ix, loc, "002-refunds:FR-002", 1) == ["002-refunds:FR-002"]
    ix, loc, _ = _loc(preset_maps["kiro"])
    assert _top(ix, loc, "ORDEREXPORT-1.2", 1) == ["ORDEREXPORT-1.2"]
    assert _top(ix, loc, "acceptance criterion 1.3", 1) == ["ORDEREXPORT-1.3"]


def test_spec_intent_propagates_from_linked_code(preset_maps):
    ix, loc, _ = _loc(preset_maps["kiro"])
    q = "which requirement writes one CSV row per order?"
    with_prop = _top(ix, loc, q, 1)
    loc.link_lambda = 0.0
    assert with_prop[0].startswith("ORDEREXPORT-1")
    loc.link_lambda = 0.8
    r = loc.rank(q, 10, ix=ix)
    assert any("linked" in x["matched"] or x["id"] in loc.linked for x in r)


def test_test_code_ranks_lower_unless_asked(preset_maps):
    ix, loc, _ = _loc(preset_maps["kiro"])
    tests = [i for i in loc.is_test]
    assert tests, "the kiro fixture has a test module"
    q = "export orders"
    plain = {r["id"]: r["score"] for r in loc.rank(q, 50, ix=ix)}
    asked = {r["id"]: r["score"] for r in loc.rank(q + " tests", 50, ix=ix)}
    t = next(i for i in tests if i in plain)
    assert asked[t] > plain[t]


def test_status_order_puts_ports_first():
    assert status_rank("http_route") == status_rank("spec_endpoint") == 0
    assert status_rank("container") == status_rank("component") == 1
    assert status_rank("function") == status_rank("requirement") == 2


def test_status_tool_order_on_fixture(tmp_path):
    out = tmp_path / "f.ad2v"
    pipeline.extract_to_file(REPO / "fixtures" / "payments-recon", None, out, name_hint="payments-recon")
    from ad2v import materialize

    materialize.materialize_file(out, "head") if hasattr(materialize, "materialize_file") else None
    ctx = Ctx(FileSet(single=out))
    sc = t_status(ctx, Request(0, "tools/call", {}, "", {}, modern=True), {"status": "orphan"})[
        "structuredContent"
    ]
    kinds = [n["kind"] for n in sc["nodes"]]
    assert kinds[0] == "http_route", kinds  # q14: the orphan route before its containers
    assert [status_rank(k) for k in kinds] == sorted(status_rank(k) for k in kinds)


def test_resources_carry_kind_words_and_toucher_names(tmp_path):
    out = tmp_path / "f.ad2v"
    pipeline.extract_to_file(REPO / "fixtures" / "payments-recon", None, out, name_hint="payments-recon")
    ix, loc, _ = _loc(out)
    rid = next(i for i, n in ix.nodes.items() if n["qname"] == "external_service:env:BANK_API_URL")
    words = set(loc.k1_docs["code"].tf[rid])
    assert {"extern", "servic"} <= words or {"external", "service"} <= words
    assert locate.tokens("fetch_statement")[0] in words  # the function that calls it


def test_preset_eval_set(preset_maps):
    qs = evaluate.load_questions(PRESETS / "expected-questions.yaml")
    assert len(qs) == 10 and sum(1 for q in qs if q.get("holdout")) == 3
    r = evaluate.run_grouped(preset_maps, qs)
    assert r["overall"]["recall@5"] >= 0.9 and r["overall"]["mrr"] >= 0.8, r["overall"]
