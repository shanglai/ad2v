"""An in-memory index of one epoch of one file, shared by the agent tools (built once, cached).

Everything here is read from the file through `slices` (the same queries as the viewer) plus the
node attributes. The cache is keyed by (file, epoch id): epoch ids are content ids, so a cached
index can never be stale for its key.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v import ir, store
from ad2v.mcp import slices

RESOURCE_KINDS = frozenset({"datastore", "queue", "external_service", "llm_endpoint", "ui"})
PORT_KINDS = frozenset(ir.PORT_KINDS)
BEHAVIOR_KINDS = frozenset(ir.BEHAVIOR_KINDS)
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
UNTRUSTED_TAG = re.compile(r"</?\s*untrusted_text[^>]*>", re.I)


def clean_name(s: str, cap: int = 120) -> str:
    """Names are repository-derived: no control characters, bounded length."""
    s = CONTROL.sub(" ", s).strip()
    return s if len(s) <= cap else s[: cap - 1] + "…"


def untrusted(text: str | None, source: str) -> dict[str, Any] | None:
    """Repository- or LLM-derived free text, clearly delimited (P6 decision 9)."""
    if text is None:
        return None
    return {"untrusted_text": UNTRUSTED_TAG.sub("", text), "source": source}


def untrusted_block(text: str, source: str) -> str:
    """The same text for the model-facing `text` channel, fenced and neutralized."""
    body = UNTRUSTED_TAG.sub("", text).strip()
    return f'<untrusted_text source="{source}">\n{body}\n</untrusted_text>'


@dataclass
class EpochIndex:
    path: Path
    file_label: str
    epoch_id: str
    seq: int
    nodes: dict[str, dict[str, Any]]
    attrs: dict[str, dict[str, Any]]
    kids: dict[str, list[str]]
    norm: dict[str, dict[str, Any]]
    eff: dict[str, dict[str, Any]]
    summaries: dict[str, dict[str, Any]]
    rollups: dict[str, dict[str, int]]
    glyphs: dict[str, dict[str, Any]]
    by_qname: dict[str, list[str]]
    build_ms: float = 0.0
    _cache: dict[str, Any] = field(default_factory=dict)

    # -- basics ----------------------------------------------------------------------------------
    def parent(self, nid: str) -> str | None:
        return self.nodes[nid]["parentId"]

    def ancestors(self, nid: str) -> list[str]:
        """[root, …, parent] (excluding nid)."""
        out: list[str] = []
        p = self.parent(nid)
        while p is not None and p in self.nodes:
            out.append(p)
            p = self.parent(p)
        return out[::-1]

    def subtree(self, nid: str) -> list[str]:
        out, stack = [], [nid]
        while stack:
            n = stack.pop()
            out.append(n)
            stack.extend(reversed(self.kids.get(n, [])))
        return out

    def status(self, nid: str) -> str:
        return self.norm.get(nid, {}).get("status", "none")

    def ref(self, nid: str) -> dict[str, Any]:
        n = self.nodes[nid]
        r: dict[str, Any] = {
            "id": nid,
            "label": clean_name(n["name"]),
            "kind": n["kind"],
            "qualified_name": clean_name(n["qname"], 240),
            "status": self.status(nid),
        }
        e = self.eff.get(nid)
        if e and e["status"] != r["status"]:
            r["effective_status"] = {
                "status": e["status"],
                "source": "AI" if e["provenance"] == "llm" else "rules",
            }
        return r

    def ref_text(self, nid: str) -> str:
        r = self.ref(nid)
        eff = r.get("effective_status")
        extra = f", effective {eff['status']} ({eff['source']})" if eff else ""
        return f"{r['label']} [{r['kind']}, {r['status']}{extra}] {r['qualified_name']} ({nid})"

    def resolve(self, ref: str) -> str:
        """A node by id or by qualified name; raises KeyError with candidates when ambiguous."""
        if ref in self.nodes:
            return ref
        ids = self.by_qname.get(ref) or self.by_qname.get(ref.strip())
        if not ids:
            low = ref.strip().lower()
            ids = sorted(i for q, ii in self.by_qname.items() if q.lower() == low for i in ii)
        if not ids:
            raise KeyError(f"no node {ref!r} (use ad2v_search or ad2v_locate to find ids)")
        if len(ids) > 1:
            order = {k: i for i, k in enumerate(ir.NODE_KINDS)}
            ids = sorted(ids, key=lambda i: (order.get(self.nodes[i]["kind"], 99), i))
        return ids[0]

    # -- derived digests ---------------------------------------------------------------------------
    def digest(self, nid: str, edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        counts: dict[str, int] = {}
        ports: list[str] = []
        risks: set[str] = set()
        sub = self.subtree(nid)
        for c in sub[1:]:
            k = self.nodes[c]["kind"]
            counts[k] = counts.get(k, 0) + 1
            if k in PORT_KINDS:
                ports.append(self.nodes[c]["name"])
        for c in sub:
            if (self.glyphs.get(c) or {}).get("modifiers", {}).get("has_loop_risk"):
                risks.add("IO or LLM inside a loop")
        resources: set[str] = set()
        subset = set(sub)
        for e in edges or []:
            if e["src"] in subset and self.nodes.get(e["dst"], {}).get("kind") in RESOURCE_KINDS:
                resources.add(self.nodes[e["dst"]]["name"])
        return {
            "kind": self.nodes[nid]["kind"],
            "counts": counts,
            "ports": sorted(ports),
            "resources": sorted(resources),
            "risks": sorted(risks),
            "rollup": self.rollups.get(nid, {}),
            "status": self.status(nid),
        }


def fallback_card(label: str, d: dict[str, Any]) -> str:
    """The viewer's deterministic card (viewer/src/model/text.ts `fallbackCard`)."""

    def plural(w: str, n: int) -> str:
        if n == 1:
            return w
        return w + "es" if re.search(r"(s|x|ch|sh)$", w) else w + "s"

    s = f"{label} is a {d['kind'].replace('_', ' ')}"
    kids = [f"{n} {plural(k.replace('_', ' '), n)}" for k, n in d["counts"].items() if n > 0]
    if kids:
        s += " containing " + ", ".join(kids)
    s += "."
    if d["ports"]:
        s += f" Ports: {', '.join(d['ports'][:4])}{', …' if len(d['ports']) > 4 else ''}."
    if d["resources"]:
        s += f" Touches {', '.join(d['resources'][:4])}{', …' if len(d['resources']) > 4 else ''}."
    if d["risks"]:
        s += f" Risks: {', '.join(d['risks'])}."
    roll = [(k, n) for k, n in d["rollup"].items() if k != "none"]
    if roll:
        s += " Inside: " + ", ".join(f"{n} {k}" for k, n in roll) + "."
    return s + f" Status: {d['status']}."


