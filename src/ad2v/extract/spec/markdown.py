"""Markdown spec convention (docs/spec/spec-markdown-convention.md). No prose interpretation."""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids, ir

COMPONENT_RE = re.compile(
    r"^##\s+Component:\s*(?P<name>.+?)\s*(?:\{#(?P<id>" + ids.SPEC_ID_PATTERN + r")\})?\s*$"
)
HEADING_RE = re.compile(r"^(#{1,2})\s+")
REQ_RE = re.compile(r"^\s*[-*]\s+\[(?P<id>" + ids.SPEC_ID_PATTERN + r")\]\s+(?P<text>.+?)\s*$")

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

# P9 (ADR-0069): Spanish EARS. Same pattern names and groups; the system loses its article.
_DEBE = r"(?:deber[aá]n?|debe(?:n)?|tendr[aá]n?\s+que)"
_SYS = r"(?:el|la|los|las)\s+(?P<system>.+?)"
EARS_ES: list[tuple[str, re.Pattern[str]]] = [
    (
        "unwanted",
        re.compile(
            r"^Si\s+(?P<trigger>.+?),\s*(?:entonces\s+)?"
            + _SYS
            + r"\s+"
            + _DEBE
            + r"\s+(?P<response>.+?)\.?$",
            re.I,
        ),
    ),
    (
        "event",
        re.compile(
            r"^(?:Mientras\s+(?P<precondition>.+?),\s*)?Cuando\s+(?P<trigger>.+?),\s*"
            + _SYS
            + r"\s+"
            + _DEBE
            + r"\s+(?P<response>.+?)\.?$",
            re.I,
        ),
    ),
    (
        "state",
        re.compile(
            r"^Mientras\s+(?P<precondition>.+?),\s*" + _SYS + r"\s+" + _DEBE + r"\s+(?P<response>.+?)\.?$",
            re.I,
        ),
    ),
    (
        "optional",
        re.compile(
            r"^Donde\s+(?P<precondition>.+?),\s*" + _SYS + r"\s+" + _DEBE + r"\s+(?P<response>.+?)\.?$", re.I
        ),
    ),
    ("ubiquitous", re.compile(r"^" + _SYS + r"\s+" + _DEBE + r"\s+(?P<response>.+?)\.?$", re.I)),
]
# `- [REQ-001] (Título corto) Cuando …`: an explicit short title (P9)
TITLE_PREFIX_RE = re.compile(r"^\((?P<title>[^()]{1,80})\)\s+(?P<text>.+)$")


def detect(rel: str, text: str) -> str | None:
    """The Markdown preset that recognizes this file, or None (prose only). P6.1 M3 adds presets."""
    if any(COMPONENT_RE.match(line) or REQ_RE.match(line) for line in text.split("\n")):
        return "ad2v"
    return None


def parse_ears(text: str) -> dict[str, Any]:
    for table in (EARS, EARS_ES):
        for name, pat in table:
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
            tm = TITLE_PREFIX_RE.match(req_text)
            title = None
            if tm:
                title, req_text = tm.group("title").strip(), tm.group("text")
            attrs = {"text": req_text, **parse_ears(req_text)}
            if title:
                attrs["title"] = title
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
