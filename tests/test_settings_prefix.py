"""P7 M2 (issue 70, ADR-0053): route prefixes from settings. Off by default (P6.1: path_unresolved
-> needs_review); `pairing.path_constants` maps an expression; `pairing.resolve_settings_defaults`
reads literal pydantic Settings defaults, with a warning evidence."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ad2v import pipeline
from ad2v.manifest import from_data

from helpers import FIXTURE, run_code


def _fixture(tmp_path: Path, pairing_extra: dict) -> pipeline.Result:
    repo = tmp_path / "payments-recon"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    m = yaml.safe_load((repo / "ad2v.yaml").read_text(encoding="utf-8"))
    m.setdefault("pairing", {}).update(pairing_extra)
    (repo / "ad2v.yaml").write_text(yaml.safe_dump(m), encoding="utf-8")
    return pipeline.build(repo, None, name_hint="payments-recon")


def _audit(res: pipeline.Result) -> tuple[dict, str, list[str], str]:
    g = res.graph
    rt = next(n for n in g.nodes.values() if n.kind == "http_route" and n.name.endswith("/audit"))
    lk = next(lk for lk in res.pairing.links if lk.code_node_id == rt.id)
    return rt.attrs, lk.status, [e["kind"] for e in lk.evidence], rt.qualified_name


@pytest.mark.parametrize(
    "mode,extra,status,evidence",
    [
        ("off", {}, "needs_review", "unresolved_route_path"),
        (
            "manifest",
            {"path_constants": {"settings.AUDIT_PREFIX": "/v1/reconciliations"}},
            "implemented",
            "prefix_from_path_constants",
        ),
        ("resolver", {"resolve_settings_defaults": True}, "implemented", "prefix_from_settings_default"),
    ],
)
def test_fixture_three_modes(tmp_path, mode, extra, status, evidence):
    res = _fixture(tmp_path, extra)
    attrs, st, kinds, qname = _audit(res)
    assert st == status and evidence in kinds, (mode, st, kinds)
    if mode == "off":
        assert attrs["path_unresolved"] and attrs["path_tail"] == "/{run_id}/audit"
    else:
        assert qname == "http:api:GET /v1/reconciliations/{run_id}/audit"
        assert "path_unresolved" not in attrs
    if mode == "resolver":
        lk = next(lk for lk in res.pairing.links if "prefix_from_settings_default" in str(lk.evidence))
        ev = next(e for e in lk.evidence if e["kind"] == "prefix_from_settings_default")
        assert ev["setting"] == "api/recon_api/settings.py::Settings.AUDIT_PREFIX"
        assert "override" in ev["warning"]


def test_modes_change_config_hash():
    base = from_data({"pairing": {}}, None).config_hash
    a = from_data({"pairing": {"path_constants": {"settings.X": "/x"}}}, None).config_hash
    b = from_data({"pairing": {"resolve_settings_defaults": True}}, None).config_hash
    assert len({base, a, b}) == 3
    # keys are normalized (whitespace dropped), so "settings . X" maps the same expression
    assert from_data({"pairing": {"path_constants": {"settings . X": "/x"}}}, None).path_constants == {
        "settings.X": "/x"
    }


SETTINGS_REPO = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/config.py": """
        import os
        from pydantic_settings import BaseSettings

        class Base(BaseSettings):
            pass

        class Settings(Base):                 # a subclass of a subclass still counts
            API_V1_STR: str = "/api/v1"
            FSTR: str = f"{'/f'}"            # an f-string of literal parts
            FROM_ENV: str = os.environ.get("P", "/env")   # not a literal: stays unresolved
            CALL: str = make()                # not a literal

        class Plain:                          # not a Settings class: never read
            P: str = "/plain"

        settings = Settings()
        plain = Plain()
    """,
    "app/main.py": """
        from fastapi import APIRouter, FastAPI
        from app.core.config import settings, plain

        app = FastAPI()
        r = APIRouter()

        @r.get("/items")
        def items():
            return []

        app.include_router(r, prefix=settings.API_V1_STR)
        app.include_router(r, prefix=settings.FSTR)
        app.include_router(r, prefix=settings.FROM_ENV)
        app.include_router(r, prefix=settings.CALL)
        app.include_router(r, prefix=plain.P)
    """,
}


def _paths(g) -> dict[str, dict]:
    return {n.attrs["path"]: n.attrs for n in g.nodes.values() if n.kind == "http_route"}


def test_resolver_reads_only_literal_settings_defaults(tmp_path):
    g, _ = run_code(
        tmp_path, SETTINGS_REPO, from_data({"pairing": {"resolve_settings_defaults": True}}, None)
    )
    p = _paths(g)
    assert p["/api/v1/items"]["prefix_sources"] == [
        "settings_default:app/core/config.py::Settings.API_V1_STR"
    ]
    assert "/f/items" in p
    unresolved = [a for a in p.values() if a.get("path_unresolved")]
    assert len(unresolved) == 1 and unresolved[0]["path_tail"] == "/items"  # FROM_ENV, CALL, plain.P


def test_off_by_default_and_manifest_map_wins_without_the_resolver(tmp_path):
    g, _ = run_code(tmp_path / "a", SETTINGS_REPO, from_data({}, None))
    assert all(a.get("path_unresolved") for a in _paths(g).values())
    cfg = from_data(
        {"pairing": {"path_constants": {"settings.API_V1_STR": "/api/v1", "plain.P": "/p"}}}, None
    )
    g, _ = run_code(tmp_path / "b", SETTINGS_REPO, cfg)
    p = _paths(g)
    assert p["/api/v1/items"]["prefix_sources"] == ["path_constants:settings.API_V1_STR"]
    assert p["/p/items"]["prefix_sources"] == ["path_constants:plain.P"]
