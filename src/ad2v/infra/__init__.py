"""The infra layer (P10): Terraform plan JSON (primary) and static `.tf` (fallback) -> infra nodes.

`collect()` reads the inputs and computes the epoch's `infra_hash`; `apply()` adds the infra
nodes to the graph. ad2v never runs terraform or tofu (ADR-0074).

Rules (ADR-0074, ADR-0075):

- plans are given per environment (`--infra-plan prod=plan.json`); the default name is `default`;
- when an epoch gets no plan, the parent's plan-derived nodes carry forward (like test results);
- static `.tf` files under `infra_root` are read every epoch (history has only these);
- when a plan and a static read cover the same environment, the plan wins; the static read only
  fills gaps: resources the plan's configuration does not declare at all (the plan is older than
  the `.tf` files). Those nodes keep `source: static` and the root lists them (`filled_from_static`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v import ids, ir
from ad2v.infra import model, plan, static
from ad2v.infra.plan import InfraInputError

__all__ = ["InfraInputError", "InfraState", "apply", "collect", "parse_plan_args"]


@dataclass
class InfraState:
    plans: list[plan.PlanRead] = field(default_factory=list)
    statics: list[static.StaticRead] = field(default_factory=list)
    plan_hashes: dict[str, str] = field(default_factory=dict)  # env -> content hash
    declared: dict[str, list[str]] = field(default_factory=dict)  # env -> bases the plan declares
    carried: list[str] = field(default_factory=list)  # envs carried from the parent
    inputs: dict[str, Any] = field(default_factory=dict)
    hash: str = ""
    warnings: list[str] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.hash)


def parse_plan_args(args: list[str], default_env: str | None = None) -> list[tuple[str, Path]]:
    """`plan.json` or `env=plan.json` (repeatable). The env name defaults to `--infra-env` or
    `default`. Names: letters, digits, `_` and `-`."""
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for a in args:
        env, sep, path = a.partition("=")
        if not sep or not model.SAFE_ENV_RE.match(env) or len(env) > 64 or Path(a).exists():
            env, path = default_env or "default", a
        if not model.SAFE_ENV_RE.match(env):
            raise InfraInputError(f"invalid infra environment name {env!r}")
        if env in seen:
            raise InfraInputError(f"two plans for the infra environment {env!r}")
        seen.add(env)
        out.append((env, Path(path)))
    return out


def _plan_declared(doc: dict[str, Any]) -> list[str]:
    scopes = plan._scopes((doc.get("configuration") or {}).get("root_module") or {})
    return sorted((sc.path + "." if sc.path else "") + a for sc in scopes.values() for a in sc.resources)


def collect(
    repo: Path,
    infra_roots: tuple[str, ...],
    plans: list[tuple[str, Path]],
    parent_attrs: dict[str, Any] | None,
    read: Any,
) -> InfraState:
    st = InfraState(roots=list(infra_roots))
    for env, path in plans:
        doc = plan.load_json(Path(path).read_bytes())
        st.plan_hashes[env] = plan.content_hash(doc)
        got = plan.read(doc, env)
        st.plans.append(got)
        st.declared[env] = _plan_declared(doc)
        st.warnings += [f"plan {env}: {w}" for w in got.warnings]
    if not plans and parent_attrs:
        carried = (parent_attrs.get("infra_inputs") or {}).get("plans") or {}
        st.plan_hashes = dict(sorted(carried.items()))
        st.carried = sorted(carried)
    names = static.env_names(list(infra_roots)) if infra_roots else {}
    static_files: dict[str, dict[str, str]] = {}
    for root in infra_roots:
        sr = static.read_root(repo, root, names[root], read)
        st.statics.append(sr)
        static_files[root] = dict(sorted(sr.files.items()))
        st.warnings += [f"static {root}: {w}" for w in sr.warnings]
    if st.plan_hashes or any(static_files.values()):
        st.inputs = {"plans": st.plan_hashes, "static": static_files}
        st.hash = ids.sha256_hex(ids.canonical_json(st.inputs))
    return st


def apply(graph: ir.Graph, st: InfraState, parent_graph: ir.Graph | None) -> dict[str, Any]:
    """Add the infra nodes to `graph`; returns stats for the run summary."""
    if not st.present:
        return {}
    plan_envs = sorted({p.env for p in st.plans} | set(st.carried))
    roots: dict[str, dict[str, Any]] = {}
    resources: list[model.Resource] = []
    modules: dict[str, dict[str, dict[str, Any]]] = {}
    for p in st.plans:
        roots[p.env] = {
            "source": "plan",
            "plan_format_version": p.format_version,
            "declared": st.declared[p.env],
        }
        resources += p.resources
        modules[p.env] = dict(p.modules)
    carried_nodes: list[ir.Node] = []
    if st.carried and parent_graph is not None:
        for env in st.carried:
            rq = model.node_qname(env, "")
            prev_root = next(
                (n for n in parent_graph.nodes.values() if n.side == "infra" and n.qualified_name == rq), None
            )
            if prev_root is not None:
                roots[env] = {
                    k: v
                    for k, v in prev_root.attrs.items()
                    if k in ("source", "plan_format_version", "declared")
                }
                roots[env]["carried"] = True
            for n in parent_graph.nodes.values():
                if (
                    n.side == "infra"
                    and n.attrs.get("env") == env
                    and n.attrs.get("source") == "plan"
                    and n.qualified_name != rq
                ):
                    carried_nodes.append(n)
    # static: alone, or filling the gaps of the plan environments it covers
    filled: dict[str, list[str]] = {}
    for sr in st.statics:
        targets = (
            [sr.env] if sr.env in plan_envs else (plan_envs if len(st.statics) == 1 and plan_envs else [])
        )
        if not targets:
            roots.setdefault(sr.env, {"source": "static", "infra_root": sr.root})
            resources += sr.resources
            modules.setdefault(sr.env, {}).update(sr.modules)
            continue
        for env in targets:
            declared = set(roots.get(env, {}).get("declared") or [])
            for r in sr.resources:
                if r.base in declared:
                    continue
                gap = model.Resource(**{**r.__dict__, "env": env, "attrs": {**r.attrs, "gap_fill": True}})
                resources.append(gap)
                filled.setdefault(env, []).append(r.address)
                if r.module and r.module not in modules.setdefault(env, {}):
                    modules[env][r.module] = dict(sr.modules.get(r.module, {"source": "static"}))
    for env, addrs in filled.items():
        roots.setdefault(env, {})["filled_from_static"] = sorted(addrs)
    model.emit(graph, resources, modules, roots)
    for n in sorted(carried_nodes, key=lambda n: n.id):
        if n.id not in graph.nodes:
            copy = ir.Node(
                n.side,
                n.kind,
                n.name,
                n.qualified_name,
                parent_id=n.parent_id,
                attrs=dict(n.attrs),
                content_hash=n.content_hash,
            )
            graph.add_node(copy)
    if carried_nodes and parent_graph is not None:
        keep = {n.id for n in carried_nodes}
        for e in sorted(parent_graph.edges.values(), key=lambda e: (e.src, e.kind, e.dst)):
            if e.kind in ("references", "wires") and e.src in keep and e.dst in keep:
                graph.add_edge(e.src, e.dst, e.kind, e.weight, dict(e.attrs))
    kinds: dict[str, int] = {}
    for n in graph.nodes.values():
        if n.side == "infra" and not n.attrs.get("root"):
            kinds[n.kind] = kinds.get(n.kind, 0) + 1
    return {
        "envs": sorted(roots),
        "kinds": dict(sorted(kinds.items())),
        "carried": st.carried,
        "filled_from_static": {k: len(v) for k, v in sorted(filled.items())},
        "warnings": st.warnings,
    }
