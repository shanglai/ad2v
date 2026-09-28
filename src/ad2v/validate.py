"""Conformance checks for .ad2v files (format spec §9)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema

from ad2v import ids, ir, store
from ad2v.resources import ir_schema_path


def node_row_to_ir(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "side": r["side"],
        "kind": r["kind"],
        "name": r["name"],
        "qualified_name": r["qualified_name"],
        "parent_id": r["parent_id"],
        "path": r["path"],
        "span_start_line": r["span_start_line"],
        "span_end_line": r["span_end_line"],
        "content_hash": r["content_hash"],
        "subtree_hash": r["subtree_hash"],
        "level_hint": r["level_hint"],
        "attrs": json.loads(r["attrs_json"]),
        "spec_ref": json.loads(r["spec_ref_json"]),
    }


def load_ir(conn: sqlite3.Connection) -> dict[str, Any]:
    nodes = [node_row_to_ir(r) for r in conn.execute("SELECT * FROM nodes ORDER BY id")]
    edges = [
        {
            "src": r["src"],
            "dst": r["dst"],
            "kind": r["kind"],
            "weight": r["weight"],
            "attrs": json.loads(r["attrs_json"]),
            "provenance": r["provenance"],
        }
        for r in conn.execute("SELECT * FROM edges ORDER BY src, kind, dst")
    ]
    glyphs = [
        {
            "node_id": r["node_id"],
            "base_shape": r["base_shape"],
            "variant": r["variant"],
            "modifiers": json.loads(r["modifiers_json"]),
            "size_weight": r["size_weight"],
            "has_interior": bool(r["has_interior"]),
        }
        for r in conn.execute("SELECT * FROM glyphs ORDER BY node_id")
    ]
    workflows = []
    for w in conn.execute("SELECT * FROM workflows ORDER BY workflow_id"):
        steps = [
            {"seq": s["seq"], "node_ids": json.loads(s["node_ids_json"]), "depth": s["depth"]}
            for s in conn.execute(
                "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY seq", (w["workflow_id"],)
            )
        ]
        workflows.append(
            {
                "workflow_id": w["workflow_id"],
                "name": w["name"],
                "side": w["side"],
                "entry_node_id": w["entry_node_id"],
                "scenario_id": w["scenario_id"],
                "source": w["source"],
                "attrs": json.loads(w["attrs_json"]),
                "steps": steps,
            }
        )
    unresolved = [
        {"src": r["src"], "ref": r["ref"], "ref_kind": r["ref_kind"], "reason": r["reason"]}
        for r in conn.execute("SELECT * FROM unresolved_refs ORDER BY src, ref")
    ]
    return {
        "format_version": ir.FORMAT_VERSION,
        "nodes": nodes,
        "edges": edges,
        "glyphs": glyphs,
        "workflows": workflows,
        "unresolved_refs": unresolved,
    }


def validate(path: Path) -> list[str]:
    """Return a list of problems (empty = valid)."""
    problems: list[str] = []
    conn = store.open_readonly(Path(path))
    try:
        meta = store.read_meta(conn)
        if meta.get("format_version") != ir.FORMAT_VERSION:
            problems.append(
                f"format_version is {meta.get('format_version')!r}, expected {ir.FORMAT_VERSION!r}"
            )
        for r in conn.execute("PRAGMA foreign_key_check"):
            problems.append(f"foreign key violation in {r[0]} rowid={r[1]} -> {r[2]}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"sqlite integrity_check: {integrity}")

        doc = load_ir(conn)
        schema = json.loads(ir_schema_path().read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
            loc = "/".join(str(p) for p in err.absolute_path)
            problems.append(f"IR schema: {loc}: {err.message}")

        nodes = {n["id"]: n for n in doc["nodes"]}
        for n in doc["nodes"]:
            expect = ids.node_id(n["side"], n["kind"], n["qualified_name"])
            if expect != n["id"]:
                problems.append(f"node {n['id']}: id does not match node_id(side, kind, qualified_name)")
        glyph_ids = {g["node_id"] for g in doc["glyphs"]}
        missing = sorted(set(nodes) - glyph_ids)
        if missing:
            problems.append(f"{len(missing)} node(s) without a glyph, e.g. {missing[0]}")
        for w in doc["workflows"]:
            seqs = [s["seq"] for s in w["steps"]]
            if seqs != list(range(len(seqs))):
                problems.append(f"workflow {w['workflow_id']}: step seq not contiguous from 0")
            for s in w["steps"]:
                for nid in s["node_ids"]:
                    if nid not in nodes:
                        problems.append(f"workflow {w['workflow_id']} step {s['seq']}: unknown node {nid}")
        # subtree hashes recompute
        kids: dict[str, list[str]] = {nid: [] for nid in nodes}
        for nid, n in nodes.items():
            if n["parent_id"] in kids:
                kids[n["parent_id"]].append(nid)
        memo: dict[str, str] = {}

        def sub(nid: str) -> str:
            if nid not in memo:
                memo[nid] = ids.subtree_hash(nodes[nid]["content_hash"], [(c, sub(c)) for c in kids[nid]])
            return memo[nid]

        bad = [nid for nid in sorted(nodes) if sub(nid) != nodes[nid]["subtree_hash"]]
        if bad:
            problems.append(f"{len(bad)} node(s) with a subtree_hash that does not recompute, e.g. {bad[0]}")
        # hierarchy edges mirror parent_id
        edge_keys = {(e["src"], e["kind"], e["dst"]) for e in doc["edges"]}
        for nid, n in nodes.items():
            if n["parent_id"] is not None:
                kind = "declares" if n["side"] == "spec" else "contains"
                if (n["parent_id"], kind, nid) not in edge_keys:
                    problems.append(f"node {nid}: parent_id without a matching {kind} edge")
    finally:
        conn.close()
    return problems
