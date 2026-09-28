"""Ledger and run persistence (SQLAlchemy Core)."""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine(os.environ["RECON_DB_URL"])
SessionLocal = sessionmaker(bind=engine)


def fetch_ledger_entry(reference: str) -> dict | None:
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT reference, amount_cents FROM ledger WHERE reference = :ref"), {"ref": reference}
        ).mappings().first()
        return dict(row) if row else None


def record_run(result: dict) -> None:
    # ad2v: REQ-099
    with SessionLocal() as session:
        with session.begin():
            session.execute(
                text("INSERT INTO recon_runs (run_id, matched) VALUES (:run_id, :matched)"),
                {"run_id": result["run_id"], "matched": len(result["matches"])},
            )
            session.execute(
                text("INSERT INTO unmatched (run_id, reference) VALUES (:run_id, :reference)"),
                [{"run_id": result["run_id"], "reference": t["reference"]} for t in result["unmatched"]],
            )


def get_run(run_id: str) -> dict | None:
    with SessionLocal() as session:
        row = session.execute(text("SELECT * FROM recon_runs WHERE run_id = :id"), {"id": run_id}).first()
        return dict(row._mapping) if row else None


def list_unmatched(run_id: str) -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(text("SELECT * FROM unmatched WHERE run_id = :id"), {"id": run_id})
        return [dict(r._mapping) for r in rows]


def count_runs() -> int:
    with SessionLocal() as session:
        return session.execute(text("SELECT count(*) FROM recon_runs")).scalar_one()
