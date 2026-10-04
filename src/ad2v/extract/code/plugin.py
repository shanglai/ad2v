"""The built-in plug-ins (ADR-0063): the Python extractor and the Python framework pack.

Both are registered as entry points in pyproject.toml and in the internal registry
(`ad2v.plugins`), and both are always active. They use only the public API (`ad2v.api`) at their
boundary; their internals stay where they were (`python.py`, `schema_digest.py`).
"""

from __future__ import annotations

from pathlib import Path

from ad2v.api import API_VERSION, ExtractContext, ExtractOutput, FrameworkContext
from ad2v.extract.code import schema_digest
from ad2v.extract.code.python import PythonExtractor
from ad2v.extract.code.python_local import LOCAL_EXTRACTOR_VERSION

RULES_DIR = Path(__file__).resolve().parent / "rules"

# Node kinds the Python extractor emits besides system/container/component (ir.NODE_KINDS).
PYTHON_NODE_KINDS = frozenset(
    {
        "module",
        "class",
        "function",
        "http_route",
        "cli_command",
        "mcp_tool",
        "event_consumer",
        "datastore",
        "external_service",
        "queue",
        "llm_endpoint",
        "loop",
        "retry",
        "fan_out",
        "transaction",
        "llm_call",
    }
)
PYTHON_EDGE_KINDS = frozenset(
    {
        "contains",
        "imports",
        "calls",
        "exposes",
        "reads",
        "writes",
        "publishes",
        "consumes",
        "invokes_external",
        "invokes_llm",
    }
)


class PythonPlugin:
    """The built-in Python extractor (tree-sitter), behind the public interface.

    `version` enters the epoch identity: bump it whenever extraction output can change for the
    same files and rules (ADR-0063). `cache_version` is the per-file parse-cache record version.
    """

    api_version = API_VERSION
    name = "python"
    version = "1.0.0"
    languages = ("python",)
    file_patterns = ("*.py",)
    rules_files = (RULES_DIR / "python.yaml",)
    node_kinds = PYTHON_NODE_KINDS
    edge_kinds = PYTHON_EDGE_KINDS
    cache_version = LOCAL_EXTRACTOR_VERSION

    def extract(self, ctx: ExtractContext) -> ExtractOutput:
        ex = PythonExtractor(ctx.config, dict(ctx.rules))
        facts = ex.extract(ctx.graph, ctx.layout, list(ctx.files), dict(ctx.cache))
        return ExtractOutput(
            facts=facts,
            cache_entries=dict(ex.new_cache_entries),
            timings=dict(ex.timings),
            stats={"cache_hits": ex.cache_hits, "cache_misses": ex.cache_misses},
        )


class PythonFrameworksPack:
    """The built-in Python framework pack: FastAPI, Flask, Starlette; Celery, APScheduler,
    `schedule`; Click, Typer; MCP tool registration (rules fragment `python-frameworks.yaml`), and
    SQLAlchemy / SQL DDL / Pydantic schema digests (post-extract hook, ADR-0059)."""

    api_version = API_VERSION
    name = "python-frameworks"
    version = "1.0.0"
    attaches_to = ("python",)
    frameworks = (
        "fastapi",
        "flask",
        "starlette",
        "celery",
        "apscheduler",
        "schedule",
        "click",
        "typer",
        "sqlalchemy",
        "pydantic",
        "mcp",
    )
    file_patterns = ("*.sql",)
    rules_files = (RULES_DIR / "python-frameworks.yaml",)
    node_kinds: frozenset[str] = frozenset()  # the hook only adds attrs
    edge_kinds: frozenset[str] = frozenset()

    def post_extract(self, ctx: FrameworkContext) -> None:
        py = [f for f in ctx.files if f.path.endswith(".py")]
        sql = [f for f in ctx.files if f.path.endswith(".sql")]
        schema_digest.apply(ctx.graph, py, sql)
