"""Liveness endpoint for the worker (same route as the API: an ambiguous pairing on purpose)."""

from fastapi import FastAPI

health_app = FastAPI(title="recon-worker-health")


@health_app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "component": "worker"}
