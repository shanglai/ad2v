"""`ad2v history`: extract a range of git commits, one epoch per commit (format spec §4.3).

Commits are exported with `git archive --format=zip` into one temporary directory (so the
working tree, index and hooks are never touched) and extracted with `--into`. The first commit is
exported in full; each later one only rewrites the paths `git diff-tree` reports as changed, which
keeps unchanged files warm in the OS cache. Only `git rev-list`, `git diff-tree` and `git archive`
are run; repository code is never executed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ad2v import pipeline


class GitError(RuntimeError):
    pass


PATHS_PER_ARCHIVE = 200  # keeps the command line far below the Windows limit


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "--literal-pathspecs", *args],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
        )
    except FileNotFoundError as e:
        raise GitError("git is not installed or not on PATH") from e
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def commits(repo: Path, rev_range: str) -> list[str]:
    """Commits of a `git rev-list` range, oldest first (e.g. `HEAD~20..HEAD`, `v1.0..main`)."""
    return [c for c in _git(repo, "rev-list", "--reverse", rev_range).split() if c]


def export(repo: Path, commit: str, dest: Path, paths: list[str] | None = None) -> None:
    """Write a clean tree of `commit` (or only `paths` of it) into `dest` (git archive + zipfile)."""
    archive = dest.parent / f"{commit}.zip"
    _git(repo, "archive", "--format=zip", "-o", str(archive), commit, *(["--", *paths] if paths else []))
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(dest.resolve()):  # zip-slip guard
                    raise GitError(f"unsafe path in archive: {info.filename}")
            z.extractall(dest)
    finally:
        archive.unlink(missing_ok=True)


def _force_remove(func: Callable[..., Any], path: str, _exc: Any) -> None:
    os.chmod(path, stat.S_IWRITE)  # read-only files (e.g. from git) on Windows
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)
    else:  # pragma: no cover - Python 3.11
        shutil.rmtree(path, onerror=_force_remove)


def changed_paths(repo: Path, old: str, new: str) -> list[str]:
    """Paths added, modified, type-changed or deleted between two commits (no rename detection)."""
    out = _git(repo, "diff-tree", "-r", "-z", "--no-renames", "--name-only", old, new)
    return sorted({p for p in out.split("\0") if p})


def update(repo: Path, old: str, new: str, dest: Path) -> int:
    """Turn an exported tree of `old` into the tree `export(new)` would write. Returns #paths."""
    paths = changed_paths(repo, old, new)
    root = dest.resolve()
    for rel in paths:
        target = (dest / rel).resolve()
        if not target.is_relative_to(root):
            raise GitError(f"unsafe path in diff: {rel}")
        if target.is_dir():
            _rmtree(target)
        elif target.exists():
            os.chmod(target, stat.S_IWRITE)
            target.unlink()
        parent = target.parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()  # a full export has no empty directories either
            parent = parent.parent
    listed = (
        set(_git(repo, "ls-tree", "-r", "-z", "--name-only", new, "--", *paths).split("\0"))
        if paths
        else set()
    )
    present = [p for p in paths if p in listed]  # deleted paths are gone from `new`
    for i in range(0, len(present), PATHS_PER_ARCHIVE):
        export(repo, new, dest, present[i : i + PATHS_PER_ARCHIVE])
    return len(paths)


def _export_ignore(repo: Path, commit: str) -> bool:
    """Does the commit use `export-ignore`/`export-subst`? Then only full exports are exact."""
    attrs = [
        p
        for p in _git(repo, "ls-tree", "-r", "-z", "--name-only", commit).split("\0")
        if p == ".gitattributes" or p.endswith("/.gitattributes")
    ]
    return any("export-" in _git(repo, "show", f"{commit}:{p}") for p in attrs)


def run_history(
    repo: Path,
    rev_range: str,
    into: Path,
    spec_rel: str | list[str] | None = None,
    test_results_rel: list[str] | None = None,
    manifest_rel: str | None = None,
    use_cache: bool = True,
    on_epoch: Callable[[str, pipeline.Result], None] | None = None,
    spec_autodetect: bool = True,
) -> list[tuple[str, pipeline.Result]]:
    repo = Path(repo).resolve()
    out = []
    tmp = Path(tempfile.mkdtemp(prefix="ad2v-history-"))
    tree = tmp / "tree"
    prev: str | None = None
    try:
        for commit in commits(repo, rev_range):
            if prev is None or _export_ignore(repo, commit):
                if tree.exists():
                    _rmtree(tree)
                tree.mkdir()
                export(repo, commit, tree)
            else:
                update(repo, prev, commit, tree)
            prev = commit
            # the same resolution per commit (ADR-0047): an explicit --spec that is absent in this
            # commit means "no specs here", never a fallback to auto-detection
            rels = [spec_rel] if isinstance(spec_rel, str) else list(spec_rel or [])
            explicit = [tree / r for r in rels]
            present = [p for p in explicit if p.exists()]
            tests = [tree / t for t in test_results_rel or [] if (tree / t).is_file()]
            manifest = tree / manifest_rel if manifest_rel else None
            res = pipeline.extract_to_file(
                tree,
                present if rels else None,
                into,
                manifest,
                test_results=tests or None,
                into=True,
                use_cache=use_cache,
                name_hint=repo.name,
                repo_commit=commit,
                spec_autodetect=spec_autodetect,
            )
            out.append((commit, res))
            if on_epoch is not None:
                on_epoch(commit, res)
    finally:
        _rmtree(tmp)
    return out
