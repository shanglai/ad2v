"""Locate bundled schema files (wheel: ad2v/_schema, source checkout: <repo>/schema)."""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def schema_dir() -> Path:
    bundled = _HERE / "_schema"
    if bundled.is_dir():
        return bundled
    for parent in _HERE.parents:
        candidate = parent / "schema"
        if (candidate / "ad2v-v0.6.sql").is_file():
            return candidate
    raise FileNotFoundError("ad2v schema directory not found")


def ddl_path() -> Path:
    return schema_dir() / "ad2v-v0.6.sql"


def ir_schema_path() -> Path:
    return schema_dir() / "ir-v0.6.schema.json"


def python_rules_path() -> Path:
    return _HERE / "extract" / "code" / "rules" / "python.yaml"
