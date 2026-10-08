"""The infra model shared by the plan reader and the static reader (P10, ADR-0074..0076).

Both readers turn their input into the same three trees per resource, then into `Resource`s:

- `values`: known attribute values (plan `planned_values`; static: literals only);
- `exprs`: configuration expressions, leaves `{"references": [...]}` or `{"constant_value": …}`
  (plan `configuration`; static: python-hcl2 output normalized to that shape);
- `sensitive`: the plan's `sensitive_values` mirror (static: none).

Only what `infra.yaml` allowlists is kept, and never a value that could be a secret: env var
values are reduced to their source (reference / secret / literal / unknown), never stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids, ir

RULES_PATH = Path(__file__).with_name("infra.yaml")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
SAFE_ENV_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # infra environment names (prod, dev, ...)
MAX_STR = 200
ENV_SOURCES = ("reference", "secret", "literal", "unknown")
# references that are not resources (never followed, never stored)
NON_RESOURCE = ("each.", "count.", "path.", "self.", "terraform.", "data.")


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("version") == 1
    return data


def kind_of(rtype: str) -> str:
    t = rules()["types"].get(rtype)
    return t["kind"] if t else "infra_other"


@dataclass
class EnvVar:
    name: str
    source: str  # reference | secret | literal | unknown
    ref: str | None = None  # base address of the resource the value comes from, when known
    candidates: list[str] = field(default_factory=list)  # several possible resources: not decided

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"source": self.source}
        if self.ref:
            d["ref"] = self.ref
        if self.candidates:
            d["candidates"] = sorted(self.candidates)
        return d


@dataclass
class Resource:
    env: str
    address: str  # instance address: module.svc["api"].google_x.y[0]
    base: str  # configuration address: module.svc.google_x.y
    module: str  # module instance address ('' at the root)
    type: str
    name: str
    provider: str
    kind: str
    source: str  # plan | static
    attrs: dict[str, Any] = field(default_factory=dict)
    refs: set[str] = field(default_factory=set)  # base addresses of resources referenced
    env_vars: dict[str, EnvVar] = field(default_factory=dict)
    action: str | None = None
    env_from: str | None = None  # aws_ecs_service: the task definition's base address
    website_of: str | None = None


# -- trees ------------------------------------------------------------------------------------------
def walk(obj: Any, path: str) -> list[Any]:
    """Values at a dotted path; lists met on the way are walked element by element."""
    cur = [obj]
    for step in path.split(".") if path else []:
        nxt: list[Any] = []
        for c in cur:
            for item in c if isinstance(c, list) else [c]:
                if isinstance(item, dict) and step in item:
                    nxt.append(item[step])
        cur = nxt
    out: list[Any] = []
    for c in cur:
        out.extend(c if isinstance(c, list) else [c])
    return out


def sensitive_at(tree: Any, path: str) -> bool:
    """True when the plan marks the value at `path` (or anything above it) sensitive."""
    cur = [tree]
    for step in path.split("."):
        nxt = []
        for c in cur:
            if c is True:
                return True
            for item in c if isinstance(c, list) else [c]:
                if item is True:
                    return True
                if isinstance(item, dict) and step in item:
                    nxt.append(item[step])
        cur = nxt
    return any(c is True or (isinstance(c, list) and any(x is True for x in c)) for c in cur)


def scalar(v: Any) -> Any:
    """A storable scalar: bool / int / float / a short string. Anything else: None."""
    if isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v[:MAX_STR]
    return None


def image_repo(v: str) -> str:
    """`europe-docker.pkg.dev/p/r/backend:1.4@sha256:…` -> `europe-docker.pkg.dev/p/r/backend`; no
    credentials, tag or digest."""
    s = v.split("@", 1)[0]
    s = re.sub(r"^[a-z]+://", "", s)
    s = s.rsplit("/", 1)
    last = s[-1].split(":", 1)[0]
    head = s[0] + "/" if len(s) == 2 else ""
    head = re.sub(r"^[^/@]*:[^/@]*@", "", head)
    return (head + last)[:MAX_STR]


# -- references -------------------------------------------------------------------------------------
@dataclass
class Scope:
    """One module's configuration: where `var.x` and `module.m.out` resolve."""

    path: str  # base module path ('' or module.a.module.b)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)  # local address -> config
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)  # call name -> {expressions, ...}
    outputs: dict[str, Any] = field(default_factory=dict)  # name -> expression
    sensitive_vars: set[str] = field(default_factory=set)
    parent: Scope | None = None
    call_name: str | None = None  # this scope's call name in its parent


