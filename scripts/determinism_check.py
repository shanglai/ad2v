"""Determinism check across line endings (and, in CI, across operating systems). P8 M4.

For each fixture, extract it as checked out and from a copy with CRLF line endings and a UTF-8 BOM
on every text file, dump the normative content of every epoch, and require byte-identical dumps.
Writes {fixture: sha256 of the normative dump} as JSON, so a CI job can compare the hashes produced
on Linux, macOS and Windows.

    python scripts/determinism_check.py --out determinism-<os>.json
    python scripts/determinism_check.py --compare determinism-*.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = {
    "payments-recon": ROOT / "fixtures" / "payments-recon",
    "sdd-spec-kit": ROOT / "fixtures" / "sdd-presets" / "spec-kit",
    "sdd-kiro": ROOT / "fixtures" / "sdd-presets" / "kiro",
    "sdd-custom": ROOT / "fixtures" / "sdd-presets" / "custom",
    "polyglot": ROOT / "fixtures" / "polyglot",  # P8.1: not_evaluable TypeScript
    "sdd-table": ROOT / "fixtures" / "sdd-presets" / "table",  # P9
    "sdd-stories": ROOT / "fixtures" / "sdd-presets" / "stories",
    "brownfield-es": ROOT / "fixtures" / "brownfield-es",
}
TEXT = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".feature",
    ".sql",
    ".xml",
    ".json",
    ".toml",
    ".txt",
    ".routes",
    ".ts",
    ".tf",
    ".js",
}


def crlf_bom_copy(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.ad2v"))
    for p in sorted(dst.rglob("*")):
        if p.is_file() and p.suffix in TEXT:
            text = p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
            p.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))


def normative_dump(repo: Path, out: Path) -> bytes:
    from ad2v import dump, pipeline

    junit = repo / "test-results" / "junit.xml"
    pipeline.extract_to_file(
        repo, None, out, test_results=[junit] if junit.is_file() else None, name_hint=repo.name
    )
    return dump.canonical_dump(out, normative_only=True, epoch="all").encode("utf-8")


def run() -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="ad2v-determinism-"))
    try:
        for name, src in FIXTURES.items():
            lf_repo = tmp / "lf" / src.name
            shutil.copytree(src, lf_repo, ignore=shutil.ignore_patterns("__pycache__", "*.ad2v"))
            for p in lf_repo.rglob("*"):  # normalize whatever the checkout did (autocrlf)
                if p.is_file() and p.suffix in TEXT:
                    p.write_bytes(p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8"))
            crlf_repo = tmp / "crlf" / src.name
            crlf_bom_copy(src, crlf_repo)
            a = normative_dump(lf_repo, tmp / f"{name}-lf.ad2v")
            b = normative_dump(crlf_repo, tmp / f"{name}-crlf.ad2v")
            if a != b:
                problems.append(f"{name}: LF and CRLF+BOM normative dumps differ")
            hashes[name] = hashlib.sha256(a).hexdigest()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return hashes, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs="+", help="JSON files written by --out on different systems")
    a = ap.parse_args(argv)
    if a.compare:
        files = sorted({f for pat in a.compare for f in glob.glob(pat)})
        runs = {Path(f).stem: json.loads(Path(f).read_text(encoding="utf-8")) for f in files}
        if not runs:
            print("no result files to compare")
            return 2
        bad = 0
        for fixture in sorted({k for r in runs.values() for k in r}):
            values = {n: r.get(fixture) for n, r in runs.items()}
            same = len(set(values.values())) == 1
            bad += not same
            print(
                f"{'ok  ' if same else 'DIFF'} {fixture}: "
                + ", ".join(f"{n}={v[:12] if v else None}" for n, v in values.items())
            )
        return 1 if bad else 0
    hashes, problems = run()
    for n, h in hashes.items():
        print(f"{n}: {h}")
    if a.out:
        Path(a.out).write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for p in problems:
        sys.stderr.write(f"determinism: {p}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
