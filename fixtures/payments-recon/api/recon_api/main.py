"""ASGI entry point for the reconciliation API."""

from fastapi import FastAPI

from recon_api import db
from recon_api.routes import router

app = FastAPI(title="payments-recon")
app.include_router(router, prefix="/v1")


@app.get("/internal/debug/stats")
def debug_stats() -> dict:
    # Not in any spec: an orphan candidate for P2.
    return {"runs": db.count_runs()}
