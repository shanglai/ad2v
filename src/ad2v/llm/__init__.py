"""The bring-your-own-model LLM layer (P4, format spec §11).

Everything here is **informative**: results carry full provenance, live in their own tables, never
enter the epoch id or a normative table, and are cached content-addressed in `llm_results`.
Providers use the standard library's HTTP client only (no SDKs; ADR-0027).
"""
