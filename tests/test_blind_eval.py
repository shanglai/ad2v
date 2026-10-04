"""P8 M2: the blind retrieval eval prints aggregates only (never a question, gold id, label or row).

These tests build their own temporary question sets on the public fixture; they never read a real
blind set (AD2V_BLIND_EVAL is always set to a temporary path here)."""

from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path

import pytest
import yaml

from ad2v import pipeline
from ad2v.cli import main
from ad2v.mcp import blind

from helpers import FIXTURE

ROOT = Path(__file__).resolve().parent.parent
MARK = "zqx-secret"


@pytest.fixture(scope="module")
def fixture_map(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("blindmap") / "private-repo-name.ad2v"
    pipeline.extract_to_file(FIXTURE, None, out)
    return out


def _set(tmp_path: Path, fixture_map: Path, extra: list[dict] | None = None, n: int = 6) -> Path:
    d = tmp_path / f"{MARK}-dir"
    d.mkdir()
    shutil.copy(fixture_map, d / f"{MARK}-map.ad2v")
    qs = [
        {
            "id": f"{MARK}-id-{i}",
            "map": f"{MARK}-label",
            "type": "where",
            "q": f"where is the matching of transactions implemented {MARK}-question-{i}?",
            "gold": ["api/recon_api/matching.py"],
        }
        for i in range(n)
    ]
    qs += extra or []
    f = d / f"{MARK}-file.yaml"
    f.write_text(
        yaml.safe_dump(
            {"ad2v_blind_eval": 1, "maps": {f"{MARK}-label": f"{MARK}-map.ad2v"}, "questions": qs}
        ),
        encoding="utf-8",
    )
    return f


def _run_cli(monkeypatch, capsys, location: Path, *args: str) -> tuple[int, str]:
    monkeypatch.setenv(blind.ENV, str(location))
    code = main(["eval", "blind", *args])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def _no_leak(text: str) -> None:
    assert MARK not in text
    assert "matching" not in text and "recon_api" not in text and "private-repo-name" not in text


def test_runner_prints_and_writes_aggregates_only(monkeypatch, capsys, tmp_path, fixture_map):
    gold_missing = {
        "id": f"{MARK}-x",
        "map": f"{MARK}-label",
        "type": "risk",
        "q": f"{MARK} q?",
        "gold": [f"{MARK}/nowhere.py"],
    }
    invalid = {"id": f"{MARK}-y", "q": f"{MARK} no map"}
    f = _set(tmp_path, fixture_map, [gold_missing, invalid])
    out_file = tmp_path / "agg.json"
    for args in ((), ("--json",), ("--json", "--out", str(out_file)), ("--locate-only",)):
        code, text = _run_cli(monkeypatch, capsys, f, *args)
        assert code == 0
        _no_leak(text)
    data = json.loads(out_file.read_text(encoding="utf-8"))
    _no_leak(json.dumps(data))
    assert set(data) == {
        "ad2v_version",
        "blind_set",
        "questions",
        "method",
        "metrics",
        "by_type",
        "types_suppressed",
    }
    assert data["questions"] == {"scored": 6, "invalid": 1, "gold_not_found": 1, "failed": 0}
    assert data["blind_set"]["sha256"] == [hashlib.sha256(f.read_bytes()).hexdigest()]
    assert set(data["metrics"]) == {"mrr", "recall@5", "ndcg@5"}
    for m in data["metrics"].values():
        assert set(m) == {"mean", "ci95"} and m["ci95"][0] <= m["mean"] <= m["ci95"][1]
    assert set(data["by_type"]) == {"where"} and data["by_type"]["where"]["n"] == 6
    assert data["types_suppressed"] == 0  # the risk question was dropped (gold not found)


def test_small_type_groups_are_suppressed(monkeypatch, capsys, tmp_path, fixture_map):
    f = _set(tmp_path, fixture_map, n=4)
    code, text = _run_cli(monkeypatch, capsys, f, "--json")
    data = json.loads(text)
    assert data["by_type"] == {} and data["types_suppressed"] == 1
    _no_leak(text)


def test_directory_location_and_error_paths_do_not_leak(monkeypatch, capsys, tmp_path, fixture_map):
    f = _set(tmp_path, fixture_map)
    code, text = _run_cli(monkeypatch, capsys, f.parent)
    assert code == 0
    _no_leak(text)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "a.yaml").write_text(
        f"ad2v_blind_eval: 1\nquestions: [{{q: '{MARK}' , gold: [\n", encoding="utf-8"
    )
    code, text = _run_cli(monkeypatch, capsys, bad)
    assert code == 2 and "invalid YAML" in text
    _no_leak(text)
    (bad / "a.yaml").write_text(
        yaml.safe_dump({"ad2v_blind_eval": 1, "maps": {"x": f"{MARK}-missing.ad2v"}, "questions": []}),
        encoding="utf-8",
    )
    code, text = _run_cli(monkeypatch, capsys, bad)
    assert code == 2 and "map file(s) not found" in text
    _no_leak(text)
    (bad / "a.yaml").write_text(
        yaml.safe_dump(
            {
                "ad2v_blind_eval": 1,
                "maps": {"x": "a.yaml"},
                "questions": [{"id": "1", "map": "x", "type": "t", "q": MARK, "gold": [MARK]}],
            }
        ),
        encoding="utf-8",
    )
    code, text = _run_cli(monkeypatch, capsys, bad)
    assert code == 2 and "could not be opened" in text
    _no_leak(text)
    monkeypatch.delenv(blind.ENV, raising=False)
    assert main(["eval", "blind"]) == 2


def test_bootstrap_ci_is_seeded_and_sane():
    vals = [1.0, 0.5, 0.0, 1.0, 1.0, 0.25]
    a = blind.bootstrap_ci(vals, random.Random(987654))
    b = blind.bootstrap_ci(vals, random.Random(987654))
    assert a == b and 0.0 <= a[0] <= sum(vals) / len(vals) <= a[1] <= 1.0
    assert blind.bootstrap_ci([], random.Random(1)) == (0.0, 0.0)
    assert blind.bootstrap_ci([0.7] * 5, random.Random(1)) == (0.7, 0.7)


def test_template_runs(monkeypatch, capsys, tmp_path, fixture_map):
    tpl = tmp_path / "blind-template.yaml"
    shutil.copy(ROOT / "fixtures" / "retrieval-eval" / "blind-template.yaml", tpl)
    shutil.copy(fixture_map, tmp_path / "payments-recon.ad2v")
    code, text = _run_cli(monkeypatch, capsys, tpl, "--json")
    data = json.loads(text)
    assert code == 0 and data["questions"]["scored"] == 2 and data["questions"]["gold_not_found"] == 0


def test_blind_dir_is_gitignored():
    assert "fixtures/retrieval-eval/blind/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
