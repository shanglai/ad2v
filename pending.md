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
- More port frameworks: Django URLconf, low-level MCP SDK
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

## Done in P5 (moved from this list)

- Deterministic layout (`nestgrid-v1`, LOD 0) and the three.js viewer: LOD map, status styling,
  effective/suggestion overlays, replay, epoch diff, `ad2v view`, single-file demo.

## After P5: viewer

- **Denser layout for large repos** (issue 54). Dispatch fits 60 fps, but the home view is mostly
  empty slabs. Try shelf or squarified packing inside a parent in `nestgrid-v2`, with the same
  persisted-slot stability rule.
- **Edge bundling / aggregation by level** at the system view (issue 54): today every visible
  representative pair gets an edge, which becomes a hairball on dispatch.
- **Dash aliasing** on very long dashed ribbons at high zoom (issue 55): clamp the dash phase per
  segment, or split long ribbons.
- Tours (`tours` table) in the viewer, and LOD 1–2 layout rows (today LOD is derived on screen).
- Headed-GPU perf numbers on a discrete GPU. The M9 figures are from an Intel UHD integrated GPU,
  headless with ANGLE D3D11.

## Done in P6 (moved from this list)

- MCP server (stdlib, protocol 2026-07-28, dual-era), 13 agent tools, 20 app tools, the map as an
  MCP App, `RemoteSliceSource`, deterministic retrieval with an eval.

## Done in P6.1 (moved from this list)

- App factories, `add_api_route`/`add_url_rule`/`add_route`, Starlette `Route`/`Mount`, include
  chains with prefixes (issues 7, 22); spec-root discovery; spec-kit/Kiro/custom presets;
  `ad2v specs bootstrap/review/approve`; replay camera; opaque "dim the rest".

## After P6.1: real-repo readiness

- Opt-in resolver for pydantic `BaseSettings` defaults (`settings.API_V1_STR`), labeled as a
  default that the environment can override (issue 70).
- Kiro `design.md` and `tasks.md`; spec-kit `plan.md`, `tasks.md` and `contracts/`; tasks could
  link to requirements as `implements` edges.
- Requirements written as Markdown tables (id | text | priority).
- Routes on a router that is never statically included: flag `path_unresolved` (issue 76).
- Sub-ids in test names (`test_orderexport_1_2`) for Kiro criteria.
- Open the container of a replay step that is not visible at the current LOD (issue 71).
- Isolate the first-render regression on dispatch (issue 73) and the replay warm-up p5 dip
  (issue 74).
- `ad2v specs bootstrap` against a real model, with the cost shown in the plan (P6.1 used the fake
  provider only).

## After P6: MCP and retrieval

- A larger question set (≥ 100, several repositories) before tuning retrieval weights further
  (issue 68); per-repository overlays through `rules_overlay`.
- Server-side digests for app-mode cards (issue 66); rank `ad2v_status` results by specificity
  (issue 67).
- `subscriptions/listen` for `resources/list_changed` when a file is re-extracted while the
  server runs.
- A remote deployment story (auth, TLS, a shared `--root`) for hosts that need HTTPS: not done;
  see the checklist in docs/mcp.md.
- A web-host style test (sandbox proxy, second origin) in addition to the desktop-style test host.

## P7: standalone chat (BYOM)

- The viewer's own chat agent reusing these tools as function calling (see REPORT.md open
  questions).

## Deferred from P2

- Container inference from workspaces (uv/poetry) and docker-compose services (P2 decision 7).
- Scenario ↔ workflow pairing (scenarios stay `specified` unless P4 judges them).
- `test_results` for non-pytest JUnit producers (JUnit from Java/JS runners maps `classname`
  differently); only pytest's shape is documented and tested.
- Per-kind JSON Schema for link `evidence` items (today only `kind` is required).
