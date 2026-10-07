"""Deterministic spec<->code pairing, link statuses, effective node statuses and roll-ups.

Format spec §6. Everything here is normative: no fuzzy matching, no LLM (that is P4).

Pairing methods, in priority order:
  1. annotation   explicit `annotated_as` edges code -> spec (comments, docstrings, test names)
  2. route_match  http_route <-> spec_endpoint on (METHOD, normalized path)
  3. manifest     `pairing.components: {CMP-001: api}` in ad2v.yaml
  4. name_match   spec_component <-> container/component with exactly equal slugs
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ad2v import ids, ir, scope
from ad2v.manifest import Config

PORT_KINDS = frozenset(ir.PORT_KINDS)
STRUCTURAL_ORPHAN_KINDS = frozenset({"container", "component"})
ORPHAN_KINDS = PORT_KINDS | STRUCTURAL_ORPHAN_KINDS
# When a confirmed `pairing.links` code name matches several nodes, the first kind here wins.
MANIFEST_LINK_CODE_KINDS = (
    "function",
    "class",
    "http_route",
    "mcp_tool",
    "cli_command",
    "event_consumer",
    "module",
    "component",
    "container",
)
RANK = {s: i for i, s in enumerate(ir.STATUS_PRECEDENCE)}  # 0 = highest precedence
INHERITABLE = frozenset({"implemented", "verified", "specified"})
PARAM_RE = re.compile(r"\{[^}]*\}")


@dataclass
class PairingResult:
    links: list[ir.Link]
    statuses: dict[str, ir.NodeStatus]
    rollup: dict[str, dict[str, int]]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def normalize_path(
    path: str,
    base: str = "",
    prefix_map: dict[str, str] | None = None,
    case_insensitive: bool = False,
) -> tuple[str, list[str]]:
    """Normalize an HTTP path for pairing (format spec §6.1). Returns (key path, param names).

    base (OpenAPI servers[0] path) is prepended; the longest matching `prefix_map` key (on a
    segment boundary) is replaced; `{param}` -> `{}`; `//` collapsed; trailing `/` stripped
    (except root); literal segments lowercased only when case_insensitive.
    """
    p = "/" + "/".join(x for x in (base.strip("/"), path.strip("/")) if x)
    p = re.sub(r"/+", "/", p)
    for k in sorted(prefix_map or {}, key=lambda x: (-len(x), x)):
        kk = "/" + k.strip("/") if k.strip("/") else "/"
        if kk == "/" or p == kk or p.startswith(kk + "/"):
            rest = p[len(kk) :] if kk != "/" else p
            p = "/" + "/".join(x for x in ((prefix_map or {})[k].strip("/"), rest.strip("/")) if x)
            break
    names = PARAM_RE.findall(p)
    names = [n[1:-1] for n in names]
    p = PARAM_RE.sub("{}", p)
    p = re.sub(r"/+", "/", p)
    if len(p) > 1:
        p = p.rstrip("/") or "/"
    if case_insensitive:
        p = p.lower()
    return p, names


class _Links:
    def __init__(self) -> None:
        self.by_id: dict[str, ir.Link] = {}

    def add(self, link: ir.Link) -> ir.Link:
        existing = self.by_id.get(link.link_id)
        if existing is not None:
            existing.evidence.extend(e for e in link.evidence if e not in existing.evidence)
            if RANK[link.status] < RANK[existing.status]:
                existing.status = link.status
            return existing
        self.by_id[link.link_id] = link
        return link

    def all(self) -> list[ir.Link]:
        return [self.by_id[k] for k in sorted(self.by_id)]


def _q(graph: ir.Graph, nid: str | None) -> str | None:
    return graph.nodes[nid].qualified_name if nid else None


SPEC_ITEM_KINDS = frozenset({"requirement", "scenario", "spec_component", "spec_endpoint"})


def spec_coverage(graph: ir.Graph) -> str:
    """'present' if the epoch has any spec item, else 'none' (format spec §6.2, orphan_policy)."""
    return "present" if any(n.kind in SPEC_ITEM_KINDS for n in graph.nodes.values()) else "none"


def assigns_orphans(graph: ir.Graph, config: Config) -> bool:
    if config.orphan_policy == "off":
        return False
    if config.orphan_policy == "auto":
        return spec_coverage(graph) == "present"
    return True


def pair(graph: ir.Graph, config: Config, tests: dict[str, ir.TestResult] | None = None) -> PairingResult:
    """Structural pairing and statuses for one epoch without history (see ad2v.history for stale)."""
    links, warnings = pair_links(graph, config, tests)
    return finalize(graph, links, warnings)


def pair_links(
    graph: ir.Graph, config: Config, tests: dict[str, ir.TestResult] | None = None
) -> tuple[list[ir.Link], list[dict[str, Any]]]:
    tests = tests or {}
    nodes = graph.nodes
    links = _Links()
    warnings: list[dict[str, Any]] = []
    by_kind: dict[str, list[str]] = defaultdict(list)
    for nid in sorted(nodes):
        by_kind[nodes[nid].kind].append(nid)

    # 1. annotation --------------------------------------------------------------------------
    for (src, kind, dst), edge in sorted(graph.edges.items()):
        if kind == "annotated_as" and nodes[src].side == "code" and nodes[dst].side == "spec":
            ref = edge.attrs.get("ref", nodes[dst].qualified_name)
            sources = nodes[src].attrs.get("spec_ref_sources", {}).get(ref, [])
            ev: list[dict[str, Any]] = [{"kind": "annotation", "ref": ref, "sources": sources}]
            status = "implemented"
            if edge.attrs.get("ambiguous"):  # a bare id that several namespaces define (ADR-0048)
                status = "needs_review"
                ev.append({"kind": "ambiguous_spec_ref", "ref": ref, "candidates": edge.attrs["ambiguous"]})
            links.add(ir.Link(dst, src, status, "annotation", ev))

    # 2. route_match -------------------------------------------------------------------------
    pm, ci = config.path_prefix_map, config.case_insensitive
    routes: dict[tuple[str, str], list[tuple[str, list[str]]]] = defaultdict(list)
    for nid in by_kind["http_route"]:
        a = nodes[nid].attrs
        key, names = normalize_path(a["path"], "", pm, ci)
        routes[(a["method"], key)].append((nid, names))
    endpoints: dict[tuple[str, str], list[tuple[str, list[str]]]] = defaultdict(list)
    for nid in by_kind["spec_endpoint"]:
        a = nodes[nid].attrs
        key, names = normalize_path(a["path"], a.get("base_path", ""), pm, ci)
        endpoints[(a["method"], key)].append((nid, names))
    for key in sorted(endpoints):
        eps, rts = endpoints[key], routes.get(key, [])
        if not rts:
            continue
        ambiguous = len(eps) > 1 or len(rts) > 1
        for ep, ep_names in eps:
            for rt, rt_names in rts:
                ev: list[dict[str, Any]] = [
                    {"kind": "route_match", "method": key[0], "normalized_path": key[1]}
                ]
                if ep_names != rt_names:
                    ev.append({"kind": "param_name_mismatch", "spec": ep_names, "code": rt_names})
                ev.extend(_prefix_evidence(nodes[rt].attrs))
                drift = _structural_drift(graph, ep, rt, len(rt_names))
                ev.extend(drift)
                if ambiguous:
                    ev.append(
                        {
                            "kind": "ambiguous",
                            "spec_candidates": sorted(_q(graph, e) for e, _ in eps),
                            "code_candidates": sorted(_q(graph, r) for r, _ in rts),
                        }
                    )
                status = "drift" if drift else ("needs_review" if ambiguous else "implemented")
                links.add(ir.Link(ep, rt, status, "route_match", ev))

    # 3. manifest ----------------------------------------------------------------------------
    manifested: set[str] = set()
    for spec_id, target in sorted(config.pairing_components.items()):
        specs = [n for n in by_kind["spec_component"] if nodes[n].qualified_name == spec_id]
        if not specs:
            warnings.append({"kind": "manifest_spec_id_not_found", "spec_id": spec_id})
            continue
        code = _structural_target(graph, target)
        for s in specs:
            manifested.add(s)
            if code is None:
                links.add(
                    ir.Link(s, None, "missing", "manifest", [{"kind": "target_not_found", "target": target}])
                )
            else:
                links.add(
                    ir.Link(s, code, "implemented", "manifest", [{"kind": "manifest", "target": target}])
                )

    # 4. name_match --------------------------------------------------------------------------
    structural = by_kind["container"] + by_kind["component"]
    for s in by_kind["spec_component"]:
        if s in manifested:
            continue
        want = slug(nodes[s].name)
        cands = [c for c in structural if want and slug(nodes[c].name) == want]
        for c in cands:
            ev = [{"kind": "name_match", "slug": want}]
            if len(cands) > 1:
                ev.append({"kind": "ambiguous", "code_candidates": sorted(_q(graph, x) for x in cands)})
            links.add(ir.Link(s, c, "needs_review" if len(cands) > 1 else "implemented", "name_match", ev))

    # 5. manifest_link: human-confirmed pairs (accepted suggestions, `pairing.links`) ------------
    code_kind_order = {k: i for i, k in enumerate(MANIFEST_LINK_CODE_KINDS)}
    for spec_q, code_q in config.pairing_links:
        specs = sorted(n for n in nodes if nodes[n].side == "spec" and nodes[n].qualified_name == spec_q)
        if not specs:
            warnings.append({"kind": "manifest_link_spec_not_found", "spec": spec_q})
            continue
        codes = sorted(
            (n for n in nodes if nodes[n].side == "code" and nodes[n].qualified_name == code_q),
            key=lambda n: (code_kind_order.get(nodes[n].kind, 99), n),
        )
        for s in specs[:1]:
            if not codes:
                links.add(
                    ir.Link(
                        s, None, "missing", "manifest_link", [{"kind": "target_not_found", "target": code_q}]
                    )
                )
            else:
                links.add(
                    ir.Link(
                        s,
                        codes[0],
                        "implemented",
                        "manifest_link",
                        [{"kind": "manifest_link", "code": code_q}],
                    )
                )

    # verification from linked tests -----------------------------------------------------------
    test_ids = [n for n in by_kind["function"] if nodes[n].attrs.get("is_test")]
    for link in links.all():
        if link.spec_node_id is None or link.code_node_id is None:
            continue
        spec = nodes[link.spec_node_id]
        wanted = {spec.qualified_name, *spec.spec_ref}
        linked = [t for t in test_ids if wanted & set(nodes[t].spec_ref)]
        outcomes = {t: tests[t].outcome for t in linked if t in tests}
        passed = sorted(_q(graph, t) or "" for t, o in outcomes.items() if o == "passed")
        failed = sorted(_q(graph, t) or "" for t, o in outcomes.items() if o == "failed")
        if passed:
            link.evidence.append({"kind": "tests_passed", "tests": passed})
        if failed:
            link.evidence.append({"kind": "tests_failed", "tests": failed})
        if passed and link.status == "implemented":
            link.status = "verified"

    # routes whose path could not be resolved statically (P6.1, ADR-0046) --------------------
    # An unpaired spec endpoint is offered every unresolved route with the same method whose
    # known tail ends its path (or, with no tail, whose known prefix starts it): needs_review,
    # never a false `missing`.
    unresolved = [nid for nid in by_kind["http_route"] if nodes[nid].attrs.get("path_unresolved")]
    if unresolved:
        paired_now = {lk.spec_node_id for lk in links.all() if lk.spec_node_id}
        for ep in by_kind["spec_endpoint"]:
            if ep in paired_now:
                continue
            a = nodes[ep].attrs
            key, _ = normalize_path(a["path"], a.get("base_path", ""), pm, ci)
            for rt in sorted(unresolved):
                ra = nodes[rt].attrs
                if ra["method"] != a["method"]:
                    continue
                tail = ra.get("path_tail") or ""
                if tail:
                    tkey = normalize_path(tail, "", None, ci)[0]
                    hit = tkey != "/" and key.endswith(tkey)
                else:
                    pkey = normalize_path(ra["path"], "", None, ci)[0]
                    hit = pkey != "/" and key.startswith(pkey)
                if hit:
                    links.add(
                        ir.Link(
                            ep,
                            rt,
                            "needs_review",
                            "route_match",
                            [{"kind": "unresolved_route_path", "route_path": ra["path"], "known_tail": tail}],
                        )
                    )

    # code ad2v cannot read (P8.1, ADR-0066): implemented there means "not evaluable" -----------
    out_of_scope = _out_of_scope(graph)
    for lk in links.all():
        if lk.code_node_id in out_of_scope and lk.status == "implemented":
            lk.status = "not_evaluable"
            lk.evidence.append(out_of_scope[lk.code_node_id])
            refs = nodes[lk.code_node_id].attrs.get("spec_ref_sources", {})
            ref = next((e.get("ref") for e in lk.evidence if e.get("kind") == "annotation"), None)
            if ref is not None and "test_title" in refs.get(ref, []):  # P9 (ADR-0070)
                lk.evidence.append({"kind": "test_in_unread_language"})
    # P9 (ADR-0070, issue 95): a spec component paired with code nobody reads makes its unpaired
    # requirements not_evaluable too
    comp_scope: dict[str, dict[str, Any]] = {}
    for lk in links.all():
        if (
            lk.status == "not_evaluable"
            and lk.spec_node_id is not None
            and lk.code_node_id is not None
            and nodes[lk.spec_node_id].kind == "spec_component"
        ):
            ev = out_of_scope.get(lk.code_node_id, {})
            comp_scope[lk.spec_node_id] = {
                "kind": "component_out_of_scope",
                "component": nodes[lk.spec_node_id].qualified_name,
                "languages": ev.get("languages", []),
            }

    # unpaired spec items ----------------------------------------------------------------------
    paired_spec = {lk.spec_node_id for lk in links.all() if lk.spec_node_id}
    for nid in by_kind["spec_endpoint"]:
        if nid not in paired_spec:
            links.add(ir.Link(nid, None, "missing", "none", [{"kind": "no_matching_route"}]))
    spec_anc = _ancestors(graph) if comp_scope else {}
    for kind in ("requirement", "scenario", "spec_component"):
        for nid in by_kind[kind]:
            if nid not in paired_spec:
                comp = next((a for a in spec_anc.get(nid, []) if a in comp_scope), None)
                if kind == "requirement" and comp is not None:
                    links.add(ir.Link(nid, None, "not_evaluable", "none", [comp_scope[comp]]))
                else:
                    links.add(ir.Link(nid, None, "specified", "none", [{"kind": "no_deterministic_pair"}]))

    # orphans ----------------------------------------------------------------------------------
    code_linked = {lk.code_node_id for lk in links.all() if lk.code_node_id and lk.spec_node_id}
    structural_linked = {c for c in code_linked if nodes[c].kind in STRUCTURAL_ORPHAN_KINDS}
    anc = _ancestors(graph)
    orphan_candidates = (
        sorted(n for k in ORPHAN_KINDS for n in by_kind[k]) if assigns_orphans(graph, config) else []
    )
    for nid in sorted(n for n in out_of_scope if n not in code_linked):  # never an orphan
        links.add(ir.Link(None, nid, "not_evaluable", "none", [out_of_scope[nid]]))
    for nid in orphan_candidates:
        node = nodes[nid]
        if nid in code_linked or nid in out_of_scope:
            continue
        if node.kind in PORT_KINDS and _handler(graph, node) in code_linked:
            continue
        if any(a in structural_linked for a in anc[nid]):
            continue
        links.add(ir.Link(None, nid, "orphan", "none", [{"kind": "no_spec_link"}]))

    return links.all(), warnings


def finalize(
    graph: ir.Graph,
    links: list[ir.Link],
    warnings: list[dict[str, Any]] | None = None,
    extra_reasons: dict[str, list[dict[str, Any]]] | None = None,
) -> PairingResult:
    """Effective node statuses and roll-ups from final link statuses (format spec §6.4)."""
    links = sorted(links, key=lambda lk: lk.link_id)
    statuses = _node_statuses(graph, links, _ancestors(graph), extra_reasons or {})
    return PairingResult(links, statuses, _rollup(graph, statuses), list(warnings or []))


def _out_of_scope(graph: ir.Graph) -> dict[str, dict[str, Any]]:
    """Unextracted modules, and containers/components whose modules are all unextracted, with the
    evidence that says why (the languages)."""
    nodes = graph.nodes
    out: dict[str, dict[str, Any]] = {}
    langs: dict[str, set[str]] = defaultdict(set)  # structural node -> languages below it
    evaluable: set[str] = set()  # structural nodes with at least one extracted module below
    anc = _ancestors(graph)
    for nid in sorted(nodes):
        n = nodes[nid]
        if n.kind != "module" or n.side != "code":
            continue
        if scope.is_unextracted(n):
            lang = str(n.attrs.get("language"))
            out[nid] = {"kind": "language_out_of_scope", "languages": [lang]}
            for a in anc[nid]:
                langs[a].add(lang)
        else:
            evaluable.update(anc[nid])
    for nid, ls in sorted(langs.items()):
        if nid not in evaluable and nodes[nid].kind in STRUCTURAL_ORPHAN_KINDS:
            out[nid] = {"kind": "language_out_of_scope", "languages": sorted(ls)}
    return out


def _handler(graph: ir.Graph, port: ir.Node) -> str | None:
    h = port.attrs.get("handler")
    nid = ids.node_id("code", "function", h) if h else None
    return nid if nid in graph.nodes else None


def _structural_target(graph: ir.Graph, target: str) -> str | None:
    for kind, qn in (("container", f"container:{target}"), ("container", target), ("component", target)):
        nid = ids.node_id("code", kind, qn)
        if nid in graph.nodes:
            return nid
    return None


def _prefix_evidence(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """P7 (ADR-0053): where a route's prefix came from, when it was not a literal in the code."""
    out: list[dict[str, Any]] = []
    for src in attrs.get("prefix_sources", []):
        kind, _, expr = src.partition(":")
        if kind == "path_constants":
            out.append({"kind": "prefix_from_path_constants", "expression": expr})
        elif kind == "settings_default":
            out.append(
                {
                    "kind": "prefix_from_settings_default",
                    "setting": expr,
                    "warning": "a default; the environment can override it at run time",
                }
            )
    return out


