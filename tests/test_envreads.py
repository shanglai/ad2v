"""P10 (ADR-0080): the env var names the Python code reads (names only, nothing executed)."""

from __future__ import annotations

from ad2v import ir
from ad2v.infra import envreads

SRC = """import os
from os import environ, getenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

A = os.environ["A_URL"]
B = os.getenv("B")
C = os.environ.setdefault("C_MODE", "x")
D = environ["D_KEY"]
E = os.getenv(f"DYN_{A}")        # not a literal: ignored
F = os.environ[A]                # not a literal: ignored
G = os.getenv("bad name")        # not an env var name: ignored


def handler():
    return environ.get("H_TOKEN") or getenv("I_LEVEL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="app_")
    db_url: str = "x"
    token: str = Field("", alias="BANK_TOKEN")
    region: str = Field("eu", validation_alias="CLOUD_REGION")
    _private: int = 1
    plain = 3                     # no annotation: not a field


class Legacy(BaseSettings):
    class Config:
        env_prefix = "LEG_"

    port: int = 8080


class NoPrefix(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")
    timeout: int = 5


class NotSettings:
    ignored: str = "x"
"""


def test_reads_in_finds_literals_settings_and_prefixes():
    got = envreads.reads_in(SRC)
    names = sorted({n for n, _ in got})
    assert names == [
        "APP_DB_URL",
        "A_URL",
        "B",
        "BANK_TOKEN",
        "CLOUD_REGION",
        "C_MODE",
        "D_KEY",
        "H_TOKEN",
        "I_LEVEL",
        "LEG_PORT",
        "TIMEOUT",
    ]
    lines = dict(got)
    assert lines["A_URL"] == 6 and lines["H_TOKEN"] == 16


def test_collect_attaches_to_innermost_node_and_container():
    g = ir.Graph()
    sysn = g.add_node(ir.Node("code", "system", "s", "s"))
    c = g.add_node(ir.Node("code", "container", "api", "container:api", parent_id=sysn.id))
    m = g.add_node(
        ir.Node(
            "code",
            "module",
            "app.py",
            "api/app.py",
            parent_id=c.id,
            path="api/app.py",
            span_start_line=1,
            span_end_line=45,
        )
    )
    f = g.add_node(
        ir.Node(
            "code",
            "function",
            "handler",
            "api/app.py::handler",
            parent_id=m.id,
            path="api/app.py",
            span_start_line=16,
            span_end_line=17,
        )
    )
    got = envreads.collect(g, {"api/app.py": SRC, "README.md": "x"})
    assert got[f.id] == ["H_TOKEN", "I_LEVEL"]
    assert "A_URL" in got[m.id] and "H_TOKEN" not in got[m.id]
    assert set(got[c.id]) == {n for n, _ in envreads.reads_in(SRC)}
    assert envreads.collect(g, {}) == {}  # no source text: nothing found
