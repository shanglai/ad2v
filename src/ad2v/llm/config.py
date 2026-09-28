"""The `llm:` section of `ad2v.yaml` (format spec §11.1). Hashed on its own, never in `config_hash`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ad2v import ids

PROVIDERS = ("fake", "vertex", "openai_compatible")
TASKS = ("judge", "suggest", "summarize", "narrate", "extract-prose")
SEED = 987654

DEFAULT_SLICE = {
    "code_max_lines": 150,
    "code_head": 100,
    "code_tail": 50,
    "callee_sig_max_lines": 40,
    "openapi_max_lines": 60,
    "stale_diff_max_lines": 80,
}


class LLMConfigError(ValueError):
    pass


@dataclass
class LLMConfig:
    provider: str = "fake"
    project: str | None = None
    location: str | None = None
    model: str = "fake-1"
    base_url: str | None = None  # openai_compatible
    api_key_env: str | None = None  # openai_compatible: name of the env var holding the key
    output_language: str = "en"
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    budget_usd: float = 1.00
    slice: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SLICE))
    min_confidence: float = 0.6
    suggest_top_k: int = 5
    summaries_scope: str = "structural"
    fake_replay_dir: str | None = None  # fake provider: recorded outputs (tests/llm_recordings)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def llm_config_hash(self) -> str:
        return ids.sha256_hex(ids.canonical_json(self.effective()))

    def effective(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "project": self.project,
            "location": self.location,
            "model": self.model,
            "base_url": self.base_url,
            "output_language": self.output_language,
            "pricing": {"input_per_mtok": self.input_per_mtok, "output_per_mtok": self.output_per_mtok},
            "budget_usd": self.budget_usd,
            "slice": dict(sorted(self.slice.items())),
            "judge": {"min_confidence": self.min_confidence},
            "suggest": {"top_k": self.suggest_top_k},
            "summaries": {"scope": self.summaries_scope},
        }

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_per_mtok is None or self.output_per_mtok is None:
            return None
        return round(input_tokens / 1e6 * self.input_per_mtok + output_tokens / 1e6 * self.output_per_mtok, 6)


def from_data(data: dict[str, Any] | None) -> LLMConfig:
    data = data or {}
    cfg = LLMConfig(raw=data)
    cfg.provider = str(data.get("provider", cfg.provider))
    if cfg.provider not in PROVIDERS:
        raise LLMConfigError(f"llm.provider must be one of {', '.join(PROVIDERS)}")
    cfg.project = data.get("project")
    cfg.location = data.get("location")
    cfg.model = str(data.get("model") or ("fake-1" if cfg.provider == "fake" else ""))
    if not cfg.model:
        raise LLMConfigError("llm.model is required for a live provider")
    cfg.base_url = data.get("base_url")
    cfg.api_key_env = data.get("api_key_env")
    if "api_key" in data:
        raise LLMConfigError(
            "llm.api_key is not allowed in the config file; name an env var in llm.api_key_env"
        )
    cfg.output_language = str(data.get("output_language", "en"))
    pricing = data.get("pricing") or {}
    cfg.input_per_mtok = _num(pricing.get("input_per_mtok"))
    cfg.output_per_mtok = _num(pricing.get("output_per_mtok"))
    cfg.budget_usd = float(data.get("budget_usd", cfg.budget_usd))
    sl = data.get("slice") or {}
    unknown = set(sl) - set(DEFAULT_SLICE)
    if unknown:
        raise LLMConfigError(f"unknown llm.slice keys: {', '.join(sorted(unknown))}")
    cfg.slice = {**DEFAULT_SLICE, **{k: int(v) for k, v in sl.items()}}
    cfg.min_confidence = float((data.get("judge") or {}).get("min_confidence", cfg.min_confidence))
    cfg.suggest_top_k = int((data.get("suggest") or {}).get("top_k", cfg.suggest_top_k))
    cfg.summaries_scope = str((data.get("summaries") or {}).get("scope", cfg.summaries_scope))
    if cfg.summaries_scope not in ("structural", "all"):
        raise LLMConfigError("llm.summaries.scope must be structural or all")
    cfg.fake_replay_dir = data.get("fake_replay_dir")
    if cfg.provider == "vertex" and not (cfg.project and cfg.location):
        raise LLMConfigError("llm.project and llm.location are required for the vertex provider")
    if cfg.provider == "openai_compatible" and not cfg.base_url:
        raise LLMConfigError("llm.base_url is required for the openai_compatible provider")
    return cfg


def _num(v: Any) -> float | None:
    return None if v is None else float(v)
