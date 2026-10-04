"""P6.1 M1: routes registered imperatively, inside app factories, and through route lists."""

from __future__ import annotations

import sqlite3

from ad2v import pipeline

from helpers import run_code, write_tree


def routes(g) -> dict[str, dict]:
    return {
        f"{n.attrs['method']} {n.attrs['path']}": n.attrs for n in g.nodes.values() if n.kind == "http_route"
    }


def test_fastapi_factory_decorators_and_include_chains(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/items.py": """
                from fastapi import APIRouter
                from app.admin import admin

                router = APIRouter(prefix="/items")
                router.include_router(admin, prefix="/admin")

                @router.get("/{item_id}")
                def get_item(item_id: str):
                    return {}
            """,
            "app/admin.py": """
                from fastapi import APIRouter

                admin = APIRouter()

                def purge():
                    return {}

                admin.add_api_route("/purge", purge, methods=["POST", "DELETE"])
            """,
            "app/factory.py": """
                from fastapi import FastAPI
                from app.items import router as items_router

                BASE = "/api"
                VERSION = "v2"

                def create_app():
                    app = FastAPI()
                    prefix = BASE + "/" + VERSION

                    @app.get("/ping")
                    def ping():
                        return {}

                    app.include_router(items_router, prefix=f"{prefix}")
                    return app
            """,
        },
    )
    r = routes(g)
    assert set(r) == {
        "GET /ping",
        "GET /api/v2/items/{item_id}",
        "POST /api/v2/items/admin/purge",
        "DELETE /api/v2/items/admin/purge",
    }, sorted(r)
    assert r["POST /api/v2/items/admin/purge"]["registration"] == "add_api_route"
    assert not any(a.get("path_unresolved") for a in r.values())
    assert "registration" not in r["GET /ping"]  # decorator routes keep their P6 attrs


def test_flask_blueprint_in_factory_and_add_url_rule(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "web/__init__.py": """
                from flask import Blueprint, Flask

                def stats_view():
                    return "ok"

                def create_app():
                    app = Flask(__name__)
                    bp = Blueprint("admin", __name__)
                    bp.add_url_rule("/stats", "stats", stats_view, methods=["GET", "POST"])

                    @bp.route("/health")
                    def health():
                        return "ok"

                    app.add_url_rule("/", view_func=stats_view)
                    app.register_blueprint(bp, url_prefix="/admin")
                    return app
            """,
        },
    )
    assert set(routes(g)) == {"GET /admin/stats", "POST /admin/stats", "GET /admin/health", "GET /"}


def test_starlette_route_lists_and_mounts(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "svc/main.py": """
                from starlette.applications import Starlette
                from starlette.routing import Mount, Route

                async def home(request):
                    return None

                async def user(request):
                    return None

                USERS = "/users"
                routes = [
                    Route("/", home),
                    Mount(USERS, routes=[Route("/{id}", user, methods=["GET", "DELETE"])]),
                ]
                app = Starlette(routes=routes)

                def make_admin():
                    inner = [Route("/ping", endpoint=home)]
                    return Starlette(routes=[Mount("/admin", routes=inner)])
            """,
        },
    )
    r = routes(g)
    assert set(r) == {"GET /", "GET /users/{id}", "DELETE /users/{id}", "GET /admin/ping"}
    assert r["GET /users/{id}"]["registration"] == "route_list"


def test_unresolved_prefix_is_emitted_and_pairs_as_needs_review(tmp_path):
    repo = tmp_path / "repo"
    write_tree(
        repo,
        {
            "svc/main.py": """
                import os
                from fastapi import APIRouter, FastAPI

                router = APIRouter()

                @router.get("/items/{item_id}")
                def get_item(item_id: str):
                    return {}

                app = FastAPI()
                app.include_router(router, prefix=os.environ["API_PREFIX"])
            """,
            "specs/openapi.yaml": """
                openapi: 3.0.3
                info: {title: t, version: "1"}
                paths:
                  /api/items/{item_id}:
                    get:
                      responses: {"200": {description: ok}}
                  /api/other:
                    get:
                      responses: {"200": {description: ok}}
            """,
        },
    )
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(repo, repo / "specs", out)
    c = sqlite3.connect(out)
    head = c.execute("SELECT value FROM meta WHERE key='head_epoch'").fetchone()[0]
    rows = dict(
        c.execute(
            "SELECT n.qualified_name, s.status FROM nodes n JOIN node_status s"
            " ON s.node_id = n.id AND s.epoch_id = n.epoch_id"
            " WHERE n.epoch_id = ? AND n.kind IN ('spec_endpoint', 'http_route')",
            (head,),
        ).fetchall()
    )
    route = next(q for q in rows if q.startswith("http:"))
    assert rows["GET /api/items/{item_id}"] == "needs_review"  # never a false `missing`
    assert rows["GET /api/other"] == "missing"  # the tail does not match: still missing
    attrs = c.execute(
        "SELECT attrs_json FROM nodes WHERE epoch_id = ? AND qualified_name = ?", (head, route)
    ).fetchone()[0]
    assert '"path_unresolved":true' in attrs and '"path_tail":"/items/{item_id}"' in attrs
    ev = c.execute(
        "SELECT evidence_json FROM links WHERE epoch_id = ? AND status = 'needs_review'", (head,)
    ).fetchone()[0]
    assert "unresolved_route_path" in ev


def test_fold_keeps_partial_fstrings_inexact(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "svc/main.py": """
                from fastapi import FastAPI

                def version():
                    return "v9"

                app = FastAPI()

                @app.get(f"/api/{version()}/x")
                def x():
                    return {}
            """,
        },
    )
    (a,) = routes(g).values()
    assert a["path_unresolved"] is True and a["path"] == "/api" and a["path_tail"] == ""
