"""Canonical JSONL dump (format spec §8).

Two conforming producers given the same inputs must produce byte-identical canonical dumps.
One line per row: {"table": <name>, "row": {...}}. Tables in name order, rows in primary-key
order. `*_json` columns are decoded so the dump nests them. Wall-clock columns and informative
meta keys are omitted.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ad2v import ids, store


def iter_canonical(path: Path) -> Iterator[str]:
    conn = store.open_readonly(Path(path))
    try:
        for table in store.table_names(conn):
            cols = [c for c in store.columns(conn, table) if c not in store.EXCLUDED_COLUMNS]
            order = ", ".join(store.primary_key(conn, table))
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}")
            for r in rows:
                row: dict[str, Any] = {}
                for c in cols:
                    v = r[c]
                    if c.endswith("_json") and isinstance(v, str):
                        v = json.loads(v)
                    row[c] = v
                if table == "meta" and row["key"] in store.INFORMATIVE_META_KEYS:
                    continue
                yield ids.canonical_json({"table": table, "row": row})
    finally:
        conn.close()


def canonical_dump(path: Path) -> str:
    return "".join(line + "\n" for line in iter_canonical(path))
