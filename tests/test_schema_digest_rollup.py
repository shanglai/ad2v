"""P7 M6: datastore schema digests (ADR-0059) and the judge roll-up for containers/components
(ADR-0060)."""

from __future__ import annotations

import json

from ad2v import pipeline, store
from ad2v.extract.code import schema_digest as sd
from ad2v.llm import api, judge
from ad2v.llm.config import from_data
from ad2v.llm.context import EpochView

from helpers import FIXTURE, JUNIT, run_code, write_tree

RECORDINGS = FIXTURE.parent.parent / "tests" / "llm_recordings"


def test_sqlalchemy_and_sql_parsers():
    py = """
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

class A(Base):
    __tablename__ = "a"
    __table_args__ = (UniqueConstraint("x", "y"), Index("ix", "z", unique=True))
    id = Column(Integer, primary_key=True)
    x = Column("x_col", String(20), unique=True, nullable=False)
    b_id = Column(ForeignKey("b.id"))
    n: Mapped[int] = mapped_column()

class NotATable:
    x = Column(Integer)
"""
    (t,) = sd.sqlalchemy_tables("m.py", py)
    assert t["table"] == "a" and t["class"] == "A" and t["unique"] == [["x", "y"], ["z"]]
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["id"] == {"name": "id", "type": "Integer", "pk": True}
    assert cols["x_col"] == {"name": "x_col", "type": "String", "unique": True, "not_null": True}
    assert cols["b_id"]["fk"] == "b.id" and cols["n"]["type"] == "int"
    assert sd.sqlalchemy_tables("bad.py", "def (") == []
    sql = """
-- comment
CREATE TABLE IF NOT EXISTS "t1" (id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL,
  org INT REFERENCES org(id), CONSTRAINT u UNIQUE (org, email));
create table t2 (a int, b int, primary key (a, b), foreign key (b) references t1(id));
"""
    t1, t2 = sd.sql_tables("s.sql", sql)
    assert t1["table"] == "t1" and t1["unique"] == [["email", "org"]]
    c = {x["name"]: x for x in t1["columns"]}
    assert c["id"]["pk"] and c["email"]["unique"] and c["email"]["not_null"] and c["org"]["fk"] == "org.id"
    assert {x["name"] for x in t2["columns"] if x.get("pk")} == {"a", "b"} and t2["columns"][1][
        "fk"
    ] == "t1.id"
    lines = sd.digest_lines(
        {"tables": [t2, {"table": "z", "source": "sql", "path": "p", "columns": [], "unique": []}]}
    )
    assert "  (no primary key or unique constraint)" in lines
    many = {
        "tables": [
            {
                "table": f"t{i}",
                "source": "sql",
                "path": "p",
                "columns": [{"name": "c", "type": "INT"}],
                "unique": [],
            }
            for i in range(30)
        ]
    }
    out = sd.digest_lines(many)
    assert len(out) == 40 and out[-1].startswith("…")


def test_fixture_digest_and_route_models():
    res = pipeline.build(FIXTURE, None, name_hint="payments-recon")
    ds = next(n for n in res.graph.nodes.values() if n.kind == "datastore")
    tables = {t["table"]: t for t in ds.attrs["schema_digest"]["tables"]}
    assert set(tables) == {"classifications", "ledger", "recon_runs", "unmatched"}
    assert tables["classifications"]["unique"] == []  # REQ-009: nothing stops a double classification
    assert tables["unmatched"]["unique"] == [["reference", "run_id"]]
    lines = sd.digest_lines(ds.attrs["schema_digest"])
    i = lines.index("table classifications (sqlalchemy, api/recon_api/models.py)")
    assert "  (no unique constraint besides the primary key)" in lines[i : i + 7]
    rt = next(n for n in res.graph.nodes.values() if n.qualified_name == "http:api:POST /v1/reconciliations")
    assert rt.attrs["schema_models"] == [
        {"role": "request", "class": "RunRequest", "fields": [{"name": "account_ids", "type": "list[str]"}]}
    ]