def build(conn: sqlite3.Connection, path: Path, file_label: str, epoch_id: str) -> EpochIndex:
    t0 = time.perf_counter()
    rows = slices.nodes(conn, epoch_id)
    nodes = {n["id"]: n for n in rows}
    attrs = {
        r["id"]: json.loads(r["attrs_json"])
        for r in conn.execute("SELECT id, attrs_json FROM nodes WHERE epoch_id = ?", (epoch_id,))
    }
    kids: dict[str, list[str]] = {}
    by_qname: dict[str, list[str]] = {}
    for n in rows:
        if n["parentId"] is not None:
            kids.setdefault(n["parentId"], []).append(n["id"])
        by_qname.setdefault(n["qname"], []).append(n["id"])
    order = {k: i for i, k in enumerate(ir.NODE_KINDS)}
    for v in kids.values():
        v.sort(key=lambda i: (order.get(nodes[i]["kind"], 99), nodes[i]["qname"], i))
    ix = EpochIndex(
        path=path,
        file_label=file_label,
        epoch_id=epoch_id,
        seq=store.epoch_seq(conn, epoch_id),
        nodes=nodes,
        attrs=attrs,
        kids=kids,
        norm=slices.status(conn, epoch_id, "normative"),
        eff=slices.status(conn, epoch_id, "effective"),
        summaries=slices.summaries(conn, epoch_id),
        rollups=slices.rollups(conn, epoch_id),
        glyphs=slices.glyphs(conn, epoch_id),
        by_qname=by_qname,
    )
    ix.build_ms = (time.perf_counter() - t0) * 1000
    return ix


class IndexCache:
    """LRU of EpochIndex by (file, epoch); thread-safe; small (indexes of big repos are ~MBs)."""

    def __init__(self, size: int = 6) -> None:
        self.size = size
        self._d: OrderedDict[tuple[str, str], EpochIndex] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, conn: sqlite3.Connection, path: Path, label: str, epoch_id: str) -> EpochIndex:
        key = (str(path), epoch_id)
        with self._lock:
            ix = self._d.get(key)
            if ix is not None:
                self._d.move_to_end(key)
                return ix
        ix = build(conn, path, label, epoch_id)
        with self._lock:
            self._d[key] = ix
            while len(self._d) > self.size:
                self._d.popitem(last=False)
        return ix
