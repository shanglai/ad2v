"""Deterministic offline provider: all tests use it (format spec §11.2).

Two modes, tried in order:
1. **replay**: a recorded output for `(task, params["subject"])` from `*.json` files in a
   directory (`tests/llm_recordings/`). Each file holds `{"recordings": [{"task", "subject",
   "output"}]}`. A recording may be any JSON, including schema-invalid output, which is how
   tests exercise validation and prompt-injection handling.
2. **synthetic**: a schema-valid output derived from sha256(seed | task | input); cautious by
   construction (verdicts `cannot_tell` / `no_match`, empty evidence), so it never fabricates a
   positive claim.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from ad2v.llm.config import SEED
from ad2v.llm.providers.base import ProviderResult, estimate_tokens

CAUTIOUS = ("cannot_tell", "no_match")


class FakeProvider:
    name = "fake"
    live = False

    def __init__(self, model: str = "fake-1", replay_dir: str | Path | None = None) -> None:
        self.model = model
        self.recordings: dict[tuple[str, str], Any] = {}
        self.calls: list[dict[str, Any]] = []
        if replay_dir is not None:
            for f in sorted(Path(replay_dir).glob("*.json")):
                for r in json.loads(f.read_text(encoding="utf-8")).get("recordings", []):
                    self.recordings[(r["task"], r["subject"])] = r["output"]

    def count_tokens(self, task: str, system: str, user_parts: list[str]) -> int:
        return estimate_tokens(system, user_parts)

    def generate(
        self,
        task: str,
        system: str,
        user_parts: list[str],
        response_schema: dict[str, Any],
        params: dict[str, Any],
    ) -> ProviderResult:
        self.calls.append(
            {"task": task, "subject": params.get("subject"), "system": system, "user": user_parts}
        )
        key = (task, str(params.get("subject")))
        if key in self.recordings:
            out = self.recordings[key]
        else:
            digest = hashlib.sha256(f"{SEED}|{task}|{system}|{'|'.join(user_parts)}".encode()).hexdigest()
            out = synthesize(response_schema, random.Random(int(digest[:16], 16)), digest[:8])
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, sort_keys=True)
        parsed = out if not isinstance(out, str) else None
        n_in = estimate_tokens(system, user_parts)
        return ProviderResult(text, parsed, n_in, max(1, len(text) // 4), f"{self.model}-replay", 0)


def synthesize(schema: dict[str, Any], rng: random.Random, tag: str, index: int = 0) -> Any:
    t = schema.get("type")
    if "enum" in schema:
        options = list(schema["enum"])
        cautious = [o for o in options if o in CAUTIOUS]
        return cautious[0] if cautious else options[rng.randrange(len(options))]
    if t == "object":
        props = schema.get("properties", {})
        out = {}
        for k, v in sorted(props.items()):
            if k in schema.get("required", props):
                out[k] = index if k == "step" else synthesize(v, rng, tag)
        return out
    if t == "array":  # minimum length; items numbered (narration steps)
        return [
            synthesize(schema.get("items", {}), rng, tag, i) for i in range(int(schema.get("minItems", 0)))
        ]
    if t == "number":
        lo, hi = schema.get("minimum", 0.0), schema.get("maximum", 1.0)
        return round(lo + (hi - lo) * rng.random() * 0.5, 2)  # low confidence: never over a threshold by luck
    if t == "integer":
        return int(schema.get("minimum", 0))
    if t == "boolean":
        return False
    if t == "string":
        return f"(fake {tag})"[: schema.get("maxLength", 200)]
    return None
