"""Builds the P3 history scenario: a temporary git repo starting from fixtures/payments-recon,
then scripted commits (format spec §6.6-6.7 and REPORT §3). Deterministic: fixed author/dates,
so commit SHAs are identical across runs for identical content.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ad2v import ids

from helpers import FIXTURE

REQ3_OLD = "- [REQ-003] The matcher shall treat amounts that differ by at most one cent as equal."
REQ3_NEW = "- [REQ-003] The matcher shall treat amounts that differ by at most two cents as equal."
REQ3_FP = ids.content_hash(REQ3_NEW)[:8]  # the requirement's content_hash covers its line


def git_available() -> bool:
    return shutil.which("git") is not None


def _git(repo: Path, *args: str, date: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "ad2v",
        "GIT_AUTHOR_EMAIL": "ad2v@example.invalid",
        "GIT_COMMITTER_NAME": "ad2v",
        "GIT_COMMITTER_EMAIL": "ad2v@example.invalid",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return out.stdout.strip()


class Scenario:
    def __init__(self, root: Path, crlf: bool = False, bom: bool = False) -> None:
        self.repo = root / "payments-recon"
        self.crlf, self.bom = crlf, bom
        self.commits: list[tuple[str, str]] = []  # (label, sha)

    def _write(self, rel: str, text: str) -> None:
        data = text.replace("\r\n", "\n")
        if self.crlf:
            data = data.replace("\n", "\r\n")
        raw = data.encode("utf-8")
        if self.bom and rel.endswith((".py", ".md")):
            raw = b"\xef\xbb\xbf" + raw
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)

    def _read(self, rel: str) -> str:
        return ids.read_normalized(self.repo / rel)

    def edit(self, rel: str, old: str, new: str) -> None:
        text = self._read(rel)
        assert text.count(old) >= 1, (rel, old)
        self._write(rel, text.replace(old, new))

    def commit(self, label: str) -> str:
        date = f"2026-01-{len(self.commits) + 1:02d}T12:00:00+00:00"
        _git(self.repo, "add", "-A", date=date)
        _git(self.repo, "commit", "-q", "-m", label, date=date)
        sha = _git(self.repo, "rev-parse", "HEAD", date=date)
        self.commits.append((label, sha))
        return sha

    def build(self) -> Scenario:
        self.repo.mkdir(parents=True)
        for src in sorted(FIXTURE.rglob("*")):
            if src.is_file() and "__pycache__" not in src.parts:
                rel = src.relative_to(FIXTURE).as_posix()
                if src.suffix in (".py", ".md", ".yaml", ".yml", ".feature", ".toml", ".xml"):
                    self._write(rel, ids.read_normalized(src))
                else:
                    (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, self.repo / rel)
        _git(self.repo, "init", "-q", "-b", "main", date="2026-01-01T12:00:00+00:00")
        for label, step in STEPS:
            step(self)
            self.commit(label)
        return self


def _rename(s: Scenario) -> None:  # 2: identical body, new name -> lineage same_content
    s.edit("api/recon_api/matching.py", "def amounts_match(", "def amounts_equal(")
    s.edit("api/recon_api/matching.py", "and amounts_match(tx", "and amounts_equal(tx")
    s.edit(
        "api/tests/test_matching.py", "import amounts_match, match_batch", "import amounts_equal, match_batch"
    )
    s.edit(
        "api/tests/test_matching.py", "assert amounts_match(1000, 1001)", "assert amounts_equal(1000, 1001)"
    )
    s.edit("api/tests/test_matching.py", "assert not amounts_match(", "assert not amounts_equal(")


def _spec_edit(s: Scenario) -> None:  # 3: REQ-003 text changes -> its links go stale
    s.edit("specs/components.md", REQ3_OLD, REQ3_NEW)


def _approve(s: Scenario) -> None:  # 4: the approve endpoint gets a route -> missing -> implemented
    s.edit(
        "api/recon_api/routes.py",
        '@router.get("/{run_id}/unmatched")',
        '@router.post("/{run_id}/approve")\n'
        "def approve_run(run_id: str) -> dict:\n"
        "    # ad2v: REQ-007\n"
        '    return {"run_id": run_id, "status": "approved"}\n\n\n'
        '@router.get("/{run_id}/unmatched")',
    )


def _start_run_body(s: Scenario) -> None:  # 5a: verified code changes, same test results -> stale
    s.edit(
        "api/recon_api/routes.py",
        "    db.record_run(result)\n",
        "    result['accounts'] = len(req.account_ids)\n    db.record_run(result)\n",
    )


def _tests_only(s: Scenario) -> None:  # 5b: a new passing test run -> back to verified (tests_only)
    s.edit("test-results/junit.xml", 'timestamp="2026-09-28T09:00:00"', 'timestamp="2026-09-29T09:00:00"')
    s.edit(
        "test-results/junit.xml",
        'name="test_req_001_start_run_returns_run_result" time="0.012"',
        'name="test_req_001_start_run_returns_run_result" time="0.014"',
    )


def _loop_header(s: Scenario) -> None:  # 6: loop header edited slightly -> lineage anchored_header
    s.edit("api/recon_api/matching.py", "    for tx in transactions:\n", "    for tx in transactions[:]:\n")


def _reannotate(s: Scenario) -> None:  # 7: "I re-checked this against the current spec" -> stale clears
    s.edit("api/recon_api/matching.py", "# ad2v: REQ-003\n", f"# ad2v: REQ-003@{REQ3_FP}\n")
    s.edit(
        "api/tests/test_matching.py",
        "def test_req_003_amounts_within_one_cent_match():\n",
        f"def test_req_003_amounts_within_one_cent_match():\n    # ad2v: REQ-003@{REQ3_FP}\n",
    )


STEPS: list[tuple[str, Callable[[Scenario], None]]] = [
    ("1 baseline", lambda s: None),
    ("2 rename amounts_match -> amounts_equal", _rename),
    ("3 edit REQ-003 spec text", _spec_edit),
    ("4 add approve route", _approve),
    ("5a change start_run body", _start_run_body),
    ("5b tests-only: new passing JUnit run", _tests_only),
    ("6 edit loop header in match_batch", _loop_header),
    ("7 re-annotate REQ-003 with spec fingerprint", _reannotate),
]
