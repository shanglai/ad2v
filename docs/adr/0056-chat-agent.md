# ADR-0056: The viewer's own chat agent (bring your own model)

- Status: accepted (P7)
- Decisions (P7 §2.1–2.6, plus what the prompt left open):
  1. **Where it runs.** Server-side, in `ad2v view --chat` (Python). Credentials stay in the
     environment, and the P4 providers, pricing and labels are reused. The browser gets only the UI
     and a token.
  2. **Tools.**
     - Calls go in-process through the MCP server's dispatcher (`Server.call_tool`): the same
       argument validation, the same handlers, the same fenced `untrusted_text`.
     - The agent gets every agent tool except `ad2v_files` and `ad2v_llm_plan`. The `file`
       parameter is removed, since one file is served.
     - Declarations are generated from the MCP input schemas (`chat/schemas.py`):
       - for Vertex `functionDeclarations`: upper-case types, unsupported keys dropped, unions
         collapsed, `nullable`;
       - for OpenAI `tools`: JSON Schema as is.
  3. **Ending a turn.** The model calls a virtual tool `ad2v_answer {answer_markdown, citations,
     show?}`. It works the same on every provider, and Gemini does not combine function calling
     with a JSON response schema. A plain-text reply is taken as an uncited answer.
  4. **Gemini thought signatures.** A model turn is kept exactly as returned (`ChatMsg.raw`) and
     sent back unchanged, as Gemini 3 function calling requires.
  5. **Limits.**
     - At most 6 model steps per turn.
     - Tool results are capped at 8,000 characters.
     - History keeps the last 6 question/answer pairs, without the tool steps.
     - Thinking and max output tokens come from `llm.tasks.chat` (default thinking `low`,
       2,048 output tokens; ADR-0058).
  6. **Grounding.**
     - A cited id counts only if it appeared in this turn's tool results (structured content or
       text). Others are dropped and reported in `citation_check`.
     - An answer that repeats an injection phrase found in the tool results is flagged
       `echoed_injection`, reusing the P4 guard.
     - `ad2v_show` calls, and the final `show`, are re-run through the tool for validation and
       sent to the map as App-mode intents.
  7. **Budget.**
     - Each launch has a USD cap (`--chat-budget-usd`, default 0.25) and a meter.
     - Before a turn, and before each model call, the adaptive estimate (ADR-0032) is checked
       against the cap. The estimate is static × 2.2 for live models until the session has
       observed calls, then the observed per-call output and calls per turn.
     - At the cap, the turn is refused with the command to raise it. There is no silent model
       switch, and a reset clears the history, never the meter.
  8. **Storage (class I).** Each model call is an `llm_results` row (task `chat`, subject
     `chat:<session>:<turn>:<step>`, output = text + tool calls). Each turn is an `llm_runs` row
     whose notes hold the tools used, citation counts, flags and the error, if any.
  9. **Language.** `llm.output_language: auto` answers in the question's language.
  10. **Fake provider.** Scripted multi-step transcripts keyed by the question. Without a script,
      it locates and then cites what it found, grounded by construction.
- SSE events: `estimate`, `tool_call`, `tool_result` (size, node ids), `show`, `usage`,
  `citation_check`, `answer`, `error` (`budget`, `iterations`, `cancelled`, `provider`), `done`.
