"""The C4 view (P10 M6, ADR-0079): derived, never drawn by hand. A pure function of the epoch's graph
(spec + code + infra) and its pairing, per infra environment ('' when the epoch has no infra).

Context level: the system; persons from user-story actors (`attrs.actor`, deduplicated by
normalized name); external systems from code `external_service` / `llm_endpoint` nodes.

Container level: deployment units (each listing the code containers it deploys) and website
buckets (static sites); managed datastores, queues, buckets and schedulers; code containers that
no unit deploys (`undeployed`, `ambiguous`, or `unknown` without infra). Without infra, the code
side's datastores and queues stand in for the data row.

Relations: code edges aggregated to containers (calls / reads / writes / publishes / consumes /
invokes); `wires` and `references` between infra elements; person -> container where a story's
requirement pairs with code in that container. Components are the map itself (click-through).

Each container carries the roll-up of the statuses of the requirements linked to its code, its
infra status, and the NFRs of the spec components mapped to it (not checked against infra in P10).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ad2v import ids, ir
from ad2v.infra import bridge

CODE_EDGE_KINDS = ("calls", "reads", "writes", "publishes", "consumes", "invokes_external", "invokes_llm")
DATA_KINDS = ("managed_datastore", "managed_queue", "bucket", "scheduler")
PRECEDENCE = {s: i for i, s in enumerate(ir.STATUS_PRECEDENCE)}


def element_id(kind: str, key: str) -> str:
    return "c4_" + ids.sha256_hex(f"{kind}|{key}")[:20]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _ancestors(graph: ir.Graph, nid: str) -> list[str]:
    out = []
    p = graph.nodes[nid].parent_id
    while p is not None and p in graph.nodes and len(out) < 64:
        out.append(p)
        p = graph.nodes[p].parent_id
    return out


def _container_of(graph: ir.Graph, nid: str) -> str | None:
    if graph.nodes[nid].kind == "container":
        return nid
    for a in _ancestors(graph, nid):
        if graph.nodes[a].kind == "container":
            return a
    return None


def derive(graph: ir.Graph, statuses: dict[str, ir.NodeStatus], links: list[ir.Link]) -> dict[str, Any]:
    """{env: {"elements": {id: element}, "relations": {(src, dst, kind): attrs}}}."""
    infra_rows = bridge.statuses(graph)
    istatus: dict[tuple[str, str], tuple[str, list[dict[str, Any]]]] = {
        (nid, env): (st, rs) for nid, env, st, rs in infra_rows
    }
    envs = sorted(
        {str(n.attrs.get("env")) for n in graph.nodes.values() if n.side == "infra" and n.attrs.get("root")}
    )
    system = next((n for n in graph.nodes.values() if n.side == "code" and n.kind == "system"), None)
    unwired_in: dict[tuple[str, str], set[str]] = {}  # (code container, env) -> env vars nothing provides
    for nid, env, st, rs in infra_rows:
        if st == "unwired":
            cid = _container_of(graph, nid)
            if cid is not None:
                unwired_in.setdefault((cid, env), set()).update(
                    str(r.get("env_var")) for r in rs if isinstance(r, dict) and r.get("env_var")
                )
    containers = sorted(
        (n for n in graph.nodes.values() if n.side == "code" and n.kind == "container"), key=lambda n: n.id
    )
    # requirement coverage per code container (through the existing links)
    cover: dict[str, Counter[str]] = {c.id: Counter() for c in containers}
    req_of_container: dict[str, set[str]] = {c.id: set() for c in containers}
    nfr_of_container: dict[str, set[str]] = {c.id: set() for c in containers}
    for lk in links:
        if lk.spec_node_id is None or lk.code_node_id is None:
            continue
        if lk.spec_node_id not in graph.nodes or lk.code_node_id not in graph.nodes:
            continue
        cid = _container_of(graph, lk.code_node_id)
        if cid is None:
            continue
        sn = graph.nodes[lk.spec_node_id]
        if sn.kind == "requirement":
            req_of_container[cid].add(sn.id)
        elif sn.kind == "spec_component":  # its NFRs belong to the container it maps to
            for r in graph.nodes.values():
                if (
                    r.kind == "requirement"
                    and r.attrs.get("requirement_type") == "nonfunctional"
                    and (sn.id in _ancestors(graph, r.id))
                ):
                    nfr_of_container[cid].add(r.id)
    for cid, reqs in req_of_container.items():
        for rid in reqs:
            cover[cid][statuses[rid].status if rid in statuses else "none"] += 1
    actors: dict[str, dict[str, Any]] = {}
    for r in sorted(graph.nodes.values(), key=lambda n: n.id):
        a = r.attrs.get("actor") if r.side == "spec" else None
        if isinstance(a, str) and a.strip():
            key = _slug(a)
            label = a.strip()[:80]
            d = actors.setdefault(key, {"name": label[:1].upper() + label[1:], "reqs": []})
            d["reqs"].append(r.id)
    externals: dict[str, list[str]] = {}
    for n in sorted(graph.nodes.values(), key=lambda n: n.id):
        if n.side == "code" and n.kind in ("external_service", "llm_endpoint"):
            externals.setdefault(n.name, []).append(n.id)

    out: dict[str, Any] = {}
    for env in envs or [""]:
        els: dict[str, dict[str, Any]] = {}
        sys_id = element_id("system", system.id if system else "system")
        els[sys_id] = {
            "level": "context",
            "kind": "system",
            "name": system.name if system else "system",
            "node_ids": [system.id] if system else [],
            "attrs": {},
        }
        for key, a in sorted(actors.items()):
            els[element_id("person", key)] = {
                "level": "context",
                "kind": "person",
                "name": a["name"],
                "node_ids": sorted(a["reqs"]),
                "attrs": {"stories": len(a["reqs"])},
            }
        ext_el: dict[str, str] = {}
        for name, nids in sorted(externals.items()):
            eid = element_id("external_system", name)
            els[eid] = {
                "level": "context",
                "kind": "external_system",
                "name": name,
                "node_ids": nids,
                "attrs": {},
            }
            for nid in nids:
                ext_el[nid] = eid
        # containers ------------------------------------------------------------------------------
        hosted_by: dict[str, list[str]] = {}  # code container -> element ids that deploy it
        infra_el: dict[str, str] = {}  # infra node -> element
        for u in bridge.hosts(graph):
            if str(u.attrs.get("env")) != env:
                continue
            deployed = sorted(
                e.dst
                for e in graph.edges.values()
                if e.kind == "deploys" and e.src == u.id and e.dst in graph.nodes
            )
            eid = element_id("unit", u.id)
            infra_el[u.id] = eid
            st = istatus.get((u.id, env), ("unknown", []))[0]
            cov: Counter[str] = Counter()
            nfrs: set[str] = set()
            unwired: set[str] = set()
            for c in deployed:
                cov.update(cover.get(c, Counter()))
                nfrs |= nfr_of_container.get(c, set())
                hosted_by.setdefault(c, []).append(eid)
                unwired |= unwired_in.get((c, env), set())
            els[eid] = {
                "level": "container",
                "kind": "static_site" if u.kind == "bucket" else "deployment_unit",
                "name": str(u.attrs.get("name") or u.name),
                "node_ids": [u.id, *deployed],
                "attrs": {
                    "type": u.attrs.get("type"),
                    "deploys": [graph.nodes[c].name for c in deployed],
                    **({"unwired": sorted(unwired)} if unwired else {}),
                    "infra_status": st,
                    **_coverage(cov),
                    **({"nfr": sorted(graph.nodes[r].qualified_name for r in nfrs)} if nfrs else {}),
                    **{k: u.attrs[k] for k in ("image", "location", "region", "source") if k in u.attrs},
                },
            }
        for n in sorted(graph.nodes.values(), key=lambda n: n.id):
            if (
                n.side != "infra"
                or str(n.attrs.get("env")) != env
                or n.kind not in DATA_KINDS
                or n.id in infra_el
            ):
                continue
            eid = element_id("infra", n.id)
            infra_el[n.id] = eid
            els[eid] = {
                "level": "container",
                "kind": n.kind,
                "name": str(n.attrs.get("name") or n.name),
                "node_ids": [n.id],
                "attrs": {
                    "type": n.attrs.get("type"),
                    "infra_status": istatus.get((n.id, env), ("unknown", []))[0],
                    **{
                        k: n.attrs[k]
                        for k in ("engine", "location", "region", "schedule", "source")
                        if k in n.attrs
                    },
                },
            }
        code_el: dict[str, list[str]] = {}
        for c in containers:
            if c.id in hosted_by:
                code_el[c.id] = sorted(set(hosted_by[c.id]))
                continue
            st = istatus.get((c.id, env), ("unknown", []))
            eid = element_id("code_container", c.id)
            els[eid] = {
                "level": "container",
                "kind": "code_container",
                "name": c.name,
                "node_ids": [c.id],
                "attrs": {
                    "infra_status": st[0] if envs else "unknown",
                    **({"candidates": st[1][0].get("units", [])} if st[0] == "ambiguous" else {}),
                    **_coverage(cover.get(c.id, Counter())),
                    **(
                        {
                            "nfr": sorted(
                                graph.nodes[r].qualified_name for r in nfr_of_container.get(c.id, set())
                            )
                        }
                        if nfr_of_container.get(c.id)
                        else {}
                    ),
                    **({"language": c.attrs["language"]} if "language" in c.attrs else {}),
                },
            }
            code_el[c.id] = [eid]
        res_el: dict[str, str] = {}  # code resource node -> element (data row stand-ins / wired infra)
        if not envs:
            for n in sorted(graph.nodes.values(), key=lambda n: n.id):
                if n.side == "code" and n.kind in ("datastore", "queue"):
                    eid = element_id("code_resource", n.id)
                    res_el[n.id] = eid
                    els[eid] = {
                        "level": "container",
                        "kind": "managed_datastore" if n.kind == "datastore" else "managed_queue",
                        "name": n.name,
                        "node_ids": [n.id],
                        "attrs": {"infra_status": "unknown", "from_code": True},
                    }

        # relations -------------------------------------------------------------------------------
        acc = _Relations(graph, els, res_el, ext_el, code_el)
        for e in sorted(graph.edges.values(), key=lambda e: (e.src, e.kind, e.dst)):
            if e.kind in CODE_EDGE_KINDS and e.src in graph.nodes and e.dst in graph.nodes:
                kind = "invokes" if e.kind.startswith("invokes") else e.kind
                for s in acc.elements_of(e.src):
                    for d in acc.elements_of(e.dst):
                        acc.add(s, d, kind)
            elif e.kind in ("wires", "references") and e.src in infra_el and e.dst in infra_el:
                if e.kind == "references" and (e.src, "wires", e.dst) in graph.edges:
                    continue  # the wire says more
                extra = {"env_vars": e.attrs["env_vars"]} if e.attrs.get("env_vars") else {}
                acc.add(infra_el[e.src], infra_el[e.dst], e.kind, **extra)
        for key, a in sorted(actors.items()):
            pid = element_id("person", key)
            reqs = set(a["reqs"])
            for lk in links:
                if (
                    lk.spec_node_id in reqs
                    and lk.code_node_id in graph.nodes
                    and lk.status not in ("missing", "specified")
                ):
                    for d in acc.elements_of(lk.code_node_id):
                        acc.add(pid, d, "uses")
        rels = acc.rels
        out[env] = {"elements": els, "relations": rels}
    return out


class _Relations:
    """Relations of one environment's view, aggregated to elements."""

    def __init__(
        self,
        graph: ir.Graph,
        els: dict[str, dict[str, Any]],
        res_el: dict[str, str],
        ext_el: dict[str, str],
        code_el: dict[str, list[str]],
    ) -> None:
        self.graph, self.els = graph, els
        self.res_el, self.ext_el, self.code_el = res_el, ext_el, code_el
        self.rels: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(self, src: str, dst: str, kind: str, **attrs: Any) -> None:
        if src == dst or src not in self.els or dst not in self.els:
            return
        cur = self.rels.setdefault((src, dst, kind), {"weight": 0})
        cur["weight"] += 1
        for k, v in attrs.items():
            if isinstance(v, list):
                cur[k] = sorted(set(cur.get(k, [])) | set(v))

    def elements_of(self, nid: str) -> list[str]:
        if nid in self.res_el:
            return [self.res_el[nid]]
        if nid in self.ext_el:
            return [self.ext_el[nid]]
        cid = _container_of(self.graph, nid)
        return self.code_el.get(cid, []) if cid else []


