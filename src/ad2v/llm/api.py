"""`ad2v llm plan|run` and the cache-only rebuild of informative rows (format spec §11.2).

- `plan`: read-only. Lists the calls still needed after cache hits, with token and USD
  estimates per task (the provider's countTokens when live and allowed, else chars/4).
- `run`: needs an explicit `max_cost_usd` (the CLI also needs `--yes`). Materializes the epoch,
  answers from the cache, calls the provider for misses until the next call would exceed the
  budget, and logs an `llm_runs` row.
- `rebuild`: cache only, never a call. Rebuilds a materialized epoch's informative rows (new
  heads, `materialize`, `pin`), so a cache hit costs nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ad2v import materialize, store
from ad2v.llm import judge, narrate, prose, suggest, summarize
from ad2v.llm.config import TASKS, LLMConfig
from ad2v.llm.context import EpochView
from ad2v.llm.providers import LLMProvider, get_provider
from ad2v.llm.runner import Executor, end_run, start_run


class LLMRunError(RuntimeError):
    pass


def parse_tasks(spec: str | None) -> list[str]:
    tasks = [t.strip() for t in (spec or ",".join(TASKS)).split(",") if t.strip()]
    bad = [t for t in tasks if t not in TASKS]
    if bad:
        raise LLMRunError(f"unknown task(s): {', '.join(bad)}; choose from {', '.join(TASKS)}")
    return [t for t in TASKS if t in tasks]  # dependency order: judge, suggest, summarize, narrate, prose


def _dispatch(view: EpochView, ex: Executor, task: str, opts: dict[str, Any]) -> None:
    if task == "judge":
        judge.run(view, ex)
    elif task == "suggest":
        suggest.run(view, ex)
    elif task == "summarize":
        summarize.run(view, ex, opts.get("scope"))
    elif task == "narrate":
        narrate.run(view, ex, opts.get("mode", "containment"), opts.get("workflow"))
    elif task == "extract-prose":
        prose.run(view, ex, opts.get("spec_root"), opts.get("first_req", 1), opts.get("first_cmp", 1))


def plan(
    path: Path,
    cfg: LLMConfig,
    tasks: list[str],
    epoch: str = "head",
    *,
    provider: LLMProvider | None = None,
    count_tokens: bool = False,
    use_cache: bool = True,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = store.open_readonly(Path(path))
    try:
        epochs = (
            [r["epoch_id"] for r in store.epoch_rows(conn)]
            if epoch == "all"
            else [store.resolve_epoch(conn, epoch)]
        )
        prov = provider or get_provider(cfg)
        ex = Executor(conn, cfg, prov, mode="plan", use_cache=use_cache, count_live_tokens=count_tokens)
        for e in epochs:  # oldest first: a job planned for an earlier epoch is a later cache hit
            view = EpochView(conn, e, cfg)
            for t in tasks:
                _dispatch(view, ex, t, opts or {})
        r = report(ex, epochs[-1], cfg, tasks)
        r["epochs_planned"] = len(epochs)
        return r
    finally:
        conn.close()


def run(
    path: Path,
    cfg: LLMConfig,
    tasks: list[str],
    max_cost_usd: float,
    epoch: str = "head",
    *,
    provider: LLMProvider | None = None,
    use_cache: bool = True,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prov = provider or get_provider(cfg)
    if max_cost_usd > cfg.budget_usd:
        raise LLMRunError(f"--max-cost-usd {max_cost_usd} exceeds llm.budget_usd {cfg.budget_usd}")
    if prov.live and (cfg.input_per_mtok is None or cfg.output_per_mtok is None):
        raise LLMRunError(
            "a live provider needs llm.pricing (input_per_mtok, output_per_mtok) to enforce the budget"
        )
    conn = store.open_rw(Path(path))
    try:
        e = store.resolve_epoch(conn, epoch)
        with conn:
            materialize.materialize(conn, e)
        ex = Executor(conn, cfg, prov, mode="run", max_cost_usd=max_cost_usd, use_cache=use_cache)
        with conn:
            start_run(conn, ex, e, tasks)
        view = EpochView(conn, e, cfg)
        for t in tasks:
            with conn:  # commit per task: results already paid for are never lost
                _dispatch(view, ex, t, opts or {})
        with conn:
            end_run(conn, ex, {"use_cache": use_cache, **{k: str(v) for k, v in (opts or {}).items()}})
        return report(ex, e, cfg, tasks)
    finally:
        conn.close()


def rebuild(
    conn: sqlite3.Connection, epoch_id: str, cfg: LLMConfig, provider: LLMProvider | None = None
) -> dict[str, Any]:
    """Informative rows of a materialized epoch from cached results only. No provider call."""
    if not conn.execute("SELECT 1 FROM llm_results LIMIT 1").fetchone() or not store.is_materialized(
        conn, epoch_id
    ):
        return {}
    ex = Executor(conn, cfg, provider or get_provider(cfg), mode="cache_only")
    view = EpochView(conn, epoch_id, cfg)
    for t in ("judge", "suggest", "summarize", "narrate"):
        _dispatch(view, ex, t, {})
    return report(ex, epoch_id, cfg, list(TASKS))


def report(ex: Executor, epoch_id: str, cfg: LLMConfig, tasks: list[str]) -> dict[str, Any]:
    per = {t: asdict(ex.stats.get(t) or type(ex.totals())()) for t in tasks}
    tot = asdict(ex.totals())
    return {
        "epoch_id": epoch_id,
        "mode": ex.mode,
        "provider": ex.provider.name,
        "model": ex.provider.model,
        "model_version": ex.model_version,
        "llm_config_hash": cfg.llm_config_hash,
        "token_counter": ex.token_counter_used,
        "priced": cfg.input_per_mtok is not None and cfg.output_per_mtok is not None,
        "tasks": per,
        "totals": tot,
        "aborted": ex.aborted,
        "run_id": ex.run_id,
        "spent_usd": round(ex.spent_usd, 6),
    }
