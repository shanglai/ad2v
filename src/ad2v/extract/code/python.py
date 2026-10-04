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
import time
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
from ad2v.extract.code.python_local import (
    LOCAL_EXTRACTOR_VERSION,
    body_hash,
    find_node,
    import_ops,
    local_facts,
)
from ad2v.extract.files import SourceFile
from ad2v.manifest import Config
from ad2v.resources import python_rules_path

PY_LANGUAGE = Language(tsp.language())

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
    exact: bool = True  # False: `literal` is only the known prefix (an f-string with a non-constant part)


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
    nodes: dict[str, TSNode] = field(default_factory=dict)  # local name -> list/tuple literal node


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


def _is_main_guard(cond: TSNode) -> bool:
    """`__name__ == "__main__"` (either order, either quote style)."""
    if cond.type != "comparison_operator":
        return False
    parts = [c for c in cond.named_children]
    if len(parts) != 2:
        return False
    texts = {
        _text(parts[0]).strip(),
        (_string_value(parts[1]) or "") if parts[1].type == "string" else _text(parts[1]),
    }
    texts |= {(_string_value(parts[0]) or "") if parts[0].type == "string" else _text(parts[0])}
    return "__name__" in texts and "__main__" in texts and "==" in _text(cond)


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
        # P6.1: imperative registration and route lists (rules-driven, covered by rules_hash)
        self.http_add_routes = {r["method"]: r for r in http.get("add_route_methods", [])}
        self.http_route_lists = set(http.get("route_list_constructors", []))
        self.http_route_ctors = set(http.get("route_constructors", []))
        self.http_mount_ctors = set(http.get("mount_constructors", []))
        self.http_mount_methods = {r["method"]: r for r in http.get("mount_methods", [])}
        mcp = ports.get("mcp", {})
        self.mcp_ctors = set(mcp.get("server_constructors", []))
        self.mcp_decos = set(mcp.get("tool_decorators", ["tool"]))
        cli = ports.get("cli", {})
        self.typer_ctors = set(cli.get("typer_constructors", []))
        self.typer_decos = set(cli.get("typer_decorators", ["command"]))
        self.click_decos = set(cli.get("click_decorators", []))
        self.click_group_decos = set(cli.get("click_group_decorators", []))
        self.event_rules = ports.get("events", [])
        ep = ports.get("entry_points", {})
        self.main_block = bool(ep.get("main_block", False))
        cel = ep.get("celery", {})
        self.celery_ctors = set(cel.get("app_constructors", []))
        self.celery_task_decos = set(cel.get("task_decorators", []))
        self.celery_task_methods = set(cel.get("app_task_methods", []))
        self.celery_beat_names = set(cel.get("beat_schedule_names", []))
        aps = ep.get("apscheduler", {})
        self.aps_ctors = set(aps.get("scheduler_constructors", []))
        self.aps_add = set(aps.get("add_job_methods", []))
        self.aps_decos = set(aps.get("decorator_methods", []))
        sch = ep.get("schedule", {})
        self.schedule_every = set(sch.get("every_callables", []))
        self.schedule_do = set(sch.get("do_methods", []))

        # state
        self.graph: ir.Graph
        self.layout: Layout
        self.modules: dict[str, ModuleInfo] = {}
        self.index: dict[str, list[str]] = {}
        self.funcs: dict[str, FuncInfo] = {}
        self.origin_objs: dict[tuple[str, str], Obj] = {}  # router/app identity -> object (its own prefix)
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
        self.call_sites: dict[str, list[tuple[int, int, int, str]]] = {}  # fn id -> (row, col0, col1, callee)
        self.click_group_info: dict[str, tuple[str, str | None]] = {}  # group id -> (name, parent group id)
        self.ports: set[tuple[str, str]] = set()  # (port id, handler id)
        self.entry_decls: list[dict[str, Any]] = []  # non-framework entry points (ADR-0021)
        self.cache_hits = 0
        self.timings = {"parse": 0.0, "local_facts": 0.0, "apply_local": 0.0, "global_walk": 0.0}
        self.cache_misses = 0
        self.new_cache_entries: dict[str, tuple[str, dict[str, Any]]] = {}  # path -> (hash, local facts)

    # =========================================================================================
    # entry point
    # =========================================================================================

    def extract(
        self,
        graph: ir.Graph,
        layout: Layout,
        files: list[SourceFile],
        cache: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> CodeFacts:
        """Extract `files`. `cache` maps (path, content_hash) -> local facts (python_local)."""
        self.graph, self.layout = graph, layout
        facts = CodeFacts()
        cache = cache or {}
        local: dict[str, dict[str, Any]] = {}
        clock = time.perf_counter
        for f in files:
            facts.files_read[f.path] = f.content_hash
            t0 = clock()
            tree = self.parser.parse(f.text.encode("utf-8"))
            t1 = clock()
            self.timings["parse"] += t1 - t0
            lf = cache.get((f.path, f.content_hash))
            if lf is not None and lf.get("v") == LOCAL_EXTRACTOR_VERSION:
                self.cache_hits += 1
            else:
                lf = local_facts(f.path, f.text, tree.root_node)
                self.new_cache_entries[f.path] = (f.content_hash, lf)
                self.cache_misses += 1
            self.timings["local_facts"] += clock() - t1
            local[f.path] = lf
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
                    span_end_line=lf["end_line"],
                    content_hash=f.content_hash,
                    attrs={"language": "python"},
                )
            )
            self.modules[f.path] = ModuleInfo(f.path, f.text, tree, node, container.name)
        t0 = clock()
        self._build_index()
        for m in self._sorted_modules():
            self._apply_defs(m, local[m.path])
        for m in self._sorted_modules():
            self._apply_imports(m, local[m.path])
        for m in self._sorted_modules():
            self._apply_refs(m, local[m.path])
        t1 = clock()
        self.timings["apply_local"] += t1 - t0
        for m in self._sorted_modules():
            self._walk_module(m)
        for m in self._sorted_modules():
            for fi in m.functions:
                self._walk_function(fi)
        self._resolve_click_groups()
        for m in self._sorted_modules():
            for fi in m.functions:
                self._ports_from_decorators(fi)
        self._finalize_call_sites()
        self._finalize_behaviors(facts)
        self._finalize_ports(facts)
        self.timings["global_walk"] += clock() - t1
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

    def _finalize_call_sites(self) -> None:
        """`call_masked_hash` + `call_sites` per function (ADR-0026).

        The body hash with the defined name *and* every resolved repo callee name masked, plus the
        callee ids in source order. Two versions of a function whose texts differ only in callee
        names are the same code when their callee ids agree after lineage mapping.
        """
        for fid, sites in sorted(self.call_sites.items()):
            node = self.graph.nodes.get(fid)
            fi = self.funcs.get(fid)
            if node is None or fi is None or node.span_start_line is None:
                continue
            start = node.span_start_line - 1
            lines = [ln.encode("utf-8") for ln in fi.module.text.split("\n")[start : node.span_end_line]]
            ordered = sorted(sites)
            for row, c0, c1, _t in sorted(ordered, key=lambda s: (s[0], -s[1])):
                i = row - start
                if 0 <= i < len(lines):
                    lines[i] = lines[i][:c0] + b"\x01" + lines[i][c1:]
            text = b"\n".join(lines).decode("utf-8", "replace")
            node.attrs["call_masked_hash"] = body_hash(text, "def", node.name)
            node.attrs["call_sites"] = [t for *_pos, t in ordered]

    def _span_text(self, m: ModuleInfo, start: int, end: int) -> str:
        lines = m.text.split("\n")
        return "\n".join(lines[start - 1 : end])

    def _apply_defs(self, m: ModuleInfo, lf: dict[str, Any]) -> None:
        """Create class/function nodes and structure records from local facts (cached or fresh)."""
        root = m.tree.root_node
        for d in lf["defs"]:
            pkind, pq = d["parent"]
            parent_id = m.node.id if pkind == "module" else ids.node_id("code", pkind, pq)
            kind = "function" if d["k"] == "f" else "class"
            start, end = d["span"]
            node = self.graph.add_node(
                ir.Node(
                    "code",
                    kind,
                    d["name"],
                    d["qname"],
                    parent_id=parent_id,
                    path=m.path,
                    span_start_line=start,
                    span_end_line=end,
                    content_hash=d["hash"],
                    attrs=dict(d["attrs"]),
                )
            )
            ts_type = "function_definition" if kind == "function" else "class_definition"
            ts = find_node(root, d["ts"], ts_type)
            outer = find_node(root, d["outer"], d["outer_type"])
            parent_func = self.funcs.get(ids.node_id("code", "function", d["pfunc"])) if d["pfunc"] else None
            if kind == "function":
                class_info = self.classes.get(d["class"]) if d["class"] else None
                decorators = [find_node(root, r, "decorator") for r in d["decos"]]
                fi = FuncInfo(
                    node,
                    ts,
                    outer,
                    m,
                    class_info.node.qualified_name if class_info else None,
                    parent_func,
                    decorators,
                )
                if node.id not in self.funcs:  # duplicate definition (e.g. if/else): first wins
                    self.funcs[node.id] = fi
                    m.functions.append(fi)
                if class_info is not None:
                    class_info.methods.setdefault(d["name"], node.id)
            else:
                if d["qname"] not in self.classes:
                    bases = [find_node(root, [b[0], b[1]], b[2]) for b in d["bases"]]
                    self.classes[d["qname"]] = ClassInfo(node, ts, m, bases=bases)
            if d["top"]:
                m.top_defs.setdefault(d["name"], node.id)
            if parent_func is not None:
                parent_func.local_defs.setdefault(d["name"], node.id)

    # -- imports and module-level assignments --------------------------------------------------

    def _apply_imports(self, m: ModuleInfo, lf: dict[str, Any]) -> None:
        root = m.tree.root_node
        for op in lf["ops"]:
            kind = op[0]
            if kind == "imp_root":
                _, first, fq, line = op
                m.raw_bindings.setdefault(first, ("import", first))
                self._add_import_edge(m, self.resolve_fq(fq, m), line)
            elif kind == "imp_alias":
                _, alias, fq, line = op
                m.raw_bindings[alias] = ("import", fq)
                self._add_import_edge(m, self.resolve_fq(fq, m), line)
            elif kind == "from_abs":
                _, alias, dotted, name, line = op
                m.raw_bindings[alias] = ("import", f"{dotted}.{name}")
                self._add_import_edge(m, self.resolve_fq(f"{dotted}.{name}", m), line)
            elif kind == "from_rel":
                _, alias, base, dotted, name, line = op
                v = self._relative(base, dotted, name)
                m.raw_bindings[alias] = ("value", v)
                self._add_import_edge(m, v, line)
            elif kind == "assign":
                _, name, rng, type_ = op
                m.raw_bindings[name] = ("expr", find_node(root, rng, type_))

    def _local_import(self, n: TSNode, ctx: Ctx) -> None:
        """An import inside a function binds in the function's scope and shadows module names."""
        m = ctx.module
        for op in import_ops(n, m.path):
            kind = op[0]
            if kind == "imp_root":
                name, v = op[1], self.resolve_fq(op[1], m)
            elif kind == "imp_alias":
                name, v = op[1], self.resolve_fq(op[2], m)
            elif kind == "from_abs":
                name, v = op[1], self.resolve_fq(f"{op[2]}.{op[3]}", m)
            else:  # from_rel
                name, v = op[1], self._relative(op[2], op[3], op[4])
            if isinstance(v, RepoSym) and v.attrs:
                v = self.lookup(v)
            ctx.local[name] = v

    def _add_import_edge(self, m: ModuleInfo, v: Value, line: int) -> None:
        if isinstance(v, RepoSym) and v.module != m.path:
            self.graph.add_edge(m.node.id, self.modules[v.module].node.id, "imports", lines=[line])

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
                    self.origin_objs[v.origin] = v
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
            s, exact = self._fold_str(n, ctx)
            if exact:
                return Const(literal=s)
            s = _string_value(n)
            return Const(literal=s, exact=False) if s is not None else None
        if t == "subscript":
            base = self.eval(n.child_by_field_name("value"), ctx)
            sub = n.child_by_field_name("subscript")
            if isinstance(base, ExtSym) and base.fq == "os.environ" and sub is not None:
                s = _string_value(sub)
                return Const(env=s) if s else None
            return None
        if t == "call":
            return self._eval_call(n, ctx)
        if t == "binary_operator":  # "a" + B: string concatenation (P6.1)
            s, exact = self._fold_str(n, ctx)
            if s is not None:
                return Const(literal=s, exact=exact)
            return None
        if t == "as_pattern":
            return self.eval(n.named_children[0] if n.named_children else None, ctx)
        return None

    def _fold_str(self, n: TSNode | None, ctx: Ctx, depth: int = 0) -> tuple[str | None, bool]:
        """Constant-fold a string expression (P6.1): (value, exact). Literals, f-strings whose parts
        are constants, `+` concatenation, and names bound to such values (module constants, simple
        locals). Not exact: the value is the known prefix up to the first non-constant part."""
        if n is None or depth > 8:
            return None, False
        n = _unwrap(n)
        t = n.type
        if t == "string":
            out: list[str] = []
            for c in n.named_children:
                if c.type == "string_content":
                    out.append(_text(c))
                elif c.type == "interpolation":
                    kids = c.named_children
                    if not kids or any(k.type in ("format_specifier", "type_conversion") for k in kids):
                        return "".join(out), False
                    v, ok = self._fold_str(kids[0], ctx, depth + 1)
                    if not ok:
                        return "".join(out) + (v or ""), False
                    out.append(v or "")
            return "".join(out), True
        if t == "concatenated_string" or (
            t == "binary_operator" and _text(n.child_by_field_name("operator") or n) == "+"
        ):
            parts = (
                n.named_children
                if t == "concatenated_string"
                else [
                    n.child_by_field_name("left"),
                    n.child_by_field_name("right"),
                ]
            )
            acc = ""
            for p in parts:
                v, ok = self._fold_str(p, ctx, depth + 1)
                if not ok:
                    return acc + (v or ""), False
                acc += v or ""
            return acc, True
        if t in ("identifier", "attribute"):
            v = self.eval(n, ctx)
            if isinstance(v, Const) and v.literal is not None and v.env is None:
                return v.literal, v.exact
        return None, False

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
                    s, exact = self._fold_str(kw[k], ctx)
                    if s is not None or not exact:
                        meta["prefix"] = s or ""
                        if not exact:
                            meta["prefix_exact"] = False
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

    def _apply_refs(self, m: ModuleInfo, lf: dict[str, Any]) -> None:
        kinds = {"m": "module", "f": "function", "c": "class"}
        for k, q, found, source in lf["refs"]:
            nid = m.node.id if k == "m" else ids.node_id("code", kinds[k], q)
            self._add_refs(nid, [r for r, _ in found], source, {r: fp for r, fp in found if fp})
        # test names (config-dependent, so applied here rather than cached)
        prefixes = "|".join(re.escape(p.lower()) for p in self.config.test_ref_prefixes)
        if prefixes:
            # `test_req_001_x` -> REQ-001; `test_payments_fr_001_x` -> FR-001 with the namespace hint
            # `payments` (spec-kit features, ADR-0048)
            pat = re.compile(rf"(?:^|_)(?:([a-z0-9_]+?)_)?({prefixes})_([0-9]+)(?=_|$)", re.IGNORECASE)
            for fi in m.functions:
                if fi.node.attrs.get("is_test"):
                    found = pat.findall(fi.node.name)
                    refs = [f"{p.upper()}-{d}" for _, p, d in found]
                    if refs:
                        self._add_refs(fi.node.id, refs, "test_name")
                        hints = {
                            f"{p.upper()}-{d}": h
                            for ns, p, d in found
                            if (h := re.sub(r"^test_?", "", ns.lower())) and h != "test"
                        }
                        if hints:
                            fi.node.attrs.setdefault("spec_ref_hints", {}).update(hints)

    def _add_refs(
        self, nid: str, refs: list[str], source: str, fingerprints: dict[str, str] | None = None
    ) -> None:
        node = self.graph.nodes[nid]
        node.spec_ref = sorted(set(node.spec_ref) | set(refs))
        srcs = node.attrs.setdefault("spec_ref_sources", {})
        for r in refs:
            srcs[r] = sorted(set(srcs.get(r, [])) | {source})
        if fingerprints:  # `# ad2v: REQ-012@1a2b3c4d` re-annotation (format spec §6.6)
            fps = node.attrs.setdefault("spec_ref_fingerprints", {})
            fps.update(fingerprints)

    # =========================================================================================
    # pass 4: bodies
    # =========================================================================================

    def _walk_module(self, m: ModuleInfo) -> None:
        ctx = Ctx(m.node.id, m.path, m, None, None, {})
        self._walk_block(m.tree.root_node, ctx)
        if self.main_block:
            for stmt in m.tree.root_node.named_children:
                cond = stmt.child_by_field_name("condition") if stmt.type == "if_statement" else None
                if cond is not None and _is_main_guard(cond):
                    self.entry_decls.append(
                        {
                            "kind": "cli_command",
                            "trigger": "main",
                            "handler": m.node.id,
                            "module": m.path,
                            "qname": f"cli:{m.container}:__main__:{m.path}",
                            "name": f"__main__ ({m.path})",
                            "attrs": {"command": "__main__", "framework": "python"},
                            "span": [_line(stmt), _end_line(stmt)],
                        }
                    )
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
            attrs={**attrs, "header": head},
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
        if t in ("import_statement", "import_from_statement"):
            if ctx.func is not None:  # module-level imports are bound by the local facts
                self._local_import(n, ctx)
            return
        if t == "assignment":
            right = n.child_by_field_name("right")
            if right is not None:
                self._walk(right, ctx)
            left = n.child_by_field_name("left")
            if left is not None and right is not None and _unwrap(right).type == "dictionary":
                target = dotted_text(left) or ""
                if target.rsplit(".", 1)[-1] in self.celery_beat_names:
                    self._beat_schedule(_unwrap(right), ctx)
            is_module_scope = ctx.func is None and ctx.class_qname is None  # module_value() owns these
            if left is not None and left.type == "identifier" and right is not None and not is_module_scope:
                self._bind_local(ctx, _text(left), right)
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
                    self._bind_local(ctx, _text(ident), expr)
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

    def _bind_local(self, ctx: Ctx, name: str, value: TSNode) -> None:
        """A local assignment. App/router objects built inside a function (factories) get an
        identity, so include_router / register_blueprint chains can mount them (P6.1)."""
        v = self.eval(value, ctx)
        if isinstance(v, Obj) and v.origin is None and v.ctor in self.http_ctors:
            v.origin = (ctx.module.path, f"{ctx.scope_qname}:{name}")
            self.origin_objs[v.origin] = v
        ctx.local[name] = v
        u = _unwrap(value)
        if u.type in ("list", "tuple"):
            ctx.nodes[name] = u

    def _handle_call(self, call: TSNode, ctx: Ctx) -> None:
        fn_node = call.child_by_field_name("function")
        callee = self.eval(fn_node, ctx)
        pos, kw, raw = _call_args(call)
        if (
            fn_node is not None
            and fn_node.type == "attribute"
            and _text(fn_node.child_by_field_name("attribute")) in self.schedule_do
            and pos
            and self._chain_calls(fn_node.child_by_field_name("object"), self.schedule_every, ctx)
        ):
            self._scheduled_entry(pos[0], "schedule", "schedule", call, ctx)
        args_done = False
        target = self._callable_target(callee)
        if target is not None:
            self._emit_call(target, call, ctx)
            if ctx.func is not None and fn_node is not None:
                tok = fn_node.child_by_field_name("attribute") if fn_node.type == "attribute" else fn_node
                if tok is not None and tok.type == "identifier":
                    self.call_sites.setdefault(ctx.func.node.id, []).append(
                        (tok.start_point[0], tok.start_point[1], tok.end_point[1], target)
                    )
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
        if fq in self.http_route_lists and "routes" in kw:
            self._route_list(kw["routes"], "", True, ctx, fq.split(".")[0])
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
                prefix, exact = "", True
                for k in self.http_prefix_kw:
                    if k in kw:
                        s, exact = self._fold_str(kw[k], ctx)
                        prefix = s or ""
                self.mounts.setdefault(inner.origin, []).append((obj.origin, prefix, exact))
        if method in self.http_mount_methods and obj.ctor in self.http_ctors:
            # Starlette sub-application mount: app.mount("/api/v1", app=api) (P6.1)
            r = self.http_mount_methods[method]
            path_node = (
                kw.get(r["path"][1])
                if r["path"][1] in kw
                else (pos[r["path"][0]] if len(pos) > r["path"][0] else None)
            )
            app_node = (
                kw.get(r["app"][1])
                if r["app"][1] in kw
                else (pos[r["app"][0]] if len(pos) > r["app"][0] else None)
            )
            inner = self.eval(app_node, ctx) if app_node is not None else None
            if (
                isinstance(inner, Obj)
                and inner.origin is not None
                and inner.ctor in self.http_ctors
                and path_node is not None
            ):
                prefix, exact = self._fold_str(path_node, ctx)
                self.mounts.setdefault(inner.origin, []).append((obj.origin, prefix or "", exact))
        if method in self.http_add_routes and obj.ctor in self.http_ctors:
            self._imperative_route(obj, self.http_add_routes[method], pos, kw, ctx)
        if obj.ctor in self.aps_ctors and method in self.aps_add:
            fn_ref = kw.get("func") or (pos[0] if pos else None)
            if fn_ref is not None:
                self._scheduled_entry(fn_ref, "apscheduler", "apscheduler", call, ctx)
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
        # a nested route function (inside an app factory) resolves `app` in its parent's scope
        mctx = Ctx(
            fi.module.node.id,
            fi.module.path,
            fi.module,
            fi.parent_func,
            fi.class_qname,
            {},
            parent_scope=fi.parent_func.scope if fi.parent_func else None,
        )
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
                    path_node = pos[0] if pos else kw.get("path") or kw.get("rule")
                    if path_node is None:
                        continue
                    path, path_exact = self._fold_str(path_node, mctx)
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
                            "path": path or "",
                            "path_exact": path_exact,
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
                elif obj.ctor in self.celery_ctors and meth in self.celery_task_methods:
                    self._event_entry(fi.node.id, "celery_task", "celery", {})
                elif obj.ctor in self.aps_ctors and meth in self.aps_decos:
                    self._event_entry(fi.node.id, "apscheduler", "apscheduler", {})
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
            elif isinstance(v, ExtSym) and v.fq in self.celery_task_decos:
                self._event_entry(fi.node.id, "celery_task", "celery", {})
            elif isinstance(v, ExtSym) and v.fq in self.click_decos:
                name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                cmd = name or fi.node.name.replace("_", "-")
                self._make_port(
                    fi,
                    "cli_command",
                    f"cli:{fi.module.container}:{cmd}",
                    cmd,
                    {"command": cmd, "framework": "click", "trigger": "click"},
                )
            if callee_node is not None and callee_node.type == "attribute":
                base = self.eval(callee_node.child_by_field_name("object"), mctx)
                meth = _text(callee_node.child_by_field_name("attribute"))
                gid = self._callable_target(base)
                if gid is not None and gid in self.click_groups and meth in self.click_group_decos:
                    name = _string_value(_unwrap(kw["name"])) if "name" in kw else first
                    cmd = " ".join([*self._click_group_path(gid), name or fi.node.name.replace("_", "-")])
                    self._make_port(
                        fi,
                        "cli_command",
                        f"cli:{fi.module.container}:{cmd}",
                        cmd,
                        {
                            "command": cmd,
                            "framework": "click",
                            "group": self.graph.nodes[gid].qualified_name,
                            "trigger": "click",
                        },
                    )

    def _click_group_path(self, gid: str) -> list[str]:
        """Names of the nested groups above a command, excluding the root group (the program itself)."""
        path: list[str] = []
        seen = set()
        while gid in self.click_group_info and gid not in seen:
            seen.add(gid)
            name, parent = self.click_group_info[gid]
            if parent is None:
                break
            path.insert(0, name)
            gid = parent
        return path

    def _chain_calls(self, n: TSNode | None, fqs: set[str], ctx: Ctx) -> bool:
        """Does an attribute/call chain (`schedule.every(5).minutes`) contain a call to one of `fqs`?"""
        while n is not None and n.type in ("attribute", "call"):
            if n.type == "call":
                v = self.eval(n.child_by_field_name("function"), ctx)
                if isinstance(v, ExtSym) and v.fq in fqs:
                    return True
                n = n.child_by_field_name("function")
            else:
                n = n.child_by_field_name("object")
        return False

    def _scheduled_entry(self, fn_ref: TSNode, trigger: str, framework: str, at: TSNode, ctx: Ctx) -> None:
        handler = self._callable_target(self.eval(fn_ref, ctx))
        if handler is None:
            return
        self._event_entry(handler, trigger, framework, {"line": _line(at)})

    def _event_entry(self, handler: str, trigger: str, framework: str, extra: dict[str, Any]) -> None:
        h = self.graph.nodes[handler]
        m = self.modules.get(h.path, None)
        if m is None:
            return
        self.entry_decls.append(
            {
                "kind": "event_consumer",
                "trigger": trigger,
                "handler": handler,
                "module": m.path,
                "qname": f"event:{m.container}:{trigger}:{h.qualified_name}",
                "name": h.name,
                "attrs": {"framework": framework, **{k: v for k, v in extra.items() if k != "line"}},
                "span": None,
            }
        )

    def _beat_schedule(self, d: TSNode, ctx: Ctx) -> None:
        """Celery beat: {"name": {"task": "pkg.mod.fn", ...}} -> an entry per resolvable task."""
        for pair in d.named_children:
            if pair.type != "pair":
                continue
            key, value = pair.child_by_field_name("key"), pair.child_by_field_name("value")
            if value is None or _unwrap(value).type != "dictionary":
                continue
            for inner in _unwrap(value).named_children:
                if inner.type != "pair":
                    continue
                ik, iv = inner.child_by_field_name("key"), inner.child_by_field_name("value")
                if ik is None or iv is None or _string_value(_unwrap(ik)) != "task":
                    continue
                task = _string_value(_unwrap(iv))
                target = self._callable_target(self.resolve_fq(task, ctx.module)) if task else None
                if target is not None:
                    name = _string_value(_unwrap(key)) if key is not None else None
                    self._event_entry(target, "celery_beat", "celery", {"schedule_name": name})

    def _resolve_click_groups(self) -> None:
        """Click groups, including nested ones (`@cli.group()` under `@click.group()`): a fixpoint."""
        changed = True
        while changed:
            changed = False
            for m in self._sorted_modules():
                mctx = Ctx(m.node.id, m.path, m, None, None, {})
                for fi in m.functions:
                    if fi.node.id in self.click_groups:
                        continue
                    for d in fi.decorators:
                        expr = d.named_children[0] if d.named_children else None
                        if expr is None:
                            continue
                        callee = expr.child_by_field_name("function") if expr.type == "call" else expr
                        v = self.eval(callee, mctx)
                        is_group = (
                            isinstance(v, ExtSym) and v.fq in self.click_decos and v.fq.endswith(".group")
                        )
                        parent = None
                        if not is_group and callee is not None and callee.type == "attribute":
                            base = self._callable_target(
                                self.eval(callee.child_by_field_name("object"), mctx)
                            )
                            meth = _text(callee.child_by_field_name("attribute"))
                            is_group = base in self.click_groups and meth == "group"
                            parent = base if is_group else None
                        if is_group:
                            self.click_groups.add(fi.node.id)
                            name = None
                            if expr.type == "call":
                                pos, kw, _ = _call_args(expr)
                                name = (
                                    _string_value(_unwrap(kw["name"] if "name" in kw else pos[0]))
                                    if ("name" in kw or pos)
                                    else None
                                )
                            self.click_group_info[fi.node.id] = (
                                name or fi.node.name.replace("_", "-"),
                                parent,
                            )
                            changed = True
                            break

    def _make_port(
        self,
        fi: FuncInfo | None,
        kind: str,
        qname: str,
        name: str,
        attrs: dict[str, Any],
        handler: str | None = None,
        container: str | None = None,
        span: list[int] | None = None,
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
                span_start_line=span[0] if span else hnode.span_start_line,
                span_end_line=span[1] if span else hnode.span_start_line,
                attrs=attrs,
                content_hash=ids.attrs_hash(kind, name, attrs),
            )
        )
        self.graph.add_edge(cont.id, port.id, "exposes")
        self.graph.add_edge(port.id, hid, "calls")
        self.ports.add((port.id, hid))

    @staticmethod
    def _extend(tail: str | None, piece: str, exact: bool) -> str | None:
        """The known tail after the last unresolved piece; None while everything is exact."""
        if not exact:
            return ""
        return None if tail is None else join_route(tail, piece)

    def _prefixes(
        self, origin: tuple[str, str] | None, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> list[tuple[str, str | None]]:
        """All mount prefixes for a router object (include_router / register_blueprint / mount
        chains): (full prefix, known tail after the last unresolved piece, or None if exact)."""
        if origin is None or origin in seen or origin not in self.mounts:
            return [("", None)]
        out = []
        for parent, prefix, exact in sorted(
            self.mounts[origin], key=lambda x: (x[0] or ("", ""), x[1], x[2])
        ):
            # the parent router's own prefix applies too:
            # APIRouter(prefix="/a").include_router(r, prefix="/b")
            pobj = self.origin_objs.get(parent) if parent is not None else None
            pown = pobj.meta.get("prefix", "") if pobj is not None else ""
            pown_exact = pobj.meta.get("prefix_exact", True) if pobj is not None else True
            for pp, ptail in self._prefixes(parent, seen | {origin}):
                full = join_route(pp, pown, prefix) if pp or pown or prefix else ""
                tail = self._extend(self._extend(ptail, pown, pown_exact), prefix, exact)
                out.append((full, tail))
        return sorted(set(out), key=lambda x: (x[0], x[1] is None, x[1] or ""))

    def _route_target(self, node: TSNode | None, ctx: Ctx) -> FuncInfo | None:
        target = self._callable_target(self.eval(node, ctx)) if node is not None else None
        return self.funcs.get(target) if target is not None else None

    @staticmethod
    def _methods(node: TSNode | None, default: list[str]) -> list[str]:
        u = _unwrap(node) if node is not None else None
        if u is not None and u.type in ("list", "tuple", "set"):
            got = sorted({(_string_value(x) or "").upper() for x in u.named_children if _string_value(x)})
            return got or list(default)
        return list(default)

    def _imperative_route(
        self, obj: Obj, rule: dict[str, Any], pos: list[TSNode], kw: dict[str, TSNode], ctx: Ctx
    ) -> None:
        """`app.add_api_route(path, endpoint, methods=[…])`, Flask `add_url_rule`, Starlette
        `add_route`: the argument positions and keywords come from the rules."""

        def arg(spec: list[Any]) -> TSNode | None:
            idx, name = spec
            return kw.get(name) if name in kw else (pos[idx] if len(pos) > idx else None)

        path_node, ep_node = arg(rule["path"]), arg(rule["endpoint"])
        fi = self._route_target(ep_node, ctx)
        if path_node is None or fi is None:
            return
        path, exact = self._fold_str(path_node, ctx)
        self.route_decls.append(
            {
                "fi": fi,
                "obj": obj,
                "path": path or "",
                "path_exact": exact,
                "methods": self._methods(
                    kw.get(rule.get("methods_kw", "methods")), rule.get("default_methods", ["GET"])
                ),
                "framework": obj.ctor.split(".")[0],
                "registration": rule["method"],
            }
        )

    def _route_list(
        self, node: TSNode, prefix: str, exact: bool, ctx: Ctx, framework: str, depth: int = 0
    ) -> None:
        """Starlette-style `routes=[Route(path, endpoint, methods=…), Mount(prefix, routes=[…])]`."""
        if depth > 6:
            return
        n = _unwrap(node)
        if n.type == "identifier":
            name = _text(n)
            found = ctx.nodes.get(name)
            if found is None:
                raw = ctx.module.raw_bindings.get(name)
                found = raw[1] if raw is not None and raw[0] == "expr" else None
            if found is None:
                return
            n = _unwrap(found)
        if n.type not in ("list", "tuple"):
            return
        for el in n.named_children:
            el = _unwrap(el)
            if el.type != "call":
                continue
            cv = self.eval(el.child_by_field_name("function"), ctx)
            if not isinstance(cv, ExtSym):
                continue
            p, k, _ = _call_args(el)
            if cv.fq in self.http_route_ctors:
                fi = self._route_target(k.get("endpoint") or (p[1] if len(p) > 1 else None), ctx)
                path_node = k.get("path") or (p[0] if p else None)
                if fi is None or path_node is None:
                    continue
                path, ok = self._fold_str(path_node, ctx)
                self.route_decls.append(
                    {
                        "fi": fi,
                        "obj": None,
                        "path": join_route(prefix, path or ""),
                        "path_exact": exact and ok,
                        "methods": self._methods(k.get("methods"), ["GET"]),
                        "framework": framework,
                        "registration": "route_list",
                    }
                )
            elif cv.fq in self.http_mount_ctors:
                mp_node = k.get("path") or (p[0] if p else None)
                sub = k.get("routes") or (p[1] if len(p) > 1 else None)
                if sub is None:
                    continue
                mp, ok = self._fold_str(mp_node, ctx) if mp_node is not None else ("", True)
                self._route_list(sub, join_route(prefix, mp or ""), exact and ok, ctx, framework, depth + 1)

    def _finalize_ports(self, facts: CodeFacts) -> None:
        for decl in self.route_decls:
            fi: FuncInfo = decl["fi"]
            obj: Obj | None = decl["obj"]
            own = obj.meta.get("prefix", "") if obj is not None else ""
            own_exact = obj.meta.get("prefix_exact", True) if obj is not None else True
            mounts = self._prefixes(obj.origin) if obj is not None else [("", None)]
            for mount, mount_tail in mounts:
                full = join_route(mount, own, decl["path"])
                tail = self._extend(
                    self._extend(mount_tail, own, own_exact), decl["path"], decl.get("path_exact", True)
                )
                exact = tail is None
                for method in decl["methods"]:
                    attrs: dict[str, Any] = {"method": method, "path": full, "framework": decl["framework"]}
                    if "registration" in decl:
                        attrs["registration"] = decl["registration"]
                    if not exact:
                        # P6.1: emitted anyway, with the literal parts kept; pairing offers it as a
                        # needs_review candidate, never a false `missing` (ADR-0046)
                        attrs["path_unresolved"] = True
                        attrs["path_tail"] = tail
                    self._make_port(
                        fi,
                        "http_route",
                        f"http:{fi.module.container}:{method} {full}",
                        f"{method} {full}",
                        attrs,
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
        for e in sorted(self.entry_decls, key=lambda x: (x["qname"], x["handler"])):
            attrs = {**e["attrs"], "trigger": e["trigger"]}
            self._make_port(
                None,
                e["kind"],
                e["qname"],
                e["name"],
                attrs,
                handler=e["handler"],
                container=self.modules[e["module"]].container,
                span=e["span"],
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
