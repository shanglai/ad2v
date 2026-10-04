"""P6.1 M2: where specs come from (--spec > ad2v.yaml spec_root > auto-detection)."""

from __future__ import annotations

import subprocess

import pytest

from ad2v import gitsource, pipeline, specroots
from ad2v.cli import main

from helpers import write_tree

CODE = {
    "svc/main.py": """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/items")
        def items():
            return []
    """
}
OPENAPI = """
    openapi: 3.0.3
    info: {title: t, version: "1"}
    paths:
      /items:
        get:
          responses: {"200": {description: ok}}
"""
CONVENTION = """
    ## Component: Store {#CMP-001}

    - [REQ-001] The store shall list items.
"""


def spec_docs(res) -> list[str]:
    return sorted(n.qualified_name for n in res.graph.nodes.values() if n.kind == "spec_doc")


def test_cli_wins_and_is_repeatable(tmp_path):
    write_tree(
        tmp_path, {**CODE, "specs/api.yaml": OPENAPI, "docs/req.md": CONVENTION, "other/x.md": CONVENTION}
    )
    one = pipeline.build(tmp_path, tmp_path / "docs")
    assert one.spec_roots.source == "cli" and one.spec_roots.labels == ["docs"]
    assert spec_docs(one) == ["req.md"]  # one root: paths relative to it, as before P6.1
    two = pipeline.build(tmp_path, [tmp_path / "docs", tmp_path / "other"])
    assert spec_docs(two) == ["docs/req.md", "other/x.md"]  # several roots: prefixed, never colliding
    assert two.spec_roots.describe() == "spec roots (--spec): docs/, other/"
    assert one.config.config_hash != two.config.config_hash  # discovery is part of the config


def test_manifest_spec_root_string_list_and_missing(tmp_path):
    write_tree(
        tmp_path / "a",
        {
            **CODE,
            "requirements/r.md": CONVENTION,
            "specs/api.yaml": OPENAPI,
            "ad2v.yaml": "spec_root: requirements\n",
        },
    )
    res = pipeline.build(tmp_path / "a")
    assert res.spec_roots.source == "manifest" and spec_docs(res) == ["r.md"]  # specs/ is NOT auto-detected
    write_tree(
        tmp_path / "b",
        {**CODE, "r1/a.md": CONVENTION, "r2/b.yaml": OPENAPI, "ad2v.yaml": "spec_root: [r1, r2]\n"},
    )
    assert spec_docs(pipeline.build(tmp_path / "b")) == ["r1/a.md", "r2/b.yaml"]
    write_tree(tmp_path / "c", {**CODE, "ad2v.yaml": "spec_root: nope\n"})
    with pytest.raises(specroots.SpecRootError):
        pipeline.build(tmp_path / "c")
    write_tree(tmp_path / "d", {**CODE, "ad2v.yaml": "spec_root: {a: 1}\n"})
    with pytest.raises(Exception, match="spec_root"):
        pipeline.build(tmp_path / "d")


def test_autodetect_order_root_openapi_and_prose_only(tmp_path):
    write_tree(
        tmp_path,
        {
            **CODE,
            "spec/a.feature": "Feature: F\n  Scenario: S\n    Given x\n",
            # not recognized (prose only): docs/specs/ is skipped
            "docs/specs/notes.md": "# Notes\n\nJust prose, no requirements here.\n",
            "specs/req.md": CONVENTION,
            "openapi.json": '{"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}}',
            "specs/helper.py": "def not_code_side():\n    return 1\n",
        },
    )
    res = pipeline.build(tmp_path)
    assert res.spec_roots.source == "auto"
    assert res.spec_roots.labels == ["specs", "spec", "openapi.json"]
    assert spec_docs(res) == ["openapi.json", "spec/a.feature", "specs/req.md"]
    assert not any(n.path == "specs/helper.py" for n in res.graph.nodes.values())  # never double-counted
    off = pipeline.build(tmp_path, spec_autodetect=False)
    assert off.spec_roots.source == "none" and spec_docs(off) == [] and off.meta["spec_coverage"] == "none"
    assert off.spec_roots.describe().startswith("spec roots: none found (prose only?")


def test_project_with_specs_inside_and_no_flags(tmp_path, capsys):
    """The developer's question: code in project/, the SDD in project/specs/, no flags."""
    write_tree(
        tmp_path / "project", {**CODE, "specs/openapi.yaml": OPENAPI, "specs/components.md": CONVENTION}
    )
    out = tmp_path / "p.ad2v"
    assert main(["extract", "--repo", str(tmp_path / "project"), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "spec roots (auto-detected): specs/" in printed
    res = pipeline.build(tmp_path / "project")
    assert res.meta["spec_coverage"] == "present" and spec_docs(res) == ["components.md", "openapi.yaml"]
    statuses = {res.graph.nodes[n].qualified_name: s.status for n, s in res.pairing.statuses.items()}
    assert statuses["GET /items"] == "implemented"
    capsys.readouterr()
    assert (
        main(["extract", "--repo", str(tmp_path / "project"), "--no-spec-autodetect", "--out", str(out)]) == 0
    )
    assert "spec roots: none found" in capsys.readouterr().out


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_history_resolves_per_commit(tmp_path):
    repo = tmp_path / "r"
    write_tree(repo, CODE)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "code")
    write_tree(repo, {"specs/openapi.yaml": OPENAPI})
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "specs")
    first = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    out = tmp_path / "h.ad2v"
    got = gitsource.run_history(repo, f"{first}^!", out)
    got += gitsource.run_history(repo, f"{first}..HEAD", out)
    assert [r.spec_roots.labels for _, r in got] == [[], ["specs"]]
    assert got[1][1].epoch.change_kind in ("spec", "mixed")
    explicit = gitsource.run_history(repo, f"{first}^!", tmp_path / "e.ad2v", spec_rel="specs")
    assert (
        explicit[0][1].spec_roots.source == "cli" and explicit[0][1].spec_roots.roots == []
    )  # absent: no fallback
