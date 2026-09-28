"""Markdown spec convention (docs/spec/spec-markdown-convention.md). No prose interpretation."""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids, ir

COMPONENT_RE = re.compile(r"^##\s+Component:\s*(?P<name>.+?)\s*(?:\{#(?P<id>[A-Z][A-Z0-9]*-[0-9]+)\})?\s*$")
HEADING_RE = re.compile(r"^(#{1,2})\s+")
REQ_RE = re.compile(r"^\s*[-*]\s+\[(?P<id>[A-Z][A-Z0-9]*-[0-9]+)\]\s+(?P<text>.+?)\s*$")

# EARS templates, tried in order. Case-insensitive on keywords only.
EARS: list[tuple[str, re.Pattern[str]]] = [
    (
        "unwanted",
        re.compile(
            r"^If\s+(?P<trigger>.+?),\s*then\s+the\s+(?P<system>.+?)\s+shall\s+(?P<response>.+?)\.?$", re.I
        ),
    ),
    (
        "event",
        re.compile(
            r"^(?:While\s+(?P<precondition>.+?),\s*)?When\s+(?P<trigger>.+?),\s*the\s+(?P<system>.+?)"
            r"\s+shall\s+(?P<response>.+?)\.?$",
            re.I,
        ),
    ),
    (
        "state",
        re.compile(
            r"^While\s+(?P<precondition>.+?),\s*the\s+(?P<system>.+?)\s+shall\s+(?P<response>.+?)\.?$", re.I
        ),
    ),
    (
        "optional",
        re.compile(
            r"^Where\s+(?P<precondition>.+?),\s*the\s+(?P<system>.+?)\s+shall\s+(?P<response>.+?)\.?$", re.I
        ),
    ),
    ("ubiquitous", re.compile(r"^The\s+(?P<system>.+?)\s+shall\s+(?P<response>.+?)\.?$", re.I)),
]


def parse_ears(text: str) -> dict[str, Any]:
    for name, pat in EARS:
        m = pat.match(text.strip())
        if m:
            d = {k: v for k, v in m.groupdict().items() if v is not None}
            return {"ears": name, **d}
    return {"ears": None}


def extract(graph: ir.Graph, rel: str, text: str) -> None:
    lines = text.split("\n")
    doc_attrs: dict[str, Any] = {"format": "markdown"}
    doc = ir.Node(
        "spec",
        "spec_doc",
        rel.rsplit("/", 1)[-1],
        rel,
        path=rel,
        span_start_line=1,
        span_end_line=max(1, len(lines) - (1 if text.endswith("\n") else 0)),
        content_hash=ids.content_hash(text),
        attrs=doc_attrs,
    )
    graph.add_node(doc)
    prose: list[str] = []
    comp: ir.Node | None = None
    comp_text: list[str] = []
    comp_last = 0

    def close_component() -> None:
        nonlocal comp, comp_text
        if comp is not None:
            comp.span_end_line = comp_last
            comp.attrs["text"] = "\n".join(comp_text).strip()
            comp.content_hash = ids.content_hash(
                "\n".join(lines[(comp.span_start_line or 1) - 1 : comp_last])
            )
        comp, comp_text = None, []

    in_fence = False
    for i, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        cm = None if in_fence else COMPONENT_RE.match(line)
        if cm:
            close_component()
            name = cm.group("name").strip()
            qname = cm.group("id") or f"{rel}::{name}"
            comp = graph.add_node(
                ir.Node(
                    "spec",
                    "spec_component",
                    name,
                    qname,
                    parent_id=doc.id,
                    path=rel,
                    span_start_line=i,
                    span_end_line=i,
                    attrs={"spec_id": cm.group("id")},
                )
            )
            comp_last = i
            continue
        if not in_fence and HEADING_RE.match(line):
            close_component()
            prose.append(line)
            continue
        rm = None if in_fence else REQ_RE.match(line)
        if rm:
            req_text = rm.group("text")
            attrs = {"text": req_text, **parse_ears(req_text)}
            graph.add_node(
                ir.Node(
                    "spec",
                    "requirement",
                    rm.group("id"),
                    rm.group("id"),
                    parent_id=comp.id if comp is not None else doc.id,
                    path=rel,
                    span_start_line=i,
                    span_end_line=i,
                    content_hash=ids.content_hash(line),
                    attrs=attrs,
                )
            )
            if comp is not None:
                comp_last = i
            continue
        if comp is not None:
            comp_text.append(line)
            if line.strip():
                comp_last = i
        else:
            prose.append(line)
    close_component()
    doc_attrs["prose"] = "\n".join(prose).strip()
