"""Canonical JSONL dump (format spec §8).

One line per row: {"row": {...}, "table": <name>}. Tables in name order, rows in primary-key
order. `*_json` columns are decoded so the dump nests them.

Default (canonical): every row except wall-clock columns (`created_at`) and informative `meta`
rows (`meta.class = 'I'`: generator, generator_version, repo_root_name, created_at).

`normative_only=True` additionally drops informative columns (those marked `I` in the DDL, see
the format spec's Appendix A), rows produced by an LLM or at runtime
(`provenance IN ('llm','runtime')`, `source IN ('llm_inferred','runtime')`) and the purely
informative tables (`summaries`, `narrations`). The determinism guarantee covers exactly this
normative dump; informative rows are reproducible only through caching by
`input_hash`/`prompt_hash` (P4).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from ad2v import ddl, ids, store

INFORMATIVE_TABLES = frozenset({"summaries", "narrations"})
INFORMATIVE_PROVENANCE = frozenset({"llm", "runtime"})
INFORMATIVE_SOURCES = frozenset({"llm_inferred", "runtime"})


@lru_cache(maxsize=1)
def _informative_columns() -> dict[str, frozenset[str]]:
    return {t: frozenset(c for c, k, _ in cols if k == "I") for t, cols in ddl.column_classes().items()}


def _is_informative_row(table: str, row: dict[str, Any]) -> bool:
    if table == "meta":
        return row.get("class") == "I"
    if row.get("provenance") in INFORMATIVE_PROVENANCE:
        return True
    return row.get("source") in INFORMATIVE_SOURCES


def iter_canonical(path: Path, normative_only: bool = False) -> Iterator[str]:
    conn = store.open_readonly(Path(path))
    info_cols = _informative_columns() if normative_only else {}
    try:
        for table in store.table_names(conn):
            if normative_only and table in INFORMATIVE_TABLES:
                continue
            all_cols = store.columns(conn, table)
            order = ", ".join(store.primary_key(conn, table))
            rows = conn.execute(f"SELECT {', '.join(all_cols)} FROM {table} ORDER BY {order}")
            keep = [
                c
                for c in all_cols
                if c not in store.EXCLUDED_COLUMNS and c not in info_cols.get(table, frozenset())
            ]
            for r in rows:
                full = {c: r[c] for c in all_cols}
                if table == "meta" and full["class"] == "I":
                    continue
                if normative_only and _is_informative_row(table, full):
                    continue
                row: dict[str, Any] = {}
                for c in keep:
                    v = full[c]
                    if c.endswith("_json") and isinstance(v, str):
                        v = json.loads(v)
                    row[c] = v
                yield ids.canonical_json({"table": table, "row": row})
    finally:
        conn.close()


def canonical_dump(path: Path, normative_only: bool = False) -> str:
    return "".join(line + "\n" for line in iter_canonical(path, normative_only))
