"""Static workflow traces and detail projection (format spec §7)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ad2v import ir
from ad2v.extract.code.base import CodeFacts
from ad2v.manifest import Config

PORT_KINDS = frozenset(ir.PORT_KINDS)


class _Budget(Exception):
    pass


def trace_port(
    graph: ir.Graph, facts: CodeFacts, port_id: str, handler_id: str, max_depth: int, max_steps: int
) -> tuple[list[ir.WorkflowStep], bool]:
    """Finest-level DFS trace from an entry port. Returns (steps, truncated)."""
    steps: list[ir.WorkflowStep] = []

    def emit(node_ids: list[str], depth: int) -> None:
        if len(steps) >= max_steps:
            raise _Budget
        dedup = list(dict.fromkeys(node_ids))
        steps.append(ir.WorkflowStep(len(steps), dedup, depth))

    def visit(targets: tuple[str, ...], prefix: tuple[str, ...], depth: int, stack: tuple[str, ...]) -> None:
        if depth > max_depth:
            return
        nodes = list(prefix)
        for t in targets:
            nodes.extend(facts.wrappers.get(t, []))
            nodes.append(t)
        emit(nodes, depth)
        for t in targets:
            if t in stack or depth + 1 > max_depth:
                continue
            for ev in facts.events.get(t, []):
                if ev.kind == "touch":
                    if depth + 1 <= max_depth:
                        emit(list(ev.behaviors) + list(ev.targets), depth + 1)
                else:
                    visit(ev.targets, ev.behaviors, depth + 1, stack + (t,))

    truncated = False
    try:
        emit([port_id], 0)
        visit((handler_id,), (), 1, (port_id,))
    except _Budget:
        truncated = True
    return steps, truncated


def build_all(graph: ir.Graph, facts: CodeFacts, config: Config) -> list[ir.Workflow]:
    out: list[ir.Workflow] = []
    for port_id, handler_id in sorted(facts.entry_ports):
        port = graph.nodes[port_id]
        steps, truncated = trace_port(
            graph, facts, port_id, handler_id, config.workflow_max_depth, config.workflow_max_steps
        )
        attrs = {"max_depth": config.workflow_max_depth, "truncated": truncated, "port_kind": port.kind}
        out.append(ir.Workflow(port.name, "code", port_id, "static", steps, attrs=attrs))
    out.extend(spec_workflows(graph))
    return sorted(out, key=lambda w: w.workflow_id)


def spec_workflows(graph: ir.Graph) -> list[ir.Workflow]:
    kids = graph.children()
    out = []
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        if n.kind != "scenario" or n.attrs.get("background"):
            continue
        feature = graph.nodes[n.parent_id] if n.parent_id else None
        backgrounds = []
        if feature is not None:
            backgrounds = [
                graph.nodes[c]
                for c in kids[feature.id]
                if graph.nodes[c].kind == "scenario"
                and graph.nodes[c].attrs.get("background")
                and graph.nodes[c].attrs.get("rule") in (None, n.attrs.get("rule"))
            ]
        step_nodes: list[ir.Node] = []
        for b in sorted(backgrounds, key=lambda x: x.span_start_line or 0):
            step_nodes += sorted((graph.nodes[c] for c in kids[b.id]), key=lambda x: x.span_start_line or 0)
        step_nodes += sorted((graph.nodes[c] for c in kids[nid]), key=lambda x: x.span_start_line or 0)
        steps = [ir.WorkflowStep(i, [s.id], 0) for i, s in enumerate(step_nodes)]
        if not steps:
            steps = [ir.WorkflowStep(0, [nid], 0)]
        out.append(ir.Workflow(n.name, "spec", nid, "static", steps, scenario_id=nid, attrs={}))
    return out


# ---------------------------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CoarseStep:
    seq: int
    node_ids: list[str]  # nodes of the anchor step
    touched: list[str]  # union of all nodes in the span, first-seen order
    depth: int
    span: tuple[int, int]  # inclusive fine seq range


def project(
    steps: Sequence[ir.WorkflowStep], detail_level: int
) -> tuple[list[CoarseStep], list[tuple[int, int]]]:
    """Collapse a fine trace to `detail_level`.

    Step i joins the group anchored at g(i) = max{ j <= i : depth_j <= k }; steps before any
    such j form one leading group. Groups are contiguous and partition the trace.
    Returns (coarse_steps, fine_span_per_coarse_step).
    """
    if detail_level < 0:
        raise ValueError("detail_level must be >= 0")
    groups: list[list[int]] = []
    anchor_of: list[int | None] = []
    for i, s in enumerate(steps):
        if s.depth <= detail_level:
            groups.append([i])
            anchor_of.append(i)
        elif not groups:  # leading steps deeper than k, before any anchor
            groups.append([i])
            anchor_of.append(None)
        else:
            groups[-1].append(i)
    coarse: list[CoarseStep] = []
    spans: list[tuple[int, int]] = []
    for gi, (members, anchor) in enumerate(zip(groups, anchor_of, strict=True)):
        a = steps[anchor] if anchor is not None else steps[members[0]]
        touched = list(dict.fromkeys(n for m in members for n in steps[m].node_ids))
        span = (steps[members[0]].seq, steps[members[-1]].seq)
        coarse.append(CoarseStep(gi, list(a.node_ids), touched, a.depth, span))
        spans.append(span)
    return coarse, spans
