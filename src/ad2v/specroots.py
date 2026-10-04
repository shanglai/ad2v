"""Where the specs come from (P6.1, ADR-0047).

Resolution order (the first step that gives an answer wins; `extract` and `history` print it):

1. `--spec <dir|file>` on the command line (repeatable);
2. `spec_root:` in ad2v.yaml (a string or a list, relative to the repo);
3. auto-detection, unless disabled (`--no-spec-autodetect`): each of `specs/`, `spec/`,
   `docs/specs/`, `.kiro/specs/` that holds at least one recognized spec file (Gherkin, OpenAPI,
   or Markdown that a preset recognizes), plus an OpenAPI file at the repo root
   (`openapi.yaml|yml|json`).

The effective roots, as repo-relative POSIX paths, enter `config_hash` (a change in discovery is
a new epoch). With one root, spec file paths stay relative to it (as before P6.1); with several,
each path is prefixed with its root's label so that paths never collide. Each Markdown file's
preset (ADR-0048) is chosen here, on its repo-relative path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v.extract import files as filewalk
from ad2v.extract.spec import SPEC_SUFFIXES, spec_files

AUTO_DIRS = ("specs", "spec", "docs/specs", ".kiro/specs")
ROOT_OPENAPI = ("openapi.yaml", "openapi.yml", "openapi.json")


class SpecRootError(ValueError):
    pass


@dataclass
class SpecRoots:
    roots: list[Path] = field(default_factory=list)  # absolute; a directory or a single file
    labels: list[str] = field(default_factory=list)  # repo-relative POSIX (or "external:<name>")
    source: str = "none"  # cli | manifest | auto | none
    choices: dict[str, Any] = field(default_factory=dict)  # Markdown spec path -> presets.Choice

    def describe(self) -> str:
        if not self.roots:
            how = {"none": "none found", "cli": "--spec given but missing", "manifest": "spec_root missing"}
            hint = " (prose only? `ad2v specs bootstrap --from docs --plan`)" if self.source == "none" else ""
            return f"spec roots: {how.get(self.source, 'none')}{hint}"
        src = {"cli": "--spec", "manifest": "ad2v.yaml spec_root", "auto": "auto-detected"}[self.source]
        shown = [lbl + ("/" if r.is_dir() else "") for lbl, r in zip(self.labels, self.roots, strict=True)]
        return f"spec roots ({src}): " + ", ".join(shown)


def label(repo: Path, root: Path) -> str:
    try:
        rel = root.resolve().relative_to(repo.resolve()).as_posix()
        return rel if rel != "." else "."
    except ValueError:
        return f"external:{root.name}"


def recognized(repo: Path, root: Path, exclude: tuple[str, ...], rules: list[dict[str, Any]]) -> bool:
    """A directory holds a spec file a parser understands (prose-only Markdown does not count)."""
    from ad2v.extract.spec import presets

    lbl = label(repo, root)
    for rel, fmt, text in spec_files(root, exclude):
        if fmt in ("gherkin", "openapi"):
            return True
        if fmt == "markdown" and presets.choose(f"{lbl}/{rel}", text, rules) is not None:
            return True
    return False


def autodetect(repo: Path, exclude: tuple[str, ...], rules: list[dict[str, Any]] | None = None) -> list[Path]:
    out: list[Path] = []
    for d in AUTO_DIRS:
        p = repo / d
        if (
            p.is_dir()
            and any(True for _ in filewalk.walk(p, exclude, SPEC_SUFFIXES))
            and recognized(repo, p, exclude, rules or [])
        ):
            out.append(p)
    for f in ROOT_OPENAPI:
        p = repo / f
        if p.is_file() and spec_files(p, exclude):
            out.append(p)
    return out


def resolve(
    repo: Path,
    cli: list[Path] | None,
    manifest_roots: list[str] | None,
    exclude: tuple[str, ...],
    autodetect_enabled: bool = True,
    rules: list[dict[str, Any]] | None = None,
) -> SpecRoots:
    repo = Path(repo).resolve()
    if cli is not None:  # given on the command line (an empty list: given, but absent in this commit)
        roots = [Path(p).resolve() for p in cli]
        roots = [r for r in roots if r.exists()]
        source = "cli"
    elif manifest_roots:
        roots = [(repo / r).resolve() for r in manifest_roots]
        missing = [r for r, p in zip(manifest_roots, roots, strict=True) if not p.exists()]
        if missing:
            raise SpecRootError(f"ad2v.yaml spec_root not found: {', '.join(missing)}")
        source = "manifest"
    elif autodetect_enabled:
        roots, source = autodetect(repo, exclude, rules), "auto"
    else:
        roots, source = [], "none"
    # de-duplicate, keep order; drop roots inside another root
    uniq: list[Path] = []
    for r in roots:
        if r not in uniq and not any(r != u and r.is_relative_to(u) for u in uniq if u.is_dir()):
            uniq.append(r)
    return SpecRoots(uniq, [label(repo, r) for r in uniq], source if uniq or source != "auto" else "none")


def _repo_path(root: Path, lbl: str, rel: str) -> str:
    """The repo-relative path of a spec file (what presets select on)."""
    if root.is_file():
        return lbl
    return rel if lbl == "." else f"{lbl}/{rel}"


def collect(
    sr: SpecRoots, exclude: tuple[str, ...], rules: list[dict[str, Any]] | None = None
) -> list[tuple[str, str, str]]:
    """Spec files of all roots as (path, format, text), sorted; prefixed by root label when > 1 root.
    Also fills `sr.choices`: the Markdown preset of each file (ADR-0048)."""
    from ad2v.extract.spec import presets

    out: dict[str, tuple[str, str, str]] = {}
    choices: dict[str, Any] = {}
    single = len(sr.roots) == 1
    for root, lbl in zip(sr.roots, sr.labels, strict=True):
        for rel, fmt, text in spec_files(root, exclude):
            key = rel if (single or root.is_file() or lbl == ".") else f"{lbl}/{rel}"
            if key in out:
                raise SpecRootError(f"two spec roots yield the same path {key!r}")
            out[key] = (key, fmt, text)
            if fmt == "markdown":
                ch = presets.choose(_repo_path(root, lbl, rel), text, rules or [])
                if ch is not None:
                    choices[key] = ch
    sr.choices = presets.assign_prefixes(choices)
    return [out[k] for k in sorted(out)]
