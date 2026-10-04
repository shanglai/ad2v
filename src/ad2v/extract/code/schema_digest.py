"""Deterministic datastore schema digests (P7, ADR-0059; format spec §3.8).

Normative, from the repository text only (no database is contacted):

- **SQLAlchemy declarative models**: classes with `__tablename__`; columns from `Column(...)` /
  `mapped_column(...)` (type, primary key, foreign key, unique, nullable) and table-level
  `UniqueConstraint` / `PrimaryKeyConstraint` / unique `Index` in `__table_args__`;
- **SQL DDL**: `CREATE TABLE` statements in `*.sql` files (column constraints and table
  constraints);
- **Pydantic models** used by routes: a handler parameter annotated with a `BaseModel` subclass
  (request) and `response_model=` (response) become `attrs.models` on the route.

A model attaches to the datastore whose code touches it: the module that reads or writes the
datastore defines the model, or imports the model's module. SQL DDL attaches to the only
SQL-library datastore. Otherwise a synthetic `datastore:<lib>:models` node holds it.
The digest is `attrs.schema_digest = {"tables": [...]}` sorted by table name.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from typing import Any

from ad2v import ids, ir

SQL_LIBS = frozenset({"sqlalchemy", "psycopg", "psycopg2", "asyncpg", "sqlite3", "sqlmodel", "databases"})
MAX_LINES = 40


# -- SQLAlchemy --------------------------------------------------------------------------------------
def _name(n: ast.AST | None) -> str:
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return n.attr
    if isinstance(n, ast.Call):
        return _name(n.func)
    if isinstance(n, ast.Subscript):
        return _name(n.value)
    return ""


def _const(n: ast.AST | None) -> Any:
    return n.value if isinstance(n, ast.Constant) else None


def _kw(call: ast.Call, key: str) -> Any:
    for k in call.keywords:
        if k.arg == key:
            return _const(k.value)
    return None


def _column(name: str, call: ast.Call, annotation: ast.AST | None) -> dict[str, Any]:
    typ, fk = "", None
    for a in call.args:
        if isinstance(a, ast.Call) and _name(a.func) == "ForeignKey":
            fk = _const(a.args[0]) if a.args else None
        elif not typ and _name(a) and _name(a) not in ("ForeignKey",):
            typ = _name(a)
    if not typ and isinstance(annotation, ast.Subscript):  # Mapped[int]
        typ = _name(annotation.slice) or ast.unparse(annotation.slice)
    positional = _const(call.args[0]) if call.args else None  # Column("db_name", Type, ...)
    col: dict[str, Any] = {
        "name": _kw(call, "name") or (positional if isinstance(positional, str) else name),
        "type": typ or "?",
    }
    if _kw(call, "primary_key") is True:
        col["pk"] = True
    if _kw(call, "unique") is True:
        col["unique"] = True
    if _kw(call, "nullable") is False:
        col["not_null"] = True
    if fk:
        col["fk"] = str(fk)
    return col


def sqlalchemy_tables(path: str, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        table, cols, uniques = None, [], []
        for st in cls.body:
            target = value = annotation = None
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                target, value = st.targets[0].id, st.value
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                target, value, annotation = st.target.id, st.value, st.annotation
            if target is None:
                continue
            if target == "__tablename__":
                table = _const(value)
            elif target == "__table_args__" and isinstance(value, (ast.Tuple, ast.List)):
                for el in value.elts:
                    if isinstance(el, ast.Call) and (
                        _name(el.func) == "UniqueConstraint"
                        or (_name(el.func) == "Index" and _kw(el, "unique") is True)
                    ):
                        names = [_const(a) for a in el.args if isinstance(_const(a), str)]
                        if _name(el.func) == "Index":
                            names = names[1:]  # Index("name", "col", ...)
                        uniques.append(sorted(str(x) for x in names))
            elif isinstance(value, ast.Call) and _name(value.func) in ("Column", "mapped_column"):
                cols.append(_column(target, value, annotation))
        if isinstance(table, str) and cols:
            out.append(
                {"table": table, "source": "sqlalchemy", "path": path, "class": cls.name, "columns": cols,
                 "unique": sorted(uniques)}
            )  # fmt: skip
    return out


# -- SQL DDL ---------------------------------------------------------------------------------------
CREATE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"`]+)\s*\(", re.I)


def _split_top(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _cols(s: str) -> list[str]:
    return sorted(c.strip().strip('"`').lower() for c in s.split(","))


def sql_tables(path: str, text: str) -> list[dict[str, Any]]:
    text = re.sub(r"--[^\n]*", "", text)
    out = []
    for m in CREATE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body = text[m.end() : i - 1]
        cols, uniques, pk = [], [], []
        for item in _split_top(body):
            low = item.lower()
            tm = re.match(r"(?:constraint\s+\w+\s+)?(primary\s+key|unique)\s*\(([^)]*)\)", low)
            if tm:
                (pk if tm.group(1).startswith("primary") else uniques).append(_cols(tm.group(2)))
                continue
            fm = re.match(
                r"(?:constraint\s+\w+\s+)?foreign\s+key\s*\(([^)]*)\)\s*references\s+([\w.]+)\s*\(([^)]*)\)",
                low,
            )
            if fm:
                for c in cols:
                    if c["name"] == fm.group(1).strip():
                        c["fk"] = f"{fm.group(2)}.{fm.group(3).strip()}"
                continue
            words = item.split()
            if len(words) < 2:
                continue
            col: dict[str, Any] = {
                "name": words[0].strip('"`').lower(),
                "type": words[1].upper().split("(")[0],
            }
            if "primary key" in low:
                col["pk"] = True
            if re.search(r"\bunique\b", low):
                col["unique"] = True
            if "not null" in low:
                col["not_null"] = True
            rm = re.search(r"references\s+([\w.]+)\s*\(([^)]*)\)", low)
            if rm:
                col["fk"] = f"{rm.group(1)}.{rm.group(2).strip()}"
            cols.append(col)
        for group in pk:
            for c in cols:
                if c["name"] in group:
                    c["pk"] = True
        table = m.group(1).strip('"`').lower()
        out.append(
            {"table": table, "source": "sql", "path": path, "columns": cols, "unique": sorted(uniques)}
        )
    return out


# -- Pydantic models on routes ---------------------------------------------------------------------
def pydantic_models(text: str) -> dict[str, list[dict[str, str]]]:
    """Classes deriving (directly or within the module) from BaseModel/SQLModel: their fields."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    classes = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}
    models: dict[str, list[dict[str, str]]] = {}

    def is_model(c: ast.ClassDef, seen: frozenset[str] = frozenset()) -> bool:
        for b in c.bases:
            n = _name(b)
            if n in ("BaseModel", "SQLModel"):
                return True
            if n in classes and n not in seen and is_model(classes[n], seen | {c.name}):
                return True
        return False

    for name, c in classes.items():
        if is_model(c):
            models[name] = [
                {"name": st.target.id, "type": ast.unparse(st.annotation)}
                for st in c.body
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
            ]
    return models


