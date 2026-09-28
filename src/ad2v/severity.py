"""Deterministic risk severity for behavior nodes (format spec §3.8, ADR-0014).

severity = (max base weight over the node's risk flags + nesting bonuses) * reach_factor
reach_factor = `unreachable` when no code workflow passes through the node, otherwise
               min(cap, reachable + per_extra_workflow * (workflows - 1))

Weights come from the rules (`severity:`), so they are covered by rules_hash. Severity is
rounded to 4 decimals so the float is stable across platforms. severity_rank orders all
behavior nodes: 1 = worst, ties broken by node id.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ad2v import ir

BEHAVIOR_KINDS = frozenset(ir.BEHAVIOR_KINDS)


def workflow_reach(workflows: list[ir.Workflow]) -> dict[str, int]:
    """Number of distinct code-side workflows whose steps include each node."""
    seen: dict[str, set[str]] = defaultdict(set)
    for w in workflows:
        if w.side != "code":
            continue
        for s in w.steps:
            for n in s.node_ids:
                seen[n].add(w.workflow_id)
    return {n: len(ws) for n, ws in seen.items()}


def score(risk: list[str], reach: int, weights: dict[str, Any]) -> float:
    base_w = weights.get("base", {})
    bonus_w = weights.get("nesting_bonus", {})
    r = weights.get("reach", {})
    base = max((float(base_w.get(f, 0)) for f in risk), default=0.0)
    bonus = sum(float(bonus_w.get(f, 0)) for f in risk)
    if reach <= 0:
        factor = float(r.get("unreachable", 1.0))
    else:
        factor = min(
            float(r.get("cap", 2.5)),
            float(r.get("reachable", 1.5)) + float(r.get("per_extra_workflow", 0.1)) * (reach - 1),
        )
    return round((base + bonus) * factor, 4)


def apply(graph: ir.Graph, workflows: list[ir.Workflow], rules: dict[str, Any]) -> list[str]:
    """Set attrs.severity / severity_reach / severity_rank on behavior nodes. Returns ids by rank."""
    weights = rules.get("severity", {})
    reach = workflow_reach(workflows)
    behavior = [nid for nid in sorted(graph.nodes) if graph.nodes[nid].kind in BEHAVIOR_KINDS]
    for nid in behavior:
        a = graph.nodes[nid].attrs
        a["severity_reach"] = reach.get(nid, 0)
        a["severity"] = score(list(a.get("risk", [])), a["severity_reach"], weights)
    ranked = sorted(behavior, key=lambda n: (-graph.nodes[n].attrs["severity"], n))
    for i, nid in enumerate(ranked, start=1):
        graph.nodes[nid].attrs["severity_rank"] = i
    return ranked
