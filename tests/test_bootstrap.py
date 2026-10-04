"""P6.1 M4: `ad2v specs bootstrap / review / approve` with the fake provider (no real LLM calls)."""

from __future__ import annotations

import json

import pytest

from ad2v import bootstrap, pipeline
from ad2v.cli import main

from helpers import write_tree

NOTES = """
    # Team notes

    The worker must retry the bank feed with exponential backoff, at most five times.
    When a reconciliation run completes, the operator needs a CSV export of the unmatched rows.
"""
REPO = {
    "app/export.py": """
        def export_unmatched(run_id):
            return []
    """,
    "specs/components.md": """
        ## Component: Exports {#CMP-001}

        - [REQ-001] When a reconciliation run completes, the API shall offer the unmatched rows as CSV.
    """,
    "docs/NOTES.md": NOTES,
    "docs/short.md": "# Short\n\nToo short.\n",
}


def recordings(tmp_path, subject: str = "NOTES.md"):
    d = tmp_path / "rec"
    d.mkdir()
    out = {
        "requirements": [
            {
                "component": "Exports",
                "ears": "event",
                "text": "When a reconciliation run completes, the export service shall produce a CSV of the "
                "unmatched rows.",
                "source_start_line": 4,
                "source_end_line": 4,
            },
            {
                "component": "Bank feed",
                "ears": "ubiquitous",
                "text": "The worker shall retry the bank feed with exponential backoff at most five times.",
                "source_start_line": 3,
                "source_end_line": 3,
            },
        ]
    }
    (d / "rec.json").write_text(
        json.dumps({"recordings": [{"task": "extract-prose", "subject": subject, "output": out}]})
    )
    return d


def run(repo, rec, *extra):
    return main(
        [
            "specs",
            "bootstrap",
            "--repo",
            str(repo),
            "--from",
            str(repo / "docs"),
            "--provider",
            "fake",
            "--replay-dir",
            str(rec),
            *extra,
        ]
    )


def test_full_cycle_plan_run_review_approve_extract(tmp_path, capsys):
    repo = tmp_path / "repo"
    write_tree(repo, REPO)
    rec = recordings(tmp_path)

    # plan: lists the qualifying files (outside the spec root too) and makes no calls
    assert run(repo, rec, "--plan") == 0
    out = capsys.readouterr().out
    assert "yes  docs/NOTES.md  (free prose)" in out and "no   docs/short.md  (too little prose" in out
    assert "plan (no calls made): 1 call(s)" in out
    assert not (repo / "specs" / ".ad2v-extracted").exists()
    assert run(repo, rec) == 2  # no --yes: refused

    # run: writes the proposal and its index entry
    assert run(repo, rec, "--yes", "--max-cost-usd", "0.1") == 0
    out = capsys.readouterr().out
    assert "proposed .ad2v-extracted/notes.md  <- docs/NOTES.md" in out
    prop = repo / "specs" / ".ad2v-extracted" / "notes.md"
    text = prop.read_text(encoding="utf-8")
    assert (
        "REVIEW BEFORE COMMITTING" in text
        and "{#CMP-X001}" in text
        and "- [REQ-X001] When a reconciliation" in text
    )
    idx = json.loads((prop.parent / "index.json").read_text(encoding="utf-8"))
    assert idx["notes.md"]["source"] == "docs/NOTES.md" and idx["notes.md"]["model"] == "fake-1"

    # review: counts, overlap with the existing spec, not stale
    rows = bootstrap.review(repo, repo / "specs", overlap_min=0.2)
    assert rows[0]["components"] == 2 and rows[0]["requirements"] == 2 and rows[0]["stale"] is False
    assert any(o["existing"] in ("REQ-001", "CMP-001") for o in rows[0]["overlaps"])
    assert main(["specs", "review", "--repo", str(repo)]) == 0
    assert "current" in capsys.readouterr().out

    # proposals are never parsed while in .ad2v-extracted/
    before = pipeline.build(repo)
    assert "REQ-X001" not in {n.qualified_name for n in before.graph.nodes.values()}

    # approve (the human act) -> the next extract parses it -> an annotation pairs it
    assert main(["specs", "approve", "--repo", str(repo), "notes.md"]) == 0
    assert (repo / "specs" / "notes.md").is_file() and not prop.exists()
    assert "notes.md" not in json.loads((prop.parent / "index.json").read_text(encoding="utf-8"))
    (repo / "app" / "export.py").write_text(
        "def export_unmatched(run_id):\n    # ad2v: REQ-X001\n    return []\n"
    )
    after = pipeline.build(repo)
    st = {after.graph.nodes[k].qualified_name: v.status for k, v in after.pairing.statuses.items()}
    assert st["REQ-X001"] == "implemented" and st["REQ-X002"] == "specified"

    # a second bootstrap continues the -X numbering after the approved ids
    assert bootstrap._next_x(repo / "specs") == (3, 3)


