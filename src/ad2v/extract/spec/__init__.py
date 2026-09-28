"""Spec-side extractors. Dispatch is by file name/content, in sorted path order."""

from __future__ import annotations

from pathlib import Path

from ad2v import ids, ir
from ad2v.extract import files as filewalk
from ad2v.extract.spec import gherkin, markdown, openapi

SPEC_SUFFIXES = (".feature", ".md", ".markdown", ".yaml", ".yml", ".json")


def spec_files(spec_root: Path, exclude: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Recognized spec files as (relative path, format, normalized text), sorted by path."""
    if spec_root.is_file():
        root, rels = spec_root.parent, [spec_root.name]
    else:
        root, rels = spec_root, filewalk.walk(spec_root, exclude, SPEC_SUFFIXES)
    out = []
    for rel in rels:
        text = ids.read_normalized(root / rel)
        if rel.endswith(".feature"):
            out.append((rel, "gherkin", text))
        elif rel.endswith((".md", ".markdown")):
            out.append((rel, "markdown", text))
        elif openapi.is_openapi(text):
            out.append((rel, "openapi", text))
    return out


def spec_tree_hash(files: list[tuple[str, str, str]]) -> str:
    return ids.tree_hash({rel: ids.content_hash(text) for rel, _, text in files})


def extract_specs(
    graph: ir.Graph,
    spec_root: Path,
    exclude: tuple[str, ...],
    root_name: str = "spec",
    files: list[tuple[str, str, str]] | None = None,
) -> dict[str, str]:
    """Extract every spec file under `spec_root`. Returns {path: content_hash} of files read.

    All `spec_doc` nodes hang under one synthetic `spec_root` node (qualified name = `root_name`,
    the system name), so the spec side has a single root like the code side (format spec §3.2).
    """
    read: dict[str, str] = {}
    root_node = graph.add_node(
        ir.Node(
            "spec", "spec_root", root_name, root_name, content_hash=ids.attrs_hash("spec_root", root_name, {})
        )
    )
    for rel, fmt, text in files if files is not None else spec_files(spec_root, exclude):
        if fmt == "gherkin":
            gherkin.extract(graph, rel, text)
        elif fmt == "markdown":
            markdown.extract(graph, rel, text)
        else:
            openapi.extract(graph, rel, text)
        read[rel] = ids.content_hash(text)
        graph.nodes[ids.node_id("spec", "spec_doc", rel)].parent_id = root_node.id
    return read
