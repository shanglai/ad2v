"""The viewer's own chat agent (P7, ADR-0056): bring your own model, server-side in `ad2v view`.

One turn: the question plus a trimmed history goes to the model with tool declarations generated
from the MCP agent tools; each tool call runs in-process through the MCP server's dispatcher
(same validation, same fenced `untrusted_text` output); up to `max_iterations` model steps; the
model ends the turn with the `ad2v_answer` tool. Then, deterministically:

- citations are checked: an id counts only if it appeared in this turn's tool results;
- an answer that echoes an injection phrase found in the tool results is flagged;
- every model call is an `llm_results` row (task 'chat') and the turn an `llm_runs` row (class I).

There are no write tools. The session has a USD budget with a meter; at the cap the turn is
refused (or stopped before the next call), never silently moved to another model.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v import ids, store
from ad2v.llm import fence
from ad2v.llm.config import LLMConfig
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.providers.base import ChatMsg, ProviderError, ToolCall, estimate_tokens
from ad2v.llm.runner import now
from ad2v.mcp import make_server
from ad2v.mcp.files import FileSet
from ad2v.mcp.protocol import RpcError

EXCLUDED_TOOLS = ("ad2v_files", "ad2v_llm_plan")  # decision 2: the agent gets the rest
NODE_ID = re.compile(r"\bn_[0-9a-f]{20}\b")
MAX_RESULT_CHARS = 8000
HISTORY_TURNS = 6
STATIC_OUT_PER_CALL = 400  # the static estimate (ADR-0032) ...
CALIBRATION = 2.2  # ... times the output factor observed in P4 for a live model, until this session observes
DEFAULT_CALLS_PER_TURN = 3
DEFAULT_RESULT_TOKENS = 900

ANSWER_TOOL = {
    "name": "ad2v_answer",
    "description": "Finish the turn: the answer, the node ids that support it, and optionally what "
    "the map should show. Call exactly once, last.",
    "parameters": {
        "type": "object",
        "properties": {
            "answer_markdown": {"type": "string", "maxLength": 6000, "description": "the answer, Markdown"},
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
                "description": "node ids (n_…) from this turn's tool results",
            },
            "show": {
                "type": "object",
                "description": "what the map should show at the end (optional)",
                "properties": {
                    "intent": {"type": "string", "enum": ["focus", "fit", "path", "replay", "diff"]},
                    "node_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
                    "workflow_id": {"type": "string"},
                },
                "required": ["intent"],
            },
        },
        "required": ["answer_markdown", "citations"],
    },
}

Emit = Callable[[str, dict[str, Any]], None]


@dataclass
class Meter:
    budget_usd: float
    spent_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    turns: int = 0
    result_tokens: int = 0  # tool-result tokens sent, for the per-step growth estimate
    steps_with_results: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "budget_usd": self.budget_usd,
            "spent_usd": round(self.spent_usd, 6),
            "remaining_usd": round(max(0.0, self.budget_usd - self.spent_usd), 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
            "turns": self.turns,
        }


@dataclass
class Turn:
    question: str
    answer: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def output_language(cfg: LLMConfig) -> str:
    lang = cfg.output_language
    return "the language of the user's question" if lang in ("auto", "", None) else lang


class ChatService:
    def __init__(
        self,
        ad2v_file: Path,
        cfg: LLMConfig,
        provider: Any,
        budget_usd: float = 0.25,
        max_iterations: int = 6,
    ) -> None:
        self.file = Path(ad2v_file)
        self.cfg = cfg
        self.provider = provider
        self.max_iterations = max_iterations
        self.meter = Meter(budget_usd)
        self.server = make_server(FileSet(single=self.file))
        self.history: list[Turn] = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.session_id = "c_" + ids.sha256_hex(f"{self.file}|{now()}|{id(self)}")[:12]
        self.prompt = load_prompt("chat")
        self.decls = self._declarations()

    # -- declarations -------------------------------------------------------------------------------
    def _declarations(self) -> list[dict[str, Any]]:
        out = []
        for t in self.server.tools.values():
            if t.app_only or t.name in EXCLUDED_TOOLS:
                continue
            params = json.loads(json.dumps(t.input_schema))
            params.get("properties", {}).pop("file", None)  # one file is served
            params["required"] = [r for r in params.get("required", []) if r != "file"]
            out.append({"name": t.name, "description": t.description, "parameters": params})
        out.sort(key=lambda d: d["name"])
        return [*out, ANSWER_TOOL]

    @property
    def tool_names(self) -> list[str]:
        return [d["name"] for d in self.decls]

    def system(self) -> str:
        return self.prompt.system.replace("{max_iterations}", str(self.max_iterations)).replace(
            "{output_language}", output_language(self.cfg)
        )

    # -- estimates ----------------------------------------------------------------------------------
    def _messages_for(self, question: str) -> list[ChatMsg]:
        msgs: list[ChatMsg] = []
        for t in [h for h in self.history if h.answer][-HISTORY_TURNS:]:
            # an unanswered turn is not carried: the model would answer it again (live run, P7 M8)
            msgs.append(ChatMsg("user", t.question))
            msgs.append(ChatMsg("model", t.answer))
        msgs.append(ChatMsg("user", self.prompt.user.replace("{question}", question)))
        return msgs

    def _out_per_call(self) -> int:
        if self.meter.calls:
            return max(1, self.meter.output_tokens // self.meter.calls)
        return int(STATIC_OUT_PER_CALL * (CALIBRATION if getattr(self.provider, "live", False) else 1))

    def estimate(self, question: str = "") -> dict[str, Any]:
        """Before sending: the adaptive per-turn estimate (static, then calibrated by what this
        session observed)."""
        base = estimate_tokens(
            self.system() + json.dumps(self.decls),
            [m.text or "" for m in self._messages_for(question or "x" * 80)],
        )
        calls = (
            max(1, round(self.meter.calls / self.meter.turns)) if self.meter.turns else DEFAULT_CALLS_PER_TURN
        )
        growth = (
            self.meter.result_tokens // self.meter.steps_with_results
            if self.meter.steps_with_results
            else DEFAULT_RESULT_TOKENS
        )
        tin = sum(base + growth * i for i in range(calls))
        tout = self._out_per_call() * calls
        usd = self.cfg.cost_usd(tin, tout)
        return {
            "calls": calls,
            "input_tokens": tin,
            "output_tokens": tout,
            "usd": usd,
            "priced": usd is not None,
        }

    def _call_cost(self, msgs: list[ChatMsg]) -> float:
        tin = estimate_tokens(
            self.system() + json.dumps(self.decls),
            [m.text or "" for m in msgs] + [t for m in msgs for _, t in m.results],
        )
        return self.cfg.cost_usd(tin, self._out_per_call()) or 0.0

    # -- the turn -----------------------------------------------------------------------------------
    def turn(self, question: str, emit: Emit) -> Turn:
        with self.lock:
            self.cancel_event.clear()
            return self._turn(question.strip()[:2000], emit)

    def cancel(self) -> None:
        self.cancel_event.set()

    def reset(self) -> None:
        with self.lock:
            self.history.clear()  # the meter is per launch: a reset never refills the budget

    def _turn(self, question: str, emit: Emit) -> Turn:
        t = Turn(question)
        est = self.estimate(question)
        if self.meter.spent_usd + self._call_cost(self._messages_for(question)) > self.meter.budget_usd:
            t.error = "budget"
            emit(
                "error", {"code": "budget", "message": self._budget_message(), "meter": self.meter.to_json()}
            )
            return t
        emit("estimate", est)
        msgs = self._messages_for(question)
        seen: set[str] = set()
        tool_text: list[str] = []
        final: dict[str, Any] | None = None
        run_id = self._start_run()
        calls_this_turn = 0
        for step in range(self.max_iterations):
            if self.cancel_event.is_set():
                t.error = "cancelled"
                emit("error", {"code": "cancelled", "message": "cancelled"})
                break
            if self.meter.spent_usd + self._call_cost(msgs) > self.meter.budget_usd:
                t.error = "budget"
                emit(
                    "error",
                    {"code": "budget", "message": self._budget_message(), "meter": self.meter.to_json()},
                )
                break
            params = {
                "subject": question,
                "step": step,
                "thinking": self.cfg.thinking("chat"),
                "max_output_tokens": self.cfg.max_output_tokens("chat"),
                # the last allowed step must answer (live run: the model kept calling tools)
                "force_answer": step == self.max_iterations - 1,
            }
            try:
                resp = self.provider.chat(self.system(), msgs, self.decls, params)
            except ProviderError as e:
                t.error = "provider"
                emit("error", {"code": "provider", "message": str(e)[:300]})
                break
            calls_this_turn += 1
            cost = self.cfg.cost_usd(resp.input_tokens, resp.output_tokens) or 0.0
            self.meter.spent_usd += cost
            self.meter.input_tokens += resp.input_tokens
            self.meter.output_tokens += resp.output_tokens
            self.meter.calls += 1
            self._store_call(run_id, question, step, msgs, params, resp, cost)
            emit(
                "usage",
                {"step": step, "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                 "usd": cost, "meter": self.meter.to_json()},
            )  # fmt: skip
            answer_call = next((c for c in resp.calls if c.name == "ad2v_answer"), None)
            if answer_call is not None:
                final = answer_call.args
                break
            if not resp.calls:  # plain text: take it as the answer, uncited
                final = _answer_from_text(resp.text)
                break
            msgs.append(ChatMsg("model", resp.text or None, list(resp.calls), raw=resp.raw))
            results: list[tuple[ToolCall, str]] = []
            for c in resp.calls:
                emit("tool_call", {"step": step, "name": c.name, "args": c.args})
                text, node_ids, show = self._run_tool(c)
                seen.update(node_ids)
                tool_text.append(text)
                t.steps.append(
                    {"name": c.name, "args": c.args, "chars": len(text), "node_ids": node_ids[:50]}
                )
                emit(
                    "tool_result",
                    {"step": step, "name": c.name, "chars": len(text), "node_ids": node_ids[:50]},
                )
                if show is not None:
                    emit("show", show)
                results.append((c, text))
                self.meter.result_tokens += len(text) // 4
            self.meter.steps_with_results += 1
            msgs.append(ChatMsg("tool", results=results))
        else:
            t.error = "iterations"
            emit("error", {"code": "iterations", "message": f"no answer within {self.max_iterations} steps"})
        if final is not None:
            self._finish(t, final, seen, "\n".join(tool_text), emit)
        self.meter.turns += 1
        self._end_run(run_id, calls_this_turn, t)
        self.history.append(t)
        emit("done", {"meter": self.meter.to_json(), "error": t.error})
        return t

    def _budget_message(self) -> str:
        return (
            f"The chat budget for this session is used up (${self.meter.spent_usd:.4f} of "
            f"${self.meter.budget_usd:.2f}). Restart with a higher cap, for example: "
            f"ad2v view {self.file.name} --chat --chat-budget-usd {max(0.5, self.meter.budget_usd * 2):.2f} "
            "--manifest ad2v.yaml"
        )

    def _run_tool(self, c: ToolCall) -> tuple[str, list[str], dict[str, Any] | None]:
        if c.name not in self.tool_names or c.name == "ad2v_answer":
            return f"Unknown tool: {c.name}", [], None
        try:
            r = self.server.call_tool(c.name, dict(c.args), self.cancel_event)
        except RpcError as e:
            return f"Tool error: {e.message}", [], None
        text = "\n".join(x.get("text", "") for x in r.get("content", []) if x.get("type") == "text")
        sc = r.get("structuredContent") or {}
        found = list(dict.fromkeys([*_ids_in(sc), *NODE_ID.findall(text)]))
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n… (truncated)"
        show = sc if c.name == "ad2v_show" and not r.get("isError") else None
        return text, found, show

    def _finish(self, t: Turn, final: dict[str, Any], seen: set[str], tool_text: str, emit: Emit) -> None:
        answer = str(final.get("answer_markdown") or "")[:6000]
        cited = [str(c) for c in (final.get("citations") or []) if isinstance(c, str)]
        valid = [c for c in dict.fromkeys(cited) if c in seen]
        dropped = [c for c in dict.fromkeys(cited) if c not in seen]
        ix, _ = self.server.ctx.index({})  # type: ignore[attr-defined]
        refs = [ix.ref(c) for c in valid if c in ix.nodes]
        t.answer, t.citations, t.dropped = answer, refs, dropped
        emit("citation_check", {"valid": [r["id"] for r in refs], "dropped": dropped})
        phrases = fence.injection_phrases(tool_text)
        low = answer.lower()
        if phrases and any(p.lower() in low for p in phrases):
            t.flags.append("echoed_injection")
        copied = fence.verbatim_copy(answer, tool_text)
        if copied is not None and fence.injection_phrases(copied):
            t.flags.append("echoed_injection")
        t.flags = sorted(set(t.flags))
        show = final.get("show")
        if isinstance(show, dict) and show.get("intent"):
            args = {k: v for k, v in show.items() if k in ("intent", "node_ids", "workflow_id")}
            args["node_ids"] = [n for n in args.get("node_ids") or [] if n in seen]
            text, _, sc = self._run_tool(ToolCall("final_show", "ad2v_show", args))
            if sc is not None:
                emit("show", sc)
        emit("answer", {"answer_markdown": answer, "citations": refs, "dropped": dropped, "flags": t.flags})

    # -- storage (class I) --------------------------------------------------------------------------
    def _conn(self) -> Any:
        return store.open_rw(self.file)

    def _start_run(self) -> str:
        started = now()
        run_id = (
            "u_" + ids.sha256_hex(f"{started}|chat|{self.session_id}|{self.meter.turns}")[: ids.ID_HEX_LEN]
        )
        conn = self._conn()
        try:
            head = store.resolve_epoch(conn, "head")
            conn.execute(
                "INSERT INTO llm_runs(run_id, started_at, epoch_id, provider, model, llm_config_hash,"
                " llm_config_json, tasks_json, max_cost_usd) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    started,
                    head,
                    self.provider.name,
                    self.provider.model,
                    self.cfg.llm_config_hash,
                    ids.canonical_json(self.cfg.effective()),
                    ids.canonical_json(["chat"]),
                    round(max(0.0, self.meter.budget_usd - self.meter.spent_usd), 6),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def _store_call(
        self,
        run_id: str,
        question: str,
        step: int,
        msgs: list[ChatMsg],
        params: dict[str, Any],
        resp: Any,
        cost: float,
    ) -> None:
        payload = [
            [m.role, m.text, [[c.name, c.args] for c in m.calls], [[c.name, x] for c, x in m.results]]
            for m in msgs
        ]
        input_hash = ids.sha256_hex(ids.canonical_json(payload))
        p = {k: v for k, v in params.items() if k != "subject"}
        params_hash = ids.sha256_hex(ids.canonical_json({**p, "task": "chat"}))
        key = (
            "chat",
            input_hash,
            self.prompt.prompt_hash,
            self.provider.name,
            self.provider.model,
            params_hash,
        )
        out = {"text": resp.text, "calls": [{"name": c.name, "args": c.args} for c in resp.calls]}
        usage = {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens}
        conn = self._conn()
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM llm_results WHERE task=? AND input_hash=? AND prompt_hash=?"
                " AND provider=? AND model=? AND params_hash=?",
                key,
            ).fetchone()[0]
            rid = "r_" + ids.sha256_hex(ids.canonical_json([*key, n, run_id, step]))[: ids.ID_HEX_LEN]
            seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM llm_results").fetchone()[0]
            conn.execute(
                "INSERT INTO llm_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid, seq, key[0], key[1], key[2], key[3], key[4], resp.model_version, key[5],
                    f"chat:{self.session_id}:{self.meter.turns}:{step}",
                    ids.canonical_json(out), 1, "[]",
                    ids.canonical_json(usage),
                    cost if self.cfg.cost_usd(0, 0) is not None else None, resp.latency_ms, now(),
                ),
            )  # fmt: skip
            conn.execute("INSERT OR IGNORE INTO llm_run_results VALUES (?,?,?)", (run_id, rid, 0))
            conn.commit()
        finally:
            conn.close()

    def _end_run(self, run_id: str, calls: int, t: Turn) -> None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(json_extract(r.usage_json,'$.input_tokens')),0),"
                " COALESCE(SUM(json_extract(r.usage_json,'$.output_tokens')),0),"
                " COALESCE(SUM(r.cost_usd_est),0)"
                " FROM llm_run_results x JOIN llm_results r ON r.result_id = x.result_id WHERE x.run_id = ?",
                (run_id,),
            ).fetchone()
            notes = {
                "question_chars": len(t.question),
                "tools": [s["name"] for s in t.steps],
                "citations_valid": len(t.citations),
                "citations_dropped": t.dropped,
                "flags": t.flags,
                "error": t.error,
            }
            conn.execute(
                "UPDATE llm_runs SET ended_at=?, calls=?, input_tokens=?, output_tokens=?, cost_usd_est=?,"
                " aborted=?, notes_json=? WHERE run_id=?",
                (now(), calls, row[0], row[1], round(row[2], 6), int(t.error == "budget"),
                 ids.canonical_json(notes), run_id),
            )  # fmt: skip
            conn.commit()
        finally:
            conn.close()

    # -- session view -------------------------------------------------------------------------------
    def session(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": self.provider.name,
            "model": self.provider.model,
            "live": bool(getattr(self.provider, "live", False)),
            "max_iterations": self.max_iterations,
            "meter": self.meter.to_json(),
            "estimate": self.estimate(),
            "history": [
                {
                    "question": t.question,
                    "answer_markdown": t.answer,
                    "citations": t.citations,
                    "dropped": t.dropped,
                    "flags": t.flags,
                    "steps": t.steps,
                    "error": t.error,
                }
                for t in self.history
            ],
        }


def _ids_in(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += _ids_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _ids_in(v)
    elif isinstance(obj, str) and NODE_ID.fullmatch(obj):
        out.append(obj)
    return out


def _answer_from_text(text: str) -> dict[str, Any]:
    from ad2v.llm.providers.base import parse_json

    parsed = parse_json(text or "")
    if isinstance(parsed, dict) and "answer_markdown" in parsed:
        return parsed
    return {"answer_markdown": text or "", "citations": []}
