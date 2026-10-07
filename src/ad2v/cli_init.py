"""`ad2v init` (P9, ADR-0071): propose an ad2v.yaml for an existing repository. Deterministic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ad2v import init as onboarding


def _out(text: str) -> None:
    sys.stdout.write(text)


def cmd_init(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    if not repo.is_dir():
        sys.stderr.write(f"ad2v: error: not a directory: {a.repo}\n")
        return 2
    label = a.repo.replace("\\", "/").rstrip("/") or "."
    fd = onboarding.scan(repo, label)
    manifest = onboarding.proposal(fd)
    text = onboarding.render_yaml(fd, manifest)
    if a.check:
        existing = yaml.safe_load(Path(a.check).read_text(encoding="utf-8")) or {}
        diffs = onboarding.check(fd, existing)
        if not diffs:
            _out(f"{a.check}: up to date with what `ad2v init` proposes today\n")
            return 0
        _out(f"{a.check}: {len(diffs)} difference(s) with what `ad2v init` proposes today:\n")
        _out("".join(f"  - {d}\n" for d in diffs))
        return 1
    if a.write:
        dest = Path(a.write)
        if dest.exists() and not a.force:
            sys.stderr.write(f"ad2v: error: {a.write} exists; pass --force to overwrite it\n")
            return 2
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            text if a.format == "yaml" else onboarding.to_json(fd, manifest) + "\n", encoding="utf-8"
        )
    if a.format == "json":
        _out(onboarding.to_json(fd, manifest) + "\n")
        return 0
    _out(onboarding.render_report(fd, a.write))
    _out("\n# ---- proposed ad2v.yaml" + (f" (written to {a.write})" if a.write else "") + " ----\n")
    _out(text)
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser(
        "init",
        help="scan an existing repository and propose an ad2v.yaml (deterministic, writes only with --write)",
    )
    p.add_argument("--repo", required=True)
    p.add_argument(
        "--write", metavar="FILE", help="write the proposal here (refuses to overwrite without --force)"
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--format", choices=("yaml", "json"), default="yaml")
    p.add_argument(
        "--check", metavar="AD2V_YAML", help="list the differences with an existing manifest (exit 1)"
    )
    p.set_defaults(func=cmd_init)