def test_unlinked_models_get_a_synthetic_datastore_and_sql_is_an_input(tmp_path):
    files = {
        "app/__init__.py": "",
        "app/models.py": "class T(Base):\n    __tablename__ = 't'\n"
        "    id = Column(Integer, primary_key=True)\n",
    }
    g, _ = run_code(tmp_path, files)
    res = pipeline.build(tmp_path, None, name_hint="x")
    syn = [n for n in res.graph.nodes.values() if n.qualified_name == "datastore:sqlalchemy:models"]
    assert syn and syn[0].attrs["schema_digest"]["tables"][0]["table"] == "t"
    e1 = res.epoch.repo_tree_hash
    write_tree(tmp_path, {"db/schema.sql": "CREATE TABLE s (id INT PRIMARY KEY);"})
    res2 = pipeline.build(tmp_path, None, name_hint="x")
    assert res2.epoch.repo_tree_hash != e1  # a .sql file is an epoch input
    syn2 = next(n for n in res2.graph.nodes.values() if n.qualified_name == "datastore:sqlalchemy:models")
    assert {t["table"] for t in syn2.attrs["schema_digest"]["tables"]} == {"s", "t"}


def _ran(tmp_path):  # noqa: ANN202
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, test_results=[JUNIT])
    cfg = from_data({"provider": "fake", "fake_replay_dir": str(RECORDINGS)})
    api.run(out, cfg, ["judge"], 1.0)
    return out, cfg


def test_judge_slice_carries_the_schema_and_containers_are_not_judged(tmp_path):
    out, cfg = _ran(tmp_path)
    conn = store.open_readonly(out)
    try:
        view = EpochView(conn, store.head_epoch(conn), cfg)
        links = judge.judgeable(view)
        kinds = {view.graph.nodes[lk.code_node_id].kind for lk in links}
        assert not kinds & judge.ROLLUP_KINDS
        lk = next(lk for lk in links if view.graph.nodes[lk.spec_node_id].qualified_name == "REQ-009")
        sl = judge.build_slice(view, lk)
        assert any(line.startswith("table classifications") for line in sl["code"]["schema"])
        assert len(sl["code"]["schema"]) <= sd.MAX_LINES
        parts = judge.serialize(sl)
        assert any("datastore schema digest" in p and "classifications" in p for p in parts)
    finally:
        conn.close()


def test_rollup_is_the_worst_confident_descendant_verdict(tmp_path):
    out, cfg = _ran(tmp_path)
    conn = store.open_readonly(out)
    try:
        head = store.head_epoch(conn)
        rows = {
            r["node_id"]: dict(r)
            for r in conn.execute("SELECT * FROM judge_rollups WHERE epoch_id = ?", (head,))
        }
        names = {
            r[0]: r[1]
            for r in conn.execute("SELECT id, qualified_name FROM nodes WHERE epoch_id = ?", (head,))
        }
        by_name = {names[k]: v for k, v in rows.items()}
        api_row = by_name["container:api"]
        assert api_row["verdict"] == "drift"  # REQ-003 drift inside the api container
        counts = json.loads(api_row["counts_json"])
        assert counts.get("drift", 0) >= 1 and sum(counts.values()) == len(
            json.loads(api_row["link_ids_json"])
        )
        eff = conn.execute(
            "SELECT status, provenance FROM node_status_effective WHERE epoch_id = ? AND node_id = ?",
            (head, next(k for k, v in names.items() if v == "container:api")),
        ).fetchone()
        assert eff["provenance"] in ("llm", "deterministic")  # orphan containers keep their status
        again = judge.rollup(conn, head, cfg.min_confidence)
        assert [r[1:] for r in again] == [
            (
                r["node_id"],
                r["verdict"],
                r["confidence"],
                r["counts_json"],
                r["link_ids_json"],
                r["min_confidence"],
            )
            for r in sorted(rows.values(), key=lambda r: r["node_id"])
        ]  # deterministic
        assert judge.rollup(conn, head, 1.01) == []  # nothing confident enough: no row
    finally:
        conn.close()
