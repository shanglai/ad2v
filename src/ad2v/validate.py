"""Conformance checks for .ad2v files (format spec §9)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema

from ad2v import admin, ids, ir, store
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


def load_ir(conn: sqlite3.Connection, epoch_id: str) -> dict[str, Any]:
    """The IR document of one epoch (base facts through the views, derived rows if materialized)."""
    e = (epoch_id,)
    nodes = [node_row_to_ir(r) for r in conn.execute("SELECT * FROM nodes WHERE epoch_id = ? ORDER BY id", e)]
    edges = [
        {
            "src": r["src"],
            "dst": r["dst"],
            "kind": r["kind"],
            "weight": r["weight"],
            "attrs": json.loads(r["attrs_json"]),
            "provenance": r["provenance"],
        }
        for r in conn.execute("SELECT * FROM edges WHERE epoch_id = ? ORDER BY src, kind, dst", e)
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
        for r in conn.execute("SELECT * FROM glyphs WHERE epoch_id = ? ORDER BY node_id", e)
    ]
    workflows = []
    for w in conn.execute("SELECT * FROM workflows WHERE epoch_id = ? ORDER BY workflow_id", e):
        steps = [
            {"seq": s["seq"], "node_ids": json.loads(s["node_ids_json"]), "depth": s["depth"]}
            for s in conn.execute(
                "SELECT * FROM workflow_steps WHERE epoch_id = ? AND workflow_id = ? ORDER BY seq",
                (epoch_id, w["workflow_id"]),
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
        for r in conn.execute("SELECT * FROM unresolved_refs WHERE epoch_id = ? ORDER BY src, ref", e)
    ]
    links = [
        {
            "link_id": r["link_id"],
            "spec_node_id": r["spec_node_id"],
            "code_node_id": r["code_node_id"],
            "status": r["status"],
            "method": r["method"],
            "provenance": r["provenance"],
            "confidence": r["confidence"],
            "evidence": json.loads(r["evidence_json"]),
        }
        for r in conn.execute("SELECT * FROM links WHERE epoch_id = ? ORDER BY link_id", e)
    ]
    statuses = [
        {"node_id": r["node_id"], "status": r["status"], "reasons": json.loads(r["reasons_json"])}
        for r in conn.execute("SELECT * FROM node_status WHERE epoch_id = ? ORDER BY node_id", e)
    ]
    tests = [
        {
            "test_node_id": r["test_node_id"],
            "outcome": r["outcome"],
            "source_file": r["source_file"],
            "duration_ms": r["duration_ms"],
        }
        for r in conn.execute("SELECT * FROM test_results WHERE epoch_id = ? ORDER BY test_node_id", e)
    ]
    return {
        "format_version": ir.FORMAT_VERSION,
        "nodes": nodes,
        "edges": edges,
        "glyphs": glyphs,
        "workflows": workflows,
        "unresolved_refs": unresolved,
        "links": links,
        "node_status": statuses,
        "test_results": tests,
    }


def validate(path: Path, epoch: str | None = None) -> list[str]:
    """Return a list of problems (empty = valid). Checks every epoch unless `epoch` is given."""
    problems: list[str] = []
    conn = store.open_readonly(Path(path))
    try:
        meta = store.read_meta(conn)
        version = meta.get("format_version")
        if version not in ir.SUPPORTED_FORMAT_VERSIONS:
            return [
                f"format_version is {version!r}; supported: {', '.join(ir.SUPPORTED_FORMAT_VERSIONS)}."
                " Older files are not migrated: re-run `ad2v extract` with this ad2v version."
            ]
        for r in conn.execute("PRAGMA foreign_key_check"):
            problems.append(f"foreign key violation in {r[0]} rowid={r[1]} -> {r[2]}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"sqlite integrity_check: {integrity}")
        problems.extend(_check_file(conn, meta))
        schema = json.loads(ir_schema_path().read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        epochs = (
            [store.resolve_epoch(conn, epoch)] if epoch else [r["epoch_id"] for r in store.epoch_rows(conn)]
        )
        for e in epochs:
            problems.extend(f"[{e}] {p}" for p in _check_epoch(conn, e, validator))
    finally:
        conn.close()
    return problems


# Columns that must name a node of the same epoch. Membership rows carry no node ids, so these
# are checked here instead of by FOREIGN KEYs (ADR-0017).
NODE_REFS = (
    ("edges", "src"),
    ("edges", "dst"),
    ("unresolved_refs", "src"),
    ("test_results", "test_node_id"),
    ("glyphs", "node_id"),
    ("workflows", "entry_node_id"),
    ("workflow_step_nodes", "node_id"),
    ("links", "spec_node_id"),
    ("links", "code_node_id"),
    ("node_status", "node_id"),
    ("status_rollup", "node_id"),
    ("summaries", "node_id"),
    ("layout", "node_id"),
    ("tour_stops", "node_id"),
)


def _check_node_refs(conn: sqlite3.Connection, e: str, nodes: dict[str, Any]) -> list[str]:
    problems = []
    for table, col in NODE_REFS:
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM {table} WHERE epoch_id = ? AND {col} IS NOT NULL", (e,)
        )
        missing = sorted(r[0] for r in rows if r[0] not in nodes)
        if missing:
            problems.append(
                f"{table}.{col}: {len(missing)} id(s) not a node of this epoch, e.g. {missing[0]}"
            )
    return problems


def _check_file(conn: sqlite3.Connection, meta: dict[str, str]) -> list[str]:
    """Epoch chain, head, version integrity and garbage (unreferenced versions)."""
    problems: list[str] = []
    rows = store.epoch_rows(conn)
    if not rows:
        return ["file has no epochs"]
    head = meta.get("head_epoch")
    if head != rows[-1]["epoch_id"]:
        problems.append(f"meta.head_epoch {head!r} is not the last epoch {rows[-1]['epoch_id']!r}")
    for prev, cur in zip(rows, rows[1:], strict=False):
        if cur["parent_epoch_id"] not in (None, prev["epoch_id"]):
            problems.append(f"epoch {cur['epoch_id']}: parent is not the previous kept epoch")
    for r in rows:
        materialized = conn.execute(
            "SELECT COUNT(*) FROM epoch_materialized WHERE epoch_id = ?", (r["epoch_id"],)
        ).fetchone()[0]
        if bool(r["materialized"]) != (materialized == len(store.DERIVED_TABLES)):
            problems.append(f"epoch {r['epoch_id']}: materialized flag disagrees with epoch_materialized")
        if r["epoch_id"] == head and not r["materialized"]:
            problems.append("the head epoch is not materialized")
    for r in conn.execute("SELECT * FROM node_versions"):
        payload = {
            "attrs": json.loads(r["attrs_json"]),
            "content_hash": r["content_hash"],
            "id": r["node_id"],
            "kind": r["kind"],
            "level_hint": r["level_hint"],
            "name": r["name"],
            "parent_id": r["parent_id"],
            "path": r["path"],
            "qualified_name": r["qualified_name"],
            "side": r["side"],
            "spec_ref": json.loads(r["spec_ref_json"]),
            "subtree_hash": r["subtree_hash"],
        }
        if r["version_key"] != "v_" + ids.sha256_hex(ids.canonical_json(payload))[: ids.ID_HEX_LEN]:
            problems.append(f"node version {r['version_key']}: key does not match its payload")
            break
    for table, members in admin.MEMBERSHIP:
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE vid NOT IN (SELECT vid FROM {members})"
        ).fetchone()[0]
        if n:
            problems.append(f"{n} unreferenced row(s) in {table} (run `ad2v prune`)")
    for members in ("epoch_nodes", "epoch_code_facts"):  # at most one version per id per epoch
        key = "v.node_id" if members == "epoch_nodes" else "v.fact_kind, v.subject_id"
        versions = "node_versions" if members == "epoch_nodes" else "code_fact_versions"
        dup = conn.execute(
            f"SELECT m.seq FROM {members} m JOIN {versions} v ON v.vid = m.vid GROUP BY m.seq, {key}"
            " HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if dup is not None:
            problems.append(f"{members}: an id has several versions in epoch seq {dup[0]}")
    return problems


def _check_epoch(conn: sqlite3.Connection, e: str, validator: jsonschema.Draft202012Validator) -> list[str]:
    problems: list[str] = []
    doc = load_ir(conn, e)
    for err in sorted(validator.iter_errors(doc), key=lambda x: list(x.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path)
        problems.append(f"IR schema: {loc}: {err.message}")
    nodes = {n["id"]: n for n in doc["nodes"]}
    for n in doc["nodes"]:
        if ids.node_id(n["side"], n["kind"], n["qualified_name"]) != n["id"]:
            problems.append(f"node {n['id']}: id does not match node_id(side, kind, qualified_name)")
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
    problems.extend(_check_node_refs(conn, e, nodes))
    edge_keys = {(x["src"], x["kind"], x["dst"]) for x in doc["edges"]}
    for nid, n in nodes.items():
        if n["parent_id"] is not None:
            kind = "declares" if n["side"] == "spec" else "contains"
            if (n["parent_id"], kind, nid) not in edge_keys:
                problems.append(f"node {nid}: parent_id without a matching {kind} edge")
    ep = store.get_epoch(conn, e)
    # lineage rows refer to the epoch's original parent; after a prune re-parents it (seq gap),
    # that parent may be gone, so only check old ids against an immediate predecessor
    direct_parent = (
        ep.parent_epoch_id is not None and store.get_epoch(conn, ep.parent_epoch_id).seq == ep.seq - 1
    )
    for old, new, _method, _score in store.load_lineage(conn, e):
        if new not in nodes:
            problems.append(f"lineage row {old} -> {new}: new id not in this epoch")
        if (
            direct_parent
            and conn.execute(
                "SELECT 1 FROM nodes WHERE epoch_id = ? AND id = ?", (ep.parent_epoch_id, old)
            ).fetchone()
            is None
        ):
            problems.append(f"lineage row {old} -> {new}: old id not in the parent epoch")
    if store.is_materialized(conn, e):
        problems.extend(_check_derived(conn, e, doc, nodes, kids))
    return problems


def _check_derived(
    conn: sqlite3.Connection, e: str, doc: dict[str, Any], nodes: dict[str, Any], kids: dict[str, list[str]]
) -> list[str]:
    problems: list[str] = []
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
    status = {s["node_id"]: s["status"] for s in doc["node_status"]}
    if set(status) != set(nodes):
        problems.append(
            f"node_status covers {len(status)} of {len(nodes)} nodes (must be exactly one per node)"
        )
    state = store.load_link_state(conn, e)
    for lk in doc["links"]:
        if lk["link_id"] != ids.link_id(lk["spec_node_id"], lk["code_node_id"], lk["method"]):
            problems.append(f"link {lk['link_id']}: id does not match link_id(spec, code, method)")
        if lk["provenance"] == "deterministic" and lk["confidence"] != 1.0:
            problems.append(f"link {lk['link_id']}: deterministic link with confidence != 1.0")
        row = state.get(lk["link_id"])
        if row is not None and row["status"] != lk["status"]:
            problems.append(
                f"link {lk['link_id']}: status {lk['status']} disagrees with link_state {row['status']}"
            )
    derived = sorted(
        {(w["workflow_id"], s["seq"], n) for w in doc["workflows"] for s in w["steps"] for n in s["node_ids"]}
    )
    stored = sorted(
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT workflow_id, seq, node_id FROM workflow_step_nodes WHERE epoch_id = ?", (e,)
        )
    )
    if derived != stored:
        problems.append("workflow_step_nodes does not match workflow_steps")
    rollup = {
        r[0]: json.loads(r[1])
        for r in conn.execute("SELECT node_id, counts_json FROM status_rollup WHERE epoch_id = ?", (e,))
    }
    memo: dict[str, dict[str, int]] = {}

    def counts(nid: str) -> dict[str, int]:
        if nid not in memo:
            acc: dict[str, int] = {}
            for c in kids[nid]:
                acc[status.get(c, "none")] = acc.get(status.get(c, "none"), 0) + 1
                for k, v in counts(c).items():
                    acc[k] = acc.get(k, 0) + v
            memo[nid] = acc
        return memo[nid]

    if rollup != {nid: counts(nid) for nid in nodes if kids[nid]}:
        problems.append("status_rollup does not recompute from node_status")
    return problems