def _structural_drift(graph: ir.Graph, ep: str, rt: str, route_params: int) -> list[dict[str, Any]]:
    """Structural drift between a spec endpoint and a route (format spec §6.3)."""
    out: list[dict[str, Any]] = []
    a = graph.nodes[ep].attrs
    declared = a.get("path_params", [])
    if declared and len(declared) != route_params:
        out.append({"kind": "path_param_count", "spec": len(declared), "code": route_params})
    handler = _handler(graph, graph.nodes[rt])
    if handler is not None:
        h = graph.nodes[handler].attrs
        if not h.get("var_kwargs"):
            missing = [q for q in a.get("required_query", []) if q not in h.get("params", [])]
            if missing:
                out.append(
                    {
                        "kind": "required_query_param_missing",
                        "params": missing,
                        "handler": graph.nodes[handler].qualified_name,
                    }
                )
    return out


def _ancestors(graph: ir.Graph) -> dict[str, list[str]]:
    """{node: [parent, grandparent, ...]} (nearest first)."""
    out: dict[str, list[str]] = {}
    for nid in sorted(graph.nodes):
        chain, cur, seen = [], graph.nodes[nid].parent_id, {nid}
        while cur is not None and cur in graph.nodes and cur not in seen:
            chain.append(cur)
            seen.add(cur)
            cur = graph.nodes[cur].parent_id
        out[nid] = chain
    return out


