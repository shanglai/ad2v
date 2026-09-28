"""LLM providers (format spec §11.2). `get_provider` builds one from the `llm:` config."""

from __future__ import annotations

from ad2v.llm.config import LLMConfig
from ad2v.llm.providers.base import LLMProvider, ProviderError, ProviderResult
from ad2v.llm.providers.fake import FakeProvider
from ad2v.llm.providers.openai_compatible import OpenAICompatibleProvider
from ad2v.llm.providers.vertex import VertexProvider

__all__ = ["LLMProvider", "ProviderError", "ProviderResult", "get_provider"]


def get_provider(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "fake":
        return FakeProvider(cfg.model, cfg.fake_replay_dir)
    if cfg.provider == "vertex":
        return VertexProvider(str(cfg.project), str(cfg.location), cfg.model)
    return OpenAICompatibleProvider(str(cfg.base_url), cfg.model, cfg.api_key_env)
