"""Tool declarations for the chat agent, generated from the MCP tools' input schemas (P7, ADR-0056).

One source of truth: the MCP server's JSON Schemas. Two targets:

- **Vertex** `functionDeclarations`: an OpenAPI-3 subset. Types are upper-case; only the keys
  Vertex accepts are kept (`additionalProperties`, `minLength`, `pattern`, `default`, `const`,
  `$schema` are dropped); `anyOf`/`oneOf` of simple types collapse to the first non-null type
  (Vertex rejects union-typed fields in function parameters, as P4 found for response schemas,
  ADR-0030); a list-valued `type` (`["string", "null"]`) becomes `nullable`.
- **OpenAI** `tools`: JSON Schema as is, minus `$schema`; `strict` is off because optional
  properties are not all listed in `required`.
"""

from __future__ import annotations

import copy
from typing import Any

VERTEX_KEYS = (
    "description",
    "enum",
    "format",
    "items",
    "maxItems",
    "minItems",
    "maximum",
    "minimum",
    "nullable",
    "properties",
    "required",
)


def to_vertex(schema: dict[str, Any]) -> dict[str, Any]:
    s = dict(schema)
    for union in ("anyOf", "oneOf"):
        if union in s:
            options = [o for o in s.pop(union) if o.get("type") != "null"]
            if options:
                s = {**options[0], **{k: v for k, v in s.items() if k != "type"}}
    t = s.get("type")
    out: dict[str, Any] = {}
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        out["type"] = (non_null[0] if non_null else "string").upper()
        if "null" in t:
            out["nullable"] = True
    elif t is not None:
        out["type"] = str(t).upper()
    for k in VERTEX_KEYS:
        if k not in s:
            continue
        v = s[k]
        if k == "properties":
            out[k] = {p: to_vertex(x) for p, x in v.items()}
        elif k == "items":
            out[k] = to_vertex(v)
        elif k in ("maxItems", "minItems"):
            out[k] = str(v)  # int64 fields are strings in proto3 JSON
        elif k == "required":
            if v:
                out[k] = list(v)
        else:
            out[k] = v
    if out.get("type") == "OBJECT" and "properties" not in out:
        out["properties"] = {}
    return out


def to_openai(schema: dict[str, Any]) -> dict[str, Any]:
    s = copy.deepcopy(schema)
    s.pop("$schema", None)
    return s


def vertex_tools(decls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {"name": d["name"], "description": d["description"], "parameters": to_vertex(d["parameters"])}
                for d in decls
            ]
        }
    ]


def openai_tools(decls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": to_openai(d["parameters"]),
            },
        }
        for d in decls
    ]
