"""Everything an LLM task needs about one epoch, read from the .ad2v file alone (format spec §11).

The graph and the derived data come from the file (materialized or derived in memory); source
text comes from `source_blobs`. Building a slice is pure: the same epoch gives the same slices.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from ad2v import ir, materialize, store
from ad2v.llm.config import LLMConfig
from ad2v.manifest import Config, from_config_json

RESOURCE_KINDS = frozenset({"datastore", "queue", "external_service", "llm_endpoint", "ui"})
PORT_KINDS = frozenset(ir.PORT_KINDS)
IO_EDGES = ("calls", "reads", "writes", "publishes", "consumes", "invokes_external", "invokes_llm")


@dataclass
class EpochView:
    conn: sqlite3.Connection
    epoch_id: str
    cfg: LLMConfig
    _lines: dict[tuple[str, str], list[str] | None] = field(default_factory=dict)

    @cached_property
    def epoch(self) -> store.Epoch:
        return store.get_epoch(self.conn, self.epoch_id)

    @cached_property
    def graph(self) -> ir.Graph:
        return store.load_graph(self.conn, self.epoch_id)

    @cached_property
    def derived(self) -> store.Derived:
        return materialize.derive(self.conn, self.epoch_id)

    @cached_property
    def config(self) -> Config:
        return from_config_json(store.load_config_json(self.conn, self.epoch.config_hash))

    @cached_property
    def by_qname(self) -> dict[tuple[str, str], str]:
        return {(n.kind, n.qualified_name): n.id for n in self.graph.nodes.values()}

    @cached_property
    def kids(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for n in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if n.parent_id is not None:
                out.setdefault(n.parent_id, []).append(n.id)
        return out

    @cached_property
    def out_edges(self) -> dict[str, list[ir.Edge]]:
        out: dict[str, list[ir.Edge]] = {}
        for key in sorted(self.graph.edges):
            e = self.graph.edges[key]
            out.setdefault(e.src, []).append(e)
        return out

    @cached_property
    def workflows_of(self) -> dict[str, list[ir.Workflow]]:
        """node id -> code workflows whose steps include it."""
        out: dict[str, list[ir.Workflow]] = {}
        for w in self.derived.workflows:
            if w.side != "code":
                continue
            seen: set[str] = set()
            for s in w.steps:
                for nid in s.node_ids:
                    if nid not in seen:
                        seen.add(nid)
                        out.setdefault(nid, []).append(w)
        return out

    # -- source text --------------------------------------------------------------------------
    def file_lines(self, side: str, path: str | None) -> list[str] | None:
        if path is None:
            return None
        key = (side, path)
        if key not in self._lines:
            kind = "module" if side == "code" else "spec_doc"
            nid = self.by_qname.get((kind, path))
            text = store.load_source(self.conn, self.graph.nodes[nid].content_hash) if nid else None
            self._lines[key] = text.split("\n") if text is not None else None
        return self._lines[key]

    def span_lines(
        self, n: ir.Node, start: int | None = None, end: int | None = None
    ) -> list[tuple[int, str]]:
        lines = self.file_lines(n.side, n.path)
        s, e = start or n.span_start_line, end or n.span_end_line
        if lines is None or s is None or e is None:
            return []
        return [(i, lines[i - 1]) for i in range(s, min(e, len(lines)) + 1)]

    def node(self, nid: str | None) -> ir.Node | None:
        return self.graph.nodes.get(nid) if nid else None

    def handler_of(self, n: ir.Node) -> ir.Node:
        """A port's handler function (its code), else the node itself."""
        if n.kind in PORT_KINDS and n.attrs.get("handler"):
            for kind in ("function", "module", "class"):
                nid = self.by_qname.get((kind, n.attrs["handler"]))
                if nid is not None:
                    return self.graph.nodes[nid]
        return n

    def signature(self, n: ir.Node, max_lines: int = 5) -> list[tuple[int, str]]:
        """The def/class header of a function or class (from `def` to the closing `:`)."""
        out: list[tuple[int, str]] = []
        for i, t in self.span_lines(n):
            if not out and not t.lstrip().startswith(("def ", "async def ", "class ")):
                continue
            out.append((i, t))
            if t.rstrip().endswith(":") or len(out) >= max_lines:
                break
        return out

    def resources_reached(self, nid: str) -> list[str]:
        """Resources in workflow steps below the node (and those it touches directly), sorted."""
        found = {
            self.graph.nodes[e.dst].qualified_name
            for e in self.out_edges.get(nid, [])
            if e.dst in self.graph.nodes and self.graph.nodes[e.dst].kind in RESOURCE_KINDS
        }
        if not self.workflows_of.get(nid):  # on no workflow: what its direct callees touch
            for e in self.out_edges.get(nid, []):
                if e.kind != "calls":
                    continue
                for e2 in self.out_edges.get(e.dst, []):
                    dst = self.graph.nodes.get(e2.dst)
                    if dst is not None and dst.kind in RESOURCE_KINDS:
                        found.add(dst.qualified_name)
        for w in self.workflows_of.get(nid, []):
            steps = w.steps
            for i, s in enumerate(steps):
                if nid not in s.node_ids:
                    continue
                for t in steps[i + 1 :]:
                    if t.depth <= s.depth:
                        break
                    for x in t.node_ids:
                        xn = self.graph.nodes.get(x)
                        if xn is not None and xn.kind in RESOURCE_KINDS:
                            found.add(xn.qualified_name)
        return sorted(found)

    def digest(self, n: ir.Node, start: int | None = None, end: int | None = None) -> dict[str, Any]:
        """Deterministic IR digest of a node, or of lines start..end of it (the elided part)."""

        def in_range(lines: list[int] | None) -> bool:
            if start is None:
                return True
            return any(start <= ln <= (end or ln) for ln in lines or [])

        calls, touches = [], []
        for e in self.out_edges.get(n.id, []):
            dst = self.graph.nodes.get(e.dst)
            if dst is None or e.kind not in IO_EDGES or not in_range(e.attrs.get("lines")):
                continue
            (calls if e.kind == "calls" else touches).append(f"{e.kind} {dst.qualified_name}")
        behaviors = []
        for c in self.kids.get(n.id, []):
            cn = self.graph.nodes[c]
            if cn.kind in ir.BEHAVIOR_KINDS and (
                start is None or (start <= (cn.span_start_line or 0) <= (end or 0))
            ):
                behaviors.append(f"{cn.kind} at line {cn.span_start_line}: risk {cn.attrs.get('risk', [])}")
        out: dict[str, Any] = {
            "calls": sorted(set(calls)),
            "touches": sorted(set(touches)),
            "behaviors": behaviors,
        }
        if n.kind in ("container", "component", "system"):
            kids = [self.graph.nodes[c] for c in self.kids.get(n.id, [])]
            out["children"] = sorted(f"{k.kind} {k.qualified_name}" for k in kids)[:60]
            ports = [
                self.graph.nodes[e.dst].qualified_name
                for e in self.out_edges.get(n.id, [])
                if e.kind == "exposes" and e.dst in self.graph.nodes
            ]
            out["ports"] = sorted(ports)
        return out

    def status_of(self, nid: str) -> str:
        s = self.derived.pairing.statuses.get(nid)
        return s.status if s is not None else "none"
