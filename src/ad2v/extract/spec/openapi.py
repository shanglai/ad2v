"""OpenAPI 3.x extractor (pyyaml; JSON is parsed as YAML)."""

from __future__ import annotations

from typing import Any

import yaml

from ad2v import ids, ir

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def is_openapi(text: str) -> bool:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and str(data.get("openapi", "")).startswith("3")


def _mapping(node: yaml.Node) -> dict[str, tuple[yaml.Node, yaml.Node]]:
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {str(k.value): (k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def extract(graph: ir.Graph, rel: str, text: str) -> None:
    lines = text.split("\n")
    data: dict[str, Any] = yaml.safe_load(text)
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    info = data.get("info") or {}
    doc = graph.add_node(
        ir.Node(
            "spec",
            "spec_doc",
            rel.rsplit("/", 1)[-1],
            rel,
            path=rel,
            span_start_line=1,
            span_end_line=max(1, len(lines) - (1 if text.endswith("\n") else 0)),
            content_hash=ids.content_hash(text),
            attrs={
                "format": "openapi",
                "openapi": str(data.get("openapi")),
                "title": info.get("title"),
                "version": str(info.get("version")) if info.get("version") is not None else None,
            },
        )
    )
    paths_entry = _mapping(root).get("paths")
    if paths_entry is None:
        return
    for path, (_pk, pv) in sorted(_mapping(paths_entry[1]).items()):
        for method, (mk, mv) in sorted(_mapping(pv).items()):
            if method.lower() not in HTTP_METHODS:
                continue
            op = (data["paths"][path] or {}).get(method) or {}
            start = mk.start_mark.line + 1
            # end_mark points just past the value; if only indentation precedes it on its line, the
            # value ended on an earlier line (block mappings end where the next key starts).
            el, ec = mv.end_mark.line, mv.end_mark.column
            before = lines[el][:ec] if el < len(lines) else ""
            end = max(start, el if not before.strip() else el + 1)
            while end > start and not lines[end - 1].strip():
                end -= 1
            refs = op.get("x-ad2v-refs") or []
            m = method.upper()
            graph.add_node(
                ir.Node(
                    "spec",
                    "spec_endpoint",
                    f"{m} {path}",
                    f"{m} {path}",
                    parent_id=doc.id,
                    path=rel,
                    span_start_line=start,
                    span_end_line=end,
                    content_hash=ids.content_hash("\n".join(lines[start - 1 : end])),
                    attrs={
                        "method": m,
                        "path": path,
                        "operation_id": op.get("operationId"),
                        "summary": op.get("summary"),
                        "tags": sorted(op.get("tags") or []),
                    },
                    spec_ref=sorted({str(r) for r in refs}),
                )
            )
