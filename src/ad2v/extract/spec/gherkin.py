"""Gherkin (*.feature) extractor using gherkin-official."""

from __future__ import annotations

import re
from typing import Any

from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner

from ad2v import ids, ir

SPEC_ID_TAG_RE = re.compile(r"^@(" + ids.SPEC_ID_PATTERN + r")$")


def _tag_ids(tags: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    names = sorted(t["name"] for t in tags)
    spec_ids = sorted({m.group(1) for n in names if (m := SPEC_ID_TAG_RE.match(n))})
    return names, spec_ids


def _span(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def extract(graph: ir.Graph, rel: str, text: str) -> list[str]:
    """Add nodes for one feature file. Returns scenario node ids in file order."""
    lines = text.split("\n")
    last_line = max(1, len(lines) - (1 if text.endswith("\n") else 0))
    doc = graph.add_node(
        ir.Node(
            "spec",
            "spec_doc",
            rel.rsplit("/", 1)[-1],
            rel,
            path=rel,
            span_start_line=1,
            span_end_line=last_line,
            content_hash=ids.content_hash(text),
            attrs={"format": "gherkin"},
        )
    )
    parsed = Parser().parse(TokenScanner(text))
    feature = parsed.get("feature")
    if not feature:
        return []
    tags, spec_ids = _tag_ids(feature.get("tags", []))
    fstart = min([feature["location"]["line"]] + [t["location"]["line"] for t in feature.get("tags", [])])
    fname = feature["name"] or rel
    fnode = graph.add_node(
        ir.Node(
            "spec",
            "spec_component",
            fname,
            f"{rel}::{fname}",
            parent_id=doc.id,
            path=rel,
            span_start_line=fstart,
            span_end_line=last_line,
            content_hash=ids.content_hash(_span(lines, fstart, last_line)),
            attrs={
                "keyword": feature["keyword"],
                "tags": tags,
                "description": feature.get("description", "").strip(),
            },
            spec_ref=spec_ids,
        )
    )
    scenarios: list[str] = []
    seen: dict[str, int] = {}
    children = feature.get("children", [])
    flat: list[tuple[dict[str, Any], str | None]] = []
    for ch in children:
        if "rule" in ch:
            for rch in ch["rule"].get("children", []):
                flat.append((rch, ch["rule"]["name"]))
        else:
            flat.append((ch, None))
    starts = sorted(
        min(
            [(c.get("scenario") or c.get("background"))["location"]["line"]]
            + [t["location"]["line"] for t in (c.get("scenario") or {}).get("tags", [])]
        )
        for c, _ in flat
        if c.get("scenario") or c.get("background")
    )
    for ch, rule in flat:
        item = ch.get("scenario") or ch.get("background")
        if item is None:
            continue
        background = "background" in ch
        stags, sids = _tag_ids(item.get("tags", []))
        base = item["name"] or ("Background" if background else item["keyword"])
        label = f"{rule}::{base}" if rule else base
        n = seen.get(label, 0) + 1
        seen[label] = n
        qn = f"{fnode.qualified_name}::{label}" + (f"#{n}" if n > 1 else "")
        start = min([item["location"]["line"]] + [t["location"]["line"] for t in item.get("tags", [])])
        later = [s for s in starts if s > start]
        end = (later[0] - 1) if later else last_line
        while end > start and not lines[end - 1].strip():
            end -= 1
        snode = graph.add_node(
            ir.Node(
                "spec",
                "scenario",
                base,
                qn,
                parent_id=fnode.id,
                path=rel,
                span_start_line=start,
                span_end_line=end,
                content_hash=ids.content_hash(_span(lines, start, end)),
                attrs={
                    "keyword": item["keyword"],
                    "tags": stags,
                    "background": background,
                    "examples": sum(len(e.get("tableBody", [])) for e in item.get("examples", [])),
                    "rule": rule,
                },
                spec_ref=sids,
            )
        )
        for i, step in enumerate(item.get("steps", []), start=1):
            ln = step["location"]["line"]
            end_ln = ln + (len(step["dataTable"]["rows"]) if step.get("dataTable") else 0)
            graph.add_node(
                ir.Node(
                    "spec",
                    "scenario_step",
                    f"{step['keyword'].strip()} {step['text']}",
                    f"{qn}::step[{i}]",
                    parent_id=snode.id,
                    path=rel,
                    span_start_line=ln,
                    span_end_line=end_ln,
                    content_hash=ids.content_hash(_span(lines, ln, end_ln)),
                    attrs={
                        "keyword": step["keyword"].strip(),
                        "keyword_type": step.get("keywordType"),
                        "text": step["text"],
                    },
                )
            )
        scenarios.append(snode.id)
    return scenarios
