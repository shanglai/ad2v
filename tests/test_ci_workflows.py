"""P8 M4: static checks of .github/workflows (actionlint is not installed here).

Every action pinned by a full commit SHA, read-only default permissions, no costly OS on push while
the repo is private, and a release workflow that cannot publish (manual trigger only, `if: false`)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name: str) -> dict:
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as true
    return data


def _uses(node) -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += [v] if k == "uses" else _uses(v)
    elif isinstance(node, list):
        for v in node:
            out += _uses(v)
    return out


def test_actions_are_pinned_by_full_sha_and_permissions_are_minimal():
    files = sorted(p.name for p in WF.glob("*.yml"))
    assert files == ["ci.yml", "release.yml"]
    for name in files:
        wf = _load(name)
        assert wf["permissions"] == {"contents": "read"}, name
        uses = _uses(wf["jobs"])
        assert uses, name
        for u in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u), (name, u)
        for job in wf["jobs"].values():
            assert "timeout-minutes" in job
            for perm in (job.get("permissions") or {}).values():
                assert perm in ("read", "write")
        text = (WF / name).read_text(encoding="utf-8")
        assert all(f"@{u.split('@')[1]} # v" in text for u in uses), "each pin names its tag"


def test_ci_runs_windows_and_macos_only_on_manual_dispatch():
    wf = _load("ci.yml")
    assert set(wf["on"]) == {"push", "pull_request", "workflow_dispatch"}
    for job in ("viewer", "python"):
        expr = wf["jobs"][job]["strategy"]["matrix"]["os"]
        assert "workflow_dispatch" in expr and "inputs.all_os" in expr
        assert expr.rstrip(" }").endswith("'[\"ubuntu-latest\"]')")
    for job in ("determinism", "plugins"):
        assert wf["jobs"][job]["runs-on"] == "ubuntu-latest"


def test_release_cannot_publish():
    wf = _load("release.yml")
    assert set(wf["on"]) == {"workflow_dispatch"}
    pub = wf["jobs"]["publish"]
    assert pub["if"] is False
    assert pub["environment"]["name"] == "pypi"
    assert pub["permissions"] == {"id-token": "write"}
    assert "dev" in (WF / "release.yml").read_text(encoding="utf-8")  # refuses .dev versions