def base_path(module_address: str) -> str:
    """module.svc["api"].module.x[0] -> module.svc.module.x"""
    return re.sub(r"\[[^\]]*\]", "", module_address)


def strip_index(address: str) -> str:
    return re.sub(r"\[[^\]]*\]$", "", address)


def _ref_target(ref: str) -> str:
    """`google_x.y.attr[0]` -> `google_x.y`; `module.m.out` stays."""
    parts = re.sub(r"\[[^\]]*\]", "", ref).split(".")
    if parts[0] in ("var", "module", "local", "data"):
        return ".".join(parts[:3]) if parts[0] in ("module", "data") else ".".join(parts[:2])
    return ".".join(parts[:2])


def resolve_refs(refs: list[str], scope: Scope, scopes: dict[str, Scope], depth: int = 0) -> set[str]:
    """Base addresses of the resources a list of references points at, through module variables and
    outputs (bounded depth). Unresolvable references (locals, data sources, …) are dropped."""
    out: set[str] = set()
    if depth > 8:
        return out
    prefix = scope.path + "." if scope.path else ""
    for raw in refs:
        r = _ref_target(raw)
        if r.startswith(NON_RESOURCE) or "." not in r:
            continue
        if r.startswith("local."):  # static reads only (the plan JSON has no locals)
            expr = scope.outputs.get("__local__." + r[6:])
            if isinstance(expr, dict):
                out |= resolve_refs(expr_refs(expr), scope, scopes, depth + 1)
            continue
        if r.startswith("var."):
            name = r[4:]
            parent = scope.parent
            call = parent.calls.get(scope.call_name or "") if parent else None
            expr = (call or {}).get("expressions", {}).get(name)
            if parent is not None and isinstance(expr, dict):
                out |= resolve_refs(expr_refs(expr), parent, scopes, depth + 1)
            continue
        if r.startswith("module."):
            _, call_name, *rest = r.split(".")
            child = scopes.get(f"{prefix}module.{call_name}")
            if child is not None and rest:
                expr = child.outputs.get(rest[0])
                if isinstance(expr, dict):
                    out |= resolve_refs(expr_refs(expr), child, scopes, depth + 1)
            continue
        if r in scope.resources:
            out.add(prefix + r)
    return out


def expr_refs(expr: Any) -> list[str]:
    """Every reference inside an expression tree (sorted, unique)."""
    found: set[str] = set()

    def go(x: Any) -> None:
        if isinstance(x, dict):
            refs = x.get("references")
            if isinstance(refs, list):
                found.update(str(r) for r in refs)
            for k, v in x.items():
                if k not in ("references", "constant_value"):
                    go(v)
        elif isinstance(x, list):
            for v in x:
                go(v)

    go(expr)
    return sorted(found)


def is_const(expr: Any) -> bool:
    return isinstance(expr, dict) and "constant_value" in expr and not expr.get("references")


