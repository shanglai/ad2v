"""P6.1 M3: SDD Markdown presets (spec-kit, Kiro, custom) against their goldens; ids; determinism."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ad2v import dump, ids, pipeline
from ad2v.extract.spec import presets

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sdd-presets"


def _build(name: str):
    return pipeline.build(FIX / name, name_hint=name)


def _q(res, nid: str) -> str:
    return res.graph.nodes[nid].qualified_name


@pytest.mark.parametrize("name", ["spec-kit", "kiro", "custom", "table", "stories"])
def test_preset_fixture_matches_golden(name):
    exp = yaml.safe_load((FIX / name / "expected.yaml").read_text(encoding="utf-8"))
    res = _build(name)
    g = res.graph
    assert res.spec_roots.labels == exp["spec_roots"]
    assert res.config.spec_presets == exp["presets"]
    counts: dict[str, int] = {}
    for n in g.nodes.values():
        if n.side == "spec" and n.kind != "spec_root":
            counts[n.kind] = counts.get(n.kind, 0) + 1
    assert counts == exp["counts"]
    status = {_q(res, k): v.status for k, v in res.pairing.statuses.items()}
    by_q = {n.qualified_name: n for n in g.nodes.values()}
    for q, st, extra in exp["requirements"]:
        assert status[q] == st, q
        n = by_q[q]
        assert n.kind == "requirement"
        if name == "spec-kit":
            assert n.attrs["category"] == extra and n.attrs["spec_id"] == q
        else:
            assert n.attrs.get("ears") == extra, q
    for child, parent in (exp.get("parents") or {}).items():
        assert _q(res, by_q[child].parent_id) == parent
    if "links" in exp:
        got = sorted(
            [_q(res, lk.spec_node_id), _q(res, lk.code_node_id), lk.status, [e["kind"] for e in lk.evidence]]
            for lk in res.pairing.links
            if lk.code_node_id and lk.spec_node_id
        )
        assert got == sorted(exp["links"])
    for q, steps in (exp.get("scenarios") or {}).items():
        kids = sorted(
            (n for n in g.nodes.values() if n.parent_id == by_q[q].id), key=lambda n: n.qualified_name
        )
        assert [k.name for k in kids] == steps
    if "skipped_ids" in exp:
        doc = next(n for n in g.nodes.values() if n.kind == "spec_doc")
        assert doc.attrs["skipped_ids"] == exp["skipped_ids"]
    # P9 (ADR-0069): titles, non-functional requirements, actors, Given/When/Then, doc notes
    for q, title in (exp.get("titles") or {}).items():
        assert by_q[q].attrs["title"] == title, q
    if "nonfunctional" in exp:
        got = sorted(
            n.qualified_name for n in g.nodes.values() if n.attrs.get("requirement_type") == "nonfunctional"
        )
        assert got == exp["nonfunctional"]
        assert res.stats["nonfunctional_requirements"] == len(got)
    for q, actor in (exp.get("actors") or {}).items():
        assert by_q[q].attrs["actor"] == actor, q
    for q, parts in (exp.get("gwt") or {}).items():
        assert by_q[q].attrs["gwt"] == parts, q
    for doc_q, attrs in (exp.get("docs") or {}).items():
        for k, v in attrs.items():
            assert by_q[doc_q].attrs[k] == v, (doc_q, k)


def test_spec_id_grammar_and_kiro_prefixes():
    import re

    full = re.compile(r"^" + ids.SPEC_ID_PATTERN + r"$")
    for ok in ("REQ-001", "REQ-X001", "003-payments:FR-001", "ORDEREXPORT-1.2", "a:B-1.10"):
        assert full.match(ok), ok
    for bad in ("req-1", "FR-", "003-Payments:FR-001", ":FR-1"):
        assert not full.match(bad), bad
    assert presets.kiro_prefix("order-export") == "ORDEREXPORT"
    assert presets.kiro_prefix("001-auth") == "K001AUTH"
    assert presets.kiro_prefix("a-very-long-feature-name") == "AVERYLONGFEA"
    a = presets.Choice("kiro", prefix="AUTH", feature="auth")
    got = presets.assign_prefixes({"x/auth/requirements.md": a, "y/auth/requirements.md": a})
    assert [got[k].prefix for k in sorted(got)] == ["AUTH", "AUTH2"]  # collisions: deterministic suffix


def test_selection_rules_and_auto_detection():
    speckit = "# Feature Specification: X\n\n### Functional Requirements\n\n- **FR-001**: System MUST x.\n"
    assert presets.detect("specs/003-x/spec.md", speckit) == "spec-kit"
    assert presets.detect("specs/003-x/notes.md", speckit) is None  # spec-kit needs spec.md
    assert presets.detect(".kiro/specs/f/requirements.md", "anything") == "kiro"
    # spec-kit's own checklists/requirements.md is not Kiro (path, not just the name)
    assert presets.detect("specs/003-x/checklists/requirements.md", "- [ ] CHK001 x") is None
    assert presets.detect("docs/a.md", "## Component: A {#CMP-1}\n") == "ad2v"
    rules = [{"glob": "docs/*.md", "preset": "kiro", "id_prefix": "PAY"}]
    ch = presets.choose("docs/a.md", "## Component: A {#CMP-1}\n", rules)
    assert ch.preset == "kiro" and ch.prefix == "PAY"  # a rule wins over auto-selection
    with pytest.raises(presets.PresetError):
        presets.choose("docs/a.md", "", [{"glob": "docs/*", "preset": "nope"}])
    with pytest.raises(presets.PresetError):
        presets.choose("docs/a.md", "", [{"glob": "docs/*", "preset": "custom"}])  # custom needs regexes


def test_kiro_ears_both_generations():
    assert presets.parse_ears("WHEN x happens THEN the Exporter SHALL write y")["system"] == "the Exporter"
    new = presets.parse_ears("WHEN a user submits a form, THE SYSTEM SHALL validate it")
    assert new["ears"] == "event" and new["system"] == "SYSTEM" and new["trigger"] == "a user submits a form"
    assert presets.parse_ears("THE CLI SHALL NOT need a sandbox")["response"] == "NOT need a sandbox"
    assert presets.parse_ears("WHERE dark mode is on, THE app SHALL dim")["ears"] == "optional"
    assert (
        presets.parse_ears("When it rains, the roof shall hold.")["ears"] == "event"
    )  # ad2v templates still apply
    assert presets.parse_ears("Something else")["ears"] is None


def _crlf_bom_copy(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)
    for p in dst.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".py", ".yaml", ".feature"):
            text = p.read_text(encoding="utf-8").replace("\n", "\r\n")
            p.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))


@pytest.mark.parametrize("name", ["spec-kit", "kiro", "custom", "table", "stories"])
def test_preset_dumps_are_deterministic_and_crlf_bom_invariant(name, tmp_path):
    outs = []
    for i, src in enumerate([FIX / name, FIX / name, tmp_path / "crlf" / name]):
        if i == 2:
            _crlf_bom_copy(FIX / name, src)
        out = tmp_path / f"{i}.ad2v"
        pipeline.extract_to_file(src, None, out, name_hint=name)
        outs.append(dump.canonical_dump(out, normative_only=True))
    assert outs[0] == outs[1] == outs[2]
