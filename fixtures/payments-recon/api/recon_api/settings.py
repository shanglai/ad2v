"""Operator settings (P7 fixture: a route prefix that comes from a pydantic Settings default).

The prefix is a class-attribute default that the environment can override (`AUDIT_PREFIX=...`),
so ad2v leaves it unresolved unless ad2v.yaml maps it (`pairing.path_constants`) or opts in to
reading the default (`pairing.resolve_settings_defaults: true`).
"""

from fastapi import APIRouter
from pydantic_settings import BaseSettings

from recon_api import db


class Settings(BaseSettings):
    API_V1_STR: str = "/v1"
    AUDIT_PREFIX: str = "/v1" + "/reconciliations"


settings = Settings()

audit = APIRouter(prefix=settings.AUDIT_PREFIX)


@audit.get("/{run_id}/audit")
def run_audit(run_id: str) -> dict:
    run = db.get_run(run_id)
    return {"run_id": run_id, "events": run["events"] if run else []}
