"""Vertex AI `generateContent` / `countTokens` over stdlib HTTP (format spec §11.2, ADR-0027).

Auth: an OAuth access token from the gcloud CLI (Application Default Credentials, else the gcloud
user login), cached until ~5 minutes before it expires, or `AD2V_ACCESS_TOKEN` (CI). API keys are
never used. Every request carries the labels `project=ad2v` and `ad2v_task=<task>`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from ad2v.llm.config import SEED
from ad2v.llm.providers.base import (
    ChatMsg,
    ChatResponse,
    HttpOpen,
    ProviderError,
    ProviderResult,
    ToolCall,
    parse_json,
    post_json,
)

TOKEN_MARGIN_S = 300
DEFAULT_TOKEN_LIFETIME_S = 3600
# Keys of Vertex's OpenAPI-subset Schema object that ad2v's response schemas use.
SCHEMA_KEYS = (
    "description",
    "enum",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minimum",
    "properties",
    "required",
)


def gcloud_exe() -> str:
    name = "gcloud.cmd" if sys.platform == "win32" else "gcloud"
    return shutil.which(name) or name


class TokenSource:
    """Access token from the environment or the gcloud CLI, cached until shortly before expiry."""

    def __init__(
        self, run: Callable[[list[str]], str] | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self._run = run or _run_gcloud
        self._clock = clock
        self._token: str | None = None
        self._expires = 0.0
        self.fetches = 0

    def token(self) -> str:
        env = os.environ.get("AD2V_ACCESS_TOKEN")
        if env:
            return env.strip()
        if self._token is None or self._clock() >= self._expires - TOKEN_MARGIN_S:
            try:
                tok = self._run([gcloud_exe(), "auth", "application-default", "print-access-token"])
            except ProviderError:
                tok = self._run([gcloud_exe(), "auth", "print-access-token"])
            self._token = tok.strip()
            self._expires = self._clock() + DEFAULT_TOKEN_LIFETIME_S
            self.fetches += 1
        return self._token


def _run_gcloud(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise ProviderError(f"gcloud is not available: {e}") from e
    if p.returncode != 0 or not p.stdout.strip():
        raise ProviderError(f"{' '.join(cmd[1:])} failed: {p.stderr.strip()[:300]}")
    return p.stdout


def to_vertex_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema (ad2v's subset) -> Vertex Schema: uppercase types, supported keys only."""
    out: dict[str, Any] = {}
    if "type" in schema:
        out["type"] = str(schema["type"]).upper()
    for k in SCHEMA_KEYS:
        if k not in schema:
            continue
        v = schema[k]
        if k == "properties":
            out[k] = {p: to_vertex_schema(s) for p, s in v.items()}
            out["propertyOrdering"] = list(v)
        elif k == "items":
            out[k] = to_vertex_schema(v)
        elif k in ("maxLength", "maxItems", "minItems"):
            out[k] = str(v)  # int64 fields are strings in proto3 JSON
        else:
            out[k] = v
    return out


