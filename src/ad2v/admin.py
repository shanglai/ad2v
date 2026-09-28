"""Epoch management: log, pin/unpin, prune with garbage collection (format spec §5.4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ad2v import materialize, store

EPOCH_TABLES = (  # per-epoch rows keyed by epoch_id, deleted with their epoch (FK-safe order)
    "tour_stops",
    "tours",
    "layout",
    *store.LLM_DERIVED_TABLES,
    *store.DERIVED_DELETE_ORDER,
    "epoch_materialized",
    "id_lineage",
    "link_state",
)
MEMBERSHIP = (  # (versions, membership keyed by epoch seq)
    ("node_versions", "epoch_nodes"),
    ("edge_versions", "epoch_edges"),
    ("unresolved_ref_versions", "epoch_unresolved_refs"),
    ("test_result_versions", "epoch_test_results"),
    ("code_fact_versions", "epoch_code_facts"),
)


def log(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    head = store.head_epoch(conn)
    out = []
    for r in store.epoch_rows(conn):
        n = conn.execute("SELECT COUNT(*) FROM epoch_nodes WHERE seq = ?", (r["seq"],)).fetchone()[0]
        out.append(
            {
                "seq": r["seq"],
                "epoch_id": r["epoch_id"],
                "parent": r["parent_epoch_id"],
                "commit": r["repo_commit"],
                "change_kind": r["change_kind"],
                "pinned": bool(r["pinned"]),
                "label": r["label"],
                "materialized": bool(r["materialized"]),
                "nodes": n,
                "head": r["epoch_id"] == head,
            }
        )
    return out


def pin(conn: sqlite3.Connection, epoch_id: str, label: str | None) -> None:
    if label is not None:
        clash = conn.execute(
            "SELECT epoch_id FROM epochs WHERE label = ? AND epoch_id <> ?", (label, epoch_id)
        ).fetchone()
        if clash:
            raise ValueError(f"label {label!r} is already used by {clash[0]}")
    conn.execute(
        "UPDATE epochs SET pinned = 1, label = COALESCE(?, label) WHERE epoch_id = ?", (label, epoch_id)
    )
    materialize.materialize(conn, epoch_id)


def unpin(conn: sqlite3.Connection, epoch_id: str) -> None:
    conn.execute("UPDATE epochs SET pinned = 0 WHERE epoch_id = ?", (epoch_id,))
    if epoch_id != store.head_epoch(conn):
        store.drop_derived(conn, epoch_id)


def prune(
    conn: sqlite3.Connection, keep_last: int, keep_pinned: bool, drop_llm_cache: bool = False
) -> dict[str, int]:
    """Delete old epochs (never the head), re-parent survivors, garbage-collect unreferenced rows."""
    rows = store.epoch_rows(conn)
    head = store.head_epoch(conn)
    keep = {r["epoch_id"] for r in rows[-max(keep_last, 1) :]} | {head}
    if keep_pinned:
        keep |= {r["epoch_id"] for r in rows if r["pinned"]}
    remove = [r["epoch_id"] for r in rows if r["epoch_id"] not in keep]
    conn.execute("PRAGMA defer_foreign_keys = ON")
    kept_ancestor: str | None = None
    for r in rows:  # oldest first: point every kept epoch at its nearest kept ancestor
        if r["epoch_id"] in keep:
            if r["parent_epoch_id"] != kept_ancestor:
                conn.execute(
                    "UPDATE epochs SET parent_epoch_id = ? WHERE epoch_id = ?", (kept_ancestor, r["epoch_id"])
                )
            kept_ancestor = r["epoch_id"]
    for e in remove:
        seq = store.epoch_seq(conn, e)
        for t in EPOCH_TABLES:
            conn.execute(f"DELETE FROM {t} WHERE epoch_id = ?", (e,))
        for _versions, members in MEMBERSHIP:
            conn.execute(f"DELETE FROM {members} WHERE seq = ?", (seq,))
        conn.execute("DELETE FROM epochs WHERE epoch_id = ?", (e,))
    stats = {"epochs_removed": len(remove)}
    stats.update(gc(conn, drop_llm_cache))
    return stats


def gc(conn: sqlite3.Connection, drop_llm_cache: bool = False) -> dict[str, int]:
    """Delete version, input and cache rows that no remaining epoch references.

    `llm_results` rows are a costly cache and are kept unless `drop_llm_cache` (then only rows no
    informative table references go).
    """
    before = conn.total_changes
    for versions, members in MEMBERSHIP:
        conn.execute(f"DELETE FROM {versions} WHERE vid NOT IN (SELECT vid FROM {members})")
    conn.execute("DELETE FROM rules_versions WHERE rules_hash NOT IN (SELECT rules_hash FROM epochs)")
    conn.execute("DELETE FROM config_versions WHERE config_hash NOT IN (SELECT config_hash FROM epochs)")
    versions_removed = conn.total_changes - before
    before = conn.total_changes
    # a cache row survives if some remaining epoch has that file content under that rules hash
    conn.execute(
        "DELETE FROM parse_cache WHERE NOT EXISTS ("
        " SELECT 1 FROM epoch_nodes en JOIN node_versions v ON v.vid = en.vid"
        " JOIN epochs e ON e.seq = en.seq"
        " WHERE v.kind = 'module' AND v.side = 'code' AND v.path = parse_cache.path"
        " AND v.content_hash = parse_cache.content_hash AND e.rules_hash = parse_cache.rules_hash)"
    )
    conn.execute(
        "DELETE FROM source_blobs WHERE content_hash NOT IN (SELECT v.content_hash FROM node_versions v"
        " WHERE v.kind IN ('module','spec_doc'))"
    )
    cache_removed = conn.total_changes - before
    llm_removed = 0
    if drop_llm_cache:
        refs = " UNION ".join(
            f"SELECT result_id FROM {t} WHERE result_id IS NOT NULL" for t in store.LLM_DERIVED_TABLES
        )
        before = conn.total_changes
        conn.execute(f"DELETE FROM llm_run_results WHERE result_id NOT IN ({refs})")
        conn.execute(f"DELETE FROM llm_results WHERE result_id NOT IN ({refs})")
        llm_removed = conn.total_changes - before
    return {
        "version_rows_removed": versions_removed,
        "cache_rows_removed": cache_removed,
        "llm_rows_removed": llm_removed,
    }


def prune_file(path: Path, keep_last: int, keep_pinned: bool, drop_llm_cache: bool = False) -> dict[str, int]:
    conn = store.open_rw(Path(path))
    try:
        with conn:
            stats = prune(conn, keep_last, keep_pinned, drop_llm_cache)
        conn.execute("VACUUM")
    finally:
        conn.close()
    return stats
