"""OpenAI-compatible `/chat/completions` over stdlib HTTP (Ollama, vLLM, LiteLLM, hosted APIs).

The key is read from the environment variable named by `llm.api_key_env`, never from the config
file. Tested offline only (format spec §11.2).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from ad2v.llm.config import SEED
from ad2v.llm.providers.base import (
    HttpOpen,
    ProviderError,
    ProviderResult,
    estimate_tokens,
    parse_json,
    post_json,
)


class OpenAICompatibleProvider:
    name = "openai_compatible"
    live = True

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        *,
        opener: HttpOpen | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url, self.model, self.api_key_env = base_url.rstrip("/"), model, api_key_env
        self.opener, self.sleep = opener, sleep
        self.last_request: dict[str, Any] | None = None

    def _headers(self) -> dict[str, str]:
        if not self.api_key_env:
            return {}
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set")
        return {"Authorization": f"Bearer {key}"}

    def count_tokens(self, task: str, system: str, user_parts: list[str]) -> int:
        return estimate_tokens(system, user_parts)  # no portable count endpoint

    def request_body(
        self, task: str, system: str, user_parts: list[str], schema: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
            "temperature": 0,
            "seed": SEED,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": task.replace("-", "_"), "schema": schema, "strict": True},
            },
            "metadata": {"project": "ad2v", "ad2v_task": task},
        }

    def generate(
        self,
        task: str,
        system: str,
        user_parts: list[str],
        response_schema: dict[str, Any],
        params: dict[str, Any],
    ) -> ProviderResult:
        body = self.request_body(task, system, user_parts, response_schema)
        self.last_request = body
        t0 = time.perf_counter()
        data, attempts = post_json(
            f"{self.base_url}/chat/completions", body, self._headers(), opener=self.opener, sleep=self.sleep
        )
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
        usage = data.get("usage") or {}
        return ProviderResult(
            text=text,
            parsed=parse_json(text),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model_version=data.get("model"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            attempts=attempts,
        )
