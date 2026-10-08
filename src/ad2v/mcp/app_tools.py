"""App-only tools: the viewer's `DataSource`, one tool per method (P6 §4, ADR-0041).

`_meta.ui.visibility = ["app"]`: hosts hide these from the model and let only the ad2v map (the
MCP App) call them. Results are the `slices` values under `structuredContent.data`; lists and
maps longer than a page are paginated with `nextCursor` (the client loops). The text content
is a one-line receipt: these results never need to reach the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ad2v.mcp import slices
from ad2v.mcp.files import FileAccessError
from ad2v.mcp.protocol import Request, Tool, tool_error
from ad2v.mcp.tools import EPOCH, FILE, MAP_URI, Ctx, ToolFail, schema

PAGE = 2000  # items per page for lists and maps
MAX_SCENE_BYTES = 8 * 1024 * 1024
INTERNAL = "internal: used by the ad2v map UI. "
ID = {"type": "string", "minLength": 1, "maxLength": 200}
CUR = {"type": "string", "maxLength": 16}


def _page(value: Any, cursor: str | None) -> dict[str, Any]:
    try:
        start = int(cursor or 0)
    except ValueError:
        raise ToolFail("invalid cursor") from None
    if isinstance(value, list):
        chunk: Any = value[start : start + PAGE]
        total = len(value)
    elif isinstance(value, dict) and (len(value) > PAGE or cursor):
        keys = sorted(value)
        chunk = {k: value[k] for k in keys[start : start + PAGE]}
        total = len(keys)
    else:
        return {"data": value}
    out: dict[str, Any] = {"data": chunk}
    if start + PAGE < total:
        out["nextCursor"] = str(start + PAGE)
    return out


def make_app_tools(ctx: Ctx) -> list[Tool]:
    def mk(
        name: str,
        method: str,
        props: dict[str, Any],
        required: list[str],
        fn: Callable[..., Any],
        materialized: bool = True,
        paged: bool = True,
    ) -> Tool:
        def h(req: Request, a: dict[str, Any]) -> dict[str, Any]:
            try:
                path, conn, e = ctx.open(
                    {"file": a.get("file"), "epoch": a.get("epoch")}, need_materialized=materialized
                )
                val = fn(conn, e, a)
                sc = _page(val, a.get("cursor")) if paged else {"data": val}
                if name == "viewer_scene":
                    size = len(json.dumps(sc, separators=(",", ":")))
                    if size > MAX_SCENE_BYTES:
                        raise ToolFail("scene too large: pass root_id and a smaller depth")
                sc["file"] = ctx.files.label(path)
                n = len(sc["data"]) if isinstance(sc["data"], (list, dict)) else 1
                return {
                    "content": [{"type": "text", "text": f"{name}: {n} item(s)"}],
                    "structuredContent": sc,
                }
            except ToolFail as ex:
                return tool_error(ex.message, ex.data)
            except FileAccessError as ex:
                return tool_error(str(ex))
            except KeyError as ex:
                return tool_error(f"not found: {ex.args[0] if ex.args else ''}")

        props = {"file": FILE, **props}
        if paged:
            props["cursor"] = CUR
        return Tool(
            name,
            f"ad2v map: {method}",
            INTERNAL + f"Mirrors DataSource.{method}() of the viewer.",
            schema(props, required),
            h,
            visibility=("app",),
            resource_uri=MAP_URI,
        )

    ep = {"epoch": EPOCH}
    return [
        mk("viewer_meta", "meta", {}, [], lambda c, e, a: slices.meta(c), materialized=False, paged=False),
        mk("viewer_epochs", "epochs", {}, [], lambda c, e, a: slices.epochs(c), materialized=False),
        mk("viewer_nodes", "nodes", ep, ["epoch"], lambda c, e, a: slices.nodes(c, e)),
        mk("viewer_layout", "layout", ep, ["epoch"], lambda c, e, a: slices.layout(c, e)),
        mk("viewer_glyphs", "glyphs", ep, ["epoch"], lambda c, e, a: slices.glyphs(c, e)),
        mk("viewer_edges", "edges", ep, ["epoch"], lambda c, e, a: slices.edges(c, e)),
        mk(
            "viewer_status",
            "status",
            {**ep, "mode": {"type": "string", "enum": ["normative", "effective"]}},
            ["epoch", "mode"],
            lambda c, e, a: slices.status(c, e, a["mode"]),
        ),
        mk("viewer_rollups", "rollups", ep, ["epoch"], lambda c, e, a: slices.rollups(c, e)),
        mk(
            "viewer_node_detail",
            "nodeDetail",
            {**ep, "node_id": ID},
            ["epoch", "node_id"],
            lambda c, e, a: slices.node_detail(c, e, a["node_id"]),
            paged=False,
        ),
        mk("viewer_links", "links", ep, ["epoch"], lambda c, e, a: slices.links(c, e)),
        mk("viewer_judgments", "judgments", ep, ["epoch"], lambda c, e, a: slices.judgments(c, e)),
        mk("viewer_suggestions", "suggestions", ep, ["epoch"], lambda c, e, a: slices.suggestions(c, e)),
        mk("viewer_summaries", "summaries", ep, ["epoch"], lambda c, e, a: slices.summaries(c, e)),
        mk("viewer_workflows", "workflows", ep, ["epoch"], lambda c, e, a: slices.workflows(c, e)),
        mk("viewer_c4", "c4", ep, ["epoch"], lambda c, e, a: slices.c4(c, e), paged=False),
        mk("viewer_infra_status", "infraStatus", ep, ["epoch"], lambda c, e, a: slices.infra_status(c, e)),
        mk(
            "viewer_steps",
            "steps",
            {**ep, "workflow_id": ID},
            ["epoch", "workflow_id"],
            lambda c, e, a: slices.steps(c, e, a["workflow_id"]),
        ),
        mk(
            "viewer_narrations",
            "narrations",
            {**ep, "workflow_id": ID, "mode": {"type": "string", "enum": ["containment", "call_depth"]}},
            ["epoch", "workflow_id"],
            lambda c, e, a: slices.narrations(c, e, a["workflow_id"], a.get("mode") or "containment"),
        ),
        mk(
            "viewer_workflows_through",
            "workflowsThrough",
            {**ep, "node_id": ID},
            ["epoch", "node_id"],
            lambda c, e, a: slices.workflows_through(c, e, a["node_id"]),
        ),
        mk("viewer_lineage", "lineage", ep, ["epoch"], lambda c, e, a: slices.lineage(c, e)),
        mk(
            "viewer_status_history",
            "statusHistory",
            {"node_id": ID},
            ["node_id"],
            lambda c, e, a: slices.status_history(c, a["node_id"]),
            materialized=False,
        ),
        mk(
            "viewer_scene",
            "scene",
            {
                **ep,
                "root_id": {"type": "string", "maxLength": 200, "description": "omit for the whole epoch"},
                "depth": {"type": "integer", "minimum": -1, "maximum": 50},
            },
            ["epoch", "depth"],
            lambda c, e, a: slices.scene(c, e, a.get("root_id"), int(a["depth"])),
            paged=False,
        ),
    ]
