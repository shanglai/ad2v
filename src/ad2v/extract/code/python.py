"""Python code extractor (tree-sitter). Read-only static analysis; never imports repo code.

Pipeline (all passes iterate in sorted, source order):
 1. parse every file; build the module index (import roots, format spec §3.3);
 2. structure: module/class/function nodes, import bindings, module-level assignments;
 3. explicit spec refs (comments, docstrings, test names);
 4. bodies: calls, resource touches, behavior candidates, events;
 5. ports (decorators, subscriptions) with router prefixes;
 6. risk flags → behavior node emission → events finalized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import tree_sitter_python as tsp
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from ad2v import ids, ir
from ad2v import rules as rules_mod
from ad2v.extract.code.base import CodeFacts, Event, Layout
from ad2v.extract.files import SourceFile
from ad2v.manifest import Config
from ad2v.resources import python_rules_path

PY_LANGUAGE = Language(tsp.language())

SPEC_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*-[0-9]+)\b")
AD2V_MARK_RE = re.compile(r"\bad2v:\s*(.+)$")
IO_KINDS = frozenset({"datastore", "external_service", "queue"})
SLOW_TX_KINDS = frozenset({"external_service", "llm_endpoint", "queue"})
COMPREHENSIONS = frozenset(
    {"list_comprehension", "set_comprehension", "dictionary_comprehension", "generator_expression"}
)
EDGE_FOR_KIND = {"external_service": "invokes_external", "llm_endpoint": "invokes_llm"}
ENV_GETTERS = frozenset({"os.getenv", "os.environ.get", "os.environ.setdefault"})


def load_rules(path: Path | None = None) -> dict[str, Any]:
    """Built-in (or given) rules without overlay; see `ad2v.rules` for overlays and hashing."""
    return rules_mod.load(path or python_rules_path())


# ---------------------------------------------------------------------------------------------
# Values produced by static evaluation
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResKey:
    kind: str
    name: str
    library: str
    name_source: str  # literal | env | unknown


@dataclass(frozen=True)
class Const:
    literal: str | None = None
    env: str | None = None


@dataclass(frozen=True)
class RepoSym:
    module: str
    attrs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtSym:
    fq: str


@dataclass(frozen=True)
class FnRef:
    node_id: str


@dataclass(frozen=True)
class SelfRef:
    class_qname: str


@dataclass(eq=False)
class Obj:
    ctor: str  # fully-qualified constructor (external dotted name)
    res: ResKey | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    origin: tuple[str, str] | None = None  # (module path, variable) for module-level objects


@dataclass(frozen=True)
class ObjAttr:
    obj: Obj
    chain: tuple[str, ...]


Value = Const | RepoSym | ExtSym | FnRef | SelfRef | Obj | ObjAttr | None


# ---------------------------------------------------------------------------------------------
# Structure records
# ---------------------------------------------------------------------------------------------


@dataclass
class FuncInfo:
    node: ir.Node
    ts: TSNode  # function_definition
    outer: TSNode  # decorated_definition or function_definition
    module: ModuleInfo
    class_qname: str | None
    parent_func: FuncInfo | None
    decorators: list[TSNode]
    local_defs: dict[str, str] = field(default_factory=dict)  # name -> node id of nested def
    scope: dict[str, Value] = field(default_factory=dict)  # final local scope (for closures)


@dataclass
class ClassInfo:
    node: ir.Node
    ts: TSNode
    module: ModuleInfo
    methods: dict[str, str] = field(default_factory=dict)  # name -> function node id
    bases: list[TSNode] = field(default_factory=list)


@dataclass
class ModuleInfo:
    path: str
    text: str
    tree: Any
    node: ir.Node
    container: str
    top_defs: dict[str, str] = field(default_factory=dict)  # name -> function/class node id
    raw_bindings: dict[str, tuple[str, Any]] = field(default_factory=dict)  # name -> (kind, payload)
    values: dict[str, Value] = field(default_factory=dict)
    evaluating: set[str] = field(default_factory=set)
    functions: list[FuncInfo] = field(default_factory=list)


@dataclass
class Candidate:
    """A behavior construct that may become a node if risky (or behavior.emit_all)."""

    kind: str
    qname: str
    scope_id: str
    parent: Candidate | None
    path: str
    start: int
    end: int
    text: str
    attrs: dict[str, Any] = field(default_factory=dict)
    kinds: set[str] = field(default_factory=set)
    callees: set[str] = field(default_factory=set)
    children: list[Candidate] = field(default_factory=list)
    risk: list[str] = field(default_factory=list)
    node_id: str | None = None


@dataclass
class RawEvent:
    kind: str
    targets: tuple[str, ...]
    stack: tuple[Candidate, ...]
    line: int


@dataclass
class Ctx:
    """Walking context for one scope (function, module body or class body)."""

    src_id: str  # node receiving edges
    scope_qname: str  # prefix for behavior qnames
    module: ModuleInfo
    func: FuncInfo | None
    class_qname: str | None
    local: dict[str, Value]
    parent_scope: dict[str, Value] | None = None
    stack: list[Candidate] = field(default_factory=list)
    collector: list[str] | None = None


def _text(n: TSNode | None) -> str:
    return n.text.decode("utf-8", errors="replace") if n is not None and n.text is not None else ""


def _line(n: TSNode) -> int:
    return n.start_point[0] + 1


def _end_line(n: TSNode) -> int:
    return n.end_point[0] + 1


def _string_value(n: TSNode) -> str | None:
    """Literal value of a string node; for f-strings, the literal prefix before the first {…}."""
    if n.type == "concatenated_string":
        parts = [_string_value(c) for c in n.named_children]
        return "".join(p for p in parts if p is not None) if all(p is not None for p in parts) else None
    if n.type != "string":
        return None
    out = []
    for c in n.named_children:
        if c.type == "string_content":
            out.append(_text(c))
        elif c.type == "interpolation":
            break
        elif c.type == "escape_sequence":
            out.append(_text(c))
    return "".join(out)


def _unwrap(n: TSNode) -> TSNode:
    while n.type in ("parenthesized_expression", "await") and n.named_child_count:
        n = n.named_children[0]
    return n


def _call_args(call: TSNode) -> tuple[list[TSNode], dict[str, TSNode], list[TSNode]]:
    """(positional, keyword, raw children) of a call's argument list."""
    args = call.child_by_field_name("arguments")
    pos: list[TSNode] = []
    kw: dict[str, TSNode] = {}
    raw: list[TSNode] = []
    if args is None:
        return pos, kw, raw
    if args.type == "generator_expression":
        return [args], kw, [args]
    for c in args.named_children:
        if c.type == "comment":
            continue
        raw.append(c)
        if c.type == "keyword_argument":
            name = c.child_by_field_name("name")
            value = c.child_by_field_name("value")
            if name is not None and value is not None:
                kw[_text(name)] = value
        elif c.type not in ("list_splat", "dictionary_splat"):
            pos.append(c)
    return pos, kw, raw


