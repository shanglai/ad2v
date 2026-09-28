"""Spec-side extractors. Dispatch is by file name/content, in sorted path order."""

from __future__ import annotations

from pathlib import Path

from ad2v import ids, ir
from ad2v.extract import files as filewalk
from ad2v.extract.spec import gherkin, markdown, openapi

SPEC_SUFFIXES = (".feature", ".md", ".markdown", ".yaml", ".yml", ".json")


def extract_specs(graph: ir.Graph, spec_root: Path, exclude: tuple[str, ...]) -> dict[str, str]:
    """Extract every spec file under `spec_root`. Returns {path: content_hash} of files read."""
    read: dict[str, str] = {}
    if spec_root.is_file():
        root, rels = spec_root.parent, [spec_root.name]
    else:
        root, rels = spec_root, filewalk.walk(spec_root, exclude, SPEC_SUFFIXES)
    for rel in rels:
        text = ids.read_normalized(root / rel)
        if rel.endswith(".feature"):
            gherkin.extract(graph, rel, text)
        elif rel.endswith((".md", ".markdown")):
            markdown.extract(graph, rel, text)
        elif openapi.is_openapi(text):
            openapi.extract(graph, rel, text)
        else:
            continue
        read[rel] = ids.content_hash(text)
    return read
