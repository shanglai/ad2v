"""In-place upgrades: v0.4 -> v0.5 (P7, ADR-0055) and v0.5 -> v0.6 (P8.1, ADR-0066).

v0.5 changes only informative objects: `llm_results.task` also allows 'chat', the new
`judge_rollups` table, and `node_status_effective` reads it. Normative tables are untouched, so
epoch ids, dumps and diffs are the same before and after. SQLite cannot alter a CHECK constraint,
so `llm_results` is rebuilt (create, copy, drop, rename) inside one transaction.

v0.6 adds the status `not_evaluable` to the CHECK constraints of `links.status` and
`node_status.status`; both tables are rebuilt the same way (their columns are unchanged), and the
view that reads them is recreated. Existing rows are copied as they are, so the normative dump is
unchanged until the next extraction.
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
        conn.execute("UPDATE meta SET value = '0.5' WHERE key = 'format_version'")
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


V06_REBUILT = (
    ("links", ("CREATE INDEX idx_links_spec", "CREATE INDEX idx_links_code")),
    ("node_status", ("CREATE INDEX idx_node_status_status",)),
)


def upgrade_v05(conn: sqlite3.Connection) -> bool:
    """Upgrade an open v0.5 file to v0.6. Returns False when there was nothing to do."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    if row is None or row[0] != "0.5":
        return False
    ddl = ddl_path().read_text(encoding="utf-8")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("DROP VIEW IF EXISTS node_status_effective")
        for table, indexes in V06_REBUILT:
            create = _statement(ddl, f"CREATE TABLE {table} ")
            conn.execute(re.sub(rf"^CREATE TABLE {table}\b", f"CREATE TABLE {table}_v06", create))
            conn.execute(f"INSERT INTO {table}_v06 SELECT * FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_v06 RENAME TO {table}")
            for head in indexes:
                conn.execute(_statement(ddl, head))
        conn.execute(_statement(ddl, "CREATE VIEW node_status_effective"))
        conn.execute("UPDATE meta SET value = '0.6' WHERE key = 'format_version'")
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


V07_REBUILT = ("epochs", "node_versions")
V07_NEW = ("infra_status", "c4_elements", "c4_relations", "c4_layout")


def _indexes_of(ddl: str, table: str) -> list[str]:
    out = []
    for raw in ddl.split(";\n"):
        body = "\n".join(line for line in raw.split("\n") if not line.lstrip().startswith("--")).strip()
        if re.match(rf"^CREATE (UNIQUE )?INDEX \w+ ON {table}\(", body):
            out.append(body)
    return out


def _views(ddl: str) -> list[str]:
    out = []
    for raw in ddl.split(";\n"):
        body = "\n".join(line for line in raw.split("\n") if not line.lstrip().startswith("--")).strip()
        if body.startswith("CREATE VIEW "):
            out.append(body)
    return out


def upgrade_v06(conn: sqlite3.Connection) -> bool:
    """Upgrade an open v0.6 file to v0.7 (P10, ADR-0077): the `infra` side (node_versions.side),
    change kind `infra` and `epochs.infra_hash` (both tables rebuilt, rows copied unchanged, infra_hash
    ''), and the new derived tables `infra_status`, `c4_elements`, `c4_relations`, `c4_layout`."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    if row is None or row[0] != "0.6":
        return False
    ddl = ddl_path().read_text(encoding="utf-8")
    views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")  # the views are dropped and recreated around this
    try:
        conn.execute("BEGIN")
        for v in views:
            conn.execute(f'DROP VIEW IF EXISTS "{v}"')
        for table in V07_REBUILT:
            create = _statement(ddl, f"CREATE TABLE {table} ")
            conn.execute(re.sub(rf"^CREATE TABLE {table}\b", f"CREATE TABLE {table}_v07", create))
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            names = ", ".join(cols)
            conn.execute(f"INSERT INTO {table}_v07 ({names}) SELECT {names} FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_v07 RENAME TO {table}")
            for idx in _indexes_of(ddl, table):
                conn.execute(idx)
        for table in V07_NEW:
            conn.execute(
                _statement(ddl, f"CREATE TABLE {table} ").replace(
                    "CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1
                )
            )
        for view in _views(ddl):
            conn.execute(view)
        # materialized epochs of a v0.6 file have no infra: their new derived tables are complete (empty)
        for (e,) in conn.execute("SELECT epoch_id FROM epochs WHERE materialized = 1").fetchall():
            for t in ("infra_status", "c4_elements", "c4_relations"):
                conn.execute("INSERT OR IGNORE INTO epoch_materialized VALUES (?, ?)", (e, t))
        conn.execute("UPDATE meta SET value = ? WHERE key = 'format_version'", (ir.FORMAT_VERSION,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        raise sqlite3.IntegrityError(f"upgrade left foreign key violations: {bad[:3]}")
    return True


def upgrade(conn: sqlite3.Connection) -> list[str]:
    """Every in-place upgrade that applies, oldest first; returns the steps taken."""
    steps = []
    if upgrade_v04(conn):
        steps.append("0.4->0.5")
    if upgrade_v05(conn):
        steps.append("0.5->0.6")
    if upgrade_v06(conn):
        steps.append("0.6->0.7")
    return steps
