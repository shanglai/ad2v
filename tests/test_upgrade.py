"""P7 (ADR-0055): a v0.4 file is upgraded to v0.5 in place when opened for writing. Only
informative objects change ('chat' in llm_results.task, judge_rollups, node_status_effective), so
the normative dump is identical before and after. P8.1 (ADR-0066): v0.5 -> v0.6 rebuilds `links`
and `node_status` so their status CHECK accepts `not_evaluable`."""

from __future__ import annotations

import sqlite3

import pytest

from ad2v import dump, ir, pipeline, store
from ad2v.resources import ddl_path
from ad2v.upgrade import _statement, upgrade_v04, upgrade_v05

from helpers import FIXTURE


def _downgrade_to_v04(path) -> None:
    """Rebuild the v0.4 shape of the informative objects (what P4–P6.1 wrote)."""
    ddl = ddl_path().read_text(encoding="utf-8")
    old = (
        _statement(ddl, "CREATE TABLE llm_results")
        .replace(",'chat')", ")")
        .replace("CREATE TABLE llm_results", "CREATE TABLE llm_results_old")
    )
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        f"""
        DROP VIEW node_status_effective;
        DROP TABLE judge_rollups;
        {old};
        INSERT INTO llm_results_old SELECT * FROM llm_results;
        DROP TABLE llm_results;
        ALTER TABLE llm_results_old RENAME TO llm_results;
        UPDATE meta SET value = '0.4' WHERE key = 'format_version';
        """
    )
    conn.commit()
    conn.close()


def _insert_result(conn, task: str, rid: str) -> None:
    conn.execute(
        "INSERT INTO llm_results(result_id, seq, task, input_hash, prompt_hash, provider, model, params_hash,"
        " subject, valid) VALUES (?, (SELECT COALESCE(MAX(seq),0)+1 FROM llm_results), ?, 'i', 'p', 'fake',"
        " 'fake-1', 'h', 's', 1)",
        (rid, task),
    )


def test_v04_file_is_upgraded_in_place_and_normative_dump_is_unchanged(tmp_path):
    out = tmp_path / "f.ad2v"
    pipeline.extract_to_file(FIXTURE, None, out, name_hint="payments-recon")
    before = dump.canonical_dump(out, normative_only=True)
    _downgrade_to_v04(out)
    conn = sqlite3.connect(out)
    _insert_result(conn, "judge", "r_old")
    with pytest.raises(sqlite3.IntegrityError):  # v0.4 has no 'chat' task
        _insert_result(conn, "chat", "r_chat0")
    conn.commit()
    conn.close()
    assert store.read_meta(store.open_readonly(out))["format_version"] == "0.4"

    conn = store.open_rw(out)  # the upgrade happens here
    assert store.read_meta(conn)["format_version"] == ir.FORMAT_VERSION == "0.7"  # 0.4 -> 0.5 -> 0.6 -> 0.7
    _insert_result(conn, "chat", "r_chat1")
    assert {r[0] for r in conn.execute("SELECT result_id FROM llm_results")} == {"r_old", "r_chat1"}
    conn.execute("SELECT * FROM judge_rollups").fetchall()
    conn.execute("SELECT * FROM node_status_effective LIMIT 1").fetchall()
    conn.commit()
    assert not upgrade_v04(conn) and not upgrade_v05(conn)  # idempotent: already v0.7
    conn.close()
    assert dump.canonical_dump(out, normative_only=True) == before


def _downgrade_to_v05(path) -> None:
    """Rebuild the v0.5 CHECK constraints of links and node_status (no `not_evaluable`)."""
    ddl = ddl_path().read_text(encoding="utf-8")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    script = ["DROP VIEW node_status_effective;"]
    for table in ("links", "node_status"):
        old = (
            _statement(ddl, f"CREATE TABLE {table} ")
            .replace(",'not_evaluable'", "")
            .replace("'not_evaluable',", "")
            .replace(f"CREATE TABLE {table} ", f"CREATE TABLE {table}_old ", 1)
        )
        assert "not_evaluable" not in old
        script += [
            f"{old};",
            f"INSERT INTO {table}_old SELECT * FROM {table};",
            f"DROP TABLE {table};",
            f"ALTER TABLE {table}_old RENAME TO {table};",
        ]
    script += [
        _statement(ddl, "CREATE VIEW node_status_effective") + ";",
        "UPDATE meta SET value = '0.5' WHERE key = 'format_version';",
    ]
    conn.executescript("\n".join(script))
    conn.commit()
    conn.close()