def _coverage(c: Counter[str]) -> dict[str, Any]:
    if not c:
        return {"coverage": {}, "coverage_worst": "none"}
    worst = min(c, key=lambda s: PRECEDENCE.get(s, 99))
    return {"coverage": dict(sorted(c.items())), "coverage_worst": worst}


def rows(epoch_id: str, graph: ir.Graph, paired: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    view = derive(graph, paired.statuses, paired.links)
    els, rels = [], []
    for env, v in sorted(view.items()):
        for eid, el in sorted(v["elements"].items()):
            els.append(
                {
                    "epoch_id": epoch_id,
                    "env": env,
                    "element_id": eid,
                    "level": el["level"],
                    "kind": el["kind"],
                    "name": el["name"],
                    "node_ids_json": ids.canonical_json(sorted(set(el["node_ids"]))),
                    "attrs_json": ids.canonical_json(el["attrs"]),
                }
            )
        for (s, d, k), attrs in sorted(v["relations"].items()):
            rels.append(
                {
                    "epoch_id": epoch_id,
                    "env": env,
                    "src": s,
                    "dst": d,
                    "kind": k,
                    "attrs_json": ids.canonical_json(attrs),
                }
            )
    return els, rels


# -- layout (deterministic; row and slot persist across epochs) -------------------------------------
ROWS = ("persons", "units", "data", "external")
ROW_OF = {
    "person": "persons",
    "system": "system",
    "deployment_unit": "units",
    "static_site": "units",
    "code_container": "units",
    "managed_datastore": "data",
    "managed_queue": "data",
    "bucket": "data",
    "scheduler": "data",
    "external_system": "external",
}
EL_W, EL_H, GAP, PAD = 220.0, 96.0, 28.0, 32.0
COLS, P_COLS = 4, 5  # units and data rows wrap at 4, persons at 5


def place(
    elements: list[dict[str, Any]], prev: dict[str, tuple[str, int]]
) -> list[tuple[str, str, int, float, float, float, float]]:
    """(element_id, row, slot, x, y, w, h) for one environment. An element keeps its previous slot
    while it stays in the same row; new elements take the lowest free slots in id order. Removed
    elements leave their slot free (positions do not shift)."""
    by_row: dict[str, list[str]] = {r: [] for r in (*ROWS, "system")}
    for el in sorted(elements, key=lambda e: e["element_id"]):
        by_row.setdefault(ROW_OF.get(el["kind"], "units"), []).append(el["element_id"])
    slots: dict[str, int] = {}
    for row, members in by_row.items():
        used: set[int] = set()
        for eid in members:
            p = prev.get(eid)
            if p is not None and p[0] == row and p[1] not in used:
                slots[eid] = p[1]
                used.add(p[1])
        nxt = 0
        for eid in members:
            if eid in slots:
                continue
            while nxt in used:
                nxt += 1
            slots[eid] = nxt
            used.add(nxt)

    # rows wrap at COLS (a slot's line and column follow from the slot alone)
    def lines(r: str) -> int:
        top = max((slots[e] for e in by_row.get(r, [])), default=-1)
        return max(1, top // COLS + 1)

    width = min(
        COLS, max([max((slots[e] for e in by_row[r]), default=-1) + 1 for r in ("units", "data")] + [1])
    )
    inner_w = width * (EL_W + GAP) - GAP
    p_lines = max(1, max((slots[e] for e in by_row["persons"]), default=-1) // P_COLS + 1)
    y_units = p_lines * (EL_H * 0.8 + GAP) + 2 * PAD
    y_data = y_units + lines("units") * (EL_H + GAP)
    slab_h = (lines("units") + lines("data")) * (EL_H + GAP) - GAP + 2 * PAD
    out = []
    for row, members in sorted(by_row.items()):
        for eid in members:
            s = slots[eid]
            if row == "persons":
                x = PAD + (s % P_COLS) * (EL_W * 0.7 + GAP)
                y, w, h = (s // P_COLS) * (EL_H * 0.8 + GAP), EL_W * 0.7, EL_H * 0.8
            elif row == "system":  # the system boundary: a slab around units and data
                x, y, w, h = 0.0, y_units - PAD, inner_w + 2 * PAD, slab_h
            elif row == "external":
                x, y, w, h = inner_w + 3 * PAD + GAP, y_units + s * (EL_H + GAP), EL_W, EL_H
            else:
                base = y_units if row == "units" else y_data
                x, y = PAD + (s % COLS) * (EL_W + GAP), base + (s // COLS) * (EL_H + GAP)
                w, h = EL_W, EL_H
            out.append((eid, row, s, round(x, 3), round(y, 3), round(w, 3), round(h, 3)))
    return sorted(out)


def write_layout(conn: Any, epoch_id: str) -> int:
    """c4_layout rows for one epoch from its c4_elements (derived on the fly if not materialized)."""
    from ad2v import materialize, store

    conn.execute("DELETE FROM c4_layout WHERE epoch_id = ?", (epoch_id,))
    els = [dict(r) for r in conn.execute("SELECT * FROM c4_elements WHERE epoch_id = ?", (epoch_id,))]
    if not els and not store.is_materialized(conn, epoch_id):
        d = materialize.derive(conn, epoch_id)
        els, _ = rows(epoch_id, d.graph, d.pairing) if d.graph is not None else ([], [])
    ep = store.get_epoch(conn, epoch_id)
    n = 0
    for env in sorted({e["env"] for e in els}):
        prev = {
            r["element_id"]: (r["row"], r["slot"])
            for r in conn.execute(
                "SELECT element_id, row, slot FROM c4_layout WHERE epoch_id = ? AND env = ?",
                (ep.parent_epoch_id or "", env),
            )
        }
        placed = place([e for e in els if e["env"] == env], prev)
        conn.executemany(
            "INSERT INTO c4_layout VALUES (?,?,?,?,?,?,?,?,?)",
            [(epoch_id, env, *p) for p in placed],
        )
        n += len(placed)
    return n


def ensure_layout(conn: Any, epoch_ids: list[str]) -> list[str]:
    """Lay out the given epochs, oldest first (each one inherits its parent's slots)."""
    from ad2v import store

    wanted = set(epoch_ids)
    done = []
    for r in store.epoch_rows(conn):
        if r["epoch_id"] in wanted:
            write_layout(conn, r["epoch_id"])
            done.append(r["epoch_id"])
    return done


# -- reading and exporting --------------------------------------------------------------------------
def load(conn: Any, epoch_id: str) -> dict[str, Any]:
    """{env: {"elements": [...], "relations": [...], "layout": {...}}} from the file (derived on the
    fly when the epoch is not materialized). No secret ever enters these rows (ADR-0076)."""
    import json

    from ad2v import materialize, store

    if store.is_materialized(conn, epoch_id):
        els = [dict(r) for r in conn.execute("SELECT * FROM c4_elements WHERE epoch_id = ?", (epoch_id,))]
        rels = [dict(r) for r in conn.execute("SELECT * FROM c4_relations WHERE epoch_id = ?", (epoch_id,))]
    else:
        d = materialize.derive(conn, epoch_id)
        els, rels = rows(epoch_id, d.graph, d.pairing) if d.graph is not None else ([], [])
    lay = {
        (r["env"], r["element_id"]): dict(r)
        for r in conn.execute("SELECT * FROM c4_layout WHERE epoch_id = ?", (epoch_id,))
    }
    out: dict[str, Any] = {}
    for e in sorted(els, key=lambda r: (r["env"], r["element_id"])):
        v = out.setdefault(e["env"], {"elements": [], "relations": [], "layout": {}})
        v["elements"].append(
            {
                "id": e["element_id"],
                "level": e["level"],
                "kind": e["kind"],
                "name": e["name"],
                "node_ids": json.loads(e["node_ids_json"]),
                "attrs": json.loads(e["attrs_json"]),
            }
        )
        p = lay.get((e["env"], e["element_id"]))
        if p is not None:
            v["layout"][e["element_id"]] = {k: p[k] for k in ("row", "slot", "x", "y", "w", "h")}
    for r in sorted(rels, key=lambda r: (r["env"], r["src"], r["dst"], r["kind"])):
        out.setdefault(r["env"], {"elements": [], "relations": [], "layout": {}})["relations"].append(
            {"src": r["src"], "dst": r["dst"], "kind": r["kind"], "attrs": json.loads(r["attrs_json"])}
        )
    return out


def pick_env(view: dict[str, Any], env: str | None) -> str:
    if env is not None:
        if env not in view:
            raise KeyError(f"no infra environment {env!r} (have: {', '.join(sorted(view)) or 'none'})")
        return env
    if "default" in view:
        return "default"
    return sorted(view)[0] if view else ""


GENERATED = "Generated by ad2v from the epoch graph (deterministic). Do not edit."


def _q(s: Any) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def structurizr(system: str, env: str, v: dict[str, Any]) -> str:
    """A Structurizr DSL workspace (system context + container views), deterministic."""
    els = {e["id"]: e for e in v["elements"]}
    sys_el = next((e for e in v["elements"] if e["kind"] == "system"), None)
    sys_id = sys_el["id"] if sys_el else "c4_system"
    title = f"{system} ({env})" if env else system
    lines = [
        f"workspace {_q(title)} {_q(GENERATED)} {{",
        "  model {",
    ]
    for e in v["elements"]:
        if e["kind"] == "person":
            k = e["attrs"].get("stories", 0)
            stories = f"{k} user stor{'y' if k == 1 else 'ies'}"
            lines.append(f"    {e['id']} = person {_q(e['name'])} {_q(stories)}")
    lines.append(f"    {sys_id} = softwareSystem {_q(sys_el['name'] if sys_el else system)} {{")
    for e in v["elements"]:
        if e["level"] != "container":
            continue
        a = e["attrs"]
        desc = []
        if a.get("deploys"):
            desc.append("runs " + ", ".join(a["deploys"]))
        if a.get("coverage_worst") and a.get("coverage_worst") != "none":
            desc.append("requirements: " + ", ".join(f"{k} {n}" for k, n in a.get("coverage", {}).items()))
        tech = a.get("type") or ("code container" + (f", {a['language']}" if a.get("language") else ""))
        tags = [e["kind"], str(a.get("infra_status", "unknown"))]
        if e["kind"] in ("managed_datastore", "bucket"):
            tags.append("Database")
        if e["kind"] == "managed_queue":
            tags.append("Queue")
        lines.append(f"      {e['id']} = container {_q(e['name'])} {_q('; '.join(desc))} {_q(tech)} {{")
        lines.append(f"        tags {_q(','.join(tags))}")
        lines.append("      }")
    lines.append("    }")
    for e in v["elements"]:
        if e["kind"] == "external_system":
            lines.append(f"    {e['id']} = softwareSystem {_q(e['name'])} {{")
            lines.append(f"      tags {_q('External')}")
            lines.append("    }")
    for r in v["relations"]:
        if r["src"] not in els or r["dst"] not in els:
            continue
        label = r["kind"] + (f": {', '.join(r['attrs']['env_vars'])}" if r["attrs"].get("env_vars") else "")
        lines.append(f"    {r['src']} -> {r['dst']} {_q(label)}")
    lines += [
        "  }",
        "  views {",
        f"    systemContext {sys_id} {_q('context')} {{",
        "      include *",
        "      autoLayout lr",
        "    }",
        f"    container {sys_id} {_q('containers')} {{",
        "      include *",
        "      autoLayout lr",
        "    }",
        "    styles {",
        f"      element {_q('Person')} {{",
        "        shape person",
        "      }",
        f"      element {_q('Database')} {{",
        "        shape cylinder",
        "      }",
        f"      element {_q('Queue')} {{",
        "        shape pipe",
        "      }",
        f"      element {_q('undeployed')} {{",
        "        border dashed",
        "      }",
        f"      element {_q('infra_orphan')} {{",
        "        border dotted",
        "      }",
        "    }",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"
