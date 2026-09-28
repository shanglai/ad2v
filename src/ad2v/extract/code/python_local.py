"""Per-file ("local") extraction for Python: everything that depends on one file only.

`local_facts(path, text, root)` returns a JSON-serializable record. It is the payload of the
parse cache (format spec §4.2), keyed by (path, content_hash, rules_hash, extractor_version).
Syntax-tree nodes are referenced by byte ranges and re-attached to a fresh parse with
`find_node`, because the global passes (call resolution) walk the tree.

Bump LOCAL_EXTRACTOR_VERSION whenever the shape or meaning of the record changes.
"""

from __future__ import annotations

import re
from typing import Any

from tree_sitter import Node as TSNode

from ad2v import ids

LOCAL_EXTRACTOR_VERSION = "python-local-2"  # 2: spec IDs may use the reserved `-X` range (P4)

SPEC_REF_RE = re.compile(r"\b(" + ids.SPEC_ID_PATTERN + r")(?:@([0-9a-f]{8}))?\b")
AD2V_MARK_RE = re.compile(r"\bad2v:\s*(.+)$")
TEST_FILE_RE = re.compile(r"(test_.*|.*_test)\.py$")
CONTAINER_STMTS = frozenset(
    {
        "if_statement",
        "try_statement",
        "else_clause",
        "elif_clause",
        "except_clause",
        "finally_clause",
        "block",
        "with_statement",
        "for_statement",
        "while_statement",
    }
)
NESTED_BLOCKS = frozenset({"block", "else_clause", "elif_clause", "except_clause", "finally_clause"})


def _text(n: TSNode | None) -> str:
    return n.text.decode("utf-8", errors="replace") if n is not None and n.text is not None else ""


def _rng(n: TSNode) -> list[int]:
    return [n.start_byte, n.end_byte]


def import_ops(n: TSNode, path: str) -> list[list[Any]]:
    """Binding operations of one `import` / `from ... import` statement in module `path`."""
    ops: list[list[Any]] = []
    line = n.start_point[0] + 1
    if n.type == "import_statement":
        for x in n.named_children:
            if x.type == "dotted_name":
                fq = _text(x)
                ops.append(["imp_root", fq.split(".")[0], fq, line])
            elif x.type == "aliased_import":
                ops.append(
                    [
                        "imp_alias",
                        _text(x.child_by_field_name("alias")),
                        _text(x.child_by_field_name("name")),
                        line,
                    ]
                )
        return ops
    mod = n.child_by_field_name("module_name")
    if n.type != "import_from_statement" or mod is None:
        return ops
    base: str | None = None
    if mod.type == "relative_import":
        prefix = next((c for c in mod.children if c.type == "import_prefix"), None)
        dots = len(_text(prefix)) if prefix is not None else 1
        dn = next((c for c in mod.named_children if c.type == "dotted_name"), None)
        dotted = _text(dn) if dn is not None else ""
        parts = path.split("/")[:-1]
        up = dots - 1
        if up > len(parts):
            return ops
        base = "/".join(parts[: len(parts) - up])
    else:
        dotted = _text(mod)
    for c in n.children_by_field_name("name"):
        if c.type == "aliased_import":
            name = _text(c.child_by_field_name("name"))
            alias = _text(c.child_by_field_name("alias"))
        else:
            name = alias = _text(c)
        if base is not None:
            ops.append(["from_rel", alias, base, dotted, name, line])
        else:
            ops.append(["from_abs", alias, dotted, name, line])
    return ops


def find_node(root: TSNode, rng: list[int], type_: str) -> TSNode:
    """Re-attach a cached byte range to the node of the given type in a fresh parse."""
    sb, eb = rng
    n = root.descendant_for_byte_range(sb, eb)
    while n is not None and not (n.type == type_ and n.start_byte == sb and n.end_byte == eb):
        n = n.parent
    if n is None:
        raise LookupError(f"no {type_} node at bytes {sb}..{eb}")
    return n


