"""Deterministic, read-only repository walking."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ad2v import ids


@dataclass(frozen=True)
class SourceFile:
    path: str  # root-relative, forward slashes
    abs_path: Path
    text: str  # normalized (LF, no BOM)
    content_hash: str


def _excluded(rel: str, name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(rel, p) for p in patterns)


def walk(
    root: Path,
    patterns: tuple[str, ...],
    suffixes: tuple[str, ...] | None = None,
    include: Callable[[str], bool] | None = None,
) -> list[str]:
    """Sorted root-relative posix paths of regular files. Never follows symlinks. `include`
    (P8) keeps only the relative paths it accepts (the active plug-ins' file patterns)."""
    root = Path(root).resolve()
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if not _excluded(rel, d, patterns) and not (Path(dirpath) / d).is_symlink():
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if suffixes is not None and not f.endswith(suffixes):
                continue
            if include is not None and not include(rel):
                continue
            full = Path(dirpath) / f
            if full.is_symlink() or not full.is_file() or _excluded(rel, f, patterns):
                continue
            out.append(rel)
    return sorted(out)


def load(root: Path, rel_paths: list[str]) -> list[SourceFile]:
    files = []
    for rel in rel_paths:
        p = Path(root) / rel
        text = ids.read_normalized(p)
        files.append(SourceFile(rel, p, text, ids.content_hash(text)))
    return files
