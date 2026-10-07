"""The viewer's `DataSource` in Python, one function per method (P6 decision 3b, ADR-0041).

Each function returns exactly what `viewer/src/data/LocalFileSource.ts` returns for the same
arguments, with maps as JSON objects keyed by id. `RemoteSliceSource` rebuilds the maps, and a
Vitest parity test deep-compares the two over the stdio server. The SQL mirrors the TypeScript
statement for statement, including the JS coercions (`String(null)` is "null", `Number(null)` is
0), so that parity holds on odd rows too.

`scene()` is the one addition: the slice of an epoch the map needs around a focus node.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

LAYOUT_ALGORITHM = "nestgrid-v1"
MENTIONS_RE = re.compile(r"\n\nmentions: ([^\n]*)\s*\Z")
ALL = -1  # scene depth meaning "the whole epoch"


def js_str(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def js_num(v: Any) -> float | int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(v)
    except ValueError:
        return float("nan")
    return int(f) if f.is_integer() else f


def _opt(v: Any) -> str | None:
    return None if v is None else js_str(v)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def _node(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": js_str(r["id"]),
        "side": js_str(r["side"]),
        "kind": js_str(r["kind"]),
        "name": js_str(r["name"]),
        "qname": js_str(r["qualified_name"]),
        "parentId": _opt(r["parent_id"]),
        "path": _opt(r["path"]),
        "spanStart": None if r["span_start_line"] is None else js_num(r["span_start_line"]),
        "spanEnd": None if r["span_end_line"] is None else js_num(r["span_end_line"]),
        **_display(r),
    }


def _display(r: sqlite3.Row) -> dict[str, Any]:
    """P9 (ADR-0072): title, referenced ids, non-functional flag, step keyword (LocalFileSource too)."""
    attrs = json.loads(r["attrs_json"]) if r["attrs_json"] else {}
    refs = json.loads(r["spec_ref_json"]) if r["spec_ref_json"] else []
    return {
        "title": js_str(attrs["title"]) if isinstance(attrs.get("title"), str) else None,
        "refs": sorted({js_str(x) for x in refs}),
        "nfr": attrs.get("requirement_type") == "nonfunctional",
        "keyword": js_str(attrs["keyword"]) if isinstance(attrs.get("keyword"), str) else None,
    }


NODE_COLS = (
    "id, side, kind, name, qualified_name, parent_id, path, span_start_line, span_end_line,"
    " attrs_json, spec_ref_json"
)


# -- DataSource methods ------------------------------------------------------------------------
def meta(conn: sqlite3.Connection) -> dict[str, Any]:
    m = {js_str(r["key"]): js_str(r["value"]) for r in conn.execute("SELECT key, value FROM meta")}
    providers = (
        [
            js_str(r["provider"])
            for r in conn.execute("SELECT DISTINCT provider FROM llm_runs ORDER BY provider")
        ]
        if _has_table(conn, "llm_runs")
        else []
    )
    return {
        "formatVersion": m.get("format_version", "?"),
        "systemName": m.get("system_name", "system"),
        "specCoverage": m.get("spec_coverage", "present"),
        "llmProviders": providers,
    }


def epochs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    head_row = conn.execute("SELECT value FROM meta WHERE key = 'head_epoch'").fetchone()
    head = head_row["value"] if head_row else None
    return [
        {
            "epochId": js_str(r["epoch_id"]),
            "seq": js_num(r["seq"]),
            "parentEpochId": _opt(r["parent_epoch_id"]),
            "commit": _opt(r["repo_commit"]),
            "changeKind": js_str(r["change_kind"]),
            "pinned": bool(r["pinned"]),
            "label": _opt(r["label"]),
            "materialized": bool(r["materialized"]),
            "isHead": r["epoch_id"] == head,
        }
        for r in conn.execute(
            "SELECT epoch_id, seq, parent_epoch_id, repo_commit, change_kind, pinned, label, materialized"
            " FROM epochs WHERE materialized = 1 ORDER BY seq"
        )
    ]


def nodes(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    return [
        _node(r)
        for r in conn.execute(f"SELECT {NODE_COLS} FROM nodes WHERE epoch_id = ? ORDER BY id", (epoch,))
    ]


def _box(r: sqlite3.Row) -> dict[str, Any]:
    return {k: js_num(r[k]) for k in ("x", "y", "z", "w", "h", "d")}


def layout(conn: sqlite3.Connection, epoch: str) -> dict[str, Any]:
    return {
        js_str(r["node_id"]): _box(r)
        for r in conn.execute(
            "SELECT node_id, x, y, z, w, h, d FROM layout WHERE epoch_id = ? AND algorithm = ? ORDER BY "
            "node_id",
            (epoch, LAYOUT_ALGORITHM),
        )
    }


def _glyph(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "nodeId": js_str(r["node_id"]),
        "baseShape": js_str(r["base_shape"]),
        "variant": js_str(r["variant"]),
        "modifiers": json.loads(js_str(r["modifiers_json"])),
        "sizeWeight": js_num(r["size_weight"]),
        "hasInterior": bool(r["has_interior"]),
    }


def glyphs(conn: sqlite3.Connection, epoch: str) -> dict[str, Any]:
    return {
        js_str(r["node_id"]): _glyph(r)
        for r in conn.execute("SELECT * FROM glyphs WHERE epoch_id = ?", (epoch,))
    }


def _edge(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "src": js_str(r["src"]),
        "dst": js_str(r["dst"]),
        "kind": js_str(r["kind"]),
        "weight": js_num(r["weight"]),
    }


def edges(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    return [
        _edge(r)
        for r in conn.execute(
            "SELECT src, dst, kind, weight FROM edges WHERE epoch_id = ? AND kind NOT IN ('contains', "
            "'declares')"
            " ORDER BY src, kind, dst",
            (epoch,),
        )
    ]


def status(conn: sqlite3.Connection, epoch: str, mode: str) -> dict[str, Any]:
    if mode == "effective" and _has_table(conn, "node_status_effective"):
        return {
            js_str(r["node_id"]): {
                "status": js_str(r["status"]),
                "normative": js_str(r["normative_status"]),
                "provenance": "llm" if r["provenance"] == "llm" else "deterministic",
                "suggested": bool(r["suggested"]),
            }
            for r in conn.execute(
                "SELECT node_id, status, normative_status, provenance, suggested FROM node_status_effective"
                " WHERE epoch_id = ?",
                (epoch,),
            )
        }
    out: dict[str, Any] = {}
    for r in conn.execute("SELECT node_id, status FROM node_status WHERE epoch_id = ?", (epoch,)):
        s = js_str(r["status"])
        out[js_str(r["node_id"])] = {
            "status": s,
            "normative": s,
            "provenance": "deterministic",
            "suggested": False,
        }
    return out


def rollups(conn: sqlite3.Connection, epoch: str) -> dict[str, Any]:
    return {
        js_str(r["node_id"]): json.loads(js_str(r["counts_json"]))
        for r in conn.execute("SELECT node_id, counts_json FROM status_rollup WHERE epoch_id = ?", (epoch,))
    }


def node_detail(conn: sqlite3.Connection, epoch: str, node_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM nodes WHERE epoch_id = ? AND id = ?", (epoch, node_id)).fetchone()
    if r is None:
        return None
    s = conn.execute(
        "SELECT reasons_json FROM node_status WHERE epoch_id = ? AND node_id = ?", (epoch, node_id)
    ).fetchone()
    reasons = (json.loads(js_str(s["reasons_json"])).get("reasons") or []) if s else []
    return {
        "node": _node(r),
        "attrs": json.loads(js_str(r["attrs_json"])),
        "specRef": json.loads(js_str(r["spec_ref_json"])),
        "reasons": reasons,
        "contentHash": js_str(r["content_hash"]),
    }


def links(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    return [
        {
            "linkId": js_str(r["link_id"]),
            "specId": _opt(r["spec_node_id"]),
            "codeId": _opt(r["code_node_id"]),
            "method": js_str(r["method"]),
            "status": js_str(r["status"]),
            "evidence": json.loads(js_str(r["evidence_json"])),
            "provenance": js_str(r["provenance"]),
            "confidence": js_num(r["confidence"]),
        }
        for r in conn.execute("SELECT * FROM links WHERE epoch_id = ? ORDER BY link_id", (epoch,))
    ]


def judgments(conn: sqlite3.Connection, epoch: str) -> dict[str, Any]:
    if not _has_table(conn, "link_judgments"):
        return {}
    return {
        js_str(r["link_id"]): {
            "linkId": js_str(r["link_id"]),
            "verdict": js_str(r["verdict"]),
            "confidence": js_num(r["confidence"]),
            "rationale": js_str(r["rationale"]),
            "evidence": json.loads(js_str(r["evidence_json"])),
            "valid": bool(r["valid"]),
            "overlay": "drift" if r["overlay"] == "drift" else "evidence",
            "provider": _opt(r["provider"]),
            "model": _opt(r["model"]),
        }
        for r in conn.execute(
            "SELECT j.*, x.provider, x.model FROM link_judgments j LEFT JOIN llm_results x ON x.result_id = "
            "j.result_id"
            " WHERE j.epoch_id = ?",
            (epoch,),
        )
    }


def suggestions(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    if not _has_table(conn, "link_suggestions"):
        return []
    return [
        {
            "suggestionId": js_str(r["suggestion_id"]),
            "specId": js_str(r["spec_node_id"]),
            "codeId": js_str(r["code_node_id"]),
            "rank": js_num(r["candidate_rank"]),
            "lexicalScore": js_num(r["lexical_score"]),
            "verdict": js_str(r["verdict"]),
            "confidence": js_num(r["confidence"]),
            "rationale": js_str(r["rationale"]),
            "state": js_str(r["state"]),
            "provider": _opt(r["provider"]),
        }
        for r in conn.execute(
            "SELECT s.*, x.provider FROM link_suggestions s LEFT JOIN llm_results x ON x.result_id = "
            "s.result_id"
            " WHERE s.epoch_id = ? ORDER BY s.suggestion_id",
            (epoch,),
        )
    ]


def summaries(conn: sqlite3.Connection, epoch: str) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT s.node_id, s.length, s.text, s.model, x.provider FROM summaries s"
        " LEFT JOIN llm_results x ON x.result_id = s.result_id WHERE s.epoch_id = ? ORDER BY s.node_id, "
        "s.length",
        (epoch,),
    ):
        nid = js_str(r["node_id"])
        s = out.setdefault(
            nid,
            {
                "nodeId": nid,
                "label": None,
                "card": None,
                "deep": None,
                "mentions": [],
                "model": None,
                "provider": None,
            },
        )
        text = js_str(r["text"])
        if r["length"] == "label":
            s["label"] = text
        elif r["length"] == "card":
            s["card"] = text
        else:
            m = MENTIONS_RE.search(text)
            s["mentions"] = [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []
            s["deep"] = text[: m.start()] if m else text
        if r["length"] != "label":
            s["model"] = js_str(r["model"])
            s["provider"] = _opt(r["provider"])
    return out


def workflows(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    return [
        {
            "workflowId": js_str(r["workflow_id"]),
            "name": js_str(r["name"]),
            "side": js_str(r["side"]),
            "entryNodeId": js_str(r["entry_node_id"]),
            "source": js_str(r["source"]),
        }
        for r in conn.execute(
            "SELECT workflow_id, name, side, entry_node_id, source FROM workflows WHERE epoch_id = ?"
            " ORDER BY name, workflow_id",
            (epoch,),
        )
    ]


def steps(conn: sqlite3.Connection, epoch: str, workflow_id: str) -> list[dict[str, Any]]:
    return [
        {
            "seq": js_num(r["seq"]),
            "nodeIds": json.loads(js_str(r["node_ids_json"])),
            "depth": js_num(r["depth"]),
        }
        for r in conn.execute(
            "SELECT seq, node_ids_json, depth FROM workflow_steps WHERE epoch_id = ? AND workflow_id = ? "
            "ORDER BY seq",
            (epoch, workflow_id),
        )
    ]


def narrations(
    conn: sqlite3.Connection, epoch: str, workflow_id: str, mode: str = "containment"
) -> list[dict[str, Any]]:
    return [
        {
            "detailLevel": js_num(r["detail_level"]),
            "spanStart": js_num(r["span_start"]),
            "spanEnd": js_num(r["span_end"]),
            "text": js_str(r["text"]),
            "model": js_str(r["model"]),
            "mode": js_str(r["mode"]),
        }
        for r in conn.execute(
            "SELECT detail_level, span_start, span_end, text, model, mode FROM narrations"
            " WHERE epoch_id = ? AND workflow_id = ? AND mode = ? ORDER BY detail_level, span_start",
            (epoch, workflow_id, mode),
        )
    ]


def workflows_through(conn: sqlite3.Connection, epoch: str, node_id: str) -> list[str]:
    return [
        js_str(r["workflow_id"])
        for r in conn.execute(
            "SELECT DISTINCT workflow_id FROM workflow_step_nodes WHERE epoch_id = ? AND node_id = ? ORDER "
            "BY workflow_id",
            (epoch, node_id),
        )
    ]


def lineage(conn: sqlite3.Connection, epoch: str) -> list[dict[str, Any]]:
    return [
        {
            "oldId": js_str(r["old_id"]),
            "newId": js_str(r["new_id"]),
            "method": js_str(r["method"]),
            "score": js_num(r["score"]),
        }
        for r in conn.execute(
            "SELECT old_id, new_id, method, score FROM id_lineage WHERE epoch_id = ? ORDER BY old_id",
            (epoch,),
        )
    ]


def status_history(conn: sqlite3.Connection, node_id: str) -> list[dict[str, Any]]:
    return [
        {"epochId": js_str(r["epoch_id"]), "seq": js_num(r["seq"]), "status": js_str(r["status"])}
        for r in conn.execute(
            "SELECT e.epoch_id, e.seq, s.status FROM node_status s JOIN epochs e ON e.epoch_id = s.epoch_id"
            " WHERE s.node_id = ? ORDER BY e.seq",
            (node_id,),
        )
    ]


# -- scene slices ---------------------------------------------------------------------------------
def scene_ids(conn: sqlite3.Connection, epoch: str, root_id: str | None, depth: int) -> list[str] | None:
    """The node ids of a slice, sorted; None means the whole epoch.

    A slice around `root_id` holds: every root; the ancestor chain of the root and the children
    of each ancestor (the siblings the map shows around an open container); the root's subtree
    down to `depth` levels; and the direct neighbors of that subtree along non-hierarchy edges,
    each with its own ancestor chain so that edges and portals have somewhere to land.
    """
    if root_id is None or depth == ALL:
        return None
    parent: dict[str, str | None] = {}
    kids: dict[str, list[str]] = {}
    for r in conn.execute("SELECT id, parent_id FROM nodes WHERE epoch_id = ? ORDER BY id", (epoch,)):
        parent[r["id"]] = r["parent_id"]
        if r["parent_id"] is not None:
            kids.setdefault(r["parent_id"], []).append(r["id"])
    if root_id not in parent:
        raise KeyError(root_id)
    keep: set[str] = {n for n, p in parent.items() if p is None}

    def chain(n: str | None) -> None:
        while n is not None and n not in keep:
            keep.add(n)
            n = parent.get(n)

    anc: list[str] = []
    n: str | None = root_id
    while n is not None:
        anc.append(n)
        n = parent[n]
    keep.update(anc)
    for a in anc:
        keep.update(kids.get(a, []))
    sub: set[str] = {root_id}
    frontier = [root_id]
    for _ in range(max(depth, 0)):
        nxt = [c for f in frontier for c in kids.get(f, [])]
        sub.update(nxt)
        frontier = nxt
    keep |= sub
    qs = ",".join("?" * len(sub))
    for r in conn.execute(
        f"SELECT src, dst FROM edges WHERE epoch_id = ? AND kind NOT IN ('contains', 'declares')"
        f" AND (src IN ({qs}) OR dst IN ({qs}))",
        (epoch, *sorted(sub), *sorted(sub)),
    ):
        chain(r["src"])
        chain(r["dst"])
    return sorted(keep)


def scene(conn: sqlite3.Connection, epoch: str, root_id: str | None, depth: int) -> dict[str, Any]:
    ids = scene_ids(conn, epoch, root_id, depth)
    all_nodes = nodes(conn, epoch)
    lay, gly = layout(conn, epoch), glyphs(conn, epoch)
    norm, eff, roll = status(conn, epoch, "normative"), status(conn, epoch, "effective"), rollups(conn, epoch)
    all_edges = edges(conn, epoch)
    if ids is not None:
        keep = set(ids)
        all_nodes = [n for n in all_nodes if n["id"] in keep]
        lay = {k: v for k, v in lay.items() if k in keep}
        gly = {k: v for k, v in gly.items() if k in keep}
        norm = {k: v for k, v in norm.items() if k in keep}
        eff = {k: v for k, v in eff.items() if k in keep}
        roll = {k: v for k, v in roll.items() if k in keep}
        all_edges = [e for e in all_edges if e["src"] in keep and e["dst"] in keep]
    return {
        "epoch": epoch,
        "rootId": root_id,
        "depth": depth if ids is not None else ALL,
        "complete": ids is None,
        "nodes": all_nodes,
        "layout": lay,
        "glyphs": gly,
        "edges": all_edges,
        "normative": norm,
        "effective": eff,
        "rollups": roll,
    }
