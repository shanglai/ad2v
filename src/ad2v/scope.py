"""Language scope (P8.1, ADR-0066): code that no active extractor reads.

ad2v can only evaluate code that an extractor understands. Files in other languages (TypeScript
while only the Python extractor exists, Java, Go, …) used to be invisible, so a requirement that
was specified and implemented there looked `specified` or `missing`, and their containers looked
like orphans. Now the core inventories them:

- every file under the repository whose extension is in `LANGUAGES`, that no active plug-in
  claims, outside the excludes and the spec roots, is an **unextracted** file: it becomes a
  `module` node with `attrs.language` and `attrs.extracted = false`, and its content is an epoch
  input (it enters `repo_tree_hash`);
- `ad2v: REQ-001` markers in its comments (`//`, `#`, `/*`, `*`, `--`, `<!--`) become spec
  references, exactly like Python annotations;
- pairing turns what would have been `implemented` for such code into **`not_evaluable`**, and
  marks unextracted code without a spec link `not_evaluable` instead of `orphan`
  (`ad2v.pairing`).

The table is part of the epoch rules (`scope`), so changing it changes `rules_hash`.
"""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids, ir
from ad2v.extract.code.base import Layout
from ad2v.extract.files import SourceFile

SCOPE_VERSION = 1
# extension -> language. Application-code languages only (no markup, config, shell or SQL).
LANGUAGES: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".vue": "vue",
    ".svelte": "svelte",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".m": "objective-c",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
}
MARK_RE = re.compile(r"(?://|#|/\*|^\s*\*|--|<!--)\s*ad2v:\s*(.+?)\s*(?:\*/|-->)?\s*$")
REF_RE = re.compile(r"\b(" + ids.SPEC_ID_PATTERN + r")(?:@[0-9a-f]{8})?\b")


def rules() -> dict[str, Any]:
    """What enters the epoch rules (and so `rules_hash`) under the key `scope`."""
    return {"version": SCOPE_VERSION, "languages": dict(sorted(LANGUAGES.items()))}


def language(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".d.ts"):  # type declarations, not implementation
        return None
    dot = name.rfind(".")
    return LANGUAGES.get(name[dot:].lower()) if dot > 0 else None


def refs(text: str) -> list[tuple[str, int]]:
    """(spec id, line) for every `ad2v:` marker in a comment."""
    out = []
    for i, line in enumerate(text.split("\n"), start=1):
        m = MARK_RE.search(line)
        if m:
            out += [(r.group(1), i) for r in REF_RE.finditer(m.group(1))]
    return out


def add_unextracted(graph: ir.Graph, layout: Layout, files: list[SourceFile]) -> dict[str, int]:
    """Module nodes for unextracted files (sorted by path); returns {language: count}."""
    counts: dict[str, int] = {}
    for f in sorted(files, key=lambda f: f.path):
        lang = language(f.path)
        if lang is None:
            continue
        counts[lang] = counts.get(lang, 0) + 1
        found = refs(f.text)
        attrs: dict[str, Any] = {"extracted": False, "language": lang}
        if found:
            attrs["spec_ref_sources"] = {r: ["comment"] for r in sorted({r for r, _ in found})}
        graph.add_node(
            ir.Node(
                "code",
                "module",
                f.path.rsplit("/", 1)[-1],
                f.path,
                parent_id=layout.parent_for_module(f.path),
                path=f.path,
                span_start_line=1,
                span_end_line=f.text.count("\n") + 1,
                content_hash=f.content_hash,
                attrs=attrs,
                spec_ref=sorted({r for r, _ in found}),
            )
        )
    return dict(sorted(counts.items()))


def is_unextracted(node: ir.Node) -> bool:
    return node.kind == "module" and node.attrs.get("extracted") is False
