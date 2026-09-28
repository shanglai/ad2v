# ADR-0027: Bring-your-own-model providers over stdlib HTTP

- Status: accepted (P4)
- Context: provider SDKs pull in `requests`/`httpx` and with them `certifi` (MPL-2.0, copyleft).
- Decisions:
  1. **No SDKs.** `src/ad2v/llm/providers/` has three providers behind one protocol
     (`generate`, `count_tokens`), all on `urllib.request`:
     - `fake`: deterministic, offline, replays `tests/llm_recordings`;
     - `vertex`: `generateContent` / `countTokens`, with the global host for `location: global`;
     - `openai_compatible`: `/chat/completions` with a JSON-schema response format.
  2. **Vertex auth** is an OAuth access token from the gcloud CLI: ADC
     (`gcloud auth application-default print-access-token`), else the user login, cached until 5
     minutes before an assumed 1-hour lifetime. `AD2V_ACCESS_TOKEN` overrides it for CI. Requests
     send `x-goog-user-project: <llm.project>`, so quota and billing never fall back to the gcloud
     default project. API keys are never used, and an `api_key` in the config file is rejected.
  3. Every Vertex request carries `labels: {project: ad2v, ad2v_task: <task>}` (a dash becomes an
     underscore to satisfy label syntax), `temperature: 0`, `seed: 987654`, JSON output and a
     `responseSchema`. ad2v's JSON schemas are converted to Vertex's OpenAPI subset: uppercase
     types, int64 limits as strings, and `propertyOrdering`.
  4. **Bounded retry:** at most 4 attempts on 429/5xx/network errors, with backoff of 1, 2 and
     4 s. Other errors fail at once.
  5. Reasoning ("thought") tokens are counted as output tokens, because they are billed as output.
