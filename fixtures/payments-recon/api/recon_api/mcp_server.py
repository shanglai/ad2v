"""MCP server exposing reconciliation summaries to agents."""

from mcp.server.fastmcp import FastMCP

from recon_api import db

mcp = FastMCP("payments-recon")


@mcp.tool()
def reconciliation_summary(run_id: str) -> dict:
    """Summarize a reconciliation run for an agent.

    ad2v: REQ-006
    """
    run = db.get_run(run_id)
    unmatched = db.list_unmatched(run_id)
    return {"run": run, "unmatched": len(unmatched)}