def _node_statuses(
    graph: ir.Graph,
    links: list[ir.Link],
    anc: dict[str, list[str]],
    extra_reasons: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, ir.NodeStatus]:
    nodes = graph.nodes
    own: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lk in links:
        for nid, other in ((lk.spec_node_id, lk.code_node_id), (lk.code_node_id, lk.spec_node_id)):
            if nid is not None:
                own[nid].append(
                    {
                        "status": lk.status,
                        "kind": "link",
                        "link_id": lk.link_id,
                        "method": lk.method,
                        "other": _q(graph, other),
                    }
                )
    for nid in sorted(nodes):  # ports take their handler's links when they have none of their own
        n = nodes[nid]
        if n.kind in PORT_KINDS and nid not in own:
            h = _handler(graph, n)
            for r in list(own.get(h, [])) if h else []:
                own[nid].append({**r, "kind": "via_handler", "handler": _q(graph, h)})
    for u in graph.unresolved:
        own[u.src].append({"status": "needs_review", "kind": "unresolved_ref", "ref": u.ref})
    # P9 (ADR-0072): a scenario shows the statuses of the requirements it references (its tags),
    # next to its own; a step is text inside its scenario and carries no status
    by_q = {n.qualified_name: nid for nid, n in nodes.items() if n.side == "spec" and n.kind == "requirement"}
    req_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lk in links:
        if lk.spec_node_id is not None and nodes[lk.spec_node_id].kind == "requirement":
            req_links[lk.spec_node_id].append({"status": lk.status})
    for nid in sorted(nodes):
        n = nodes[nid]
        if n.kind != "scenario":
            continue
        for ref in sorted(set(n.spec_ref)):
            rid = by_q.get(ref)
            for st in sorted({r["status"] for r in req_links.get(rid, [])} if rid else set()):
                own[nid].append({"status": st, "kind": "via_spec_ref", "ref": ref})
    for nid, extra in sorted((extra_reasons or {}).items()):
        if nid in nodes:
            own[nid].extend(extra)

    out: dict[str, ir.NodeStatus] = {}
    for nid in sorted(nodes, key=lambda x: (len(anc[x]), x)):  # parents before children
        if nodes[nid].kind == "scenario_step":
            out[nid] = ir.NodeStatus(nid, "none", [{"status": "none", "kind": "step"}])
            continue
        reasons = sorted(own.get(nid, []), key=ids.canonical_json)
        if reasons:
            status = min((r["status"] for r in reasons), key=RANK.__getitem__)
        else:
            parent = anc[nid][0] if anc[nid] else None
            ps = out[parent].status if parent is not None else "none"
            if ps in INHERITABLE:
                status = ps
                reasons = [{"status": ps, "kind": "inherited", "from": _q(graph, parent)}]
            else:
                status = "none"
                reasons = [{"status": "none", "kind": "no_coverage"}]
        out[nid] = ir.NodeStatus(nid, status, reasons)
    return out


def _rollup(graph: ir.Graph, statuses: dict[str, ir.NodeStatus]) -> dict[str, dict[str, int]]:
    kids = graph.children()
    memo: dict[str, dict[str, int]] = {}

    def visit(nid: str) -> dict[str, int]:
        if nid not in memo:
            acc: dict[str, int] = defaultdict(int)
            for c in kids[nid]:
                acc[statuses[c].status] += 1
                for k, v in visit(c).items():
                    acc[k] += v
            memo[nid] = dict(sorted(acc.items()))
        return memo[nid]

    return {nid: visit(nid) for nid in sorted(graph.nodes) if kids[nid]}
