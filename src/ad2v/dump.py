"""Canonical JSONL dump (format spec §8).

One line per row: {"row": {...}, "table": <name>}. Tables in name order, rows in primary-key
order. `*_json` columns are decoded so the dump nests them.

The dump shows the *logical* content of the selected epochs (`head`, one epoch, or `all`):
base facts through the v0.2-shaped views, derived tables (materialized on demand, in memory,
for epochs that are not materialized), history rows (`id_lineage`, `link_state`), `epochs` and
`meta`. Physical storage tables (versions, membership, caches) are never dumped, so
deduplication is invisible.

Default (canonical): omits wall-clock columns (`created_at`) and informative `meta` rows.
`normative_only=True` additionally omits every column marked `I` in Appendix A (including the
file-management columns `epochs.pinned`, `label`, `materialized`), rows produced by an LLM or at
runtime, and the informative tables (`summaries`, `narrations`, `link_judgments`,
`link_suggestions`, `spec_extractions`). The determinism guarantee covers
this normative dump.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

from ad2v import ddl, ids, materialize, store

INFORMATIVE_TABLES = frozenset(
    {"summaries", "narrations", "link_judgments", "link_suggestions", "spec_extractions", "judge_rollups"}
)
INFORMATIVE_PROVENANCE = frozenset({"llm", "runtime"})
INFORMATIVE_SOURCES = frozenset({"llm_inferred", "runtime"})
VIEW_ORDER = {
    "nodes": ("epoch_id", "id"),
    "edges": ("epoch_id", "src", "kind", "dst"),
    "unresolved_refs": ("epoch_id", "src", "ref_kind", "ref"),
    "test_results": ("epoch_id", "test_node_id"),
}
VIEW_INFORMATIVE = {"edges": frozenset({"model", "model_version", "prompt_hash", "input_hash", "confidence"})}


@cache
def _informative_columns() -> dict[str, frozenset[str]]:
    out = {t: frozenset(c for c, k, _ in cols if k == "I") for t, cols in ddl.column_classes().items()}
    out.update(VIEW_INFORMATIVE)
    return out


def _is_informative_row(table: str, row: dict[str, Any]) -> bool:
    if row.get("provenance") in INFORMATIVE_PROVENANCE:
        return True
    return row.get("source") in INFORMATIVE_SOURCES


def select_epochs(conn: sqlite3.Connection, which: str | None) -> list[str]:
    if which == "all":
        return [r["epoch_id"] for r in store.epoch_rows(conn)]
    return [store.resolve_epoch(conn, which)]


def _emit(table: str, row: dict[str, Any], keep: list[str]) -> str:
    out: dict[str, Any] = {}
    for c in keep:
        v = row[c]
        if c.endswith("_json") and isinstance(v, str):
            v = json.loads(v)
        out[c] = v
    return ids.canonical_json({"table": table, "row": out})


def iter_canonical(path: Path, normative_only: bool = False, epoch: str | None = "head") -> Iterator[str]:
    conn = store.open_readonly(Path(path))
    info_cols = _informative_columns() if normative_only else {}
    try:
        epochs = select_epochs(conn, epoch) if store.head_epoch(conn) is not None else []
        wanted = set(epochs)
        on_demand: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for e in epochs:
            if not store.is_materialized(conn, e):
                on_demand[e] = store.derived_rows(e, materialize.derive(conn, e))
        names = [t for t in store.table_names(conn) if t not in store.PHYSICAL_TABLES] + list(store.VIEWS)
        for table in sorted(names):
            if normative_only and table in INFORMATIVE_TABLES:
                continue
            all_cols = store.columns(conn, table)
            keep = [
                c for c in all_cols if c not in store.EXCLUDED_COLUMNS and c not in info_cols.get(table, ())
            ]
            order = VIEW_ORDER.get(table) or tuple(store.primary_key(conn, table))
            rows: list[dict[str, Any]] = [
                dict(r) for r in conn.execute(f"SELECT {', '.join(all_cols)} FROM {table}")
            ]
            if table in store.DERIVED_TABLES:
                for derived in on_demand.values():
                    rows.extend({c: r.get(c) for c in all_cols} for r in derived[table])
            if "epoch_id" in all_cols:
                rows = [r for r in rows if r["epoch_id"] in wanted]
            if table == "meta":
                rows = [r for r in rows if r["class"] != "I"]
            if normative_only:
                rows = [r for r in rows if not _is_informative_row(table, r)]
            rows.sort(
                key=lambda r: tuple(
                    "" if r[c] is None else str(r[c]) if not isinstance(r[c], int) else f"{r[c]:020d}"
                    for c in order
                )
            )
            for r in rows:
                yield _emit(table, r, keep)
    finally:
        conn.close()


def canonical_dump(path: Path, normative_only: bool = False, epoch: str | None = "head") -> str:
    return "".join(line + "\n" for line in iter_canonical(path, normative_only, epoch))