# -- one resource from its trees ------------------------------------------------------------------
def build_resource(
    *,
    env: str,
    address: str,
    module: str,
    rtype: str,
    name: str,
    provider: str,
    values: dict[str, Any],
    exprs: dict[str, Any],
    sensitive: Any,
    unknown: Any,
    scope: Scope,
    scopes: dict[str, Scope],
    source: str,
    known_kinds: dict[str, str] | None = None,
) -> Resource:
    rule = rules()["types"].get(rtype, {})
    kind = rule.get("kind", "infra_other")
    res = Resource(
        env=env,
        address=address,
        base=(scope.path + "." if scope.path else "") + f"{rtype}.{name}",
        module=module,
        type=rtype,
        name=name,
        provider=provider,
        kind=kind,
        source=source,
    )
    allowed = set(rules()["allowed_attrs"])
    for out_name, path in sorted((rule.get("attrs") or {}).items()):
        if out_name not in allowed:
            continue
        if sensitive_at(sensitive, path):
            res.attrs[out_name] = "sensitive"
            continue
        got = [scalar(v) for v in walk(values, path)]
        got = [g for g in got if g is not None]
        if got:
            v = got[0]
            res.attrs[out_name] = image_repo(v) if out_name == "image" and isinstance(v, str) else v
        elif walk(unknown, path) and any(u is True for u in walk(unknown, path)):
            res.attrs[out_name] = "unknown"
    if "image" not in res.attrs and rule.get("image_json"):
        img = _json_images(values, rule["image_json"])
        if img:
            res.attrs["image"] = image_repo(img[0])
    if rule.get("encrypted"):
        res.attrs["encrypted"] = any(
            not sensitive_at(sensitive, p)
            and any(bool(v) for v in walk(values, p))
            or _expr_present(exprs, p)
            for p in rule["encrypted"]
        )
    if rule.get("website"):
        res.attrs["website"] = any(
            any(bool(v) for v in walk(values, p)) or _expr_present(exprs, p) for p in rule["website"]
        )
    res.refs = resolve_refs(expr_refs(exprs), scope, scopes) - {res.base}
    for spec in rule.get("env") or []:
        for ev in _env_vars(spec, values, exprs, unknown, scope, scopes, known_kinds or {}):
            if ev.name not in res.env_vars or res.env_vars[ev.name].source == "unknown":
                res.env_vars[ev.name] = ev
    if rule.get("env_from"):
        got = resolve_refs(expr_refs(exprs.get(rule["env_from"], {})), scope, scopes)
        res.env_from = sorted(got)[0] if len(got) == 1 else None
    if rule.get("website_of"):
        got = resolve_refs(expr_refs(exprs.get(rule["website_of"], {})), scope, scopes)
        res.website_of = sorted(got)[0] if len(got) == 1 else None
    return res


def _expr_present(exprs: dict[str, Any], path: str) -> bool:
    got = walk(exprs, path)
    return any(
        (
            isinstance(g, dict)
            and (g.get("references") or g.get("constant_value") not in (None, False, "", [], {}))
        )
        for g in got
    )


def _json_images(values: dict[str, Any], path: str) -> list[str]:
    out = []
    for doc in _json_docs(values, path):
        for c in doc if isinstance(doc, list) else [doc]:
            if isinstance(c, dict) and isinstance(c.get("image"), str):
                out.append(c["image"])
    return out


def _json_docs(values: dict[str, Any], path: str) -> list[Any]:
    out = []
    for raw in walk(values, path):
        if isinstance(raw, str) and len(raw) < 1_000_000:
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
    return out


def _source_of(
    expr: Any, scope: Scope, scopes: dict[str, Scope], secret: bool, known_kinds: dict[str, str]
) -> EnvVar:
    refs = resolve_refs(expr_refs(expr), scope, scopes) if expr is not None else set()
    if secret:
        stores = sorted(r for r in refs if known_kinds.get(r) == "secret_store") or sorted(refs)
        return EnvVar(
            "", "secret", stores[0] if len(stores) == 1 else None, stores if len(stores) > 1 else []
        )
    if refs:
        stores = {r for r in refs if known_kinds.get(r) == "secret_store"}
        if refs and refs == stores and len(refs) == 1:
            return EnvVar("", "secret", next(iter(refs)))
        rs = sorted(refs)
        return EnvVar("", "reference", rs[0]) if len(rs) == 1 else EnvVar("", "unknown", None, rs)
    if is_const(expr):
        return EnvVar("", "literal")
    return EnvVar("", "unknown")


