"""Package layout (P9, ADR-0067). Project metadata lives in pyproject.toml.

The built viewer (`viewer/dist`) and MCP App (`viewer/app-dist`) are build outputs, not sources: a
fresh clone does not have them, and `pip install -e .` must still work there (the viewer is then
reported as "not built" by `ad2v view`). So they are packaged only when they exist. A release build
sets AD2V_REQUIRE_VIEWER=1, which turns a missing build into an error instead of a wheel without
a viewer.
"""

import os
from pathlib import Path

from setuptools import setup

HERE = Path(__file__).resolve().parent

PACKAGES = [
    "ad2v",
    "ad2v.extract",
    "ad2v.extract.code",
    "ad2v.extract.code.rules",
    "ad2v.extract.spec",
    "ad2v.infra",  # P10
    "ad2v.llm",
    "ad2v.llm.providers",
    "ad2v.llm.prompts",
    "ad2v._schema",
    "ad2v._schema.themes",
    "ad2v.mcp",
    "ad2v.chat",
    "ad2v.testing",
]
# schema/ is the canonical location; it ships inside the wheel as the data package ad2v._schema
PACKAGE_DIR = {"": "src", "ad2v._schema": "schema"}
PACKAGE_DATA = {
    "ad2v.extract.code.rules": ["*.yaml"],
    "ad2v.infra": ["*.yaml"],
    "ad2v.llm.prompts": ["*.md"],
    "ad2v._schema": ["*.sql", "*.json"],
    "ad2v._schema.themes": ["*.json"],
}
# (package, source directory, package data); build them with `npm ci && npm run build && npm run
# build:app` in viewer/
OPTIONAL = [
    ("ad2v._viewer", "viewer/dist", ["*.html"]),
    ("ad2v._viewer.assets", "viewer/dist/assets", ["*"]),
    ("ad2v._app", "viewer/app-dist", ["app.html"]),
]

missing = []
for package, directory, data in OPTIONAL:
    if (HERE / directory).is_dir():
        PACKAGES.append(package)
        if "." not in package.removeprefix("ad2v."):  # sub-packages follow their parent's directory
            PACKAGE_DIR[package] = directory
        PACKAGE_DATA[package] = data
    else:
        missing.append(directory)
if missing and os.environ.get("AD2V_REQUIRE_VIEWER") == "1":
    raise SystemExit(f"AD2V_REQUIRE_VIEWER=1 but these builds are missing: {', '.join(missing)}")

setup(packages=PACKAGES, package_dir=PACKAGE_DIR, package_data=PACKAGE_DATA)
