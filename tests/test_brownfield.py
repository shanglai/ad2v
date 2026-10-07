"""P9 M1 + M6 (ADR-0071): `ad2v init` on the brownfield fixture, zero-config vs init, and the
detectors one by one. Everything here is deterministic and makes no LLM call (the bootstrap cycle
uses the fake provider)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from ad2v import init as onboarding
from ad2v import pipeline
from ad2v.cli import main
from ad2v.manifest import from_data

from helpers import write_tree

ROOT = Path(__file__).resolve().parent.parent
BF = ROOT / "fixtures" / "brownfield-es"
EXP = yaml.safe_load((BF / "expected.yaml").read_text(encoding="utf-8"))


def _filled(tmp_path: Path) -> Path:
    """The proposal written by init, with the empty path_constants value filled in (the human)."""
    out = tmp_path / "bf.yaml"
    assert main(["init", "--repo", str(BF), "--write", str(out)]) == 0
    text = out.read_text(encoding="utf-8").replace(
        '"settings.API_PREFIX": ""', '"settings.API_PREFIX": "/api/v1"'
    )
    out.write_text(text, encoding="utf-8")
    return out


def _statuses(res: pipeline.Result) -> dict[str, str]:
    g = res.graph
    return {g.nodes[k].qualified_name: v.status for k, v in res.pairing.statuses.items()}


def test_init_report_and_proposal_match_the_golden(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(["init", "--repo", "fixtures/brownfield-es"]) == 0
    got = capsys.readouterr().out
    assert got == (BF / "expected-init.txt").read_text(encoding="utf-8")


def test_init_is_deterministic_and_line_ending_invariant(tmp_path):
    a = onboarding.scan(BF, "x")
    b = onboarding.scan(BF, "x")
    assert a.to_dict() == b.to_dict()
    crlf = tmp_path / "crlf" / "brownfield-es"
    shutil.copytree(BF, crlf)
    for p in crlf.rglob("*"):
        if p.is_file() and p.suffix in (
            ".md",
            ".py",
            ".feature",
            ".yaml",
            ".ts",
            ".sql",
            ".tf",
            ".toml",
            ".json",
        ):
            p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    c = onboarding.scan(crlf, "x")
    assert onboarding.render_yaml(a, onboarding.proposal(a)) == onboarding.render_yaml(
        c, onboarding.proposal(c)
    )


def test_the_proposal_is_a_valid_manifest():
    fd = onboarding.scan(BF, "fixtures/brownfield-es")
    text = onboarding.render_yaml(fd, onboarding.proposal(fd))
    data = yaml.safe_load(text)
    assert data == onboarding.proposal(fd)
    cfg = from_data(data, BF)
    assert cfg.path_constants == {}  # the empty placeholder is ignored, never a guess
    assert cfg.test_ref_prefixes == ("CMP", "FR", "HU", "REQ", "RF", "RNF")


def test_detectors_on_the_brownfield_fixture():
    fd = onboarding.scan(BF, "bf")
    assert fd.spec_roots == ["sdd"]
    assert fd.spec_candidates[0]["evidence"] == {
        "gherkin": 1,
        "openapi": 1,
        "prose": 1,
        "stories": 1,
        "table": 1,
    }
    assert fd.prose == ["sdd/contexto.md"]
    assert [(c["name"], c["language"], c["read"]) for c in fd.containers] == [
        ("backend", "python", True),
        ("frontend", "typescript", False),
    ]
    assert {e["pattern"]: e["code_files"] for e in fd.excludes} == {"dist": 2, "node_modules": 1}
    assert [s["path"] for s in fd.sql] == ["src/db/migrations/V2__indices.sql", "src/db/schema.sql"]
    assert all(s["dropped_by"] is None for s in fd.sql)
    assert fd.infra == {"terraform": ["infra"]}
    assert fd.test_results == {"junit": [], "pytest_config": ["src/backend/pyproject.toml"]}
    assert fd.path_constants == ["settings.API_PREFIX"] and fd.unresolved_routes == 3
    assert fd.spec_id_prefixes == ["HU", "RF", "RNF"] and fd.nonfunctional_prefixes == ["RNF"]


def _check_mode(res: pipeline.Result, mode: str) -> None:
    exp = EXP[mode]
    assert res.spec_roots.describe() == exp["spec_roots"]
    assert (
        sorted(n.qualified_name for n in res.graph.nodes.values() if n.kind == "container")
        == exp["containers"]
    )
    st = _statuses(res)
    for q, want in exp["status"].items():
        assert st[q] == want, (mode, q, st[q])


def test_zero_config_extract(tmp_path):
    res = pipeline.build(BF)
    counts: dict[str, int] = {}
    for n in res.graph.nodes.values():
        if n.side == "spec" and n.kind != "spec_root":
            counts[n.kind] = counts.get(n.kind, 0) + 1
    assert counts == EXP["spec_counts"]
    assert res.config.spec_presets == EXP["presets"]
    assert res.stats["unextracted"] == EXP["unextracted"]
    nf = sorted(
        n.qualified_name
        for n in res.graph.nodes.values()
        if n.attrs.get("requirement_type") == "nonfunctional"
    )
    assert nf == EXP["nonfunctional"]
    _check_mode(res, "zero_config")


def test_extract_with_the_init_proposal(tmp_path):
    res = pipeline.build(BF, manifest=_filled(tmp_path))
    _check_mode(res, "init")
    g = res.graph
    ev = {
        g.nodes[lk.spec_node_id].qualified_name: [e["kind"] for e in lk.evidence]
        for lk in res.pairing.links
        if lk.spec_node_id
    }
    assert ev["RF-007"] == ["component_out_of_scope"]
    store = next(n for n in g.nodes.values() if n.kind == "datastore")
    tables = {t["table"] for t in store.attrs["schema_digest"]["tables"]}
    assert {"corridas", "movimientos"} <= tables  # SQLAlchemy models and schema.sql
    assert not any("migrations/0002_backfill" in (n.path or "") for n in g.nodes.values())


def test_write_force_and_check(tmp_path, capsys):
    out = tmp_path / "p.yaml"
    assert main(["init", "--repo", str(BF), "--write", str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert main(["init", "--repo", str(BF), "--write", str(out)]) == 2  # refuses to overwrite
    assert "--force" in capsys.readouterr().err
    assert main(["init", "--repo", str(BF), "--write", str(out), "--force"]) == 0
    assert out.read_text(encoding="utf-8") == first
    capsys.readouterr()
    assert main(["init", "--repo", str(BF), "--check", str(out)]) == 1  # path_constants still empty
    assert "settings.API_PREFIX" in capsys.readouterr().out
    filled = _filled(tmp_path / "f")
    assert main(["init", "--repo", str(BF), "--check", str(filled)]) == 0
    stale = tmp_path / "stale.yaml"
    stale.write_text(
        "spec_root: [specs]\nexclude: [gone]\ncontainers: [{name: old, paths: [old]}]\n", encoding="utf-8"
    )
    assert main(["init", "--repo", str(BF), "--check", str(stale)]) == 1
    msg = capsys.readouterr().out
    for want in (
        "new spec folder: sdd",
        "spec folder no longer recognized: specs",
        "new container: backend",
        "container not found any more: old",
        "stale exclude (matches nothing): gone",
        "test-name prefixes not listed: HU, RF, RNF",
    ):
        assert want in msg, want
    assert main(["init", "--repo", str(BF), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["proposal"]["spec_root"] == ["sdd"] and data["findings"]["spec_roots"] == ["sdd"]
    assert main(["init", "--repo", str(tmp_path / "missing")]) == 2


def test_a_repository_with_nothing_recognizable(tmp_path, capsys):
    write_tree(
        tmp_path / "plain",
        {"app.py": "x = 1\n", "docs/notas.md": "# Notas\n\nTexto libre sobre el sistema.\n"},
    )
    assert main(["init", "--repo", str(tmp_path / "plain")]) == 0
    out = capsys.readouterr().out
    assert "No spec format recognized" in out and "specs bootstrap" in out


def test_spec_folders_by_content_and_generated_excludes(tmp_path):
    write_tree(
        tmp_path / "r",
        {
            "docs/producto/req.md": "| ID | Descripción |\n|---|---|\n| RF-1 | El sistema deberá x. |\n",
            "README.md": "# R\n",
            "web/package.json": "{}",
            "web/src/generated/client.ts": "export const c = 1;\n",
            "web/src/a.ts": "export const a = 1;\n",
            "build/out.sql": "CREATE TABLE t (id INT);\n",
            "k8s/deploy.yaml": "apiVersion: apps/v1\nkind: Deployment\n",
            "Chart.yaml": "name: x\n",
            "reports/junit.xml": "<testsuite name='x'></testsuite>\n",
        },
    )
    fd = onboarding.scan(tmp_path / "r", "r")
    assert fd.spec_roots == ["docs/producto"]  # not a named folder: found by content
    assert fd.extra_excludes == ["generated"]
    assert next(e for e in fd.excludes if e["pattern"] == "generated")["code_files"] == 1
    assert fd.sql[0]["dropped_by"] == "build"
    assert set(fd.infra) == {"helm", "kubernetes"}
    assert fd.test_results["junit"] == ["reports/junit.xml"]
    text = onboarding.render_report(fd, None)
    assert "WARNING: dropped by the exclude 'build'" in text
    assert "--test-results r/reports/junit.xml" in text


@pytest.mark.parametrize("subdir", ["sdd", "docs/sdd"])
def test_zero_config_extract_finds_sdd_folders(tmp_path, subdir):
    write_tree(
        tmp_path / "r",
        {f"{subdir}/r.md": "| ID | Descripción |\n|---|---|\n| RF-1 | El sistema deberá x. |\n"},
    )
    assert pipeline.build(tmp_path / "r").spec_roots.labels == [subdir]
    write_tree(tmp_path / "p", {f"{subdir}/notas.md": "# Notas\n\nSolo prosa.\n"})
    assert pipeline.build(tmp_path / "p").spec_roots.labels == []  # still conservative


def test_bootstrap_cycle_with_sdd_as_the_spec_root(tmp_path, capsys):
    repo = tmp_path / "brownfield-es"
    shutil.copytree(BF, repo)
    rec = tmp_path / "rec"
    rec.mkdir()
    out = {
        "requirements": [
            {
                "component": "Cierre diario",
                "ears": "ubiquitous",
                "text": "El sistema deberá dejar lista la conciliación diaria"
                " antes de las diez de la mañana.",
                "source_start_line": 7,
                "source_end_line": 7,
            }
        ]
    }
    (rec / "rec.json").write_text(
        json.dumps({"recordings": [{"task": "extract-prose", "subject": "contexto.md", "output": out}]}),
        encoding="utf-8",
    )
    base = [
        "specs",
        "bootstrap",
        "--repo",
        str(repo),
        "--from",
        "sdd/contexto.md",
        "--provider",
        "fake",
        "--replay-dir",
        str(rec),
    ]
    assert main([*base, "--plan"]) == 0
    assert "sdd/contexto.md" in capsys.readouterr().out
    assert main([*base, "--yes", "--max-cost-usd", "0.1"]) == 0
    prop = repo / "sdd" / ".ad2v-extracted" / "contexto.md"
    assert prop.is_file() and "REQ-X001" in prop.read_text(encoding="utf-8")
    # the proposal has the source's name, so it goes to its own folder (approve never overwrites)
    assert main(["specs", "approve", "--repo", str(repo), "contexto.md", "--to", "sdd/aprobados"]) == 0
    st = _statuses(pipeline.build(repo))
    assert st["REQ-X001"] == "specified"  # approved prose now counts as a spec item