def test_stale_and_overwrite_are_refused(tmp_path, capsys):
    repo = tmp_path / "repo"
    write_tree(repo, REPO)
    rec = recordings(tmp_path)
    assert run(repo, rec, "--yes", "--max-cost-usd", "0.1") == 0
    (repo / "docs" / "NOTES.md").write_text(
        "# Team notes\n\nEverything changed since the extraction, for real.\n"
    )
    assert bootstrap.review(repo, repo / "specs")[0]["stale"] is True
    capsys.readouterr()
    assert main(["specs", "approve", "--repo", str(repo), "notes.md"]) == 1
    assert "changed since extraction" in capsys.readouterr().out
    (repo / "specs" / "notes.md").write_text("already here\n")
    with pytest.raises(bootstrap.BootstrapError, match="overwrite"):
        bootstrap.approve(repo, repo / "specs", "notes.md", force_stale=True)
    dest = bootstrap.approve(
        repo, repo / "specs", "notes.md", to=repo / "specs" / "proposed", force_stale=True
    )
    assert dest == repo / "specs" / "proposed" / "notes.md"
    with pytest.raises(bootstrap.BootstrapError, match="no proposal"):
        bootstrap.approve(repo, repo / "specs", "missing.md")


def test_candidates_and_errors(tmp_path):
    repo = tmp_path / "repo"
    write_tree(
        repo,
        {
            **REPO,
            "docs/kiro/.kiro/specs/f/requirements.md": "### Requirement 1\n\n**User Story:** As a user, I "
            "want x.\n",
            "docs/plain.txt": "Operators need the export within one hour of the run, every working day of "
            "the week.\n",
            "docs/image.png": "not text",
        },
    )
    got = {
        c.rel: (c.qualifies, c.reason)
        for c in bootstrap.candidates(repo, [repo / "docs", repo / "specs" / "components.md"])
    }
    assert got["docs/NOTES.md"] == (True, "free prose")
    assert got["docs/plain.txt"][0] is True  # text files qualify
    assert got["specs/components.md"] == (False, "already parsed by the ad2v preset")
    assert got["docs/kiro/.kiro/specs/f/requirements.md"][1] == "already parsed by the kiro preset"
    assert "docs/image.png" not in got
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.candidates(repo, [repo / "nope"])
    assert bootstrap.spec_root_of(repo, None) == (repo / "specs").resolve()
    assert bootstrap.spec_root_of(repo, "elsewhere") == (repo / "elsewhere").resolve()
    r = bootstrap.bootstrap(repo, [repo / "docs" / "short.md"], None, spec_root=repo / "specs")
    assert r["note"] == "no file qualifies"
    with pytest.raises(bootstrap.BootstrapError, match="max-cost"):
        from ad2v.llm.config import from_data

        bootstrap.bootstrap(
            repo,
            [repo / "docs" / "NOTES.md"],
            from_data({"provider": "fake"}),
            spec_root=repo / "specs",
            plan_only=False,
        )
