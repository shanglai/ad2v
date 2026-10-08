"""The env-var bridge between code and infra (P10 M5, ADR-0080), deterministic.

`link()` (at extraction, base facts):

- `attrs.env_reads` on the code nodes that read env vars and on their containers (only in epochs
  with infra input: without infra the bridge does not exist and the code side stays as it was);
- `deploys` (deployment unit -> code container), per infra environment, in priority order:
  (a) the manifest (`infra.deploys`), (b) a name match (the unit's name, or its image
  repository's last segment, equals the container's slug or ends/starts with it at a `-`/`_`
  boundary), (c) env-var overlap (the container's reads are a subset of what the unit provides,
  at least two shared names, one best candidate). Several matches at one level are ambiguous
  (no edge) unless (b)'s matches deploy the same image. Many-to-many is allowed;
- `provides_env` (deployment unit -> each code node reading an env var it provides).

`statuses()` (derived, `infra_status`): one row per (node, environment) for code containers
(deployed / undeployed / ambiguous), code nodes reading env vars in a deployed container (wired /
unwired) and infra resources (in_use / infra_orphan). An epoch without infra input has no rows:
nothing is claimed (`unknown` in readers).

A website bucket (attrs.website) is a static host: it can deploy a container like a unit (ADR-0080).
"""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids, ir
from ad2v.infra import envreads

GENERIC_NAMES = frozenset({"this", "main", "default", "app", "service", "svc"})


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _container_name(n: ir.Node) -> str:
    return _slug(n.name.split(":", 1)[-1])


def hosts(graph: ir.Graph) -> list[ir.Node]:
    """Deployment units and website buckets (static hosts), sorted."""
    return sorted(
        (
            n
            for n in graph.nodes.values()
            if n.side == "infra"
            and (n.kind == "deployment_unit" or (n.kind == "bucket" and n.attrs.get("website")))
        ),
        key=lambda n: n.id,
    )


def _unit_names(u: ir.Node) -> list[str]:
    names = []
    for raw in (u.attrs.get("name"), u.attrs.get("address", "").rsplit(".", 1)[-1].split("[", 1)[0]):
        if isinstance(raw, str) and raw and _slug(raw) not in GENERIC_NAMES:
            names.append(_slug(raw))
    img = u.attrs.get("image")
    if isinstance(img, str) and img not in ("unknown", "sensitive"):
        names.append(_slug(img.rsplit("/", 1)[-1]))
    return sorted(set(n for n in names if n))


def _name_match(unit_names: list[str], c: str) -> bool:
    return any(n == c or n.endswith("-" + c) or n.startswith(c + "-") for n in unit_names)


def _provided(u: ir.Node) -> set[str]:
    return set((u.attrs.get("env_vars") or {}).keys())


def link(graph: ir.Graph, config: Any, sources: dict[str, str]) -> dict[str, Any]:
    """Add env_reads attrs and the bridge edges. Returns per-env deploy decisions (stats)."""
    if not any(n.side == "infra" for n in graph.nodes.values()):
        return {}
    reads = envreads.collect(graph, sources)
    for nid, names in reads.items():
        graph.nodes[nid].attrs["env_reads"] = names
    containers = sorted(
        (n for n in graph.nodes.values() if n.side == "code" and n.kind == "container"), key=lambda n: n.id
    )
    units_by_env: dict[str, list[ir.Node]] = {}
    for u in hosts(graph):
        units_by_env.setdefault(str(u.attrs.get("env")), []).append(u)
    decisions: dict[str, dict[str, Any]] = {}
    manifest = getattr(config, "infra_deploys", {}) or {}
    for env, units in sorted(units_by_env.items()):
        env_dec: dict[str, Any] = {}
        for c in containers:
            cname = _container_name(c)
            creads = set(c.attrs.get("env_reads") or [])
            chosen: list[ir.Node] = []
            method = None
            cands: list[str] = []
            explicit = [
                u
                for u in units
                if any(
                    key in (u.attrs.get("address"), re.sub(r"\[[^\]]*\]", "", str(u.attrs.get("address"))))
                    and any(_slug(x) == cname for x in names)
                    for key, names in manifest.items()
                )
            ]
            if explicit:
                chosen, method = explicit, "manifest"
            else:
                by_name = [u for u in units if _name_match(_unit_names(u), cname)]
                images = {u.attrs.get("image") for u in by_name}
                if len(by_name) == 1 or (len(by_name) > 1 and len(images) == 1 and None not in images):
                    chosen, method = by_name, "name"
                elif len(by_name) > 1:
                    cands, method = [u.id for u in by_name], "ambiguous_name"
                elif len(creads) >= 2:
                    scored = sorted(
                        ((len(creads & _provided(u)), u) for u in units if creads <= _provided(u)),
                        key=lambda x: (-x[0], x[1].id),
                    )
                    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                        chosen, method = [scored[0][1]], "env_overlap"
                    elif scored:
                        best = scored[0][0]
                        cands, method = [u.id for s, u in scored if s == best], "ambiguous_env_overlap"
            for u in chosen:
                graph.add_edge(u.id, c.id, "deploys", attrs={"method": method, "env": env})
            env_dec[c.id] = {"method": method, "units": [u.id for u in chosen], "candidates": cands}
            # provides_env: the unit gives the env var each reader of this container needs
            provided: dict[str, list[str]] = {}
            for u in chosen:
                for name in sorted(_provided(u) & creads):
                    provided.setdefault(u.id, []).append(name)
            for uid, names in sorted(provided.items()):
                for rid, rnames in reads.items():
                    if rid == c.id or not _inside(graph, rid, c.id):
                        continue
                    common = sorted(set(rnames) & set(names))
                    if common:
                        graph.add_edge(uid, rid, "provides_env", attrs={"env_vars": common, "env": env})
        decisions[env] = env_dec
    return decisions


