"""HTTP routes for reconciliation runs."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from recon_api import db, matching
from recon_api.bank_client import fetch_all_statements
from recon_api.classify import classify_unmatched

router = APIRouter(prefix="/reconciliations")


class RunRequest(BaseModel):
    account_ids: list[str]


@router.post("")
async def start_run(req: RunRequest) -> dict:
    # ad2v: REQ-001
    statements = await fetch_all_statements(req.account_ids)
    result = matching.match_batch(statements)
    db.record_run(result)
    return result


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/{run_id}/unmatched")
def list_unmatched(run_id: str) -> list[dict]:
    rows = db.list_unmatched(run_id)
    return classify_unmatched(rows)
