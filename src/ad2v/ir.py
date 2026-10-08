"""Intermediate representation (IR) of an ad2v extraction (format spec §3).

The IR is what extractors produce and what `store` persists. It is language- and
storage-agnostic. Everything here is normative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ad2v import ids

FORMAT_VERSION = "0.7"
# older files are upgraded on write (ADR-0055, 0066, 0077)
SUPPORTED_FORMAT_VERSIONS = ("0.4", "0.5", "0.6", "0.7")

SIDES = ("code", "spec", "infra")  # infra: P10 (ADR-0077)

STRUCTURAL_KINDS = ("system", "container", "component", "module", "class", "function")
PORT_KINDS = ("http_route", "mcp_tool", "cli_command", "event_consumer")
RESOURCE_KINDS = ("datastore", "queue", "external_service", "llm_endpoint", "ui")
BEHAVIOR_KINDS = ("loop", "retry", "fan_out", "transaction", "llm_call")
SPEC_KINDS = (
    "spec_root",
    "spec_doc",
    "spec_component",
    "requirement",
    "scenario",
    "scenario_step",
    "spec_endpoint",
)
# P10 (ADR-0074, ADR-0077): the infra side, read from a Terraform plan or `.tf` files
INFRA_KINDS = (
    "deployment_unit",
    "managed_datastore",
    "managed_queue",
    "bucket",
    "secret_store",
    "network",
    "scheduler",
    "infra_other",
    "infra_module",
)
NODE_KINDS = STRUCTURAL_KINDS + PORT_KINDS + RESOURCE_KINDS + BEHAVIOR_KINDS + SPEC_KINDS + INFRA_KINDS

EDGE_KINDS = (
    "contains",
    "imports",
    "calls",
    "reads",
    "writes",
    "publishes",
    "consumes",
    "exposes",
    "invokes_external",
    "invokes_llm",
    "declares",
    "annotated_as",
    # P10 (ADR-0077): infra -> infra (config expressions), unit -> resource (env var), unit -> code
    # container, unit -> code resource (env var name)
    "references",
    "wires",
    "deploys",
    "provides_env",
)
# P10 (ADR-0078): the infra dimension, separate from the 10-status precedence
INFRA_STATUSES = (
    "deployed",
    "undeployed",
    "wired",
    "unwired",
    "in_use",
    "infra_orphan",
    "ambiguous",
    "unknown",
)

RISK_FLAGS = (
    "io_in_loop",
    "llm_in_loop",
    "unbounded_retry",
    "fan_out",
    "nested_loop_io",
    "slow_io_in_transaction",
)

PROVENANCES = ("deterministic", "runtime", "llm")
WORKFLOW_SOURCES = ("static", "runtime", "llm_inferred")
LINK_STATUSES = (
    "specified",
    "implemented",
    "verified",
    "drift",
    "orphan",
    "stale",
    "needs_review",
    "missing",
    # P8.1 (ADR-0066): specified and implemented, but in a language no active extractor reads
    "not_evaluable",
)
# Effective node status: link statuses plus `none` (no spec coverage applies, e.g. a function
# inside an unmapped container). Precedence, highest first (format spec §6.4):
STATUS_PRECEDENCE = (
    "drift",
    "needs_review",
    "missing",
    "orphan",
    "stale",
    "verified",
    "implemented",
    "not_evaluable",
    "specified",
    "none",
)
NODE_STATUSES = STATUS_PRECEDENCE
LINK_METHODS = ("annotation", "route_match", "manifest", "manifest_link", "name_match", "none")
TEST_OUTCOMES = ("passed", "failed", "skipped")

LEVEL_HINTS: dict[str, str] = {
    "system": "system",
    "container": "container",
    "component": "component",
    "module": "code",
    "class": "code",
    "function": "code",
    **{k: "port" for k in PORT_KINDS},
    **{k: "resource" for k in RESOURCE_KINDS},
    **{k: "behavior" for k in BEHAVIOR_KINDS},
    **{k: "spec" for k in SPEC_KINDS},
    **{k: "infra" for k in INFRA_KINDS},
}


def side_of(kind: str) -> str:
    if kind in INFRA_KINDS:
        return "infra"
    return "spec" if kind in SPEC_KINDS else "code"


@dataclass
class Node:
    side: str
    kind: str
    name: str
    qualified_name: str
    parent_id: str | None = None
    path: str | None = None
    span_start_line: int | None = None
    span_end_line: int | None = None
    content_hash: str = ""
    subtree_hash: str = ""
    level_hint: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    spec_ref: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return ids.node_id(self.side, self.kind, self.qualified_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "side": self.side,
            "kind": self.kind,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "parent_id": self.parent_id,
            "path": self.path,
            "span_start_line": self.span_start_line,
            "span_end_line": self.span_end_line,
            "content_hash": self.content_hash,
            "subtree_hash": self.subtree_hash,
            "level_hint": self.level_hint,
            "attrs": self.attrs,
            "spec_ref": sorted(set(self.spec_ref)),
        }


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    weight: int = 1
    attrs: dict[str, Any] = field(default_factory=dict)
    provenance: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "dst": self.dst,
            "kind": self.kind,
            "weight": self.weight,
            "attrs": self.attrs,
            "provenance": self.provenance,
        }


@dataclass
class Glyph:
    node_id: str
    base_shape: str
    variant: str
    modifiers: dict[str, Any]
    size_weight: int
    has_interior: bool


@dataclass
class WorkflowStep:
    seq: int
    node_ids: list[str]
    depth: int


@dataclass
class Workflow:
    name: str
    side: str
    entry_node_id: str
    source: str
    steps: list[WorkflowStep]
    scenario_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def workflow_id(self) -> str:
        return ids.workflow_id(self.side, self.entry_node_id, self.source)


@dataclass
class UnresolvedRef:
    src: str
    ref: str
    ref_kind: str  # "spec_id"
    reason: str  # "not_found"


class Graph:
    """Mutable node/edge collection with deterministic merge semantics."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}
        self.unresolved: list[UnresolvedRef] = []

    def add_node(self, node: Node) -> Node:
        if node.kind not in NODE_KINDS:
            raise ValueError(f"unknown node kind {node.kind!r}")
        if node.level_hint is None:
            node.level_hint = LEVEL_HINTS.get(node.kind)
        existing = self.nodes.get(node.id)
        if existing is not None:
            existing.spec_ref = sorted(set(existing.spec_ref) | set(node.spec_ref))
            return existing
        self.nodes[node.id] = node
        return node

    def get(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def add_edge(
        self,
        src: str,
        dst: str,
        kind: str,
        weight: int = 1,
        attrs: dict[str, Any] | None = None,
        lines: list[int] | None = None,
    ) -> Edge:
        """Add or merge an edge. Weights add up; `lines` (evidence) are unioned and sorted."""
        if kind not in EDGE_KINDS:
            raise ValueError(f"unknown edge kind {kind!r}")
        key = (src, kind, dst)
        edge = self.edges.get(key)
        if edge is None:
            edge = Edge(src=src, dst=dst, kind=kind, weight=0, attrs=dict(attrs or {}))
            self.edges[key] = edge
        else:
            for k, v in (attrs or {}).items():
                edge.attrs.setdefault(k, v)
        edge.weight += weight
        if lines:
            edge.attrs["lines"] = sorted(set(edge.attrs.get("lines", [])) | set(lines))
        return edge

    def children(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for nid in sorted(self.nodes):
            p = self.nodes[nid].parent_id
            if p is not None and p in out:
                out[p].append(nid)
        return out

    def link_contains(self) -> None:
        """Materialize `contains`/`declares` edges from parent_id (idempotent)."""
        for nid in sorted(self.nodes):
            node = self.nodes[nid]
            if node.parent_id is None:
                continue
            kind = "declares" if node.side == "spec" else "contains"
            key = (node.parent_id, kind, nid)
            if key not in self.edges:
                self.add_edge(node.parent_id, nid, kind)

    def compute_subtree_hashes(self) -> None:
        kids = self.children()
        done: dict[str, str] = {}

        def visit(nid: str, stack: frozenset[str]) -> str:
            if nid in done:
                return done[nid]
            if nid in stack:  # defensive: parent cycles are a bug, but never loop forever
                return self.nodes[nid].content_hash
            h = ids.subtree_hash(
                self.nodes[nid].content_hash,
                [(c, visit(c, stack | {nid})) for c in kids[nid]],
            )
            done[nid] = h
            self.nodes[nid].subtree_hash = h
            return h

        for nid in sorted(self.nodes):
            visit(nid, frozenset())


@dataclass
class Link:
    spec_node_id: str | None
    code_node_id: str | None
    status: str
    method: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provenance: str = "deterministic"
    confidence: float = 1.0

    @property
    def link_id(self) -> str:
        return ids.link_id(self.spec_node_id, self.code_node_id, self.method)


@dataclass
class NodeStatus:
    node_id: str
    status: str
    reasons: list[dict[str, Any]]


@dataclass
class TestResult:
    test_node_id: str
    outcome: str
    source_file: str
    duration_ms: int
