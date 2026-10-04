"""App factory for the operator surface (P6.1 fixture: routes registered inside create_app).

Nothing here is a decorator: the router is built in the factory, the route is added with
add_api_route, and the router is mounted under a prefix taken from a module constant.
"""

from fastapi import APIRouter, FastAPI

from recon_api import db
from recon_api.settings import audit

API_PREFIX = "/v1"
RUNS_PREFIX = f"{API_PREFIX}/reconciliations"


def export_run(run_id: str) -> dict:
    run = db.get_run(run_id)
    return {"run_id": run_id, "rows": run["rows"] if run else []}


def create_app() -> FastAPI:
    app = FastAPI(title="payments-recon operator")
    runs = APIRouter()
    runs.add_api_route("/{run_id}/export", export_run, methods=["GET"])
    app.include_router(runs, prefix=RUNS_PREFIX)
    app.include_router(audit)  # prefix from a Settings default (P7)
    return app
