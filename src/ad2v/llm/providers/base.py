"""Provider protocol, results, JSON-schema helpers and bounded retry (format spec §11.2)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_ATTEMPTS = 4  # bounded: ad2v flags unbounded retries in other people's code
BACKOFF_S = (1.0, 2.0, 4.0)
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderResult:
    text: str  # raw model output
    parsed: Any | None  # JSON-decoded output, None if not JSON
    input_tokens: int = 0
    output_tokens: int = 0
    model_version: str | None = None
    latency_ms: int = 0
    attempts: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


# -- chat with function calling (P7, ADR-0056) -----------------------------------------------------
@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ChatMsg:
    """One conversation message, provider-neutral. `raw` keeps a model turn exactly as the provider
    returned it (Gemini's thought signatures must be sent back unchanged)."""

    role: str  # "user" | "model" | "tool"
    text: str | None = None
    calls: list[ToolCall] = field(default_factory=list)  # model: the tool calls it made
    results: list[tuple[ToolCall, str]] = field(default_factory=list)  # tool: (call, result text)
    raw: Any = None


@dataclass
class ChatResponse:
    text: str
    calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    model_version: str | None = None
    latency_ms: int = 0
    attempts: int = 1
    raw: Any = None
    finish_reason: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str
    live: bool  # True when calls leave the machine (and may cost money)

    def generate(
        self,
        task: str,
        system: str,
        user_parts: list[str],
        response_schema: dict[str, Any],
        params: dict[str, Any],
    ) -> ProviderResult: ...

    def count_tokens(self, task: str, system: str, user_parts: list[str]) -> int: ...


def estimate_tokens(system: str, user_parts: list[str]) -> int:
    """chars/4, the documented fallback estimate when a provider cannot count."""
    return (len(system) + sum(len(p) for p in user_parts) + 3) // 4


def parse_json(text: str) -> Any | None:
    t = text.strip()
    if t.startswith("```"):  # tolerate a fenced reply
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        return None


HttpOpen = Callable[[urllib.request.Request, float], Any]


def _default_open(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https URLs built by ad2v


def post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    opener: HttpOpen | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 120.0,
) -> tuple[dict[str, Any], int]:
    """POST JSON with at most MAX_ATTEMPTS attempts on 429/5xx/network errors. Returns (json, attempts)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    opener = opener or _default_open
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json", **headers}
        )
        try:
            with opener(req, timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), attempt
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500] if hasattr(e, "read") else ""
            if e.code not in RETRY_STATUS:
                raise ProviderError(f"HTTP {e.code} from {url.split('?')[0]}: {detail}") from e
            last = ProviderError(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_S[attempt - 1])
    raise ProviderError(f"giving up after {MAX_ATTEMPTS} attempts: {last}")
