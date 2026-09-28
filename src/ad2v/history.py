"""Epoch-to-epoch history: deterministic lineage (renames) and `stale` (format spec §6.6-6.7).

Both run between a new epoch and its parent, after structural pairing and before effective
node statuses. Their results are stored as base facts (`id_lineage`, `link_state`), so any
epoch can later be re-materialized from its own rows.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ad2v import ir
from ad2v.pairing import normalize_path

AGREED = frozenset({"implemented", "verified"})
STALE_REASONS = frozenset({"spec_changed_since", "code_changed_unverified", "fingerprint_mismatch"})
JACCARD_MIN = 0.6
TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Lineage:
    rows: list[tuple[str, str, str, float]] = field(default_factory=list)  # (old, new, method, score)
    forward: dict[str, str] = field(default_factory=dict)  # old id -> new id (applied rows only)

    @property
    def backward(self) -> dict[str, str]:
        return {n: o for o, n in self.forward.items()}

    def ambiguous_reasons(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for old, new, method, score in self.rows:
            if method == "ambiguous":
                out[new].append(
                    {"status": "needs_review", "kind": "lineage_ambiguous", "candidate": old, "score": score}
                )
        return dict(out)


def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 1.0
    return round(len(ta & tb) / len(ta | tb), 4)


def _fingerprint(n: ir.Node) -> str:
    """Content modulo the defined name for functions/classes (body_hash), else content_hash."""
    return str(n.attrs.get("body_hash") or n.content_hash)


def same_code(old: ir.Node | None, new: ir.Node, forward: dict[str, str]) -> bool:
    """Is `new` the same code as `old`, modulo its own name and renamed callees? (ADR-0026)

    Equal fingerprints, or equal `call_masked_hash` with the old callee ids mapped through this
    transition's lineage equal to the new ones: a callee rename changes no caller.
    """
    if old is None:
        return False
    if _fingerprint(old) == _fingerprint(new):
        return True
    a, b = old.attrs.get("call_masked_hash"), new.attrs.get("call_masked_hash")
    if not a or a != b:
        return False
    mapped = [forward.get(x, x) for x in old.attrs.get("call_sites", [])]
    return mapped == list(new.attrs.get("call_sites", []))


def _scope(qname: str) -> str:
    return qname.rsplit("@", 1)[0]


def compute_lineage(parent: ir.Graph, g: ir.Graph) -> Lineage:
    """Rename detection between consecutive epochs. Unmatched removals/additions stay as they are."""
    lin = Lineage()
    removed = sorted(set(parent.nodes) - set(g.nodes))
    added = sorted(set(g.nodes) - set(parent.nodes))
    used_new: set[str] = set()

    # (a) same_content: unique (kind, fingerprint) on both sides
    old_by: dict[tuple[str, str], list[str]] = defaultdict(list)
    new_by: dict[tuple[str, str], list[str]] = defaultdict(list)
    for o in removed:
        n = parent.nodes[o]
        old_by[(n.kind, _fingerprint(n))].append(o)
    for a in added:
        n = g.nodes[a]
        new_by[(n.kind, _fingerprint(n))].append(a)
    for key in sorted(old_by):
        olds, news = old_by[key], new_by.get(key, [])
        if len(olds) == 1 and len(news) == 1:
            lin.rows.append((olds[0], news[0], "same_content", 1.0))
            lin.forward[olds[0]] = news[0]
            used_new.add(news[0])

    # (b) anchored_header: behavior nodes in the same (possibly renamed) enclosing scope
    rem_b = [o for o in removed if o not in lin.forward and parent.nodes[o].kind in ir.BEHAVIOR_KINDS]
    add_b = [a for a in added if a not in used_new and g.nodes[a].kind in ir.BEHAVIOR_KINDS]
    qname_map = {parent.nodes[o].qualified_name: g.nodes[n].qualified_name for o, n in lin.forward.items()}
    pairs: list[tuple[float, str, str]] = []
    for o in rem_b:
        on = parent.nodes[o]
        scope = qname_map.get(_scope(on.qualified_name), _scope(on.qualified_name))
        for a in add_b:
            an = g.nodes[a]
            if an.kind != on.kind or _scope(an.qualified_name) != scope:
                continue
            score = jaccard(str(on.attrs.get("header", "")), str(an.attrs.get("header", "")))
            if score >= JACCARD_MIN:
                pairs.append((score, o, a))
    best_for_old: dict[str, list[tuple[float, str]]] = defaultdict(list)
    best_for_new: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for score, o, a in pairs:
        best_for_old[o].append((score, a))
        best_for_new[a].append((score, o))
    ambiguous_old = {
        o
        for o, c in best_for_old.items()
        if len(c) > 1 and sorted(c, reverse=True)[0][0] == sorted(c, reverse=True)[1][0]
    }
    ambiguous_new = {
        a
        for a, c in best_for_new.items()
        if len(c) > 1 and sorted(c, reverse=True)[0][0] == sorted(c, reverse=True)[1][0]
    }
    for score, o, a in sorted(pairs, key=lambda x: (-x[0], x[1], x[2])):
        if o in ambiguous_old or a in ambiguous_new:
            continue
        if o in lin.forward or a in used_new:
            continue
        lin.rows.append((o, a, "anchored_header", score))
        lin.forward[o] = a
        used_new.add(a)
    for score, o, a in sorted(pairs, key=lambda x: (x[1], x[2])):
        if (o in ambiguous_old or a in ambiguous_new) and o not in lin.forward and a not in used_new:
            lin.rows.append((o, a, "ambiguous", score))

    # (c) same_route: an HTTP port whose id changed but whose (method, normalized path) did not
    def route_key(graph: ir.Graph, nid: str, parent_map: dict[str, str]) -> tuple[str, str, str]:
        n = graph.nodes[nid]
        return (
            parent_map.get(n.parent_id or "", n.parent_id or ""),
            n.attrs.get("method", ""),
            normalize_path(n.attrs.get("path", ""))[0],
        )

    rem_r = [o for o in removed if o not in lin.forward and parent.nodes[o].kind == "http_route"]
    add_r = [a for a in added if a not in used_new and g.nodes[a].kind == "http_route"]
    old_routes: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for o in rem_r:
        old_routes[route_key(parent, o, lin.forward)].append(o)
    new_routes: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for a in add_r:
        new_routes[route_key(g, a, {})].append(a)
    for key in sorted(old_routes):
        olds, news = old_routes[key], new_routes.get(key, [])
        if len(olds) == 1 and len(news) == 1:
            lin.rows.append((olds[0], news[0], "same_route", 1.0))
            lin.forward[olds[0]] = news[0]
            used_new.add(news[0])
    lin.rows.sort(key=lambda r: (r[0], r[1]))
    return lin


def _state(
    lk: ir.Link, status: str, history: list[dict[str, Any]], agreed: tuple[Any, Any, Any]
) -> dict[str, Any]:
    return {
        "link_id": lk.link_id,
        "spec_node_id": lk.spec_node_id,
        "code_node_id": lk.code_node_id,
        "method": lk.method,
        "status": status,
        "history": history,
        "agreed_epoch_id": agreed[0],
        "agreed_spec_hash": agreed[1],
        "agreed_code_hash": agreed[2],
    }


def apply_history(
    g: ir.Graph,
    links: list[ir.Link],
    epoch_id: str,
    parent_graph: ir.Graph | None,
    parent_state: dict[str, dict[str, Any]] | None,
    lineage: Lineage | None,
    tests_fresh: bool,
) -> list[dict[str, Any]]:
    """Adjust link statuses for history (stale) in place; return this epoch's link_state rows."""
    fwd = lineage.forward if lineage else {}
    back = lineage.backward if lineage else {}
    pidx: dict[tuple[Any, Any, str], dict[str, Any]] = {}
    for row in (parent_state or {}).values():
        s = fwd.get(row["spec_node_id"], row["spec_node_id"])
        c = fwd.get(row["code_node_id"], row["code_node_id"])
        pidx[(s, c, row["method"])] = row
    states = []
    for lk in sorted(links, key=lambda x: x.link_id):
        s_id, c_id = lk.spec_node_id, lk.code_node_id
        structural = lk.status
        hist: list[dict[str, Any]] = []
        if s_id is None or c_id is None:
            states.append(_state(lk, structural, hist, (None, None, None)))
            continue
        sn, cn = g.nodes[s_id], g.nodes[c_id]
        sh, ch = sn.content_hash, cn.content_hash
        fp = (cn.attrs.get("spec_ref_fingerprints") or {}).get(sn.qualified_name)
        prow = pidx.get((s_id, c_id, lk.method))
        final = structural
        if prow is None:
            if fp and structural in AGREED:
                if fp != sh[:8]:
                    final = "stale"
                    hist.append({"kind": "fingerprint_mismatch", "fingerprint": fp, "spec": sh[:8]})
                else:
                    hist.append({"kind": "reannotated", "fingerprint": fp})
            agreed = (epoch_id, sh, ch) if final in AGREED else (None, None, None)
        else:
            prev = prow["status"]
            since = prow["agreed_epoch_id"]
            carried = [h for h in prow["history"] if h.get("kind") in STALE_REASONS]
            ps = parent_graph.nodes.get(back.get(s_id, s_id)) if parent_graph else None
            pc = parent_graph.nodes.get(back.get(c_id, c_id)) if parent_graph else None
            # compare name-masked fingerprints: a pure rename (lineage same_content) is no change
            spec_changed = ps is None or _fingerprint(ps) != _fingerprint(sn)
            code_changed = not same_code(pc, cn, fwd)
            content_same = not spec_changed and not code_changed and back.get(c_id, c_id) == c_id
            if cn.attrs.get("is_test"):
                code_changed = False  # a test is verification evidence, not the implementation
            reason = carried[0]["kind"] if carried else None
            if structural not in AGREED:
                final = structural
            elif fp and fp != sh[:8]:
                final = "stale"
                hist.append({"kind": "fingerprint_mismatch", "fingerprint": fp, "spec": sh[:8]})
            elif fp and fp == sh[:8] and (prev == "stale" or spec_changed):
                final = structural
                hist.append({"kind": "reannotated", "fingerprint": fp})
            elif spec_changed and code_changed:
                final = structural
                hist.append({"kind": "both_changed"})
            elif spec_changed:
                final = "stale"
                hist.append({"kind": "spec_changed_since", "since": since})
            elif code_changed:
                if prev == "verified" or (prev == "stale" and reason == "code_changed_unverified"):
                    if structural == "verified" and tests_fresh:
                        final = "verified"
                        hist.append({"kind": "retested"})
                    else:
                        final = "stale"
                        hist.append({"kind": "code_changed_unverified", "since": since})
                elif prev == "stale":
                    final, hist = "stale", list(carried)
                else:
                    hist.append({"kind": "code_changed_since", "since": since})
            elif prev == "stale":
                spec_same = sh == prow["agreed_spec_hash"]
                if (
                    reason == "code_changed_unverified"
                    and structural == "verified"
                    and tests_fresh
                    and spec_same
                ):
                    final = "verified"
                    hist.append({"kind": "retested"})
                else:
                    final, hist = "stale", list(carried)
            callee_renamed = pc is not None and not code_changed and _fingerprint(pc) != _fingerprint(cn)
            if callee_renamed and not cn.attrs.get("is_test"):
                hist.append({"kind": "callee_renamed"})  # same code modulo renamed callees (ADR-0026)
            if (  # only the descendants moved: evidence, never a status change (not for renames)
                ps is not None
                and pc is not None
                and content_same
                and not callee_renamed
                and (ps.subtree_hash != sn.subtree_hash or pc.subtree_hash != cn.subtree_hash)
            ):
                hist.append({"kind": "descendants_changed"})
            if final in AGREED:
                agreed = (epoch_id, sh, ch)
            else:
                agreed = (prow["agreed_epoch_id"], prow["agreed_spec_hash"], prow["agreed_code_hash"])
        lk.status = final
        lk.evidence.extend(h for h in hist if h not in lk.evidence)
        states.append(_state(lk, final, hist, agreed))
    return states


def replay_state(links: list[ir.Link], state: dict[str, dict[str, Any]]) -> None:
    """Re-apply stored link_state rows to freshly computed structural links (materialize on demand)."""
    for lk in links:
        row = state.get(lk.link_id)
        if row is None:
            continue
        lk.status = row["status"]
        lk.evidence.extend(h for h in row["history"] if h not in lk.evidence)
