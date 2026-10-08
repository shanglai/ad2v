"""Environment variables the Python code reads (P10 M5, ADR-0080). Deterministic, nothing executed.

Collected per file with tree-sitter:

- `os.environ["X"]`, `os.environ.get("X")`, `os.getenv("X")`, `os.environ.setdefault("X", …)`
  (also `environ[...]` / `getenv(...)` imported from `os`);
- pydantic `BaseSettings` subclasses: each annotated field is `env_prefix + NAME` upper-cased,
  unless `Field(alias="X")` / `Field(validation_alias="X")` names it; `env_prefix` comes from
  `model_config = SettingsConfigDict(env_prefix="…")` or an inner `class Config: env_prefix = "…"`.

Each name is attached to the innermost code node (function, class or module) whose span holds
the read, and to its container (`attrs.env_reads`). Only names are kept, never values.
"""

from __future__ import annotations

import re

import tree_sitter_python as tsp
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from ad2v import ir

PY = Language(tsp.language())
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
GETTERS = {
    "os.getenv",
    "os.environ.get",
    "os.environ.setdefault",
    "getenv",
    "environ.get",
    "environ.setdefault",
}
SUBSCRIPTS = {"os.environ", "environ"}


def _text(n: TSNode | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None and n.text is not None else ""


def _string(n: TSNode | None) -> str | None:
    if n is None or n.type != "string":
        return None
    if any(c.type == "interpolation" for c in n.children):
        return None
    body = "".join(_text(c) for c in n.children if c.type == "string_content")
    return body if NAME_RE.match(body) else None


def _kwargs(call: TSNode) -> dict[str, TSNode]:
    args = call.child_by_field_name("arguments")
    out: dict[str, TSNode] = {}
    for a in args.named_children if args is not None else []:
        if a.type == "keyword_argument":
            k, v = a.child_by_field_name("name"), a.child_by_field_name("value")
            if k is not None and v is not None:
                out[_text(k)] = v
    return out


def _positional(call: TSNode) -> list[TSNode]:
    args = call.child_by_field_name("arguments")
    return [a for a in (args.named_children if args is not None else []) if a.type != "keyword_argument"]


def _settings_reads(cls: TSNode) -> list[tuple[str, int]]:
    body = cls.child_by_field_name("body")
    if body is None:
        return []
    prefix = ""
    fields: list[tuple[str, TSNode | None, int]] = []
    for st in body.named_children:
        node = st.named_children[0] if st.type == "expression_statement" and st.named_children else st
        if node.type == "assignment":
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            typ = node.child_by_field_name("type")
            name = _text(left)
            if name == "model_config" and right is not None and right.type == "call":
                p = _kwargs(right).get("env_prefix")
                prefix = _string(p) or prefix if p is not None else prefix
                if p is not None and p.type == "string" and _string(p) is None and _text(p) in ('""', "''"):
                    prefix = ""
            elif typ is not None and NAME_RE.match(name) and not name.startswith("_"):
                fields.append((name, right, node.start_point[0] + 1))
        elif node.type == "class_definition" and _text(node.child_by_field_name("name")) == "Config":
            for inner in (node.child_by_field_name("body") or node).named_children:
                a = (
                    inner.named_children[0]
                    if inner.type == "expression_statement" and inner.named_children
                    else inner
                )
                if a.type == "assignment" and _text(a.child_by_field_name("left")) == "env_prefix":
                    prefix = _string(a.child_by_field_name("right")) or prefix
    out = []
    for name, right, line in fields:
        alias = None
        if (
            right is not None
            and right.type == "call"
            and _text(right.child_by_field_name("function")).endswith("Field")
        ):
            kw = _kwargs(right)
            alias = _string(kw.get("validation_alias")) or _string(kw.get("alias"))
        out.append(((alias or prefix + name).upper(), line))
    return out


def reads_in(text: str) -> list[tuple[str, int]]:
    """(env var name, 1-based line) for one Python source, sorted."""
    tree = Parser(PY).parse(text.encode("utf-8"))
    out: set[tuple[str, int]] = set()
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn = _text(n.child_by_field_name("function"))
            if fn in GETTERS:
                pos = _positional(n)
                name = _string(pos[0]) if pos else None
                if name:
                    out.add((name, n.start_point[0] + 1))
        elif n.type == "subscript":
            if _text(n.child_by_field_name("value")) in SUBSCRIPTS:
                name = _string(n.child_by_field_name("subscript"))
                if name:
                    out.add((name, n.start_point[0] + 1))
        elif n.type == "class_definition":
            bases = _text(n.child_by_field_name("superclasses"))
            if re.search(r"\bBaseSettings\b", bases):
                out.update(_settings_reads(n))
        stack.extend(reversed(n.children))
    return sorted(out)


def collect(graph: ir.Graph, sources: dict[str, str]) -> dict[str, list[str]]:
    """{code node id: sorted env var names} for the innermost node of each read, plus every
    container holding one. `sources`: repo-relative path -> normalized text."""
    by_path: dict[str, list[ir.Node]] = {}
    for n in graph.nodes.values():
        if n.side == "code" and n.kind in ("module", "class", "function") and n.path:
            by_path.setdefault(n.path, []).append(n)
    found: dict[str, set[str]] = {}
    for path in sorted(by_path):
        text = sources.get(path)
        if text is None or not path.endswith(".py"):
            continue
        nodes = by_path[path]
        for name, line in reads_in(text):
            holders = [
                n
                for n in nodes
                if (n.span_start_line or 0) <= line <= (n.span_end_line or 10**9) or n.kind == "module"
            ]
            best = min(
                holders,
                key=lambda n: (
                    (n.span_end_line or 10**9) - (n.span_start_line or 0),
                    n.kind != "function",
                    n.id,
                ),
            )
            found.setdefault(best.id, set()).add(name)
            p = best.parent_id
            while p is not None and p in graph.nodes:
                if graph.nodes[p].kind == "container":
                    found.setdefault(p, set()).add(name)
                    break
                p = graph.nodes[p].parent_id
    return {k: sorted(v) for k, v in sorted(found.items())}