def test_v05_file_is_upgraded_to_v06_and_accepts_not_evaluable(tmp_path):
    out = tmp_path / "f.ad2v"
    pipeline.extract_to_file(FIXTURE, None, out, name_hint="payments-recon")
    before = dump.canonical_dump(out, normative_only=True)
    _downgrade_to_v05(out)
    conn = sqlite3.connect(out)
    e = conn.execute("SELECT value FROM meta WHERE key = 'head_epoch'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):  # v0.5 has no not_evaluable
        conn.execute("UPDATE node_status SET status = 'not_evaluable' WHERE epoch_id = ?", (e,))
    conn.close()
    assert validate_ok(out)
    conn = store.open_rw(out)
    assert store.read_meta(conn)["format_version"] == "0.7"
    conn.execute("SELECT * FROM node_status_effective LIMIT 1").fetchall()
    conn.execute("SAVEPOINT s")
    conn.execute("UPDATE node_status SET status = 'not_evaluable' WHERE epoch_id = ?", (e,))
    conn.execute("ROLLBACK TO s")
    conn.commit()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_links_spec", "idx_links_code", "idx_node_status_status"} <= names
    conn.close()
    assert dump.canonical_dump(out, normative_only=True) == before


def validate_ok(path) -> bool:
    from ad2v.validate import validate

    return validate(path) == []


def test_statement_lookup_errors():
    with pytest.raises(KeyError):
        _statement("CREATE TABLE a (x);\n", "CREATE TABLE b")


def _downgrade_to_v06(path) -> None:
    """The v0.6 shape (P8.1/P9): no infra side, no change kind `infra`, no epochs.infra_hash, no
    infra_status / c4_* tables."""
    ddl = ddl_path().read_text(encoding="utf-8")
    epochs = _statement(ddl, "CREATE TABLE epochs ")
    epochs = epochs.replace("'tests_only',\n                    'infra','mixed'", "'tests_only','mixed'")
    lines = [ln for ln in epochs.split("\n") if "infra_hash" not in ln]
    epochs = "\n".join(lines).replace("created_at      TEXT,", "created_at      TEXT")
    nv = _statement(ddl, "CREATE TABLE node_versions ").replace("('code','spec','infra')", "('code','spec')")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")]
    for v in views:
        conn.execute(f'DROP VIEW "{v}"')
    for t in ("infra_status", "c4_elements", "c4_relations", "c4_layout"):
        conn.execute(f"DROP TABLE {t}")
        conn.execute("DELETE FROM epoch_materialized WHERE table_name = ?", (t,))
    for table, create in (("epochs", epochs), ("node_versions", nv)):
        conn.execute(create.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_old", 1))
        cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({table}_old)"))
        conn.execute(f"INSERT INTO {table}_old ({cols}) SELECT {cols} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
    conn.execute("CREATE INDEX idx_node_versions_node ON node_versions(node_id)")
    from ad2v.upgrade import _views

    for v in _views(ddl):
        conn.execute(v)
    conn.execute("UPDATE meta SET value = '0.6' WHERE key = 'format_version'")
    conn.commit()
    conn.close()


INFRA_ROW = (
    "INSERT INTO node_versions(vid, version_key, node_id, side, kind, name, qualified_name,"
    " content_hash, subtree_hash) VALUES (999999, 'v_x', 'n_x', 'infra', 'bucket', 'b', 'b', 'h', 'h')"
)


def test_v06_file_is_upgraded_to_v07_and_accepts_the_infra_side(tmp_path):
    """P10 (ADR-0077): epochs and node_versions are rebuilt (rows copied, infra_hash ''), the new
    derived tables are created and every materialized epoch gets them (empty)."""
    out = tmp_path / "f.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out)
    _downgrade_to_v06(out)
    conn = sqlite3.connect(out)
    assert "infra_hash" not in [r[1] for r in conn.execute("PRAGMA table_info(epochs)")]
    with pytest.raises(sqlite3.IntegrityError):  # v0.6 has no infra side
        conn.execute(INFRA_ROW)
    conn.close()
    before = dump.canonical_dump(out, normative_only=True)
    conn = store.open_rw(out)  # the upgrade happens here
    assert store.read_meta(conn)["format_version"] == "0.7"
    conn.execute("SAVEPOINT s")
    conn.execute(INFRA_ROW)
    conn.execute("ROLLBACK TO s")
    assert [tuple(r) for r in conn.execute("SELECT infra_hash FROM epochs")] == [("",)]
    conn.commit()
    conn.close()
    after = dump.canonical_dump(out, normative_only=True)
    import re

    def norm(t: str) -> str:  # the documented differences: format version, the new empty column
        t = re.sub(r'("key":"format_version","value":)"0\.[67]"', r'\1"0.x"', t)
        return t.replace(',"infra_hash":""', "")

    assert norm(after) == norm(before)
    assert validate_ok(out)