def _env_vars(
    spec: dict[str, Any],
    values: dict[str, Any],
    exprs: dict[str, Any],
    unknown: Any,
    scope: Scope,
    scopes: dict[str, Scope],
    known_kinds: dict[str, str],
) -> list[EnvVar]:
    """Env var names and where their values come from. Values are never kept."""
    out: list[EnvVar] = []
    if "json" in spec:  # a JSON document (ECS container definitions): names only, sources not traceable
        whole = exprs.get(spec["json"])
        refs = resolve_refs(expr_refs(whole), scope, scopes) if whole else set()
        for doc in _json_docs(values, spec["json"]):
            for c in doc if isinstance(doc, list) else [doc]:
                for e in c.get(spec["list"], []) if isinstance(c, dict) else []:
                    nm = e.get(spec["name"]) if isinstance(e, dict) else None
                    if not isinstance(nm, str) or not ENV_NAME_RE.match(nm):
                        continue
                    stores = sorted(r for r in refs if known_kinds.get(r) == "secret_store")
                    others = sorted(r for r in refs if r not in stores)
                    if spec.get("secret"):
                        out.append(EnvVar(nm, "secret", stores[0] if len(stores) == 1 else None))
                    else:  # resolved text: literal unless it may come from a resource
                        out.append(EnvVar(nm, "literal" if not others else "unknown", None, others))
        return out
    if "list" in spec:
        vals = [e for e in walk(values, spec["list"]) if isinstance(e, dict)]
        cfgs = [e for e in walk(exprs, spec["list"]) if isinstance(e, dict)]
        n = max(len(vals), len(cfgs))
        for i in range(n):
            v = vals[i] if i < len(vals) and len(vals) == n else {}
            c = cfgs[i] if i < len(cfgs) and len(cfgs) == n else {}
            nm = v.get(spec["name"]) if isinstance(v.get(spec["name"]), str) else None
            if nm is None:
                ce = c.get(spec["name"])
                nm = ce.get("constant_value") if isinstance(ce, dict) else None
            if not isinstance(nm, str) or not ENV_NAME_RE.match(nm):
                continue
            secret_path = spec.get("secret")
            sec_cfg = walk(c, secret_path) if secret_path else []
            sec_val = walk(v, secret_path) if secret_path else []
            if secret_path and (sec_cfg or sec_val):
                ev = _source_of(sec_cfg[0] if sec_cfg else None, scope, scopes, True, known_kinds)
            elif "value" in spec and (spec["value"] in c or spec["value"] in v):
                ev = _source_of(c.get(spec["value"]), scope, scopes, False, known_kinds)
                if spec["value"] not in c and spec["value"] in v:
                    ev = EnvVar("", "literal")  # a known value with no recorded expression
            else:
                ev = EnvVar("", "unknown")
            ev.name = nm
            out.append(ev)
        return out
    key = "secret_map" if "secret_map" in spec else "map"
    path = spec[key]
    maps = [m for m in walk(values, path) if isinstance(m, dict)]
    cexpr = walk(exprs, path)
    names = sorted(
        {k for m in maps for k in m}
        | {k for c in cexpr if isinstance(c, dict) for k in c if k not in ("references", "constant_value")}
    )
    whole = (
        cexpr[0]
        if len(cexpr) == 1
        and isinstance(cexpr[0], dict)
        and ("references" in cexpr[0] or "constant_value" in cexpr[0])
        else None
    )
    if whole is not None and isinstance(whole.get("constant_value"), dict):
        names = sorted(set(names) | set(whole["constant_value"]))
    later = {k for m in walk(unknown, path) if isinstance(m, dict) for k, v in m.items() if v is True}
    names = sorted(set(names) | later)
    for nm in names:
        if not ENV_NAME_RE.match(nm):
            continue
        per_key = cexpr[0].get(nm) if cexpr and isinstance(cexpr[0], dict) and whole is None else None
        if per_key is not None or whole is None or key == "secret_map":
            ev = _source_of(
                per_key if per_key is not None else whole, scope, scopes, key == "secret_map", known_kinds
            )
        else:
            # one expression for the whole map (plan JSON): a key known only after apply comes from a
            # resource it references; a key known now is a literal or a variable. Never guessed further.
            refs = sorted(resolve_refs(expr_refs(whole), scope, scopes))
            if nm in later:
                ev = EnvVar("", "reference", refs[0]) if len(refs) == 1 else EnvVar("", "unknown", None, refs)
            else:
                ev = EnvVar("", "literal" if is_const(whole) or not expr_refs(whole) else "unknown")
        ev.name = nm
        out.append(ev)
    return out


