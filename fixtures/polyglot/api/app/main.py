"""The API side of the polyglot fixture (P8.1): Python, so ad2v evaluates it."""

from fastapi import FastAPI

app = FastAPI()


# ad2v: REQ-001
@app.get("/v1/items")
def list_items() -> list[dict]:
    return []
