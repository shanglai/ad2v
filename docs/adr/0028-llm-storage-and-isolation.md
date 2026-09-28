# ADR-0028: LLM storage, the cache, and informative isolation (format v0.4)

- Status: accepted (P4)
- Decisions:
  1. **`llm_results`** is the content-addressed cache. Lookups use `(task, input_hash,
     prompt_hash, provider, model, params_hash)`. `model_version` is stored but is not part of the
     lookup, because it is only known after the call. `input_hash` is the sha256 of the exact
     serialized prompt parts. Several rows may share a key (`--no-llm-cache` re-runs), and the
     newest answers. `llm_run_results` records which results each run produced or reused; the
     evaluation uses it to compare runs.
  2. **`source_blobs`** stores every code and spec file's normalized text (zlib), deduplicated by
     content hash. Slices, including stale diffs against an older epoch, are cut from the file
     alone. It is class I and is not dumped. GC keeps the blobs some module or `spec_doc` node
     references.
  3. **Informative derived tables** (`link_judgments`, `link_suggestions`, `summaries`,
     `narrations`, `spec_extractions`) behave like derived tables: they exist for materialized
     epochs and are dropped with them. They are rebuilt **from the cache only**: at
     `extract --into` when the file holds LLM results (with the manifest's `llm:` config), and at
     the start of every `ad2v llm run`. A hit costs nothing.
  4. **`node_status_effective`** is a view: the normative status plus overlays. Only a valid
     `drift` judgment with confidence ≥ `llm.judge.min_confidence`, and no injection warning, can
     turn `implemented`/`verified` into `drift` (provenance `llm`). Nothing else changes a status.
     Open suggestions set a `suggested` marker. The thresholds are applied when the rows are
     written (`link_judgments.overlay`), so the view is plain SQL.
  5. `llm.*` has its own `llm_config_hash`, recorded per run. It is excluded from `config_hash`,
     so it never enters an epoch id. `prune` keeps unreferenced `llm_results` unless
     `--drop-llm-cache` is given. `dump --normative-only` excludes all of it; the default dump
     includes the informative per-epoch tables but not the cache or run log.
  6. `ad2v llm run` materializes the target epoch first (the judgments reference its links).
- Consequences: an LLM run never changes a normative byte (tested). Pinning an epoch keeps its
  informative rows.