def sanitize_url(url: str, host_only: bool) -> str:
    """scheme://host[:port][/path] without credentials, query or fragment."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return url.split("?")[0]
    base = f"{parts.scheme}://{host}{port}"
    if host_only or not parts.path or parts.path == "/":
        return base
    return base + parts.path


def join_route(*parts: str) -> str:
    joined = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + joined


def _param_info(fn: TSNode) -> dict[str, Any]:
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


def dotted_text(n: TSNode) -> str | None:
    if n.type == "identifier":
        return _text(n)
    if n.type == "attribute":
        obj = n.child_by_field_name("object")
        attr = n.child_by_field_name("attribute")
        base = dotted_text(obj) if obj is not None else None
        return f"{base}.{_text(attr)}" if base is not None and attr is not None else None
    return None


class PythonExtractor:
    language = "python"
    suffixes = (".py",)

    def __init__(self, config: Config, rules: dict[str, Any] | None = None) -> None:
        self.config = config
        self.rules = rules or load_rules()
        self.parser = Parser(PY_LANGUAGE)
        r = self.rules
        self.res_rules: dict[str, dict[str, Any]] = r.get("resources", {})
        acc = r.get("access", {})
        self.read_methods = set(acc.get("read_methods", []))
        self.write_methods = set(acc.get("write_methods", []))
        self.sql_methods = set(acc.get("sql_methods", []))
        self.sql_write = {v.upper() for v in acc.get("sql_write_verbs", [])}
        self.sql_read = {v.upper() for v in acc.get("sql_read_verbs", [])}
        self.qb_write = set(acc.get("query_builders_write", []))
        self.qb_read = set(acc.get("query_builders_read", []))
        self.q_pub = set(acc.get("queue_publish_methods", []))
        self.q_con = set(acc.get("queue_consume_methods", []))
        beh = r.get("behaviors", {})
        self.retry_rules = {x["callable"]: x.get("bounded_by", []) for x in beh.get("retry", [])}
        fo = beh.get("fan_out", {})
        self.fan_callables = set(fo.get("callables", []))
        self.exec_ctors = set(fo.get("executor_constructors", []))
        self.exec_map = set(fo.get("executor_map_methods", []))
        self.exec_submit = set(fo.get("executor_submit_methods", [])) | {"create_task", "start_soon"}
        self.taskgroup_ctors = set(fo.get("task_group_constructors", []))
        tx = beh.get("transaction", {})
        self.tx_methods = set(tx.get("methods", []))
        self.tx_callables = set(tx.get("callables", []))
        ports = r.get("ports", {})
        http = ports.get("http", {})
        self.http_ctors = set(http.get("app_constructors", []))
        self.http_methods = set(http.get("method_decorators", []))
        self.http_route_decos = set(http.get("route_decorators", []))
        self.http_include = set(http.get("include_methods", []))
        self.http_prefix_kw = list(http.get("prefix_kwargs", ["prefix"]))
        mcp = ports.get("mcp", {})
        self.mcp_ctors = set(mcp.get("server_constructors", []))
        self.mcp_decos = set(mcp.get("tool_decorators", ["tool"]))
        cli = ports.get("cli", {})
        self.typer_ctors = set(cli.get("typer_constructors", []))
        self.typer_decos = set(cli.get("typer_decorators", ["command"]))
        self.click_decos = set(cli.get("click_decorators", []))
        self.click_group_decos = set(cli.get("click_group_decorators", []))
        self.event_rules = ports.get("events", [])

        # state
        self.graph: ir.Graph
        self.layout: Layout
        self.modules: dict[str, ModuleInfo] = {}
        self.index: dict[str, list[str]] = {}
        self.funcs: dict[str, FuncInfo] = {}
        self.classes: dict[str, ClassInfo] = {}  # class qname -> info
        self.fn_direct: dict[str, set[str]] = {}
        self.fn_callees: dict[str, set[str]] = {}
        self.candidates: list[Candidate] = []
        self.fn_candidates: dict[str, list[Candidate]] = {}  # function-level (decorator) candidates
        self.raw_events: dict[str, list[RawEvent]] = {}
        self.counters: dict[tuple[str, str], int] = {}
        self.route_decls: list[dict[str, Any]] = []
        self.mounts: dict[tuple[str, str], list[tuple[tuple[str, str] | None, str]]] = {}
        self.event_ports: list[dict[str, Any]] = []
        self.click_groups: set[str] = set()
        self.ports: set[tuple[str, str]] = set()  # (port id, handler id)

    # =========================================================================================
    # entry point
    # =========================================================================================

    def extract(self, graph: ir.Graph, layout: Layout, files: list[SourceFile]) -> CodeFacts:
        self.graph, self.layout = graph, layout
        facts = CodeFacts()
        for f in files:
            facts.files_read[f.path] = f.content_hash
            tree = self.parser.parse(f.text.encode("utf-8"))
            container = layout.container_for(f.path)
            parent = layout.parent_for_module(f.path)
            node = graph.add_node(
                ir.Node(
                    "code",
                    "module",
                    f.path.rsplit("/", 1)[-1],
                    f.path,
                    parent_id=parent,
                    path=f.path,
                    span_start_line=1,
                    span_end_line=max(1, f.text.count("\n") + (0 if f.text.endswith("\n") else 1)),
                    content_hash=f.content_hash,
                    attrs={"language": "python"},
                )
            )
            self.modules[f.path] = ModuleInfo(f.path, f.text, tree, node, container.name)
        self._build_index()
        for m in self._sorted_modules():
            self._structure(m)
        for m in self._sorted_modules():
            self._imports(m)
        for m in self._sorted_modules():
            self._spec_refs(m)
        for m in self._sorted_modules():
            self._walk_module(m)
        for m in self._sorted_modules():
            for fi in m.functions:
                self._walk_function(fi)
        for m in self._sorted_modules():
            for fi in m.functions:
                self._ports_from_decorators(fi)
        self._finalize_behaviors(facts)
        self._finalize_ports(facts)
        return facts

    def _sorted_modules(self) -> list[ModuleInfo]:
        return [self.modules[p] for p in sorted(self.modules)]

    # =========================================================================================
    # module index and import resolution
    # =========================================================================================

    def _build_index(self) -> None:
        roots = {""}
        for d in self.layout.decls:
            roots.update(p for p in d.paths if p != ".")
        for p in self.modules:
            parts = p.split("/")
            for i in range(len(parts) - 1):
                if parts[i] == "src":
                    roots.add("/".join(parts[: i + 1]))
        repo = self.layout.repo
        dirs = {p.rsplit("/", 1)[0] for p in self.modules if "/" in p}
        for d in sorted(dirs):
            if any((repo / d / m).is_file() for m in ("pyproject.toml", "setup.py", "setup.cfg")):
                roots.add(d)
        for p in sorted(self.modules):
            for root in sorted(roots):
                if root and not p.startswith(root + "/"):
                    continue
                rel = p[len(root) + 1 :] if root else p
                parts = rel[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                if not parts or not all(x.isidentifier() for x in parts):
                    continue
                self.index.setdefault(".".join(parts), []).append(p)

    def _pick(self, candidates: list[str], near: ModuleInfo | None) -> str:
        def key(p: str) -> tuple[int, int, str]:
            same = 0 if near is not None and self.modules[p].container == near.container else 1
            return (same, p.count("/"), p)

        return sorted(set(candidates), key=key)[0]

    def resolve_fq(self, fq: str, near: ModuleInfo | None) -> Value:
        parts = fq.split(".")
        for i in range(len(parts), 0, -1):
            cands = self.index.get(".".join(parts[:i]))
            if cands:
                return RepoSym(self._pick(cands, near), tuple(parts[i:]))
        return ExtSym(fq)

    def _module_file(self, base_dir: str, dotted: str) -> str | None:
        rel = "/".join(x for x in [base_dir, dotted.replace(".", "/")] if x)
        for cand in (f"{rel}.py", f"{rel}/__init__.py"):
            if cand in self.modules:
                return cand
        return None

    # =========================================================================================
    # pass 2: structure
    # =========================================================================================

    def _structure(self, m: ModuleInfo) -> None:
        self._collect_defs(m, m.tree.root_node, m.node, None, None, top=True)

    def _collect_defs(
        self,
        m: ModuleInfo,
        body: TSNode,
        parent: ir.Node,
        class_info: ClassInfo | None,
        parent_func: FuncInfo | None,
        top: bool,
    ) -> None:
        for child in body.named_children:
            outer = child
            decorators: list[TSNode] = []
            target = child
            if child.type == "decorated_definition":
                decorators = [d for d in child.named_children if d.type == "decorator"]
                target = child.child_by_field_name("definition") or child
            if target.type == "function_definition":
                self._add_function(m, target, outer, decorators, parent, class_info, parent_func, top)
            elif target.type == "class_definition":
                self._add_class(m, target, outer, parent, parent_func, top)
            elif target.type in (
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
            ):
                # conditional definitions (if TYPE_CHECKING, try/except ImportError, …)
                for sub in target.named_children:
                    if sub.type in ("block", "else_clause", "elif_clause", "except_clause", "finally_clause"):
                        self._collect_defs(m, sub, parent, class_info, parent_func, top)

    def _qname_prefix(self, parent: ir.Node, m: ModuleInfo) -> str:
        return f"{m.path}::" if parent.kind == "module" else f"{parent.qualified_name}."

    def _span_text(self, m: ModuleInfo, start: int, end: int) -> str:
        lines = m.text.split("\n")
        return "\n".join(lines[start - 1 : end])

    def _add_function(
        self,
        m: ModuleInfo,
        fn: TSNode,
        outer: TSNode,
        decorators: list[TSNode],
        parent: ir.Node,
        class_info: ClassInfo | None,
        parent_func: FuncInfo | None,
        top: bool,
    ) -> None:
        name = _text(fn.child_by_field_name("name"))
        qname = self._qname_prefix(parent, m) + name
        start, end = _line(outer), _end_line(outer)
        is_test = bool(re.match(r"(test_.*|.*_test)\.py$", m.path.rsplit("/", 1)[-1])) and name.startswith(
            "test"
        )
        attrs = {
            "async": any(c.type == "async" for c in fn.children),
            "decorators": [
                dotted_text(self._deco_callee(d)) or _text(d)[1:].split("(")[0] for d in decorators
            ],
            "is_test": is_test,
            **_param_info(fn),
        }
        node = self.graph.add_node(
            ir.Node(
                "code",
                "function",
                name,
                qname,
                parent_id=parent.id,
                path=m.path,
                span_start_line=start,
                span_end_line=end,
                content_hash=ids.content_hash(self._span_text(m, start, end)),
                attrs=attrs,
            )
        )
        fi = FuncInfo(
            node,
            fn,
            outer,
            m,
            class_info.node.qualified_name if class_info else None,
            parent_func,
            decorators,
        )
        if node.id in self.funcs:
            fi = self.funcs[node.id]  # duplicate definition (e.g. if/else): first wins
        else:
            self.funcs[node.id] = fi
            m.functions.append(fi)
        if top:
            m.top_defs.setdefault(name, node.id)
        if class_info is not None:
            class_info.methods.setdefault(name, node.id)
        if parent_func is not None:
            parent_func.local_defs.setdefault(name, node.id)
        body = fn.child_by_field_name("body")
        if body is not None:
            self._collect_defs(m, body, node, None, fi, top=False)

    def _add_class(
        self,
        m: ModuleInfo,
        cls: TSNode,
        outer: TSNode,
        parent: ir.Node,
        parent_func: FuncInfo | None,
        top: bool,
    ) -> None:
        name = _text(cls.child_by_field_name("name"))
        qname = self._qname_prefix(parent, m) + name
        start, end = _line(outer), _end_line(outer)
        node = self.graph.add_node(
            ir.Node(
                "code",
                "class",
                name,
                qname,
                parent_id=parent.id,
                path=m.path,
                span_start_line=start,
                span_end_line=end,
                content_hash=ids.content_hash(self._span_text(m, start, end)),
                attrs={},
            )
        )
        ci = self.classes.get(qname)
        if ci is None:
            supers = cls.child_by_field_name("superclasses")
            ci = ClassInfo(
                node,
                cls,
                m,
                bases=[
                    b
                    for b in (supers.named_children if supers else [])
                    if b.type in ("identifier", "attribute")
                ],
            )
            self.classes[qname] = ci
        if top:
            m.top_defs.setdefault(name, node.id)
        if parent_func is not None:
            parent_func.local_defs.setdefault(name, node.id)
        body = cls.child_by_field_name("body")
        if body is not None:
            self._collect_defs(m, body, node, ci, parent_func, top=False)

    @staticmethod
    def _deco_callee(d: TSNode) -> TSNode:
        expr = d.named_children[0] if d.named_children else d
        return expr.child_by_field_name("function") if expr.type == "call" else expr

    # -- imports and module-level assignments --------------------------------------------------

    def _imports(self, m: ModuleInfo) -> None:
        def visit(n: TSNode, in_def: bool) -> None:
            for c in n.named_children:
                if c.type == "import_statement":
                    self._import_stmt(m, c)
                elif c.type == "import_from_statement":
                    self._import_from(m, c)
                elif c.type in ("function_definition", "class_definition", "decorated_definition"):
                    visit(c, True)
                elif c.type == "expression_statement" and not in_def:
                    a = c.named_children[0] if c.named_children else None
                    if a is not None and a.type == "assignment":
                        left = a.child_by_field_name("left")
                        right = a.child_by_field_name("right")
                        if left is not None and left.type == "identifier" and right is not None:
                            m.raw_bindings[_text(left)] = ("expr", right)
                else:
                    visit(c, in_def)

        visit(m.tree.root_node, False)

    def _add_import_edge(self, m: ModuleInfo, v: Value, line: int) -> None:
        if isinstance(v, RepoSym) and v.module != m.path:
            self.graph.add_edge(m.node.id, self.modules[v.module].node.id, "imports", lines=[line])

    def _import_stmt(self, m: ModuleInfo, n: TSNode) -> None:
        for c in n.named_children:
            if c.type == "dotted_name":
                fq = _text(c)
                root = fq.split(".")[0]
                m.raw_bindings.setdefault(root, ("import", root))
                self._add_import_edge(m, self.resolve_fq(fq, m), _line(n))
            elif c.type == "aliased_import":
                fq = _text(c.child_by_field_name("name"))
                alias = _text(c.child_by_field_name("alias"))
                m.raw_bindings[alias] = ("import", fq)
                self._add_import_edge(m, self.resolve_fq(fq, m), _line(n))

    def _import_from(self, m: ModuleInfo, n: TSNode) -> None:
        mod = n.child_by_field_name("module_name")
        if mod is None:
            return
        relative_base: str | None = None
        dotted = ""
        if mod.type == "relative_import":
            prefix = next((c for c in mod.children if c.type == "import_prefix"), None)
            dots = len(_text(prefix)) if prefix is not None else 1
            dn = next((c for c in mod.named_children if c.type == "dotted_name"), None)
            dotted = _text(dn) if dn is not None else ""
            parts = m.path.split("/")[:-1]
            up = dots - 1
            if up > len(parts):
                return
            relative_base = "/".join(parts[: len(parts) - up])
        else:
            dotted = _text(mod)
        names = [c for c in n.children_by_field_name("name")]
        for c in names:
            if c.type == "aliased_import":
                name = _text(c.child_by_field_name("name"))
                alias = _text(c.child_by_field_name("alias"))
            else:
                name = alias = _text(c)
            if relative_base is not None:
                v = self._relative(relative_base, dotted, name)
                m.raw_bindings[alias] = ("value", v)
            else:
                m.raw_bindings[alias] = ("import", f"{dotted}.{name}")
                v = self.resolve_fq(f"{dotted}.{name}", m)
            self._add_import_edge(m, v, _line(n))

    def _relative(self, base_dir: str, dotted: str, name: str) -> Value:
        if dotted:
            mod = self._module_file(base_dir, dotted)
            sub = self._module_file(base_dir, f"{dotted}.{name}")
            if sub is not None and (mod is None or name not in self.modules[mod].top_defs):
                return RepoSym(sub)
            return RepoSym(mod, (name,)) if mod is not None else None
        sub = self._module_file(base_dir, name)
        if sub is not None:
            return RepoSym(sub)
        init = f"{base_dir}/__init__.py" if base_dir else "__init__.py"
        return RepoSym(init, (name,)) if init in self.modules else None

    # =========================================================================================
    # static evaluation
    # =========================================================================================

    def module_value(self, m: ModuleInfo, name: str) -> Value:
        if name in m.values:
            return m.values[name]
        if name in m.top_defs:
            return RepoSym(m.path, (name,))
        raw = m.raw_bindings.get(name)
        if raw is None or name in m.evaluating:
            return None
        m.evaluating.add(name)
        try:
            kind, payload = raw
            if kind in ("import", "value"):
                v = self.resolve_fq(payload, m) if kind == "import" else payload
                if isinstance(v, RepoSym) and v.attrs:
                    v = self.lookup(v)
            else:
                ctx = Ctx(m.node.id, m.path, m, None, None, {})
                v = self.eval(payload, ctx)
                if isinstance(v, Obj) and v.origin is None:
                    v.origin = (m.path, name)
        finally:
            m.evaluating.discard(name)
        m.values[name] = v
        return v

    def lookup(self, sym: RepoSym, depth: int = 0) -> Value:
        """Resolve a repo symbol to FnRef / class RepoSym / module RepoSym / bound value."""
        if depth > 8:
            return None
        if not sym.attrs:
            return sym
        m = self.modules.get(sym.module)
        if m is None:
            return None
        name, rest = sym.attrs[0], sym.attrs[1:]
        if name in m.top_defs:
            nid = m.top_defs[name]
            node = self.graph.nodes[nid]
            if node.kind == "function":
                return FnRef(nid) if not rest else None
            ci = self.classes.get(node.qualified_name)
            if not rest:
                return RepoSym(sym.module, (name,))
            if ci is not None and len(rest) == 1 and rest[0] in ci.methods:
                return FnRef(ci.methods[rest[0]])
            return None
        if name in m.raw_bindings:
            v = self.module_value(m, name)
            for a in rest:
                v = self.attr(v, a, depth + 1)
            return v
        if sym.module.endswith("__init__.py"):
            base = sym.module.rsplit("/", 1)[0] if "/" in sym.module else ""
            sub = self._module_file(base, name)
            if sub is not None:
                return self.lookup(RepoSym(sub, rest), depth + 1)
        return None

    def attr(self, v: Value, a: str, depth: int = 0) -> Value:
        if isinstance(v, RepoSym):
            return self.lookup(RepoSym(v.module, v.attrs + (a,)), depth)
        if isinstance(v, ExtSym):
            r = self.resolve_fq(f"{v.fq}.{a}", None)  # namespace packages: `import a.b` then a.b.f
            return self.lookup(r, depth) if isinstance(r, RepoSym) else r
        if isinstance(v, Obj):
            return ObjAttr(v, (a,))
        if isinstance(v, ObjAttr):
            return ObjAttr(v.obj, v.chain + (a,))
        if isinstance(v, SelfRef):
            fn = self._method(v.class_qname, a)
            return FnRef(fn) if fn else None
        return None

    def _method(self, class_qname: str, name: str, seen: frozenset[str] = frozenset()) -> str | None:
        ci = self.classes.get(class_qname)
        if ci is None or class_qname in seen:
            return None
        if name in ci.methods:
            return ci.methods[name]
        ctx = Ctx(ci.node.id, class_qname, ci.module, None, None, {})
        for b in ci.bases:
            bv = self.eval(b, ctx)
            if isinstance(bv, RepoSym):
                bv = self.lookup(bv)
            if isinstance(bv, RepoSym) and bv.attrs:
                qn = f"{bv.module}::{'.'.join(bv.attrs)}"
                found = self._method(qn, name, seen | {class_qname})
                if found:
                    return found
        return None

    def resolve_name(self, name: str, ctx: Ctx) -> Value:
        if name in ctx.local:
            return ctx.local[name]
        if ctx.func is not None:
            f: FuncInfo | None = ctx.func
            while f is not None:
                if name in f.local_defs:
                    nid = f.local_defs[name]
                    node = self.graph.nodes[nid]
                    return FnRef(nid) if node.kind == "function" else None
                f = f.parent_func
        if ctx.parent_scope is not None and name in ctx.parent_scope:
            return ctx.parent_scope[name]
        if name in ("self", "cls") and ctx.class_qname is not None:
            return SelfRef(ctx.class_qname)
        return self.module_value(ctx.module, name)

    def eval(self, n: TSNode | None, ctx: Ctx) -> Value:
        if n is None:
            return None
        n = _unwrap(n)
        t = n.type
        if t == "identifier":
            return self.resolve_name(_text(n), ctx)
        if t == "attribute":
            base = self.eval(n.child_by_field_name("object"), ctx)
            return self.attr(base, _text(n.child_by_field_name("attribute")))
        if t in ("string", "concatenated_string"):
            s = _string_value(n)
            return Const(literal=s) if s is not None else None
        if t == "subscript":
            base = self.eval(n.child_by_field_name("value"), ctx)
            sub = n.child_by_field_name("subscript")
            if isinstance(base, ExtSym) and base.fq == "os.environ" and sub is not None:
                s = _string_value(sub)
                return Const(env=s) if s else None
            return None
        if t == "call":
            return self._eval_call(n, ctx)
        if t == "as_pattern":
            return self.eval(n.named_children[0] if n.named_children else None, ctx)
        return None

    def _eval_call(self, n: TSNode, ctx: Ctx) -> Value:
        callee = self.eval(n.child_by_field_name("function"), ctx)
        pos, kw, _ = _call_args(n)
        if isinstance(callee, ExtSym):
            if callee.fq in ENV_GETTERS and pos:
                s = _string_value(_unwrap(pos[0]))
                return Const(env=s) if s else None
            lib, rule = self.lib_rule(callee.fq)
            if rule is not None:
                tail = callee.fq[len(lib) + 1 :]
                if tail in rule.get("constructors", []):
                    return Obj(callee.fq, self._name_resource(lib, rule, pos, kw, ctx, construct=True))
                return None
            meta: dict[str, Any] = {}
            for k in self.http_prefix_kw:
                if k in kw:
                    s = _string_value(_unwrap(kw[k]))
                    if s is not None:
                        meta["prefix"] = s
            return Obj(callee.fq, None, meta)
        if isinstance(callee, Obj):
            return Obj(callee.ctor, callee.res, dict(callee.meta))
        if isinstance(callee, ObjAttr):
            lib, rule = self.lib_rule(callee.obj.ctor)
            if rule is not None and callee.chain[-1] in rule.get("pure_methods", []):
                return Obj(callee.obj.ctor, callee.obj.res)
            return None
        return None

    # =========================================================================================
    # resources
    # =========================================================================================

    def lib_rule(self, fq: str) -> tuple[str, dict[str, Any] | None]:
        parts = fq.split(".")
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in self.res_rules:
                return key, self.res_rules[key]
        return "", None

    def _hint(self, n: TSNode, ctx: Ctx, allow_plain: bool) -> tuple[str, str] | None:
        v = self.eval(n, ctx)
        if isinstance(v, Const):
            if v.env:
                return f"env:{v.env}", "env"
            if v.literal is not None and "://" in v.literal:
                return v.literal, "literal"
            if v.literal and allow_plain:
                return v.literal, "literal"
        return None

    def _name_resource(
        self,
        lib: str,
        rule: dict[str, Any],
        pos: list[TSNode],
        kw: dict[str, TSNode],
        ctx: Ctx,
        construct: bool,
        base: ResKey | None = None,
    ) -> ResKey:
        kind = rule["kind"]
        label = lib
        svc = rule.get("by_service_arg")
        if svc and pos:
            s = _string_value(_unwrap(pos[0]))
            if s in svc:
                kind, label = svc[s], f"{lib}.{s}"
                pos = pos[1:]
        plain = bool(rule.get("name_from_literal"))
        found: tuple[str, str] | None = None
        for k in rule.get("name_kwargs", []):
            if k in kw:
                found = self._hint(kw[k], ctx, allow_plain=True)
                if found:
                    break
        if found is None:
            for a in pos:
                found = self._hint(a, ctx, allow_plain=plain)
                if found:
                    break
        if found is None and base is not None:
            return base
        if found is None and construct:
            for a in list(pos) + [kw[k] for k in sorted(kw)]:
                v = self.eval(a, ctx)
                if isinstance(v, Obj) and v.res is not None:
                    return v.res
        if found is None:
            return ResKey(kind, f"{label}:unknown", label, "unknown")
        name, source = found
        if source == "literal" and "://" in name:
            name = sanitize_url(name, host_only=kind in ("external_service", "queue", "llm_endpoint"))
        return ResKey(kind, name, label, source)

    def ensure_resource(self, key: ResKey) -> ir.Node:
        qname = f"{key.kind}:{key.name}"
        nid = ids.node_id("code", key.kind, qname)
        existing = self.graph.get(nid)
        if existing is not None:
            libs = sorted(set(existing.attrs["libraries"]) | {key.library})
            if libs != existing.attrs["libraries"]:
                existing.attrs["libraries"] = libs
                existing.content_hash = ids.attrs_hash(existing.kind, existing.name, existing.attrs)
            return existing
        attrs = {"libraries": [key.library], "name_source": key.name_source, "resource_name": key.name}
        return self.graph.add_node(
            ir.Node(
                "code",
                key.kind,
                key.name,
                qname,
                parent_id=self.layout.system.id,
                attrs=attrs,
                content_hash=ids.attrs_hash(key.kind, key.name, attrs),
            )
        )

    def _access(self, kind: str, method: str, call: TSNode, ctx: Ctx) -> tuple[str, dict[str, Any]]:
        if kind == "datastore":
            if method in self.sql_methods:
                pos, _, _ = _call_args(call)
                if pos:
                    first = _unwrap(pos[0])
                    sql: str | None = None
                    if first.type == "call":
                        callee = dotted_text(first.child_by_field_name("function")) or ""
                        tail = callee.rsplit(".", 1)[-1]
                        if tail in self.qb_write:
                            return "writes", {}
                        if tail in self.qb_read:
                            return "reads", {}
                        ip, _, _ = _call_args(first)
                        if ip:
                            v = self.eval(ip[0], ctx)
                            sql = v.literal if isinstance(v, Const) else None
                    else:
                        v = self.eval(first, ctx)
                        sql = v.literal if isinstance(v, Const) else None
                    if sql:
                        verb = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
                        if verb in self.sql_write:
                            return "writes", {}
                        if verb in self.sql_read:
                            return "reads", {}
                return "reads", {"access": "default"}
            if method in self.write_methods:
                return "writes", {}
            if method in self.read_methods:
                return "reads", {}
            return "reads", {"access": "default"}
        if kind == "queue":
            if method in self.q_con:
                return "consumes", {}
            if method in self.q_pub:
                return "publishes", {}
            return "publishes", {"access": "default"}
        return EDGE_FOR_KIND.get(kind, "invokes_external"), {}

    def _touch(self, key: ResKey, method: str, call: TSNode, ctx: Ctx) -> None:
        res = self.ensure_resource(key)
        edge_kind, attrs = self._access(res.kind, method, call, ctx)
        line = _line(call)
        self.graph.add_edge(ctx.src_id, res.id, edge_kind, attrs=attrs, lines=[line])
        self.fn_direct.setdefault(ctx.src_id, set()).add(res.kind)
        for c in ctx.stack:
            c.kinds.add(res.kind)
        stack = tuple(ctx.stack)
        if res.kind == "llm_endpoint":
            cand = self._candidate("llm_call", call, ctx, {"construct": "call", "library": key.library})
            cand.kinds.add("llm_endpoint")
            stack = stack + (cand,)
        self.raw_events.setdefault(ctx.src_id, []).append(RawEvent("touch", (res.id,), stack, line))

    # =========================================================================================
    # pass 3: explicit spec references
    # =========================================================================================

    def _spec_refs(self, m: ModuleInfo) -> None:
        spans: list[tuple[int, int, int, str]] = []  # (start, end, -depth, node id)
        for fi in m.functions:
            spans.append((fi.node.span_start_line or 0, fi.node.span_end_line or 0, 0, fi.node.id))
        for ci in self.classes.values():
            if ci.module is m:
                spans.append((ci.node.span_start_line or 0, ci.node.span_end_line or 0, 0, ci.node.id))
        starts = {s: nid for s, _, _, nid in sorted(spans, key=lambda x: (x[0], -(x[1] - x[0])))}
        lines = m.text.split("\n")

        def owner_of(line: int) -> str:
            j = line  # 0-based index of the next line: contiguous comment block directly above a def?
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            if lines[line - 1].strip().startswith("#") and (j + 1) in starts:
                return starts[j + 1]
            inside = [(e - s, nid) for s, e, _, nid in spans if s <= line <= e]
            if inside:
                return sorted(inside)[0][1]
            return m.node.id

        def visit(n: TSNode) -> None:
            if n.type == "comment":
                mm = AD2V_MARK_RE.search(_text(n))
                if mm:
                    refs = SPEC_ID_RE.findall(mm.group(1))
                    if refs:
                        self._add_refs(owner_of(_line(n)), refs, "comment")
                return
            for c in n.children:
                visit(c)

        visit(m.tree.root_node)
        # docstrings
        targets: list[tuple[str, TSNode | None]] = [(m.node.id, m.tree.root_node)]
        targets += [(fi.node.id, fi.ts.child_by_field_name("body")) for fi in m.functions]
        targets += [
            (ci.node.id, ci.ts.child_by_field_name("body")) for ci in self.classes.values() if ci.module is m
        ]
        for nid, body in targets:
            if body is None or not body.named_children:
                continue
            first = body.named_children[0]
            if (
                first.type == "expression_statement"
                and first.named_children
                and first.named_children[0].type == "string"
            ):
                for ln in (_string_value(first.named_children[0]) or "").split("\n"):
                    mm = AD2V_MARK_RE.search(ln.strip())
                    if mm:
                        self._add_refs(nid, SPEC_ID_RE.findall(mm.group(1)), "docstring")
        # test names
        prefixes = "|".join(re.escape(p.lower()) for p in self.config.test_ref_prefixes)
        if prefixes:
            pat = re.compile(rf"(?:^|_)({prefixes})_([0-9]+)(?=_|$)", re.IGNORECASE)
            for fi in m.functions:
                if fi.node.attrs.get("is_test"):
                    refs = [f"{p.upper()}-{d}" for p, d in pat.findall(fi.node.name)]
                    if refs:
                        self._add_refs(fi.node.id, refs, "test_name")

    def _add_refs(self, nid: str, refs: list[str], source: str) -> None:
        node = self.graph.nodes[nid]
        node.spec_ref = sorted(set(node.spec_ref) | set(refs))
        srcs = node.attrs.setdefault("spec_ref_sources", {})
        for r in refs:
            srcs[r] = sorted(set(srcs.get(r, [])) | {source})

    # =========================================================================================
    # pass 4: bodies
    # =========================================================================================

    def _walk_module(self, m: ModuleInfo) -> None:
        ctx = Ctx(m.node.id, m.path, m, None, None, {})
        self._walk_block(m.tree.root_node, ctx)
        for ci in [c for c in self.classes.values() if c.module is m]:
            body = ci.ts.child_by_field_name("body")
            cctx = Ctx(ci.node.id, ci.node.qualified_name, m, None, ci.node.qualified_name, {})
            if body is not None:
                self._walk_block(body, cctx)

    def _walk_function(self, fi: FuncInfo) -> None:
        ctx = Ctx(
            fi.node.id,
            fi.node.qualified_name,
            fi.module,
            fi,
            fi.class_qname,
            {},
            parent_scope=fi.parent_func.scope if fi.parent_func else None,
        )
        self.fn_direct.setdefault(fi.node.id, set())
        self.fn_callees.setdefault(fi.node.id, set())
        params = fi.ts.child_by_field_name("parameters")
        for p in params.named_children if params else []:
            if p.type in ("typed_parameter", "typed_default_parameter"):
                pname = p.child_by_field_name("name") or (p.named_children[0] if p.named_children else None)
                ptype = p.child_by_field_name("type")
                v = self.eval(ptype.named_children[0] if ptype and ptype.named_children else ptype, ctx)
                if isinstance(v, ExtSym) and pname is not None and pname.type == "identifier":
                    lib, rule = self.lib_rule(v.fq)
                    if rule is not None:
                        ctx.local[_text(pname)] = Obj(
                            v.fq, ResKey(rule["kind"], f"{lib}:unknown", lib, "unknown")
                        )
        self._decorator_behaviors(fi, ctx)
        body = fi.ts.child_by_field_name("body")
        if body is not None:
            self._walk_block(body, ctx)
        fi.scope = dict(ctx.local)

    def _decorator_behaviors(self, fi: FuncInfo, ctx: Ctx) -> None:
        mctx = Ctx(fi.module.node.id, fi.module.path, fi.module, fi.parent_func, fi.class_qname, {})
        for d in fi.decorators:
            expr = d.named_children[0] if d.named_children else None
            if expr is None:
                continue
            callee_node = expr.child_by_field_name("function") if expr.type == "call" else expr
            v = self.eval(callee_node, mctx)
            if not isinstance(v, ExtSym):
                continue
            if v.fq in self.retry_rules:
                _, kw, _ = _call_args(expr) if expr.type == "call" else ([], {}, [])
                bounded = any(k in kw for k in self.retry_rules[v.fq])
                cand = self._candidate(
                    "retry",
                    d,
                    ctx,
                    {"construct": "decorator", "library": v.fq.split(".")[0], "bounded": bounded},
                    function_level=True,
                )
                self.fn_candidates.setdefault(fi.node.id, []).append(cand)
            elif v.fq in self.tx_callables:
                cand = self._candidate("transaction", d, ctx, {"construct": "decorator"}, function_level=True)
                self.fn_candidates.setdefault(fi.node.id, []).append(cand)

    def _candidate(
        self,
        kind: str,
        n: TSNode,
        ctx: Ctx,
        attrs: dict[str, Any],
        function_level: bool = False,
        header: TSNode | None = None,
    ) -> Candidate:
        """Create a behavior candidate with a content-anchored qualified name (ADR-0011).

        `<scope>@<kind>#<anchor>` where anchor = sha256(whitespace-normalized header text)[:8];
        a second identical header in the same scope and kind gets `~2`, a third `~3`, ...
        """
        head = " ".join(_text(header if header is not None else n).split())
        anchor = ids.sha256_hex(head)[:8]
        key = (ctx.scope_qname, kind, anchor)
        self.counters[key] = self.counters.get(key, 0) + 1
        dup = self.counters[key]
        parent = None if function_level or not ctx.stack else ctx.stack[-1]
        start, end = _line(n), _end_line(n)
        cand = Candidate(
            kind=kind,
            qname=f"{ctx.scope_qname}@{kind}#{anchor}" + (f"~{dup}" if dup > 1 else ""),
            scope_id=ctx.src_id,
            parent=parent,
            path=ctx.module.path,
            start=start,
            end=end,
            text=self._span_text(ctx.module, start, end),
            attrs=attrs,
        )
        if parent is not None:
            parent.children.append(cand)
        self.candidates.append(cand)
        return cand

    def _walk_block(self, n: TSNode, ctx: Ctx) -> None:
        for c in n.named_children:
            self._walk(c, ctx)

    def _walk(self, n: TSNode, ctx: Ctx) -> None:
        t = n.type
        if t in ("function_definition", "class_definition", "decorated_definition"):
            return  # separate scopes
        if t in ("for_statement", "while_statement"):
            iterable = n.child_by_field_name("right") if t == "for_statement" else None
            if iterable is not None:
                self._walk(iterable, ctx)
            loop_cand = None
            if ctx.collector is None:
                loop_cand = self._candidate(
                    "loop",
                    n,
                    ctx,
                    {
                        "construct": "for" if t == "for_statement" else "while",
                        "async": any(c.type == "async" for c in n.children),
                    },
                    header=iterable if t == "for_statement" else n.child_by_field_name("condition"),
                )
                ctx.stack.append(loop_cand)
            if t == "while_statement":
                cond = n.child_by_field_name("condition")
                if cond is not None:
                    self._walk(cond, ctx)
            body = n.child_by_field_name("body")
            if body is not None:
                self._walk(body, ctx)
            if loop_cand is not None:
                ctx.stack.pop()
            alt = n.child_by_field_name("alternative")
            if alt is not None:
                self._walk(alt, ctx)
            return
        if t in COMPREHENSIONS:
            has_call = self._has_call(n)
            if has_call and ctx.collector is None:
                clause = next((c for c in n.named_children if c.type == "for_in_clause"), None)
                head = clause.child_by_field_name("right") if clause is not None else None
                cand = self._candidate("loop", n, ctx, {"construct": "comprehension"}, header=head)
                ctx.stack.append(cand)
                for c in n.named_children:
                    self._walk(c, ctx)
                ctx.stack.pop()
            else:
                for c in n.named_children:
                    self._walk(c, ctx)
            return
        if t == "with_statement":
            self._walk_with(n, ctx)
            return
        if t == "call":
            self._handle_call(n, ctx)
            return
        if t == "assignment":
            right = n.child_by_field_name("right")
            if right is not None:
                self._walk(right, ctx)
            left = n.child_by_field_name("left")
            is_module_scope = ctx.func is None and ctx.class_qname is None  # module_value() owns these
            if left is not None and left.type == "identifier" and right is not None and not is_module_scope:
                ctx.local[_text(left)] = self.eval(right, ctx)
            return
        for c in n.named_children:
            self._walk(c, ctx)

    @staticmethod
    def _has_call(n: TSNode) -> bool:
        stack = [n]
        while stack:
            x = stack.pop()
            if x.type == "call":
                return True
            if x.type in ("lambda", "function_definition"):
                continue
            stack.extend(x.named_children)
        return False

    def _walk_with(self, n: TSNode, ctx: Ctx) -> None:
        pushed = 0
        clause = next((c for c in n.named_children if c.type == "with_clause"), None)
        items = [c for c in clause.named_children if c.type == "with_item"] if clause else []
        for item in items:
            value = item.child_by_field_name("value")
            if value is None:
                continue
            expr = value.named_children[0] if value.type == "as_pattern" and value.named_children else value
            self._walk(expr, ctx)
            if self._is_transaction(expr, ctx):
                cand = self._candidate("transaction", n, ctx, {"construct": "with"}, header=expr)
                ctx.stack.append(cand)
                pushed += 1
            if value.type == "as_pattern":
                target = value.child_by_field_name("alias")
                ident = target.named_children[0] if target is not None and target.named_children else None
                if ident is not None and ident.type == "identifier":
                    ctx.local[_text(ident)] = self.eval(expr, ctx)
        body = n.child_by_field_name("body")
        if body is not None:
            self._walk(body, ctx)
        for _ in range(pushed):
            ctx.stack.pop()

    def _is_transaction(self, expr: TSNode, ctx: Ctx) -> bool:
        expr = _unwrap(expr)
        if expr.type != "call":
            return False
        callee = self.eval(expr.child_by_field_name("function"), ctx)
        if isinstance(callee, ExtSym) and callee.fq in self.tx_callables:
            return True
        return (
            isinstance(callee, ObjAttr)
            and callee.chain[-1] in self.tx_methods
            and callee.obj.res is not None
            and callee.obj.res.kind == "datastore"
        )

    def _emit_call(self, target: str, call: TSNode, ctx: Ctx) -> None:
        self.graph.add_edge(ctx.src_id, target, "calls", lines=[_line(call)])
        self.fn_callees.setdefault(ctx.src_id, set()).add(target)
        for c in ctx.stack:
            c.callees.add(target)
        if ctx.collector is not None:
            if target not in ctx.collector:
                ctx.collector.append(target)
            return
        self.raw_events.setdefault(ctx.src_id, []).append(
            RawEvent("call", (target,), tuple(ctx.stack), _line(call))
        )

    def _callable_target(self, v: Value) -> str | None:
        if isinstance(v, RepoSym):
            v = self.lookup(v)
        if isinstance(v, FnRef):
            return v.node_id
        if isinstance(v, RepoSym) and v.attrs:
            qn = f"{v.module}::{'.'.join(v.attrs)}"
            ci = self.classes.get(qn)
            if ci is not None:
                return ci.methods.get("__init__", ci.node.id)
        return None

    def _handle_call(self, call: TSNode, ctx: Ctx) -> None:
        fn_node = call.child_by_field_name("function")
        callee = self.eval(fn_node, ctx)
        pos, kw, raw = _call_args(call)
        args_done = False
        target = self._callable_target(callee)
        if target is not None:
            self._emit_call(target, call, ctx)
        elif isinstance(callee, ExtSym):
            args_done = self._ext_call(callee, call, pos, kw, raw, ctx)
        elif isinstance(callee, ObjAttr):
            args_done = self._obj_call(callee, call, pos, kw, raw, ctx)
        # walk into the callee expression (chained calls) and the arguments
        if fn_node is not None and fn_node.type != "identifier":
            self._walk(fn_node, ctx)
        if not args_done:
            args = call.child_by_field_name("arguments")
            if args is not None:
                self._walk(args, ctx)

    def _fan_out(
        self,
        call: TSNode,
        raw: list[TSNode],
        ctx: Ctx,
        over: bool,
        lib: str,
        fn_refs: list[TSNode] | None = None,
    ) -> None:
        cand = self._candidate(
            "fan_out",
            call,
            ctx,
            {"construct": "call", "library": lib, "over_collection": over},
            header=call.child_by_field_name("arguments") if fn_refs is None else call,
        )
        ctx.stack.append(cand)
        saved = ctx.collector
        ctx.collector = []
        for r in fn_refs or []:
            t = self._callable_target(self.eval(r, ctx))
            if t is not None:
                self._emit_call(t, call, ctx)
        args = call.child_by_field_name("arguments")
        if args is not None and fn_refs is None:
            self._walk(args, ctx)
        elif fn_refs is not None:
            for r in raw[1:]:
                self._walk(r, ctx)
        targets = tuple(ctx.collector)
        ctx.collector = saved
        if targets:
            if ctx.collector is not None:
                for t in targets:
                    if t not in ctx.collector:
                        ctx.collector.append(t)
            else:
                self.raw_events.setdefault(ctx.src_id, []).append(
                    RawEvent("call", targets, tuple(ctx.stack), _line(call))
                )
        ctx.stack.pop()

    def _ext_call(
        self,
        callee: ExtSym,
        call: TSNode,
        pos: list[TSNode],
        kw: dict[str, TSNode],
        raw: list[TSNode],
        ctx: Ctx,
    ) -> bool:
        fq = callee.fq
        if fq in self.fan_callables:
            over = any(
                r.type in ("list_splat", "dictionary_splat") or _unwrap(r).type in COMPREHENSIONS for r in raw
            )
            self._fan_out(call, raw, ctx, over, fq.split(".")[0])
            return True
        if fq in self.retry_rules:
            bounded = any(k in kw for k in self.retry_rules[fq])
            self._candidate(
                "retry", call, ctx, {"construct": "call", "library": fq.split(".")[0], "bounded": bounded}
            )
            return False
        lib, rule = self.lib_rule(fq)
        if rule is None:
            return False
        tail = fq[len(lib) + 1 :]
        if tail in rule.get("constructors", []) or tail in rule.get("pure", []):
            return False
        # Module-level functions of datastore libraries are helpers (sqlalchemy.inspect, text, …);
        # IO happens on engine/session/connection objects. Other kinds (requests.get,
        # litellm.completion) do IO directly.
        direct = rule.get("direct_calls_touch", rule["kind"] != "datastore")
        if not direct and tail not in rule.get("touch_functions", []):
            return False
        key = self._name_resource(lib, rule, pos, kw, ctx, construct=False)
        self._touch(key, tail.rsplit(".", 1)[-1], call, ctx)
        return False

    def _obj_call(
        self,
        callee: ObjAttr,
        call: TSNode,
        pos: list[TSNode],
        kw: dict[str, TSNode],
        raw: list[TSNode],
        ctx: Ctx,
    ) -> bool:
        obj, method = callee.obj, callee.chain[-1]
        if obj.ctor in self.exec_ctors and method in self.exec_map and pos:
            self._fan_out(call, raw, ctx, True, obj.ctor.split(".")[0], fn_refs=[pos[0]])
            return True
        if (
            (obj.ctor in self.exec_ctors or obj.ctor in self.taskgroup_ctors)
            and method in self.exec_submit
            and pos
        ):
            in_loop = any(c.kind == "loop" for c in ctx.stack)
            first = _unwrap(pos[0])
            if first.type == "call":  # tg.create_task(f(x))
                self._fan_out(call, raw, ctx, in_loop, obj.ctor.split(".")[0])
            else:
                self._fan_out(call, raw, ctx, in_loop, obj.ctor.split(".")[0], fn_refs=[pos[0]])
            return True
        if method in self.http_include and pos and obj.ctor in self.http_ctors:
            inner = self.eval(pos[0], ctx)
            if isinstance(inner, Obj) and inner.origin is not None:
                prefix = ""
                for k in self.http_prefix_kw:
                    if k in kw:
                        prefix = _string_value(_unwrap(kw[k])) or ""
                self.mounts.setdefault(inner.origin, []).append((obj.origin, prefix))
        for rule in self.event_rules:
            if obj.ctor == rule["constructor"] and method == rule["method"]:
                cb = kw.get(rule.get("callback_kwarg", "callback"))
                idx = rule.get("callback_arg")
                if cb is None and idx is not None and len(pos) > idx:
                    cb = pos[idx]
                handler = self._callable_target(self.eval(cb, ctx)) if cb is not None else None
                src_i = rule.get("source_arg")
                source = None
                if src_i is not None and len(pos) > src_i:
                    h = self._hint(pos[src_i], ctx, allow_plain=True)
                    source = h[0] if h else None
                if handler is not None:
                    self.event_ports.append(
                        {
                            "handler": handler,
                            "module": ctx.module.path,
                            "source": source,
                            "framework": obj.ctor.split(".")[0],
                            "line": _line(call),
                        }
                    )
        if obj.res is not None:
            lib, rule = self.lib_rule(obj.ctor)
            if rule is not None and method in rule.get("pure_methods", []):
                return False
            key = obj.res
            if key.name_source == "unknown" and rule is not None:
                key = self._name_resource(lib, rule, pos, kw, ctx, construct=False, base=obj.res)
            self._touch(key, method, call, ctx)
        return False

    # =========================================================================================
    # pass 5: ports
    # =========================================================================================

    def _ports_from_decorators(self, fi: FuncInfo) -> None:
        mctx = Ctx(fi.module.node.id, fi.module.path, fi.module, fi.parent_func, fi.class_qname, {})
        for d in fi.decorators:
            expr = d.named_children[0] if d.named_children else None
            if expr is None:
                continue
            is_call = expr.type == "call"
            callee_node = expr.child_by_field_name("function") if is_call else expr
            pos, kw, _ = _call_args(expr) if is_call else ([], {}, [])
            v = self.eval(callee_node, mctx)
            first = _string_value(_unwrap(pos[0])) if pos else None
            if isinstance(v, ObjAttr) and len(v.chain) == 1:
                obj, meth = v.obj, v.chain[0]
                if obj.ctor in self.http_ctors and (
                    meth in self.http_methods or meth in self.http_route_decos
                ):
                    path = first
                    for k in ("path", "rule"):
                        if path is None and k in kw:
                            path = _string_value(_unwrap(kw[k]))
                    if path is None:
                        continue
                    if meth in self.http_methods:
                        methods = [meth.upper()]
                    else:
                        methods = ["GET"]
                        if "methods" in kw and _unwrap(kw["methods"]).type in ("list", "tuple", "set"):
                            methods = sorted(
                                {
                                    (_string_value(x) or "").upper()
                                    for x in _unwrap(kw["methods"]).named_children
                                    if _string_value(x)
                                }
                            )
                    self.route_decls.append(
                        {
                            "fi": fi,
                            "obj": obj,
                            "path": path,
                            "methods": methods,
                            "framework": obj.ctor.split(".")[0],
                        }
                    )
                elif obj.ctor in self.mcp_ctors and meth in self.mcp_decos:
                    name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                    self._make_port(
                        fi,
                        "mcp_tool",
                        f"mcp:{fi.module.container}:{name or fi.node.name}",
                        name or fi.node.name,
                        {"tool_name": name or fi.node.name, "framework": obj.ctor.split(".")[0]},
                    )
                elif obj.ctor in self.typer_ctors and meth in self.typer_decos:
                    name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                    cmd = name or fi.node.name.replace("_", "-")
                    self._make_port(
                        fi,
                        "cli_command",
                        f"cli:{fi.module.container}:{cmd}",
                        cmd,
                        {"command": cmd, "framework": "typer"},
                    )
            elif isinstance(v, ExtSym) and v.fq in self.click_decos:
                name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                cmd = name or fi.node.name.replace("_", "-")
                if v.fq.endswith(".group"):
                    self.click_groups.add(fi.node.id)
                self._make_port(
                    fi,
                    "cli_command",
                    f"cli:{fi.module.container}:{cmd}",
                    cmd,
                    {"command": cmd, "framework": "click"},
                )
            if callee_node is not None and callee_node.type == "attribute":
                base = self.eval(callee_node.child_by_field_name("object"), mctx)
                meth = _text(callee_node.child_by_field_name("attribute"))
                gid = self._callable_target(base)
                if gid is not None and gid in self.click_groups and meth in self.click_group_decos:
                    name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                    cmd = name or fi.node.name.replace("_", "-")
                    self._make_port(
                        fi,
                        "cli_command",
                        f"cli:{fi.module.container}:{cmd}",
                        cmd,
                        {"command": cmd, "framework": "click", "group": self.graph.nodes[gid].qualified_name},
                    )

    def _make_port(
        self,
        fi: FuncInfo | None,
        kind: str,
        qname: str,
        name: str,
        attrs: dict[str, Any],
        handler: str | None = None,
        container: str | None = None,
    ) -> None:
        hid = handler or (fi.node.id if fi else None)
        if hid is None:
            return
        hnode = self.graph.nodes[hid]
        attrs = {**attrs, "handler": hnode.qualified_name}
        cname = container or (fi.module.container if fi else "")
        cont = self.graph.get(ids.node_id("code", "container", f"container:{cname}"))
        if cont is None:
            return
        port = self.graph.add_node(
            ir.Node(
                "code",
                kind,
                name,
                qname,
                parent_id=cont.id,
                path=hnode.path,
                span_start_line=hnode.span_start_line,
                span_end_line=hnode.span_start_line,
                attrs=attrs,
                content_hash=ids.attrs_hash(kind, name, attrs),
            )
        )
        self.graph.add_edge(cont.id, port.id, "exposes")
        self.graph.add_edge(port.id, hid, "calls")
        self.ports.add((port.id, hid))

    def _prefixes(
        self, origin: tuple[str, str] | None, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> list[str]:
        """All mount prefixes for a router object (include_router / register_blueprint chains)."""
        if origin is None or origin in seen or origin not in self.mounts:
            return [""]
        out = []
        for parent, prefix in sorted(self.mounts[origin], key=lambda x: (x[0] or ("", ""), x[1])):
            for pp in self._prefixes(parent, seen | {origin}):
                out.append(join_route(pp, prefix) if pp or prefix else "")
        return sorted(set(out))

    def _finalize_ports(self, facts: CodeFacts) -> None:
        for decl in self.route_decls:
            fi: FuncInfo = decl["fi"]
            obj: Obj = decl["obj"]
            own = obj.meta.get("prefix", "")
            for mount in self._prefixes(obj.origin):
                full = join_route(mount, own, decl["path"])
                for method in decl["methods"]:
                    self._make_port(
                        fi,
                        "http_route",
                        f"http:{fi.module.container}:{method} {full}",
                        f"{method} {full}",
                        {"method": method, "path": full, "framework": decl["framework"]},
                    )
        for ep in self.event_ports:
            h = self.graph.nodes[ep["handler"]]
            self._make_port(
                None,
                "event_consumer",
                f"event:{self.modules[ep['module']].container}:{h.qualified_name}",
                h.name,
                {"framework": ep["framework"], "source": ep["source"]},
                handler=ep["handler"],
                container=self.modules[ep["module"]].container,
            )
        facts.entry_ports = sorted(self.ports)

    # =========================================================================================
    # pass 6: risks, behavior emission, events
    # =========================================================================================

    def _transitive(self) -> dict[str, set[str]]:
        reach = {k: set(v) for k, v in self.fn_direct.items()}
        for k in self.fn_callees:
            reach.setdefault(k, set())
        changed = True
        while changed:
            changed = False
            for fid in sorted(reach):
                acc = reach[fid]
                before = len(acc)
                for c in sorted(self.fn_callees.get(fid, ())):
                    acc |= reach.get(c, set())
                if len(acc) != before:
                    changed = True
        return reach

    def _finalize_behaviors(self, facts: CodeFacts) -> None:
        reach = self._transitive()
        for c in self.candidates:
            for callee in c.callees:
                c.kinds |= reach.get(callee, set())
        for fid, cands in self.fn_candidates.items():
            for c in cands:
                c.kinds |= reach.get(fid, set())

        def loopish_io(c: Candidate) -> bool:
            return c.kind == "loop" and bool(c.kinds & (IO_KINDS | {"llm_endpoint"}))

        def has_nested_io(c: Candidate) -> bool:
            return any(
                loopish_io(ch) or has_nested_io(ch)
                for ch in c.children
                if ch.kind in ("loop", "fan_out", "transaction", "retry")
            )

        for c in self.candidates:
            risk: set[str] = set()
            if c.kind == "loop":
                if c.kinds & IO_KINDS:
                    risk.add("io_in_loop")
                if "llm_endpoint" in c.kinds:
                    risk.add("llm_in_loop")
                if (c.kinds & (IO_KINDS | {"llm_endpoint"})) and has_nested_io(c):
                    risk.add("nested_loop_io")
            elif c.kind == "retry":
                if not c.attrs.get("bounded", True):
                    risk.add("unbounded_retry")
            elif c.kind == "fan_out":
                if c.attrs.get("over_collection"):
                    risk.add("fan_out")
            elif c.kind == "transaction":
                if c.kinds & SLOW_TX_KINDS:
                    risk.add("slow_io_in_transaction")
            elif c.kind == "llm_call":
                p = c.parent
                while p is not None:
                    if p.kind == "loop":
                        risk.add("llm_in_loop")
                        break
                    p = p.parent
            c.risk = sorted(risk)

        emit_all = self.config.behavior_emit_all
        for c in self.candidates:  # candidates are created parents-first
            if not (c.risk or emit_all):
                continue
            parent_id = c.scope_id
            p = c.parent
            while p is not None:
                if p.node_id is not None:
                    parent_id = p.node_id
                    break
                p = p.parent
            attrs = {**c.attrs, "risk": c.risk, "touches": sorted(c.kinds)}
            node = self.graph.add_node(
                ir.Node(
                    "code",
                    c.kind,
                    c.qname.rsplit("@", 1)[-1],
                    c.qname,
                    parent_id=parent_id,
                    path=c.path,
                    span_start_line=c.start,
                    span_end_line=c.end,
                    content_hash=ids.content_hash(c.text),
                    attrs=attrs,
                )
            )
            c.node_id = node.id

        for fid, cands in sorted(self.fn_candidates.items()):
            wrapped = [c.node_id for c in cands if c.node_id is not None]
            if wrapped:
                facts.wrappers[fid] = wrapped
        for src, evs in sorted(self.raw_events.items()):
            out = []
            for e in evs:
                behaviors = tuple(c.node_id for c in e.stack if c.node_id is not None)
                out.append(Event(e.kind, e.targets, behaviors, e.line))
            facts.events[src] = out
