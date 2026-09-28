"""Planning and running LLM calls: cache, budget, validation, run log (format spec §11.2).

A task produces `Job`s and asks the `Executor` for each one. The executor answers from the
`llm_results` cache when it can, and otherwise, depending on its mode:

- `plan`: records the miss with a token and USD estimate and returns None (no call);
- `cache_only`: returns None (rebuilding informative rows from the cache never costs anything);
- `run`: calls the provider unless that would exceed the budget, validates the output (JSON
  Schema, the task's deterministic checks, the injection guards), stores it, and returns it.

Nothing here writes a normative table.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from ad2v import ids
from ad2v.llm import fence
from ad2v.llm.config import SEED, LLMConfig
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.providers import LLMProvider, ProviderError

# Output-token estimates used for planning and for the pre-call budget check.
OUTPUT_ESTIMATE = {"judge": 300, "suggest": 350, "summarize": 450, "narrate": 400, "extract-prose": 1500}
MODES = ("plan", "run", "cache_only")


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Job:
    task: str
    subject: str
    data_parts: list[str]  # fenced untrusted content, in order
    instructions: str  # the task's user instructions (trusted, from the prompt template + ad2v)
    schema: dict[str, Any]
    validator: Callable[[Any], list[dict[str, str]]] = lambda _out: []
    output_estimate: int | None = None
    verbatim_check: bool = True
    # Repository-derived text the injection guards check against (default: all data parts). Tasks
    # exclude earlier LLM output they pass as context (coarser narrations, child summaries).
    haystack: str | None = None

    @property
    def user_parts(self) -> list[str]:
        return [self.instructions, *self.data_parts]

    @property
    def input_hash(self) -> str:
        return ids.sha256_hex(ids.canonical_json({"task": self.task, "parts": self.user_parts}))


@dataclass
class Result:
    result_id: str
    output: Any
    valid: bool
    errors: list[dict[str, str]]
    cached: bool
    task: str
    subject: str


@dataclass
class TaskStats:
    jobs: int = 0
    hits: int = 0
    misses: int = 0
    calls: int = 0
    invalid: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_input_tokens: int = 0
    est_output_tokens: int = 0
    cost_usd: float = 0.0
    est_cost_usd: float = 0.0
    skipped_budget: int = 0


@dataclass
class Executor:
    conn: sqlite3.Connection
    cfg: LLMConfig
    provider: LLMProvider
    mode: str = "plan"
    max_cost_usd: float = 0.0
    use_cache: bool = True
    count_live_tokens: bool = False  # plan: use the provider's countTokens (live providers only)
    run_id: str | None = None
    stats: dict[str, TaskStats] = field(default_factory=dict)
    spent_usd: float = 0.0
    aborted: bool = False
    model_version: str | None = None
    token_counter_used: str = "estimate(chars/4)"
    planned: set[tuple[str, ...]] = field(default_factory=set)  # plan mode: keys already counted

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")

    # -- keys ---------------------------------------------------------------------------------
    def params(self, task: str) -> dict[str, Any]:
        return {"temperature": 0, "seed": SEED, "output_language": self.cfg.output_language, "task": task}

    def key(self, job: Job) -> tuple[str, str, str, str, str, str]:
        prompt = load_prompt(job.task)
        return (
            job.task,
            job.input_hash,
            prompt.prompt_hash,
            self.provider.name,
            self.provider.model,
            ids.sha256_hex(ids.canonical_json(self.params(job.task))),
        )

    def lookup(self, job: Job) -> Result | None:
        row = self.conn.execute(
            "SELECT * FROM llm_results WHERE task=? AND input_hash=? AND prompt_hash=? AND provider=?"
            " AND model=? AND params_hash=? ORDER BY seq DESC LIMIT 1",
            self.key(job),
        ).fetchone()
        if row is None:
            return None
        out = json.loads(row["output_json"]) if row["output_json"] is not None else None
        errors = json.loads(row["validation_errors"])
        if not any(e["code"] == "provider_error" for e in errors):
            # validation is deterministic and cheap: re-run it, so rule fixes apply to cached outputs
            errors = self.validate(job, out)
        valid = not any(e["severity"] == "error" for e in errors)
        if self.mode != "plan" and (
            valid != bool(row["valid"]) or errors != json.loads(row["validation_errors"])
        ):
            self.conn.execute(
                "UPDATE llm_results SET valid = ?, validation_errors = ? WHERE result_id = ?",
                (int(valid), ids.canonical_json(errors), row["result_id"]),
            )
        return Result(row["result_id"], out, valid, errors, True, job.task, job.subject)

    # -- the one entry point for tasks ----------------------------------------------------------
    def call(self, job: Job) -> Result | None:
        st = self.stats.setdefault(job.task, TaskStats())
        st.jobs += 1
        hit = self.lookup(job) if self.use_cache else None
        if hit is not None:
            st.hits += 1
            self._log(hit.result_id, cached=True)
            return hit
        if self.mode == "plan" and self.use_cache:  # planned earlier in this plan (another epoch)
            key = self.key(job)
            if key in self.planned:
                st.hits += 1
                return None
            self.planned.add(key)
        st.misses += 1
        prompt = load_prompt(job.task)
        system = self.system(prompt.system)
        est_in = self._estimate_input(job, system)
        est_out = job.output_estimate or OUTPUT_ESTIMATE[job.task]
        if st.calls:  # learn from this run: reasoning models often exceed the static estimate
            est_out = max(est_out, -(-st.output_tokens // st.calls))
        est_cost = self.cfg.cost_usd(est_in, est_out) or 0.0
        st.est_input_tokens += est_in
        st.est_output_tokens += est_out
        st.est_cost_usd += est_cost
        if self.mode != "run":
            return None
        if self.aborted or self.spent_usd + est_cost > self.max_cost_usd:
            self.aborted = True
            st.skipped_budget += 1
            return None
        try:
            pr = self.provider.generate(
                job.task, system, job.user_parts, job.schema, {"subject": job.subject}
            )
        except ProviderError as e:
            pr = None
            errors = [{"code": "provider_error", "message": str(e)[:300], "severity": "error"}]
        st.calls += 1
        if pr is None:
            out, usage, latency, version = None, {"input_tokens": 0, "output_tokens": 0}, None, None
        else:
            out = pr.parsed
            usage = {"input_tokens": pr.input_tokens, "output_tokens": pr.output_tokens}
            latency, version = pr.latency_ms, pr.model_version
            self.model_version = version or self.model_version
            errors = self.validate(job, out)
        cost = self.cfg.cost_usd(usage["input_tokens"], usage["output_tokens"])
        self.spent_usd += cost or 0.0
        st.input_tokens += usage["input_tokens"]
        st.output_tokens += usage["output_tokens"]
        st.cost_usd += cost or 0.0
        valid = not any(e["severity"] == "error" for e in errors)
        st.invalid += 0 if valid else 1
        rid = self._store(job, out, valid, errors, usage, cost, latency, version)
        return Result(rid, out, valid, errors, False, job.task, job.subject)

    def system(self, template: str) -> str:
        return template.replace("{output_language}", self.cfg.output_language)

    def _estimate_input(self, job: Job, system: str) -> int:
        if self.count_live_tokens and self.provider.live:
            self.token_counter_used = f"{self.provider.name} countTokens"
            return self.provider.count_tokens(job.task, system, job.user_parts)
        return fence_estimate(system, job.user_parts)

    # -- validation -----------------------------------------------------------------------------
    def validate(self, job: Job, out: Any) -> list[dict[str, str]]:
        if out is None:
            return [{"code": "not_json", "message": "output is not JSON", "severity": "error"}]
        errors: list[dict[str, str]] = []
        for err in sorted(
            jsonschema.Draft202012Validator(job.schema).iter_errors(out), key=lambda e: list(e.path)
        ):
            errors.append({"code": "schema", "message": err.message[:200], "severity": "error"})
        if errors:
            return errors
        errors.extend(job.validator(out))
        data = job.haystack if job.haystack is not None else "\n".join(job.data_parts)
        if job.verbatim_check:
            copied = fence.verbatim_copy(out, data)
            if copied is not None:  # quoting data is flagged; echoing an instruction invalidates
                severity = "error" if fence.injection_phrases(copied) else "warning"
                errors.append({"code": "verbatim_copy", "message": copied, "severity": severity})
        phrases = fence.injection_phrases(data)
        if phrases:
            errors.append(
                {"code": "injection_suspected", "message": "; ".join(phrases)[:200], "severity": "warning"}
            )
        return errors

    # -- storage --------------------------------------------------------------------------------
    def _store(
        self,
        job: Job,
        out: Any,
        valid: bool,
        errors: list[dict[str, str]],
        usage: dict[str, int],
        cost: float | None,
        latency: int | None,
        version: str | None,
    ) -> str:
        key = self.key(job)
        n = self.conn.execute(
            "SELECT COUNT(*) FROM llm_results WHERE task=? AND input_hash=? AND prompt_hash=? AND provider=?"
            " AND model=? AND params_hash=?",
            key,
        ).fetchone()[0]
        rid = "r_" + ids.sha256_hex(ids.canonical_json([*key, n]))[: ids.ID_HEX_LEN]
        seq = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM llm_results").fetchone()[0]
        self.conn.execute(
            "INSERT INTO llm_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                seq,
                key[0],
                key[1],
                key[2],
                key[3],
                key[4],
                version,
                key[5],
                job.subject,
                None if out is None else ids.canonical_json(out),
                int(valid),
                ids.canonical_json(errors),
                ids.canonical_json(usage),
                cost,
                latency,
                now(),
            ),
        )
        self._log(rid, cached=False)
        return rid

    def _log(self, result_id: str, cached: bool) -> None:
        if self.run_id is not None:
            self.conn.execute(
                "INSERT OR IGNORE INTO llm_run_results VALUES (?,?,?)", (self.run_id, result_id, int(cached))
            )

    # -- totals ---------------------------------------------------------------------------------
    def totals(self) -> TaskStats:
        t = TaskStats()
        for s in self.stats.values():
            for f in t.__dataclass_fields__:
                setattr(t, f, getattr(t, f) + getattr(s, f))
        return t


def fence_estimate(system: str, parts: list[str]) -> int:
    from ad2v.llm.providers.base import estimate_tokens

    return estimate_tokens(system, parts)


def now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def start_run(conn: sqlite3.Connection, ex: Executor, epoch_id: str, tasks: list[str]) -> str:
    started = now()
    run_id = (
        "u_" + ids.sha256_hex(f"{started}|{','.join(tasks)}|{epoch_id}|{ex.provider.model}")[: ids.ID_HEX_LEN]
    )
    n = conn.execute("SELECT COUNT(*) FROM llm_runs WHERE run_id LIKE ?", (run_id + "%",)).fetchone()[0]
    run_id = run_id if n == 0 else f"{run_id}{n}"
    conn.execute(
        "INSERT INTO llm_runs(run_id, started_at, epoch_id, provider, model, llm_config_hash,"
        " llm_config_json, tasks_json, max_cost_usd) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            started,
            epoch_id,
            ex.provider.name,
            ex.provider.model,
            ex.cfg.llm_config_hash,
            ids.canonical_json(ex.cfg.effective()),
            ids.canonical_json(tasks),
            ex.max_cost_usd,
        ),
    )
    ex.run_id = run_id
    return run_id


def end_run(conn: sqlite3.Connection, ex: Executor, notes: dict[str, Any] | None = None) -> None:
    t = ex.totals()
    conn.execute(
        "UPDATE llm_runs SET ended_at=?, model_version=?, calls=?, cache_hits=?, input_tokens=?,"
        " output_tokens=?, cost_usd_est=?, aborted=?, notes_json=? WHERE run_id=?",
        (
            now(),
            ex.model_version,
            t.calls,
            t.hits,
            t.input_tokens,
            t.output_tokens,
            round(t.cost_usd, 6),
            int(ex.aborted),
            ids.canonical_json(notes or {}),
            ex.run_id,
        ),
    )
