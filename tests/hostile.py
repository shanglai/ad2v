"""Hostile .ad2v files for the security tests (P8 M5, docs/security.md §1).

Each variant starts from a valid file and is written to a new path:

xss      a script payload appended to every free-text column of every table and to every string
         leaf of every JSON column (names, qualified names, paths, attrs, summaries, narrations,
         evidence, rationales, labels, meta system name), plus one 100,000-character node name
huge     one node name of 2 MiB
deep     one node's attrs nested 5,000 levels deep
version  meta.format_version = "9.9"
objects  an extra table, an extra view, a redefined built-in view and a trigger that would delete
         every node if the file were ever written to

    python tests/hostile.py <src.ad2v> <dst.ad2v> <variant>
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

MARK = "__ad2vXss"
PAYLOADS = (
    f'<img src=x onerror="window.{MARK}=1">',
    f"<script>window.{MARK}=1</script>",
    f'"><svg onload="window.{MARK}=1">',
    f"[click](javascript:window.{MARK}=1)",
    f"javascript:window.{MARK}=1",
)
PAYLOAD = " ".join(PAYLOADS)
# columns that carry identity or enumerations (changing them breaks references, not rendering)
SKIP_COL = re.compile(
    r"(^|_)(id|ids|hash|key|vid|seq|kind|side|status|provenance|method|source|outcome|length|mode|"
    r"verdict|overlay|state|task|class|change_kind|created_at|model|model_version|lod|version)$"
)
SKIP_META = {"format_version", "head_epoch", "generator", "generator_version"}


def _poison(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj + " " + PAYLOAD
    if isinstance(obj, list):
        return [_poison(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _poison(v) for k, v in obj.items()}
    return obj


def _text_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if (r[2] or "").upper() == "TEXT"]


def xss(conn: sqlite3.Connection) -> None:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        if t.startswith("sqlite_") or t in ("parse_cache", "source_blobs"):
            continue
        if t == "meta":
            for (k,) in conn.execute("SELECT key FROM meta").fetchall():
                if k not in SKIP_META:
                    conn.execute("UPDATE meta SET value = value || ? WHERE key = ?", (" " + PAYLOAD, k))
            continue
        for col in _text_columns(conn, t):
            if SKIP_COL.search(col) and not col.endswith("_json"):
                continue
            if col.endswith("_json"):
                rows = conn.execute(f"SELECT DISTINCT {col} FROM {t} WHERE {col} IS NOT NULL").fetchall()
                for (raw,) in rows:
                    try:
                        val = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    with contextlib.suppress(sqlite3.IntegrityError):
                        conn.execute(
                            f"UPDATE {t} SET {col} = ? WHERE {col} = ?", (json.dumps(_poison(val)), raw)
                        )
                continue
            with contextlib.suppress(sqlite3.IntegrityError):
                conn.execute(f"UPDATE {t} SET {col} = {col} || ? WHERE {col} IS NOT NULL", (" " + PAYLOAD,))
    conn.execute(
        "UPDATE node_versions SET name = ?"
        " WHERE vid = (SELECT MIN(vid) FROM node_versions WHERE kind = 'function')",
        ("x" * 100_000 + PAYLOAD,),
    )


def huge(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE node_versions SET name = ? WHERE vid = (SELECT MIN(vid) FROM node_versions)",
        ("y" * (2 << 20),),
    )


def deep(conn: sqlite3.Connection) -> None:
    nested = "[" * 5000 + "]" * 5000
    conn.execute(
        "UPDATE node_versions SET attrs_json = ? WHERE vid = (SELECT MIN(vid) FROM node_versions)",
        ('{"deep": ' + nested + "}",),
    )


def version(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE meta SET value = '9.9' WHERE key = 'format_version'")


def objects(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE evil (x TEXT);
        CREATE VIEW evil_v AS SELECT 1 AS one;
        DROP VIEW IF EXISTS nodes;
        CREATE VIEW nodes AS SELECT * FROM node_versions WHERE 0;
        CREATE TRIGGER evil_t AFTER INSERT ON meta BEGIN DELETE FROM node_versions; END;
        """
    )


VARIANTS = {"xss": xss, "huge": huge, "deep": deep, "version": version, "objects": objects}


def make(src: Path, dst: Path, variant: str) -> Path:
    shutil.copyfile(src, dst)
    conn = sqlite3.connect(dst)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        VARIANTS[variant](conn)
        conn.commit()
    finally:
        conn.close()
    return dst


if __name__ == "__main__":
    make(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