def parse_refs(text: str) -> list[list[str | None]]:
    """`REQ-1, REQ-2@1a2b3c4d` -> [["REQ-1", None], ["REQ-2", "1a2b3c4d"]]."""
    return [[m.group(1), m.group(2)] for m in SPEC_REF_RE.finditer(text)]


def _string_value(n: TSNode) -> str | None:
    if n.type != "string":
        return None
    out = []
    for c in n.named_children:
        if c.type in ("string_content", "escape_sequence"):
            out.append(_text(c))
        elif c.type == "interpolation":
            break
    return "".join(out)


def _dotted(n: TSNode | None) -> str | None:
    if n is None:
        return None
    if n.type == "identifier":
        return _text(n)
    if n.type == "attribute":
        base = _dotted(n.child_by_field_name("object"))
        attr = n.child_by_field_name("attribute")
        return f"{base}.{_text(attr)}" if base is not None and attr is not None else None
    return None


def _deco_callee(d: TSNode) -> TSNode:
    expr = d.named_children[0] if d.named_children else d
    return expr.child_by_field_name("function") if expr.type == "call" else expr


def param_info(fn: TSNode) -> dict[str, Any]:
    """Parameter names in order (without self/cls) and whether **kwargs is present."""
    names: list[str] = []
    var_kw = False
    params = fn.child_by_field_name("parameters")
    for p in params.named_children if params is not None else []:
        first = p.named_children[0] if p.named_children else None
        if "dictionary_splat_pattern" in (p.type, first.type if first is not None else ""):
            var_kw = True
        elif p.type == "identifier":
            names.append(_text(p))
        elif p.type in ("typed_parameter", "default_parameter", "typed_default_parameter"):
            ident = p.child_by_field_name("name") or next(
                (c for c in p.named_children if c.type == "identifier"), None
            )
            if ident is not None:
                names.append(_text(ident))
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    return {"params": names, "var_kwargs": var_kw}


def _span_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def body_hash(span_text: str, keyword: str, name: str) -> str:
    """Content hash with the defined name masked: equal for a pure rename (lineage, ADR-0020)."""
    return ids.content_hash(re.sub(rf"\b{keyword}\s+{re.escape(name)}\b", f"{keyword} _", span_text, count=1))


