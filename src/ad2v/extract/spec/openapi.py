"""OpenAPI 3.x extractor (pyyaml; JSON is parsed as YAML)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

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


def server_base_path(data: dict[str, Any]) -> str:
    """Path part of servers[0].url ('' if absent, '/' or templated host only)."""
    servers = data.get("servers") or []
    if not servers or not isinstance(servers[0], dict):
        return ""
    url = str(servers[0].get("url") or "")
    path = urlsplit(url).path if "://" in url else url
    path = path.rstrip("/")
    return path if path.startswith("/") else ("/" + path if path else "")


def _resolve(data: dict[str, Any], obj: Any) -> Any:
    """Resolve a local `#/...` $ref (one level, cycles ignored)."""
    if isinstance(obj, dict) and isinstance(obj.get("$ref"), str) and obj["$ref"].startswith("#/"):
        cur: Any = data
        for part in obj["$ref"][2:].split("/"):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur if isinstance(cur, dict) else {}
    return obj


def parameters(data: dict[str, Any], path_item: dict[str, Any], op: dict[str, Any]) -> list[dict[str, Any]]:
    """Operation parameters merged over path-item parameters (keyed by (in, name))."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for src in (path_item.get("parameters") or [], op.get("parameters") or []):
        for raw in src:
            p = _resolve(data, raw)
            if isinstance(p, dict) and "name" in p and "in" in p:
                merged[(str(p["in"]), str(p["name"]))] = p
    return [merged[k] for k in sorted(merged)]


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
                "base_path": server_base_path(data),
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
            path_item = data["paths"][path] or {}
            op = path_item.get(method) or {}
            params = parameters(data, path_item, op)
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
                        "base_path": server_base_path(data),
                        "path_params": [str(q["name"]) for q in params if q["in"] == "path"],
                        "query_params": [str(q["name"]) for q in params if q["in"] == "query"],
                        "required_query": [
                            str(q["name"]) for q in params if q["in"] == "query" and q.get("required") is True
                        ],
                    },
                    spec_ref=sorted({str(r) for r in refs}),
                )
            )