def route_models(
    handler_text: str, func: str, models: dict[str, list[dict[str, str]]]
) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(handler_text)
    except (SyntaxError, ValueError):
        return []
    out = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if fn.name != func:
            continue
        for a in fn.args.args + fn.args.kwonlyargs:
            t = _name(a.annotation)
            if t in models:
                out.append({"role": "request", "class": t, "fields": models[t]})
        for d in fn.decorator_list:
            if isinstance(d, ast.Call):
                for k in d.keywords:
                    if k.arg == "response_model" and _name(k.value) in models:
                        out.append(
                            {"role": "response", "class": _name(k.value), "fields": models[_name(k.value)]}
                        )
    return out


# -- attaching -------------------------------------------------------------------------------------
def apply(graph: ir.Graph, py_files: Iterable[Any], sql_files: Iterable[Any]) -> int:
    """Attach digests to datastore nodes and request/response models to routes. Returns the number
    of tables found."""
    py = {f.path: f.text for f in py_files}
    nodes = graph.nodes
    stores = sorted((n for n in nodes.values() if n.kind == "datastore"), key=lambda n: n.id)
    touching: dict[str, set[str]] = {}  # datastore id -> module paths whose code reads/writes it
    for e in graph.edges.values():
        if e.kind in ("reads", "writes") and e.dst in nodes and nodes[e.dst].kind == "datastore":
            src = nodes.get(e.src)
            if src is not None and src.path:
                touching.setdefault(e.dst, set()).add(src.path)
    imports: dict[str, set[str]] = {}  # module path -> module paths it imports
    for e in graph.edges.values():
        if e.kind == "imports" and e.src in nodes and e.dst in nodes:
            imports.setdefault(nodes[e.src].path or "", set()).add(nodes[e.dst].path or "")
    tables: dict[str, list[dict[str, Any]]] = {}
    synthetic: list[dict[str, Any]] = []
    for path in sorted(py):
        found = sqlalchemy_tables(path, py[path])
        if not found:
            continue
        owners = [
            s.id
            for s in stores
            if any(m == path or path in imports.get(m, set()) for m in touching.get(s.id, set()))
        ]
        if owners:
            for o in owners:
                tables.setdefault(o, []).extend(found)
        else:
            synthetic.extend(found)
    sql_stores = [s.id for s in stores if set(s.attrs.get("libraries", [])) & SQL_LIBS]
    for f in sorted(sql_files, key=lambda f: f.path):
        found = sql_tables(f.path, f.text)
        if not found:
            continue
        if len(sql_stores) == 1:
            tables.setdefault(sql_stores[0], []).extend(found)
        else:
            synthetic.extend(found)
    if synthetic:
        lib = "sqlalchemy" if any(t["source"] == "sqlalchemy" for t in synthetic) else "sql"
        root = next((n for n in nodes.values() if n.kind == "system" and n.side == "code"), None)
        node = ir.Node(
            "code", "datastore", f"{lib} models", f"datastore:{lib}:models",
            parent_id=root.id if root else None,
            attrs={"libraries": [lib], "name_source": "synthetic", "resource_name": f"{lib}:models"},
        )  # fmt: skip
        node.content_hash = ids.content_hash(node.qualified_name)
        graph.add_node(node)
        tables.setdefault(node.id, []).extend(synthetic)
    n = 0
    for sid, ts in tables.items():
        ts = sorted(ts, key=lambda t: (t["table"], t["source"], t["path"]))
        nodes[sid].attrs["schema_digest"] = {"tables": ts}
        n += len(ts)
    # request / response models on routes
    model_defs: dict[str, list[dict[str, str]]] = {}
    for path in sorted(py):
        for name, fields in pydantic_models(py[path]).items():
            model_defs.setdefault(name, fields)
    for e in sorted(graph.edges.values(), key=lambda e: (e.src, e.dst)):
        rt, h = nodes.get(e.src), nodes.get(e.dst)
        if e.kind != "calls" or rt is None or h is None or rt.kind != "http_route" or h.kind != "function":
            continue
        text = py.get(h.path or "")
        if text is None:
            continue
        got = route_models(text, h.name, model_defs)
        if got:
            rt.attrs["schema_models"] = got
    return n


def digest_lines(digest: dict[str, Any], limit: int = MAX_LINES) -> list[str]:
    """A compact text rendering for LLM slices (≤ `limit` lines)."""
    lines: list[str] = []
    for t in digest.get("tables", []):
        lines.append(f"table {t['table']} ({t['source']}, {t['path']})")
        for c in t["columns"]:
            flags = [k for k in ("pk", "unique", "not_null") if c.get(k)]
            fk = f" -> {c['fk']}" if c.get("fk") else ""
            lines.append(f"  {c['name']} {c['type']}{' ' + ' '.join(flags) if flags else ''}{fk}")
        for u in t.get("unique", []):
            lines.append(f"  unique ({', '.join(u)})")
        if not t.get("unique") and not any(c.get("unique") for c in t["columns"]):
            has_pk = any(c.get("pk") for c in t["columns"])
            lines.append(
                "  (no unique constraint besides the primary key)"
                if has_pk
                else "  (no primary key or unique constraint)"
            )
    if len(lines) > limit:
        lines = lines[: limit - 1] + [f"… {len(lines) - limit + 1} more line(s)"]
    return lines