def local_facts(path: str, text: str, root: TSNode) -> dict[str, Any]:
    lines = text.split("\n")
    is_test_file = bool(TEST_FILE_RE.match(path.rsplit("/", 1)[-1]))
    defs: list[dict[str, Any]] = []

    def collect(
        body: TSNode,
        parent: tuple[str, str],
        class_q: str | None,
        pfunc_q: str | None,
        top: bool,
    ) -> None:
        prefix = f"{path}::" if parent[0] == "module" else f"{parent[1]}."
        for child in body.named_children:
            outer, target, decos = child, child, []
            if child.type == "decorated_definition":
                decos = [d for d in child.named_children if d.type == "decorator"]
                target = child.child_by_field_name("definition") or child
            if target.type in ("function_definition", "class_definition"):
                is_fn = target.type == "function_definition"
                name = _text(target.child_by_field_name("name"))
                qname = prefix + name
                start, end = outer.start_point[0] + 1, outer.end_point[0] + 1
                span = _span_text(lines, start, end)
                rec: dict[str, Any] = {
                    "k": "f" if is_fn else "c",
                    "name": name,
                    "qname": qname,
                    "parent": list(parent),
                    "class": class_q if is_fn else None,
                    "pfunc": pfunc_q,
                    "top": top,
                    "span": [start, end],
                    "hash": ids.content_hash(span),
                    "ts": _rng(target),
                    "outer": _rng(outer),
                    "outer_type": outer.type,
                    "decos": [_rng(d) for d in decos],
                }
                if is_fn:
                    rec["attrs"] = {
                        "async": any(c.type == "async" for c in target.children),
                        "body_hash": body_hash(span, "def", name),
                        "decorators": [_dotted(_deco_callee(d)) or _text(d)[1:].split("(")[0] for d in decos],
                        "is_test": is_test_file and name.startswith("test"),
                        **param_info(target),
                    }
                else:
                    supers = target.child_by_field_name("superclasses")
                    rec["bases"] = [
                        [*_rng(b), b.type]
                        for b in (supers.named_children if supers else [])
                        if b.type in ("identifier", "attribute")
                    ]
                    rec["attrs"] = {"body_hash": body_hash(span, "class", name)}
                defs.append(rec)
                inner = target.child_by_field_name("body")
                if inner is not None:
                    if is_fn:
                        collect(inner, ("function", qname), None, qname, False)
                    else:
                        collect(inner, ("class", qname), qname, pfunc_q, False)
            elif target.type in CONTAINER_STMTS:
                for sub in target.named_children:
                    if sub.type in NESTED_BLOCKS:
                        collect(sub, parent, class_q, pfunc_q, top)

    collect(root, ("module", path), None, None, True)

    # -- imports and module-level assignments, in source order -----------------------------
    ops: list[list[Any]] = []

    def visit(n: TSNode, in_def: bool) -> None:
        for c in n.named_children:
            if c.type in ("import_statement", "import_from_statement"):
                ops.extend(import_ops(c, path))
            elif c.type in ("function_definition", "class_definition", "decorated_definition"):
                visit(c, True)
            elif c.type == "expression_statement" and not in_def:
                a = c.named_children[0] if c.named_children else None
                if a is not None and a.type == "assignment":
                    left, right = a.child_by_field_name("left"), a.child_by_field_name("right")
                    if left is not None and left.type == "identifier" and right is not None:
                        ops.append(["assign", _text(left), _rng(right), right.type])
            else:
                visit(c, in_def)

    visit(root, False)

    # -- explicit spec references (comments, docstrings) ------------------------------------
    owners = [(d["span"][0], d["span"][1], d["k"], d["qname"]) for d in defs]
    starts: dict[int, tuple[str, str]] = {}
    for s, _e, k, q in sorted(owners, key=lambda x: (x[0], -(x[1] - x[0]))):
        starts[s] = (k, q)
    refs: list[list[Any]] = []

    def owner_of(line: int) -> tuple[str, str]:
        j = line  # 0-based index of the next line: contiguous comment block directly above a def?
        while j < len(lines) and lines[j].strip().startswith("#"):
            j += 1
        if lines[line - 1].strip().startswith("#") and (j + 1) in starts:
            return starts[j + 1]
        inside = sorted((e - s, k, q) for s, e, k, q in owners if s <= line <= e)
        if inside:
            return inside[0][1], inside[0][2]
        return "m", path

    def visit_comments(n: TSNode) -> None:
        if n.type == "comment":
            mm = AD2V_MARK_RE.search(_text(n))
            if mm:
                found = parse_refs(mm.group(1))
                if found:
                    k, q = owner_of(n.start_point[0] + 1)
                    refs.append([k, q, found, "comment"])
            return
        for c in n.children:
            visit_comments(c)

    visit_comments(root)
    bodies: list[tuple[str, str, TSNode | None]] = [("m", path, root)]
    for d in defs:
        node = find_node(root, d["ts"], "function_definition" if d["k"] == "f" else "class_definition")
        bodies.append((d["k"], d["qname"], node.child_by_field_name("body")))
    seen: set[tuple[str, str]] = set()
    for k, q, body in bodies:
        if (k, q) in seen or body is None or not body.named_children:
            continue
        seen.add((k, q))
        first = body.named_children[0]
        if (
            first.type == "expression_statement"
            and first.named_children
            and first.named_children[0].type == "string"
        ):
            for ln in (_string_value(first.named_children[0]) or "").split("\n"):
                mm = AD2V_MARK_RE.search(ln.strip())
                if mm:
                    found = parse_refs(mm.group(1))
                    if found:
                        refs.append([k, q, found, "docstring"])
    return {
        "v": LOCAL_EXTRACTOR_VERSION,
        "end_line": max(1, text.count("\n") + (0 if text.endswith("\n") else 1)),
        "defs": defs,
        "ops": ops,
        "refs": refs,
    }