def _inside(graph: ir.Graph, nid: str, ancestor: str) -> bool:
    p = graph.nodes[nid].parent_id
    while p is not None:
        if p == ancestor:
            return True
        p = graph.nodes[p].parent_id if p in graph.nodes else None
    return False


def statuses(graph: ir.Graph) -> list[tuple[str, str, str, list[dict[str, Any]]]]:
    """(node_id, env, status, reasons) rows of `infra_status`, sorted. Pure function of the graph."""
    infra = [n for n in graph.nodes.values() if n.side == "infra"]
    if not infra:
        return []
    envs = sorted({str(n.attrs.get("env")) for n in infra if n.attrs.get("root")})
    out: list[tuple[str, str, str, list[dict[str, Any]]]] = []
    deploys: dict[tuple[str, str], list[ir.Edge]] = {}  # (container, env) -> edges
    provides: dict[tuple[str, str], list[ir.Edge]] = {}  # (reader, env) -> edges
    touched: set[str] = set()
    for e in graph.edges.values():
        if e.kind == "deploys":
            deploys.setdefault((e.dst, str(e.attrs.get("env"))), []).append(e)
        elif e.kind == "provides_env":
            provides.setdefault((e.dst, str(e.attrs.get("env"))), []).append(e)
        if e.kind in ("references", "wires", "deploys"):
            touched.add(e.src)
            touched.add(e.dst)
    units_by_env: dict[str, list[ir.Node]] = {}
    for u in hosts(graph):
        units_by_env.setdefault(str(u.attrs.get("env")), []).append(u)
    containers = sorted(
        (n for n in graph.nodes.values() if n.side == "code" and n.kind == "container"), key=lambda n: n.id
    )
    readers = sorted(
        (
            n
            for n in graph.nodes.values()
            if n.side == "code" and n.kind != "container" and n.attrs.get("env_reads")
        ),
        key=lambda n: n.id,
    )
    for env in envs:
        units = units_by_env.get(env, [])
        for c in containers:
            es = sorted(deploys.get((c.id, env), []), key=lambda e: e.src)
            if es:
                out.append(
                    (
                        c.id,
                        env,
                        "deployed",
                        [{"kind": "deploys", "unit": e.src, "method": e.attrs.get("method")} for e in es],
                    )
                )
                continue
            amb = _ambiguity(graph, c, units)
            if amb:
                out.append((c.id, env, "ambiguous", [{"kind": "candidates", "units": amb}]))
            else:
                out.append((c.id, env, "undeployed", [{"kind": "no_deployment_unit"}]))
        for r in readers:
            c = _container_of(graph, r.id)
            if c is None or not deploys.get((c, env)):
                continue
            units_here = sorted(e.src for e in deploys[(c, env)])
            given = {n for e in provides.get((r.id, env), []) for n in e.attrs.get("env_vars", [])}
            missing = sorted(set(r.attrs["env_reads"]) - given)
            if missing:
                out.append(
                    (
                        r.id,
                        env,
                        "unwired",
                        [{"kind": "not_provided", "env_var": m, "units": units_here} for m in missing],
                    )
                )
            else:
                out.append((r.id, env, "wired", [{"kind": "provided", "env_vars": sorted(given)}]))
        for n in sorted(infra, key=lambda n: n.id):
            if str(n.attrs.get("env")) != env or n.kind == "infra_module":
                continue
            if n.id in touched:
                out.append((n.id, env, "in_use", [{"kind": "connected"}]))
            else:
                out.append((n.id, env, "infra_orphan", [{"kind": "nothing_wires_or_references_it"}]))
    return sorted(out, key=lambda r: (r[0], r[1]))


def _ambiguity(graph: ir.Graph, c: ir.Node, units: list[ir.Node]) -> list[str]:
    """Recompute the tie that left a container without a deploys edge (same rules as `link`)."""
    cname = _container_name(c)
    by_name = [u for u in units if _name_match(_unit_names(u), cname)]
    if len(by_name) > 1:
        return sorted(u.id for u in by_name)
    creads = set(c.attrs.get("env_reads") or [])
    if len(creads) >= 2:
        scored = sorted(
            ((len(creads & _provided(u)), u.id) for u in units if creads <= _provided(u)),
            key=lambda x: (-x[0], x[1]),
        )
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return sorted(i for s, i in scored if s == scored[0][0])
    return []


def _container_of(graph: ir.Graph, nid: str) -> str | None:
    p = graph.nodes[nid].parent_id
    while p is not None and p in graph.nodes:
        if graph.nodes[p].kind == "container":
            return p
        p = graph.nodes[p].parent_id
    return None


def rows(epoch_id: str, graph: ir.Graph) -> list[dict[str, Any]]:
    return [
        {
            "epoch_id": epoch_id,
            "node_id": nid,
            "env": env,
            "status": st,
            "reasons_json": ids.canonical_json(rs),
        }
        for nid, env, st, rs in statuses(graph)
    ]
