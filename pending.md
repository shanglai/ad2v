# Pending

Items consciously left out so far, grouped by the phase that should pick them up.

## Done in P2 (moved from this list)

- Route ↔ endpoint pairing with path normalization, manifest and name pairing, `links` rows and
  statuses (single epoch), findings for `unresolved_refs` (`needs_review`).
- `workflow_step_nodes` derived index. Containment projection. Content-anchored behavior ids.

## Done in P3 (moved from this list)

- Content-addressed multi-epoch storage with v0.2-shaped views, epoch chain, parse cache,
  `history`, `diff` (ignores volatile lines), lineage, `stale`, prune/GC.
- Scheduler / job detection (Celery beat, APScheduler, `schedule`) and main blocks as entry ports.
- Narrations keyed by projection mode. A "no specs" mode (`orphan_policy: auto`).

## After P3: storage and incremental

- Call-graph-closure invalidation, so global results (resolution, workflows, severity) can be
  reused for unchanged regions instead of recomputed (issue 33).
- `diff` between epochs of different files, or non-ancestor epochs (issue 37).
- Report only the innermost flagged loop per IO site (issue 32).

## Extractor recall/precision (any phase)

- A labeled corpus for risk flags, to measure `io_in_loop` precision **and recall** properly (P1 has
  only a 10-loop precision sample).
- Track `self.<attr>` bindings set in `__init__` across methods (issue 5).
- Infer untyped parameter types from call sites (issue 6).
- App factories: evaluate decorators in function scope (issue 7).
- More port frameworks: Django URLconf, Starlette `Route`, FastAPI `add_api_route`, low-level MCP SDK
  `@server.call_tool()`, Dramatiq/RQ tasks, Kafka consumer loops, AWS Lambda handlers, project-specific
  scheduler decorators (dispatch's `@scheduler.add(every(...))`) via rules overlays.
- Calls through plugin registries / instances (issue 31).
- More rules: aioboto3, motor, elasticsearch, celery, cohere, mistral, bedrock via `boto3`
  clients.
- `name_source: literal_prefix` for f-string URLs (issue 8).
- Manifest-declared components and `ui` nodes (templates, static front-ends).
- Edges from emitted behavior nodes to what they touch (`loop → datastore`), for the viewer.
- Per-kind JSON Schema for `attrs` (today only `risk` is constrained).
- Other languages behind the `CodeExtractor` protocol (TypeScript, Go).

## Done in P4 (moved from this list)

- LLM layer: judge, suggestions, summaries, narrations per projection span and mode, frozen prose
  extraction, evaluation; all informative with provenance.

## After P4: LLM layer

- Calibrate plan estimates per model (reasoning tokens; issue 41).
- Richer judge slices: callers and data shapes (issue 42); code for container/component links
  (issue 43).
- Batch / cached-context APIs to cut the dispatch cost (≈ 3.5k calls head-only).
- `openai_compatible` live test against a local server (Ollama / vLLM).

## P5/P6: viewer and MCP

- Layout algorithm writing `layout` rows (LOD 0–2). Tours.

## Deferred from P2

- Container inference from workspaces (uv/poetry) and docker-compose services (P2 decision 7).
- Scenario ↔ workflow pairing (scenarios stay `specified` unless P4 judges them).
- `test_results` for non-pytest JUnit producers (JUnit from Java/JS runners maps `classname`
  differently); only pytest's shape is documented and tested.
- Per-kind JSON Schema for link `evidence` items (today only `kind` is required).
