# ADR-0058: Thinking level per LLM task

- Status: accepted (P7)
- Context: in P4, reasoning tokens made real output about 2.2× the static estimate. Summaries and
  narrations don't need deep reasoning; the judge might.
- Sources, read 2026-10-03:
  - Vertex AI thinking docs (docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking);
  - the AI Gateway Gemini reasoning reference (updated 2026-09-08), which documents the
    REST shape `generationConfig.thinkingConfig.thinkingLevel` with lower-case values.
  - Gemini 3.7 / 3.8 Flash accept `low | medium | high` (default `medium`), not `minimal` and not
    `thinkingBudget`. Other Gemini 3.x accept `minimal` too. Gemini 2.5 uses `thinkingBudget`
    (0 = off).
- Decisions:
  1. `llm.tasks.<task>.thinking` ∈ {`off`, `low`, `default`} or an integer token budget. Defaults:
     summarize `low`, narrate `low`, suggest `low`, judge `default`, chat `low`,
     extract-prose `default`. `llm.tasks.<task>.max_output_tokens` is used by the chat (default
     2,048).
  2. Mapping (`providers/vertex.thinking_config`):
     - `default` sends nothing, so the model's own default applies (medium on 3.8 Flash);
     - `low` → `thinkingLevel: "low"`;
     - `off` → `minimal`, or `low` on 3.7/3.8 Flash, which have no minimal;
     - a budget is accepted only by Gemini 2.x and refused otherwise.
     OpenAI-compatible servers get `reasoning_effort` (`minimal`/`low`) for chat.
  3. The thinking level is in the executor's params, so it is part of `params_hash` (the cache
     key) and of `llm_config_hash` (`effective().tasks`). Changing it re-runs the affected task
     and nothing else.
- Effect: measured in M8 (judge `default` vs `low`; summaries and narrations at `low`).
