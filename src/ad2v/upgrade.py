"""In-place upgrade of a v0.4 file to v0.5 (P7, ADR-0055).

v0.5 changes only informative objects: `llm_results.task` also allows 'chat', the new
`judge_rollups` table, and `node_status_effective` reads it. Normative tables are untouched, so
epoch ids, dumps and diffs are the same before and after. SQLite cannot alter a CHECK constraint,
so `llm_results` is rebuilt (create, copy, drop, rename) inside one transaction.
"""

from __future__ import annotations

import re
import sqlite3

from ad2v import ir
from ad2v.resources import ddl_path


def _statement(ddl: str, head: str) -> str:
    """The DDL statement that starts with `head` (comment lines dropped)."""
    for raw in ddl.split(";\n"):
        body = "\n".join(line for line in raw.split("\n") if not line.lstrip().startswith("--")).strip()
        if body.startswith(head):
            return body
    raise KeyError(head)


def upgrade_v04(conn: sqlite3.Connection) -> bool:
    """Upgrade an open v0.4 file to v0.5. Returns False when there was nothing to do."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    if row is None or row[0] != "0.4":
        return False
    ddl = ddl_path().read_text(encoding="utf-8")
    create_results = _statement(ddl, "CREATE TABLE llm_results")
    new_table = re.sub(r"^CREATE TABLE llm_results\b", "CREATE TABLE llm_results_v05", create_results)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(new_table)
        conn.execute("INSERT INTO llm_results_v05 SELECT * FROM llm_results")
        conn.execute("DROP VIEW IF EXISTS node_status_effective")
        conn.execute("DROP TABLE llm_results")
        conn.execute("ALTER TABLE llm_results_v05 RENAME TO llm_results")
        conn.execute(_statement(ddl, "CREATE INDEX idx_llm_results_key"))
        conn.execute(_statement(ddl, "CREATE TABLE judge_rollups"))
        conn.execute(_statement(ddl, "CREATE VIEW node_status_effective"))
        conn.execute("UPDATE meta SET value = ? WHERE key = 'format_version'", (ir.FORMAT_VERSION,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        raise sqlite3.IntegrityError(f"upgrade left foreign key violations: {bad[:3]}")
    return True
