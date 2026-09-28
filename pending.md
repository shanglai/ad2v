# Pending

Items consciously left out so far, grouped by the phase that should pick them up.

## Done in P2 (moved from this list)

- Route ↔ endpoint pairing with path normalization, manifest and name pairing, `links` rows and
  statuses (single epoch), findings for `unresolved_refs` (`needs_review`).
- `workflow_step_nodes` derived index. Containment projection. Content-anchored behavior ids.

## P3: storage, incremental, diff (was "P2" in P1's plan)

- Structural diff between epochs (`missing`, `orphan`, `stale`) and a `parent_epoch_id` chain.
- Merkle reuse: skip unchanged subtrees by `subtree_hash`. Invalidate all code-side results when
  `rules_hash` changes (ADR-0010).
- Content-addressed storage (`node_versions` + `epoch_members`, compatibility views shaped like
  `nodes`/`edges`), decided in P2 (decision 2). Today each epoch is a full snapshot.
- Structural diff should ignore `edges.attrs.lines`, which moves with unrelated edits.
- `ad2v diff a.ad2v b.ad2v` CLI.

## Extractor recall/precision (any phase)

- A labeled corpus for risk flags, to measure `io_in_loop` precision **and recall** properly (P1 has
  only a 10-loop precision sample).
- Track `self.<attr>` bindings set in `__init__` across methods (issue 5).
- Infer untyped parameter types from call sites (issue 6).
- App factories: evaluate decorators in function scope (issue 7).
- More port frameworks: Django URLconf, Starlette `Route`, FastAPI `add_api_route`, low-level MCP SDK
  `@server.call_tool()`, Celery/Dramatiq tasks, Kafka consumer loops, AWS Lambda handlers.
- More rules: aioboto3, motor, elasticsearch, celery, cohere, mistral, bedrock via `boto3`
  clients.
- `name_source: literal_prefix` for f-string URLs (issue 8).
- Manifest-declared components and `ui` nodes (templates, static front-ends).
- Edges from emitted behavior nodes to what they touch (`loop → datastore`), for the viewer.
- Per-kind JSON Schema for `attrs` (today only `risk` is constrained).
- Other languages behind the `CodeExtractor` protocol (TypeScript, Go).

## P4: LLM layer

- Frozen LLM extraction of prose specs (Markdown text left in `spec_doc.attrs.prose`).
- Summaries (`label`/`card`/`deep`), narrations per projection span, semantic judge per pair. All
  with the provenance columns that already exist.

## P5/P6: viewer and MCP

- Layout algorithm writing `layout` rows (LOD 0–2). Tours.

## Deferred from P2

- Container inference from workspaces (uv/poetry) and docker-compose services (P2 decision 7).
- Scheduler / job detection (APScheduler, Celery beat, cron-style CLI commands) as entry ports, so
  severity reach covers scheduled jobs (issue 17).
- Scenario ↔ workflow pairing (scenarios stay `specified` unless P4 judges them).
- `test_results` for non-pytest JUnit producers (JUnit from Java/JS runners maps `classname`
  differently); only pytest's shape is documented and tested.
- A narration must record the projection mode it was written for (containment vs call_depth), or
  narrations must be keyed by mode. Decide before P4 writes narrations.
- A "no specs loaded" presentation mode, so a repo without specs is not all orphan (issue 18).
- Per-kind JSON Schema for link `evidence` items (today only `kind` is required).
