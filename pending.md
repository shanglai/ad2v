# Pending (deferred to P2+)

Items left out of P1 on purpose, grouped by the phase that should pick them up.

## P2: pairing, diff, incremental

- Spec↔code pairing beyond explicit `annotated_as`: `http_route` ↔ `spec_endpoint` by
  `(method, path)` (with path-template normalization), scenario ↔ workflow, requirement ↔ code via
  annotations and tests. Write `links` rows with statuses and the state machine (format spec §6).
- Structural diff between epochs (`missing`, `orphan`, `stale`) and a `parent_epoch_id` chain.
- Merkle reuse: skip unchanged subtrees by `subtree_hash`. Invalidate all code-side results when
  `rules_hash` changes (ADR-0010).
- Delta storage across epochs. Today each epoch is a full snapshot (REPORT §8).
- Findings for `unresolved_refs` (dangling references).
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

## P3: LLM layer

- Frozen LLM extraction of prose specs (Markdown text left in `spec_doc.attrs.prose`).
- Summaries (`label`/`card`/`deep`), narrations per projection span, semantic judge per pair. All
  with the provenance columns that already exist.

## P4/P5: viewer and MCP

- Layout algorithm writing `layout` rows (LOD 0–2). Tours.
- Projection by containment ancestry ("collapse by container"), next to the call-depth projection.
- A derived `workflow_step_nodes(workflow_id, seq, node_id)` index for "which workflows touch X"
  queries (REPORT §8).