def finalize(resources: list[Resource]) -> None:
    """Cross-resource facts within one environment: an ECS service gets its task definition's env
    vars and image (`env_from`); a website configuration marks its bucket as a website."""
    by_base: dict[str, list[Resource]] = {}
    for r in resources:
        by_base.setdefault(r.base, []).append(r)
    for r in resources:
        if r.env_from:
            for td in by_base.get(r.env_from, []):
                for k, v in td.env_vars.items():
                    r.env_vars.setdefault(k, v)
                if "image" in td.attrs and "image" not in r.attrs:
                    r.attrs["image"] = td.attrs["image"]
        if r.website_of:
            for b in by_base.get(r.website_of, []):
                b.attrs["website"] = True


# -- graph emission -------------------------------------------------------------------------------
def node_qname(env: str, address: str) -> str:
    return f"infra:{env}:{address}" if address else f"infra:{env}"


def emit(
    graph: ir.Graph,
    resources: list[Resource],
    modules: dict[str, dict[str, dict[str, Any]]],
    roots: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Add infra nodes (one root per environment, module instances, resources) and their
    `references` / `wires` edges. `modules`: env -> module instance address -> attrs; `roots`:
    env -> extra attrs of the environment's root node."""
    by_env: dict[str, list[Resource]] = {}
    for r in resources:
        by_env.setdefault(r.env, []).append(r)
    for env in sorted(set(by_env) | set(modules) | set(roots or {})):
        rattrs = {"env": env, "root": True, **(roots or {}).get(env, {})}
        root = ir.Node("infra", "infra_module", f"infra ({env})", node_qname(env, ""), attrs=rattrs)
        root.content_hash = ids.attrs_hash("infra_module", root.qualified_name, root.attrs)
        graph.add_node(root)
        mods = modules.get(env, {})
        for maddr in sorted(mods, key=lambda a: (a.count("module."), a)):
            parent = maddr.rsplit(".module.", 1)[0] if ".module." in maddr else ""
            pid = (
                ids.node_id("infra", "infra_module", node_qname(env, parent))
                if parent in mods or parent == ""
                else root.id
            )
            if parent and parent not in mods:
                pid = root.id
            attrs = {"env": env, **mods[maddr]}
            n = ir.Node("infra", "infra_module", maddr, node_qname(env, maddr), parent_id=pid, attrs=attrs)
            n.content_hash = ids.attrs_hash("infra_module", n.qualified_name, attrs)
            graph.add_node(n)
        insts: dict[str, list[str]] = {}
        for r in sorted(by_env.get(env, []), key=lambda r: r.address):
            pid = (
                ids.node_id("infra", "infra_module", node_qname(env, r.module))
                if r.module in mods
                else root.id
            )
            attrs: dict[str, Any] = {
                "env": env,
                "type": r.type,
                "provider": r.provider,
                "address": r.address,
                "source": r.source,
                **r.attrs,
            }
            if r.action:
                attrs["action"] = r.action
            if r.env_vars:
                attrs["env_vars"] = {k: r.env_vars[k].to_dict() for k in sorted(r.env_vars)}
            label = str(r.attrs.get("name") or r.address.rsplit(".", 1)[-1])
            n = ir.Node(
                "infra",
                r.kind,
                label if isinstance(label, str) else r.address,
                node_qname(env, r.address),
                parent_id=pid,
                attrs=attrs,
            )
            n.content_hash = ids.attrs_hash(r.kind, n.qualified_name, attrs)
            graph.add_node(n)
            insts.setdefault(r.base, []).append(n.id)
        for r in sorted(by_env.get(env, []), key=lambda r: r.address):
            src = ids.node_id("infra", r.kind, node_qname(env, r.address))
            for tgt_base in sorted(r.refs):
                for tid in insts.get(tgt_base, []):
                    graph.add_edge(src, tid, "references")
            wired: dict[str, list[str]] = {}
            for name, ev in sorted(r.env_vars.items()):
                if ev.ref:
                    for tid in insts.get(ev.ref, []):
                        wired.setdefault(tid, []).append(name)
            for tid, names in sorted(wired.items()):
                graph.add_edge(src, tid, "wires", attrs={"env_vars": sorted(names)})
