"""A tiny Bottle app (example fixture for the ad2v framework-pack API)."""

from bottle import Bottle

app = Bottle()


@app.get("/hello/<name>")
def hello(name: str) -> dict:
    return {"hello": name}


@app.route("/health")
def health() -> dict:
    return {"ok": True}
