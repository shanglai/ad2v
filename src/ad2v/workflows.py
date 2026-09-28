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
    node_ids: list[str]  # what the coarse step highlights (see project())
    touched: list[str]  # union of all nodes in the span, first-seen order
    depth: int
    span: tuple[int, int]  # inclusive fine seq range


def ancestry(graph: ir.Graph) -> dict[str, list[str]]:
    """{node_id: [root, ..., node_id]} along parent_id (the `contains` hierarchy)."""
    memo: dict[str, list[str]] = {}

    def chain(nid: str) -> list[str]:
        if nid not in memo:
            parent = graph.nodes[nid].parent_id
            memo[nid] = (chain(parent) if parent is not None and parent in graph.nodes else []) + [nid]
        return memo[nid]

    for nid in sorted(graph.nodes):
        chain(nid)
    return memo


def step_nodes(workflows: Sequence[ir.Workflow]) -> list[tuple[str, int, str]]:
    """Rows of the derived `workflow_step_nodes` table: (workflow_id, seq, node_id), sorted."""
    return sorted({(w.workflow_id, s.seq, n) for w in workflows for s in w.steps for n in s.node_ids})


def _group(keys: Sequence[object]) -> list[list[int]]:
    groups: list[list[int]] = []
    prev: object = object()
    for i, k in enumerate(keys):
        if groups and k == prev:
            groups[-1].append(i)
        else:
            groups.append([i])
        prev = k
    return groups


def project(
    steps: Sequence[ir.WorkflowStep],
    depth: int,
    mode: str = "containment",
    ancestry_map: dict[str, list[str]] | None = None,
) -> tuple[list[CoarseStep], list[tuple[int, int]]]:
    """Collapse a fine trace to detail `depth` (format spec §7, ADR-0009 amended by ADR-0013).

    mode="containment" (default, follows the viewer's zoom): a step's key is the tuple of the
    ancestors at relative containment depth `depth` of its nodes (a node shallower than `depth`
    is its own key). Consecutive steps with equal keys merge. The coarse step highlights those
    ancestors, i.e. the glyphs visible at that zoom. Requires `ancestry_map` (see ancestry()).

    mode="call_depth": step i joins the group anchored at g(i) = max{ j <= i : depth_j <= k };
    leading steps deeper than k form one group. The coarse step shows its anchor's nodes.

    In both modes groups are contiguous and partition the trace.
    Returns (coarse_steps, fine_span_per_coarse_step).
    """
    if depth < 0:
        raise ValueError("depth must be >= 0")
    if mode == "containment":
        if ancestry_map is None:
            raise ValueError("containment projection needs ancestry_map")

        def key(s: ir.WorkflowStep) -> tuple[str, ...]:
            out: list[str] = []
            for n in s.node_ids:
                chain = ancestry_map.get(n, [n])
                a = chain[min(depth, len(chain) - 1)]
                if a not in out:
                    out.append(a)
            return tuple(out)

        keys = [key(s) for s in steps]
        groups = _group(keys)
        anchors_nodes = [list(keys[g[0]]) for g in groups]
        depths = [depth for _ in groups]
    elif mode == "call_depth":
        groups = []
        anchored: list[bool] = []
        for i, s in enumerate(steps):
            if s.depth <= depth:
                groups.append([i])
                anchored.append(True)
            elif not groups:  # leading steps deeper than k, before any anchor
                groups.append([i])
                anchored.append(False)
            else:
                groups[-1].append(i)
        anchors_nodes = [list(steps[g[0]].node_ids) for g in groups]
        depths = [steps[g[0]].depth for g in groups]
    else:
        raise ValueError(f"unknown projection mode {mode!r}")
    coarse: list[CoarseStep] = []
    spans: list[tuple[int, int]] = []
    for gi, members in enumerate(groups):
        touched = list(dict.fromkeys(n for m in members for n in steps[m].node_ids))
        span = (steps[members[0]].seq, steps[members[-1]].seq)
        coarse.append(CoarseStep(gi, anchors_nodes[gi], touched, depths[gi], span))
        spans.append(span)
    return coarse, spans
