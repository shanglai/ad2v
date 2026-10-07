"""P7 M1: docs/quickstart.md, executed. Every local command in the guide runs against a copy of the
fixture (and the P3 history scenario), the way a user would type it. Cloud steps are skipped with
a reason. If this test fails, the guide and the CLI disagree: fix one of them (ADR-0052)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from history_scenario import Scenario, git_available

from helpers import FIXTURE

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "quickstart.md"
PRESETS = ROOT / "fixtures" / "sdd-presets"


def ad2v(*args: object, cwd: Path | None = None, inp: str | None = None, ok: bool = True) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "ad2v", *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        input=inp,
        timeout=300,
    )
    if ok:
        assert r.returncode == 0, f"ad2v {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}"
    return r.stdout + r.stderr


@pytest.fixture(scope="module")
def ws(tmp_path_factory) -> dict[str, Path]:
    tmp = tmp_path_factory.mktemp("qs")
    proj = tmp / "my-project"
    shutil.copytree(FIXTURE, proj, ignore=shutil.ignore_patterns("__pycache__", "expected*.yaml"))
    maps = tmp / "ad2v-maps"
    maps.mkdir()
    return {"tmp": tmp, "proj": proj, "maps": maps, "map": maps / "my-project.ad2v"}


def test_guide_exists_and_draft_is_gone():
    text = GUIDE.read_text(encoding="utf-8")
    assert not (ROOT / "docs" / "quickstart-draft.md").exists()
    for cmd in (
        "ad2v extract",
        "ad2v history",
        "ad2v view",
        "ad2v llm plan",
        "ad2v specs bootstrap",
        "ad2v mcp",
    ):
        assert cmd in text, cmd
    assert "Your SDD format" in text


def test_step2b_existing_project_init(ws):
    """P9 (ADR-0071): `ad2v init` on an existing project, as step 2b shows it."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "## 2b. Existing project? Start with `ad2v init`" in text
    proj = ws["tmp"] / "brownfield"
    shutil.copytree(ROOT / "fixtures" / "brownfield-es", proj)
    before = sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*"))
    out = ad2v("init", "--repo", proj)
    assert "proposed ad2v.yaml" in out and "settings.API_PREFIX" in out
    y = ws["maps"] / "brownfield.yaml"
    ad2v("init", "--repo", proj, "--write", y)
    assert sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*")) == before  # nothing written there
    y.write_text(y.read_text(encoding="utf-8").replace('": ""', '": "/api/v1"'), encoding="utf-8")
    m = ws["maps"] / "brownfield.ad2v"
    ad2v("extract", "--repo", proj, "--manifest", y, "--out", m)
    assert "POST /api/v1/conciliaciones" in ad2v("status", m, "--status", "implemented")
    assert "up to date" in ad2v("init", "--repo", proj, "--check", y)
    data = json.loads(ad2v("init", "--repo", proj, "--format", "json"))
    assert data["findings"]["spec_id_prefixes"] == ["HU", "RF", "RNF"]


def test_step5_first_extraction(ws):
    p, m = ws["proj"], ws["map"]
    out = ad2v(
        "extract", "--repo", p, "--spec", p / "specs", "--manifest", p / "ad2v.yaml",
        "--test-results", p / "test-results" / "junit.xml", "--out", m,
    )  # fmt: skip
    assert "spec roots (--spec): specs/" in out and "risky behaviors" in out and "Unresolved spec refs" in out
    auto = ad2v("extract", "--repo", p, "--out", ws["maps"] / "auto.ad2v")  # no --spec: auto-detected
    assert "spec roots (auto-detected): specs/" in auto
    assert "POST /reconciliations/{run_id}/approve" in ad2v("status", m, "--status", "missing")
    assert "http:api:GET /internal/debug/stats" in ad2v("status", m, "--status", "orphan")
    assert "unbounded_retry" in ad2v("inspect", m, "--top-risk", "10")
    assert "conforms to ad2v format" in ad2v("validate", m)


@pytest.mark.skipif(not git_available(), reason="git not installed")
def test_step6_history(ws):
    sc = Scenario(ws["tmp"] / "hist").build()  # 8 scripted commits
    h = ws["maps"] / "hist.ad2v"
    # HEAD~N..HEAD needs at least N+1 commits; the guide says so and offers `--commits HEAD`
    assert "unknown revision" in ad2v(
        "history", "--repo", sc.repo, "--commits", "HEAD~20..HEAD", "--into", h, ok=False
    )
    out = ad2v("history", "--repo", sc.repo, "--spec", "specs", "--commits", "HEAD", "--into", h)
    assert "8 commit(s) processed" in out
    assert "* = head" in ad2v("log", h)
    assert "### ad2v: epoch" in ad2v("diff", h, "--format", "md")
    assert "materialized" in ad2v("materialize", h, "--epochs", "last:5")
    assert "no changes" in ad2v("extract", "--repo", sc.repo, "--into", h)  # same inputs as the head


def test_step7_view_serves(ws):
    proc = subprocess.Popen(
        [sys.executable, "-m", "ad2v", "view", str(ws["map"]), "--no-browser", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        line = proc.stdout.readline()  # type: ignore[union-attr]
        url = re.search(r"http://127\.0\.0\.1:\d+/\S+", line)
        assert url, line
        with urllib.request.urlopen(url.group(0), timeout=10) as r:  # noqa: S310 (localhost)
            assert r.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_step8_llm_plan_offline(ws):
    man = ws["tmp"] / "llm.yaml"  # the guide's snippet with the offline provider instead of vertex
    man.write_text(
        "llm:\n  provider: fake\n  model: fake-1\n  output_language: en\n"
        "  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}\n  budget_usd: 1.00\n"
        "  summaries: {scope: structural}\n",
        encoding="utf-8",
    )
    out = ad2v("llm", "plan", ws["map"], "--manifest", man)
    assert "judge" in out and "est USD" in out
    assert "id  state" in ad2v("suggestions", "list", ws["map"], "--open")


@pytest.mark.skip(reason="cloud: `llm run` with provider vertex needs ADC and spends money (M8, approval)")
def test_step8_llm_run_vertex():  # pragma: no cover
    pass


def test_step3_bootstrap_plan_and_review(ws):
    p = ws["proj"]
    out = ad2v("specs", "bootstrap", "--repo", p, "--from", "specs", "--plan", cwd=ROOT)  # cwd != repo
    assert "yes  specs/operations.md  (free prose)" in out  # --from is repo-relative (ADR-0052)
    assert "no   specs/components.md" in out and "plan (no calls made): 1 call(s)" in out
    assert "no proposals" in ad2v("specs", "review", "--repo", p)


@pytest.mark.parametrize(
    "name,root", [("spec-kit", "specs/"), ("kiro", ".kiro/specs/"), ("custom", "requirements/")]
)
def test_sdd_format_presets(ws, name, root):
    out = ad2v("extract", "--repo", PRESETS / name, "--out", ws["maps"] / f"{name}.ad2v")
    assert root in out.splitlines()[0]


def test_step9_mcp_tools_list(ws):
    meta = "io.modelcontextprotocol/"
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {"_meta": {meta + "protocolVersion": "2026-07-28", meta + "clientCapabilities": {}}},
    }
    r = subprocess.run(
        [sys.executable, "-m", "ad2v", "mcp", "--file", str(ws["map"]), "--no-warm"],
        input=json.dumps(req) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    names = {t["name"] for t in json.loads(r.stdout.splitlines()[0])["result"]["tools"]}
    assert {"ad2v_overview", "ad2v_locate", "ad2v_show"} <= names