class VertexProvider:
    name = "vertex"
    live = True

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        *,
        tokens: TokenSource | None = None,
        opener: HttpOpen | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project, self.location, self.model = project, location, model
        self.tokens = tokens or TokenSource()
        self.opener, self.sleep = opener, sleep
        self.last_request: dict[str, Any] | None = None

    @property
    def host(self) -> str:
        return (
            "aiplatform.googleapis.com"
            if self.location == "global"
            else f"{self.location}-aiplatform.googleapis.com"
        )

    def url(self, method: str) -> str:
        p, loc, m = (urllib.parse.quote(x, safe="") for x in (self.project, self.location, self.model))
        return f"https://{self.host}/v1/projects/{p}/locations/{loc}/publishers/google/models/{m}:{method}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.token()}", "x-goog-user-project": self.project}

    def request_body(
        self,
        task: str,
        system: str,
        user_parts: list[str],
        schema: dict[str, Any] | None,
        thinking_level: Any = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": p} for p in user_parts]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "labels": {"project": "ad2v", "ad2v_task": task.replace("-", "_")},
        }
        if schema is not None:
            body["generationConfig"] = {
                "temperature": 0,
                "seed": SEED,
                "responseMimeType": "application/json",
                "responseSchema": to_vertex_schema(schema),
            }
            thinking = thinking_config(thinking_level, self.model)
            if thinking:
                body["generationConfig"]["thinkingConfig"] = thinking
        return body

    def count_tokens(self, task: str, system: str, user_parts: list[str]) -> int:
        body = self.request_body(task, system, user_parts, None)
        body.pop("labels")  # countTokens takes no labels; it is free and creates nothing
        data, _ = post_json(
            self.url("countTokens"), body, self._headers(), opener=self.opener, sleep=self.sleep
        )
        return int(data.get("totalTokens", 0))

    def generate(
        self,
        task: str,
        system: str,
        user_parts: list[str],
        response_schema: dict[str, Any],
        params: dict[str, Any],
    ) -> ProviderResult:
        body = self.request_body(task, system, user_parts, response_schema, params.get("thinking"))
        self.last_request = body
        t0 = time.perf_counter()
        data, attempts = post_json(
            self.url("generateContent"), body, self._headers(), opener=self.opener, sleep=self.sleep
        )
        latency = int((time.perf_counter() - t0) * 1000)
        cands = data.get("candidates") or []
        parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
        return ProviderResult(
            text=text,
            parsed=parse_json(text),
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
            model_version=data.get("modelVersion"),
            latency_ms=latency,
            attempts=attempts,
            extra={"finish_reason": cands[0].get("finishReason") if cands else None},
        )

    # -- chat with function calling (P7, ADR-0056) ----------------------------------------------
    @staticmethod
    def chat_contents(messages: list[ChatMsg]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "parts": [{"text": m.text or ""}]})
            elif m.role == "model":
                if m.raw is not None:  # exactly as returned: keeps thoughtSignature parts
                    out.append(m.raw)
                    continue
                parts: list[dict[str, Any]] = [{"text": m.text}] if m.text else []
                parts += [{"functionCall": {"name": c.name, "args": c.args}} for c in m.calls]
                out.append({"role": "model", "parts": parts})
            else:
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {"functionResponse": {"name": c.name, "response": {"content": text}}}
                            for c, text in m.results
                        ],
                    }
                )
        return out

    def chat_body(
        self, system: str, messages: list[ChatMsg], tools: list[dict[str, Any]], params: dict[str, Any]
    ) -> dict[str, Any]:
        from ad2v.chat.schemas import vertex_tools

        gen: dict[str, Any] = {"seed": SEED}
        if params.get("max_output_tokens"):
            gen["maxOutputTokens"] = int(params["max_output_tokens"])
        thinking = thinking_config(params.get("thinking"), self.model)
        if thinking:
            gen["thinkingConfig"] = thinking
        return {
            "contents": self.chat_contents(messages),
            "systemInstruction": {"parts": [{"text": system}]},
            "tools": vertex_tools(tools),
            "toolConfig": {
                "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["ad2v_answer"]}
                if params.get("force_answer")
                else {"mode": "AUTO"}
            },
            "generationConfig": gen,
            "labels": {"project": "ad2v", "ad2v_task": "chat"},
        }

    def chat(
        self, system: str, messages: list[ChatMsg], tools: list[dict[str, Any]], params: dict[str, Any]
    ) -> ChatResponse:
        body = self.chat_body(system, messages, tools, params)
        self.last_request = body
        t0 = time.perf_counter()
        data, attempts = post_json(
            self.url("generateContent"), body, self._headers(), opener=self.opener, sleep=self.sleep
        )
        cands = data.get("candidates") or []
        content = (cands[0].get("content") or {"role": "model", "parts": []}) if cands else None
        parts = (content or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        calls = [
            ToolCall(
                str(p["functionCall"].get("id") or f"call_{i}"),
                str(p["functionCall"].get("name", "")),
                dict(p["functionCall"].get("args") or {}),
            )
            for i, p in enumerate(parts)
            if "functionCall" in p
        ]
        usage = data.get("usageMetadata") or {}
        return ChatResponse(
            text=text,
            calls=calls,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
            model_version=data.get("modelVersion"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            attempts=attempts,
            raw={"role": "model", "parts": parts} if content is not None else None,
            finish_reason=cands[0].get("finishReason") if cands else None,
        )


# Thinking controls by model family (P7, ADR-0058; Vertex/Gemini docs read 2026-10-03):
# - Gemini 3.7 / 3.8 Flash: thinkingLevel low | medium | high (default medium); no minimal, no budget;
# - other Gemini 3.x: thinkingLevel minimal | low | medium | high;
# - Gemini 2.5: thinkingBudget (0 = off).
NO_MINIMAL = ("gemini-3.7-flash", "gemini-3.8-flash")


def thinking_config(level: Any, model: str = "") -> dict[str, Any] | None:
    """`llm.tasks.<task>.thinking` -> Vertex thinkingConfig. `default` sends nothing (the model's own)."""
    if level in (None, "default"):
        return None
    m = model.lower()
    if m.startswith("gemini-2."):
        if isinstance(level, int) and not isinstance(level, bool):
            return {"thinkingBudget": level}
        return {"thinkingBudget": 0 if level == "off" else 1024}
    if isinstance(level, int) and not isinstance(level, bool):
        raise ProviderError(f"{model or 'this model'} takes a thinking level, not a token budget ({level})")
    if level == "off":
        return {"thinkingLevel": "low" if m.startswith(NO_MINIMAL) else "minimal"}
    return {"thinkingLevel": str(level)}


def dumps_request(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True)
