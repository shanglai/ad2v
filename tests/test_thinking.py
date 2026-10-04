"""P7 M6 (ADR-0058): per-task thinking, mapped per model family, and part of the cache key."""

from __future__ import annotations

import pytest

from ad2v.llm.config import LLMConfigError, from_data
from ad2v.llm.providers.base import ProviderError
from ad2v.llm.providers.vertex import VertexProvider, thinking_config
from ad2v.llm.runner import Executor


def test_defaults_and_validation():
    cfg = from_data({})
    tasks = ("summarize", "narrate", "suggest", "judge", "chat", "extract-prose")
    assert [cfg.thinking(t) for t in tasks] == ["low", "low", "low", "default", "low", "default"]
    cfg = from_data({"tasks": {"judge": {"thinking": "low"}, "extract_prose": {"thinking": 2048}}})
    assert cfg.thinking("judge") == "low" and cfg.thinking("extract-prose") == 2048
    for bad in ({"tasks": {"nope": {}}}, {"tasks": {"judge": {"thinking": "max"}}}, {"tasks": ["judge"]}):
        with pytest.raises(LLMConfigError):
            from_data(bad)
    assert cfg.effective()["tasks"]["judge"] == {"thinking": "low"}  # in llm_config_hash


def test_mapping_per_model_family():
    assert thinking_config("low", "gemini-3.8-flash") == {"thinkingLevel": "low"}
    assert thinking_config("off", "gemini-3.8-flash") == {
        "thinkingLevel": "low"
    }  # no minimal on 3.7/3.8 Flash
    assert thinking_config("off", "gemini-3.6-flash") == {"thinkingLevel": "minimal"}
    assert thinking_config("default", "gemini-3.8-flash") is None  # the model's own default (medium)
    assert thinking_config("off", "gemini-2.5-flash") == {"thinkingBudget": 0}
    assert thinking_config(512, "gemini-2.5-flash") == {"thinkingBudget": 512}
    with pytest.raises(ProviderError):
        thinking_config(512, "gemini-3.8-flash")
    body = VertexProvider("p", "global", "gemini-3.8-flash").request_body(
        "judge", "S", ["u"], {"type": "object"}, "low"
    )
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    body = VertexProvider("p", "global", "gemini-3.8-flash").request_body(
        "judge", "S", ["u"], {"type": "object"}, "default"
    )
    assert "thinkingConfig" not in body["generationConfig"]


def test_thinking_is_in_the_cache_key():
    a = Executor(None, from_data({"tasks": {"judge": {"thinking": "default"}}}), None)  # type: ignore[arg-type]
    b = Executor(None, from_data({"tasks": {"judge": {"thinking": "low"}}}), None)  # type: ignore[arg-type]
    assert a.params("judge")["thinking"] == "default" and b.params("judge")["thinking"] == "low"
    assert a.params("judge") != b.params("judge") and a.params("chat") == b.params("chat")
