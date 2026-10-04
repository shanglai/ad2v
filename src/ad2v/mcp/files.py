"""Which .ad2v files the MCP server may read, and read-only connections to them (P6 decisions 7-8).

`--file X` exposes exactly one file. `--root D` exposes every `*.ad2v` under D. A `file` argument
is resolved strictly inside the root: absolute paths outside it, `..` segments, symlinks that
leave the root and non-`.ad2v` names are all rejected. Files are opened read-only through a
`file:…?mode=ro` URI, so a write attempt fails inside SQLite itself.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ad2v import ir, store

SUFFIX = ".ad2v"
MAX_FILES = 500  # `ad2v_files` lists at most this many; deeper trees are paginated by the tool


class FileAccessError(ValueError):
    """The requested file is outside the served set. The message never echoes resolved paths."""


@dataclass
class FileSet:
    root: Path | None = None
    single: Path | None = None
    _local: threading.local = field(default_factory=threading.local, repr=False)

    def __post_init__(self) -> None:
        if (self.root is None) == (self.single is None):
            raise ValueError("exactly one of root or single")
        if self.root is not None:
            self.root = Path(self.root).resolve(strict=True)
            if not self.root.is_dir():
                raise ValueError(f"not a directory: {self.root}")
        else:
            p = Path(self.single).resolve(strict=True)  # type: ignore[arg-type]
            if p.suffix != SUFFIX or not p.is_file():
                raise ValueError(f"not an {SUFFIX} file: {p}")
            self.single = p

    # -- listing --------------------------------------------------------------------------------
    @property
    def base(self) -> Path:
        return self.root if self.root is not None else self.single.parent  # type: ignore[union-attr]

    def listing(self) -> list[str]:
        """Relative POSIX paths, sorted; symlinks that leave the root are skipped."""
        if self.single is not None:
            return [self.single.name]
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):  # type: ignore[arg-type]
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "node_modules")
            for f in sorted(filenames):
                if not f.endswith(SUFFIX):
                    continue
                p = Path(dirpath) / f
                try:
                    self._inside(p.resolve(strict=True))
                except FileAccessError:
                    continue
                out.append(p.relative_to(self.root).as_posix())  # type: ignore[arg-type]
                if len(out) >= MAX_FILES:
                    return sorted(out)
        return sorted(out)

    def default(self) -> str | None:
        files = self.listing()
        return files[0] if len(files) == 1 else None

    # -- resolution -----------------------------------------------------------------------------
    def _inside(self, p: Path) -> None:
        base = self.root if self.root is not None else self.single.parent  # type: ignore[union-attr]
        try:
            p.relative_to(base)  # type: ignore[arg-type]
        except ValueError:
            raise FileAccessError("file is outside the served root") from None

    def resolve(self, name: str | None) -> Path:
        """The served file for `name` (relative to the root); None picks the only file."""
        if name in (None, ""):
            only = self.default()
            if only is None:
                raise FileAccessError("several files are served: pass `file` (see ad2v_files)")
            name = only
        assert name is not None
        if "\x00" in name or len(name) > 1024:
            raise FileAccessError("invalid file name")
        norm = name.replace("\\", "/")
        pp = PurePosixPath(norm)
        if pp.is_absolute() or (len(norm) > 1 and norm[1] == ":") or norm.startswith("//"):
            raise FileAccessError("absolute paths are not accepted: pass a path relative to the root")
        if any(part == ".." for part in pp.parts):
            raise FileAccessError("'..' is not accepted in file paths")
        if pp.suffix != SUFFIX:
            raise FileAccessError(f"only {SUFFIX} files are served")
        if self.single is not None:
            if norm != self.single.name:
                raise FileAccessError("this server serves a single file (see ad2v_files)")
            return self.single
        cand = self.root.joinpath(*pp.parts)  # type: ignore[union-attr]
        try:
            real = cand.resolve(strict=True)
        except (FileNotFoundError, OSError):
            raise FileAccessError("no such file under the root (see ad2v_files)") from None
        self._inside(real)  # a symlink out of the root lands here
        if not real.is_file():
            raise FileAccessError("not a file")
        return real

    def label(self, path: Path) -> str:
        return path.relative_to(self.base).as_posix()

    # -- connections ----------------------------------------------------------------------------
    def conn(self, path: Path) -> sqlite3.Connection:
        """A read-only connection per (thread, file), reused across requests."""
        cache: dict[Path, sqlite3.Connection] | None = getattr(self._local, "conns", None)
        if cache is None:
            cache = self._local.conns = {}
        c = cache.get(path)
        if c is None:
            c = store.open_readonly(path)
            c.execute("PRAGMA query_only = ON")
            # P8 (docs/security.md §1): a file with triggers or altered views is not served
            ver = c.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
            bad = store.foreign_schema_objects(c, bool(ver) and ver[0] == ir.FORMAT_VERSION)
            if bad:
                c.close()
                raise FileAccessError(
                    f"{self.label(path)} contains schema objects ad2v does not create ({bad[0]});"
                    " run `ad2v validate` on it"
                )
            cache[path] = c
        return c

    def close(self) -> None:
        for c in getattr(self._local, "conns", {}).values():
            c.close()
        self._local.conns = {}
