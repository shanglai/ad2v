"""Glyph grammar v0.1 (docs/spec/glyph-grammar-v0.1.md). Normative and deterministic.

Encoding channels: shape = kind, modifiers = attributes, line/glow = link status (reserved,
P2), size = weight. A channel never carries another channel's information.
"""

from __future__ import annotations

from ad2v import ir

BASE_SHAPES = (
    "cylinder",
    "tube",
    "trapezoid",
    "rounded_box",
    "hexagon",
    "diamond",
    "ring",
    "port_notch",
    "folded_sheet",
    "cloud",
)

# kind -> (base_shape, variant)
KIND_SHAPES: dict[str, tuple[str, str]] = {
    "system": ("rounded_box", "system"),
    "container": ("rounded_box", "container"),
    "component": ("rounded_box", "component"),
    "module": ("rounded_box", "module"),
    "class": ("rounded_box", "class"),
    "function": ("rounded_box", "function"),
    "http_route": ("port_notch", "http_route"),
    "mcp_tool": ("port_notch", "mcp_tool"),
    "cli_command": ("port_notch", "cli_command"),
    "event_consumer": ("port_notch", "event_consumer"),
    "datastore": ("cylinder", "datastore"),
    "queue": ("tube", "queue"),
    "external_service": ("cloud", "external_service"),
    "llm_endpoint": ("hexagon", "llm_endpoint"),
    "ui": ("trapezoid", "ui"),
    "loop": ("ring", "loop"),
    "retry": ("ring", "retry"),
    "fan_out": ("diamond", "fan_out"),
    "transaction": ("rounded_box", "transaction"),
    "llm_call": ("hexagon", "llm_call"),
    "spec_doc": ("folded_sheet", "spec_doc"),
    "spec_component": ("folded_sheet", "spec_component"),
    "requirement": ("folded_sheet", "requirement"),
    "scenario": ("folded_sheet", "scenario"),
    "scenario_step": ("folded_sheet", "scenario_step"),
    "spec_endpoint": ("folded_sheet", "spec_endpoint"),
}

# Container kinds (manifest `kind`) that render as a gateway/UI trapezoid instead of a box.
TRAPEZOID_CONTAINER_KINDS = frozenset({"gateway", "api_gateway", "ui", "frontend"})

LOOP_RISKS = frozenset({"io_in_loop", "llm_in_loop", "nested_loop_io", "unbounded_retry"})
PORT_EDGE = "exposes"
EXTERNAL_EDGES = frozenset({"invokes_external"})
LLM_EDGES = frozenset({"invokes_llm"})
LLM_KINDS = frozenset({"llm_endpoint", "llm_call"})
EXTERNAL_KINDS = frozenset({"external_service"})


def shape_for(node: ir.Node) -> tuple[str, str]:
    base, variant = KIND_SHAPES[node.kind]
    if node.kind == "container" and node.attrs.get("container_kind") in TRAPEZOID_CONTAINER_KINDS:
        return "trapezoid", "gateway"
    return base, variant


def compute(graph: ir.Graph) -> list[ir.Glyph]:
    """One glyph per node."""
    kids = graph.children()
    ports: dict[str, int] = {}
    self_llm: set[str] = set()
    self_ext: set[str] = set()
    fan_in: dict[str, int] = {}
    for (src, kind, dst), edge in sorted(graph.edges.items()):
        if kind == PORT_EDGE:
            ports[src] = ports.get(src, 0) + 1
        if kind in LLM_EDGES:
            self_llm.add(src)
        if kind in EXTERNAL_EDGES:
            self_ext.add(src)
        if kind not in ("contains", "declares"):
            fan_in[dst] = fan_in.get(dst, 0) + edge.weight

    loop_risk: dict[str, bool] = {}
    has_llm: dict[str, bool] = {}
    external: dict[str, bool] = {}
    loc: dict[str, int] = {}

    def visit(nid: str) -> None:
        if nid in loop_risk:
            return
        node = graph.nodes[nid]
        for c in kids[nid]:
            visit(c)
        risk = set(node.attrs.get("risk", []))
        loop_risk[nid] = bool(risk & LOOP_RISKS) or any(loop_risk[c] for c in kids[nid])
        has_llm[nid] = node.kind in LLM_KINDS or nid in self_llm or any(has_llm[c] for c in kids[nid])
        external[nid] = node.kind in EXTERNAL_KINDS or nid in self_ext or any(external[c] for c in kids[nid])
        if node.span_start_line is not None and node.span_end_line is not None:
            loc[nid] = node.span_end_line - node.span_start_line + 1
        else:
            loc[nid] = sum(loc[c] for c in kids[nid])

    for nid in sorted(graph.nodes):
        visit(nid)

    out: list[ir.Glyph] = []
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        base, variant = shape_for(node)
        if node.kind in ("datastore", "queue", "external_service", "llm_endpoint", "ui"):
            size = fan_in.get(nid, 0)
        else:
            size = loc[nid]
        out.append(
            ir.Glyph(
                node_id=nid,
                base_shape=base,
                variant=variant,
                modifiers={
                    "ports": ports.get(nid, 0),
                    "replicas": int(node.attrs.get("replicas", 1)) if node.kind == "container" else 1,
                    "has_loop_risk": loop_risk[nid],
                    "has_llm": has_llm[nid],
                    "external": external[nid],
                },
                size_weight=max(1, size),
                has_interior=bool(kids[nid]),
            )
        )
    return out
