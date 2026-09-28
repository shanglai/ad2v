"""ad2v MCP server (P6): read-only tools over .ad2v files, plus the map as an MCP App.

`make_server(files)` wires the agent tools, the app-only tools and the `ui://ad2v/map` resource
into a transport-independent `protocol.Server`; `stdio.serve` / `http.serve` run it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ad2v.mcp.app_tools import make_app_tools
from ad2v.mcp.files import FileSet
from ad2v.mcp.protocol import APP_MIME, Resource, Server
from ad2v.mcp.tools import INSTRUCTIONS, MAP_URI, Ctx, agent_tools

_HERE = Path(__file__).resolve().parent

NOT_BUILT = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>ad2v map</title></head>
<body style="font-family:sans-serif;padding:16px">The ad2v map app is not built in this checkout.
Run <code>npm ci &amp;&amp; npm run build:app</code> in <code>viewer/</code>,
or install the ad2v wheel.</body></html>"""


def app_html_path() -> Path | None:
    """The built MCP App: package data in a wheel, else viewer/app-dist in a checkout."""
    bundled = _HERE.parent / "_app" / "app.html"
    if bundled.is_file():
        return bundled
    for parent in _HERE.parents:
        cand = parent / "viewer" / "app-dist" / "app.html"
        if cand.is_file():
            return cand
    return None


def _read_app() -> dict[str, Any]:
    p = app_html_path()
    text = p.read_text(encoding="utf-8") if p else NOT_BUILT
    # No external origins at all: the app gets its data only through app tools (P6 decision 4).
    return {"text": text, "_meta": {"ui": {"csp": {}, "prefersBorder": True}}}


def make_server(files: FileSet) -> Server:
    ctx = Ctx(files)
    tools = agent_tools(ctx) + make_app_tools(ctx)
    res = Resource(
        uri=MAP_URI,
        name="ad2v_map",
        title="ad2v map",
        description="Interactive isometric map of the code and its specs; renders the result of ad2v_show.",
        mime_type=APP_MIME,
        read=_read_app,
    )
    server = Server(tools, [res], INSTRUCTIONS)
    server.ctx = ctx  # type: ignore[attr-defined]
    return server
