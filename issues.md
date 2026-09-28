# Issues

Problems found during P1–P4, with severity (high / medium / low).

## P1

| # | Severity | Issue | Status |
|---|---|---|---|
| 1 | high | Extraction output depended on `rules/python.yaml`, but the epoch identity and dump didn't record it (same epoch id for different outputs). | **fixed**: `epochs.rules_hash` column, included in the epoch id and dump (ADR-0010) |
| 2 | high | hatchling (build backend) depends on `pathspec` (MPL-2.0), which violates the no-copyleft rule at build time. | **fixed**: switched to setuptools (ADR-0008) |
| 3 | medium | Datastore library helpers (`sqlalchemy.inspect(...)`) counted as DB IO, giving false `io_in_loop` flags. In a 6-loop sample on Netflix/dispatch, 2 were false positives. | **fixed**: `direct_calls_touch` defaults to false for datastore libraries; regression test added |
| 4 | medium | `io_in_loop` **recall is unmeasured**. The precision sample is small (10/10 after fix #3; Wilson 95% lower bound ≈ 0.72). | open; needs a labeled corpus (pending.md) |
| 5 | medium | Clients stored on instance attributes (`self.client = httpx.Client()` in `__init__`, used in other methods) are not tracked, so IO through them is missed (recall gap). | open (pending.md) |
| 6 | medium | Calls on untyped parameters (`def f(session): session.execute(...)`) are unresolved. Parameters annotated with a classified library type are handled. | open (pending.md) |
| 7 | medium | App-factory patterns (`def create_app(): app = FastAPI(); @app.get(...)`) produce no routes, because decorators are evaluated in module scope. | open (pending.md) |
| 8 | low | f-string URLs name resources by their literal prefix only (`https://public-keys.auth.elb.` on dispatch). The name is deterministic, but partial. | open; mark `name_source: literal_prefix` in P2 |
| 9 | low | Behavior ordinals are per function. Inserting a new loop *before* an existing loop in the same function renumbers the later loops (their ids change). | **fixed in P2**: content-anchored ids (ADR-0011) |
| 10 | low | Duplicate definitions of the same qualified name (`if X: def f ... else: def f ...`): the first one wins, and the second body is not walked. | open |
| 11 | low | Readers used `sqlite3.connect`, which silently *creates* an empty file when given a missing path. | **fixed**: `store.open_readonly` (mode=ro, clear error) |
| 12 | low | Module-level assignments were re-bound as fresh locals during the module walk, so FastAPI routers lost their identity and `include_router` prefixes were lost. | **fixed** (covered by `test_ports`) |
| 13 | low | SQLite write time on Windows varies a lot between runs (dispatch: 1.8–7.2 s; one outlier run of the small repo took ~40 s end to end). Build time is stable. Likely the filesystem or antivirus scanning new files. | noted; report medians |
| 14 | low | On this machine `core.autocrlf=true` checks the fixture out with CRLF. Normalization makes this harmless, and a test covers it explicitly. | accepted |
| 15 | low | The Bash tool's heredoc handling occasionally failed on quoted content during development; files were written with the editor tool instead. Tooling only, no product impact. | n/a |

## P2

| # | Severity | Issue | Status |
|---|---|---|---|
| 16 | medium | SQLAlchemy query-builder calls (`query.join(...)`, `.filter`, `.where`...) on a `Query`-typed variable counted as DB IO. The P2 re-check on Netflix/dispatch ranked such a loop **#3** of 160 (reach 52 amplified it). | **fixed**: builder methods added to `pure_methods`; regression test `test_sqlalchemy_query_builders_are_not_io`; dispatch risky count 160 → 152 |
| 17 | medium | Severity rewards reachability from *recognized* entry ports. Risky loops in scheduled jobs or CLI commands registered in ways the extractor does not recognize get reach 0 (dispatch: `consume_signals`, `sync_tasks`, the SQS consumer rank 8-10 with severity 5.0, while plausibly worse in production). | **mostly fixed in P3**: main blocks, Celery, APScheduler, `schedule`, nested Click (ADR-0021); `consume_signals` now reach 1. Still reach 0: dispatch's own `@scheduler.add(every(...))` decorator (`sync_tasks`) and plugin methods called through `plugin.instance` (issue 31) |
| 18 | medium | Without specs or annotations, every port/container/component is `orphan` (dispatch: 462 orphans, 290 of them routes). Correct by the rules, but a map without specs is all red dashes at the port level. | **fixed in P3**: `pairing.orphan_policy: auto` (default) assigns no orphans without spec items; `meta.spec_coverage = 'none'` (ADR-0022) |
| 19 | low | `.ad2v` size grew ~35-40% (dispatch 11.4 → 16.1 MB) from `links`, `node_status`, `status_rollup` and `workflow_step_nodes`. `workflow_step_nodes` dominates on dispatch (~10.5k steps). | **addressed in P3**: single-epoch dispatch is 15.0 MB; each further epoch adds ~0.3 MB (ADR-0017) |
| 20 | low | The light theme's warning badge initially failed the text-contrast requirement (3.46:1). An earlier edit silently did not apply; the new contrast test caught it. | **fixed** (`#9A5800`, 5.57:1) |
| 21 | low | JUnit XML parsed with `xml.etree` (as required, stdlib only). Hostile XML (entity expansion) is mitigated by the bundled expat's limits, not by `defusedxml`. Test-result files are the user's own CI output. | accepted; revisit if results are ever fetched from untrusted sources |
| 22 | low | Route pairing uses `(METHOD, normalized path)` only. Routes mounted through app factories or `add_api_route` are invisible (P1 issue 7), so their spec endpoints show `missing`. | open (P1 issue 7) |
| 23 | low | A failing linked test leaves a link `implemented` (not `drift`), per ADR-0015. A reviewer might expect red. The evidence `tests_failed` is recorded; the viewer can badge it. | by design |
| 24 | low | The shell tool mangled backslash escapes and some quotes in heredocs, and one edit silently failed (#20). Edits were moved to scratch scripts. Tooling only. | n/a |

## P3

| # | Severity | Issue | Status |
|---|---|---|---|
| 25 | high | Two nested Click groups defining a command with the same name (dispatch: `plugins list`, `scheduler list`) produced the same port id; writing the epoch failed on a UNIQUE constraint. Found by the dispatch bench. | **fixed**: commands are named by their group path (ADR-0021), regression test |
| 26 | medium | A port bound to two handlers (the same route declared twice) produced two workflows with one workflow id, and two `entry` code facts with one key; the write failed. | **fixed**: entry facts store the handler list; one workflow per port with the handlers as parallel targets (ADR-0021), regression test |
| 27 | high | Function-local imports were hoisted to module bindings, where a top-level `def` of the same name wins. On dispatch, four CLI commands' `from dispatch.common.utils.cli import install_plugins; install_plugins()` resolved to the Click command `cli.py::install_plugins`, inflating its reach 1 → 5 and ranking its loop **#1** of the top-10. Found while reviewing the top-10. | **fixed**: imports inside functions bind in the function scope (`_local_import`), regression test |
| 28 | medium | The first multi-epoch layout keyed membership rows by text ids (`epoch_id`, `node_id`, `version_key`) plus two indexes: dispatch grew ~5 MB per epoch (3.42× one epoch after 9 epochs, target ≤ 2.5×). | **fixed**: integer `(seq, vid)` membership in WITHOUT ROWID tables, node references checked by `validate` (ADR-0017): 1.16× |
| 29 | low | Writing the new head's derived rows before dropping the previous head's doubled them at peak and left ~8 MB of free pages after the second epoch. | **fixed**: drop first, the pages are reused |
| 30 | medium | `history` re-exported every commit to a fresh directory. On this Windows machine the first read of freshly written files costs ~4 s on dispatch (antivirus scanning, as in issue 13), which dominated incremental epochs. | **fixed**: one export, then only `git diff-tree` paths are rewritten (falls back to a full export when `.gitattributes` uses `export-*`) |
| 31 | medium | Calls through plugin registries and instances (`plugin.instance.consume(...)`) are unresolved, so plugin code keeps reach 0 (dispatch's SQS consumer). | open (pending.md) |
| 32 | low | Nested loops over the same IO are each flagged (dispatch `process_signals`: the `while True` and the `for organization` loop both rank in the top-10 with the same body). | open; consider reporting only the innermost flagged loop per IO site |
| 33 | medium | The incremental speed-up is bounded: hits skip the local passes, but parsing, the global passes, pairing and the write always run (dispatch: median 7.3 s per incremental epoch vs 14.3 s cold from a fresh export, 0.51×; vs a warm cold run 0.86×). | accepted for P3 (ADR-0018); caching global results needs call-graph-closure invalidation (out of scope) |
| 34 | low | Epoch ids are not recomputed after `prune` re-parents an epoch, so an id no longer matches the formula with the new parent. | by design (ADR-0024): ids name extractions and must stay stable |
| 35 | low | In the history fixture, renaming a helper also makes `REQ-002` stale, because the caller's body changed (its call site). Correct under the rules; a reviewer might expect a rename to be invisible everywhere. | by design (ADR-0020), documented in `expected-history.yaml` |
| 36 | low | PyYAML reads a bare `off` as `false` (YAML 1.1), so `orphan_policy: off` arrived as a boolean. | **fixed**: `false` is accepted as `off` (ADR-0022) |
| 37 | low | `diff` only compares an epoch with one of its ancestors in the same file. | by design (ADR-0023) |

## P4

| # | Severity | Issue | Status |
|---|---|---|---|
| 38 | medium | Live run: the verbatim-copy guard invalidated a correct judgment whose rationale paraphrased 60+ chars of the requirement sentence. | **fixed**: a verbatim copy is a warning; it invalidates only when the copied text holds an instruction-like phrase; cached outputs are re-validated on every hit, so the fix applied at no cost (ADR-0029), regression test |
| 39 | medium | Live run: Vertex answered HTTP 400 INVALID_ARGUMENT to the extract-prose request; bisecting (400s are not billed; one successful diagnostic call) showed the nested response schema (array of objects inside an array of objects) was rejected. | **fixed**: flat schema with a `component` field per requirement; ad2v regroups (ADR-0030) |
| 40 | medium | Live run: two suggest results for code-side items were invalid because the model cited the spec candidate's lines, which the validator did not allow. | **fixed**: evidence may cite any numbered line shown for the item or that candidate; a match still needs code lines when the code side has any |
| 41 | medium | Reasoning ("thought") tokens made actual output ≈ 3× the static estimate on the judge and ≈ 2.2× over all tasks; the plan under-estimated the fixture cost ($0.25 planned vs $0.54 for the same calls). | **mitigated**: the budget pre-check uses the observed average output per task after the first call (ADR-0032); open: per-model calibration of plan estimates (pending.md) |
| 42 | medium | The planted REQ-009 drift ("at most once per run", re-classification per match attempt) came back `cannot_tell` in both live runs: the slice does not show what a run's attempts contain. | open: richer slices (callers, data shapes) in a later phase |
| 43 | low | Container/component links (CMP-002 ↔ container:worker) are judged on an IR digest only, and the live judge answered `cannot_tell`. | open (pending.md) |
| 44 | low | The live suggester proposed REQ-008 (bounded backoff) ↔ `fetch_statement` with a wrong rationale ("bounded" because `wait_exponential` caps the delay; the retry has no `stop=`). The pairing is plausible; the claim is not. | by design: suggestions need human confirmation, and an accepted link is then judged |
| 45 | low | The machine's gcloud default project is a different project; a request without an explicit quota project could be billed there. | **guarded**: every Vertex request names `llm.project` in the URL and sends `x-goog-user-project` |
| 46 | low | `plan --epoch all` cannot know children's summary result ids for epochs not yet run, so parent summaries are counted once per distinct digest; the multi-epoch summary estimate is approximate. | accepted |
| 47 | low | The `summaries.confidence` column is NOT NULL but summaries have no model confidence; ad2v stores 1.0 for a valid output. | accepted (ADR-0030) |

## P5

| # | Severity | Issue | Status |
|---|---|---|---|
| 48 | medium | Layout stability was 93.5% on the P3 history: ports reshuffled when the east/south split changed, and a growing track pushed every later track. | **fixed**: persisted port slots, quantized tracks with 20% headroom, never shrink: 765/765 (ADR-0034) |
| 49 | medium | Vite 8 pulls in `lightningcss` (MPL-2.0). | **fixed**: Vite 7 + Vitest 4; the license gate fails the build on any copyleft package (ADR-0035) |
| 50 | medium | Screen-space ribbons (outlines, edges) were invisible: back-face culling dropped them, and the quad triangulation was wrong. | **fixed**: `DoubleSide`, index order corrected |
| 51 | high | On dispatch the home view was clipped: the camera stood a fixed 1,000 units from its target (the map is ~8,500 wide), and the minimum zoom (0.02) could not fit the whole map. | **fixed**: clip planes, camera distance and minimum zoom scale with the map extent (ADR-0037) |
| 52 | low | The workflow selector grew with long workflow names and wrapped the toolbar onto two rows (dispatch). | **fixed**: capped width with ellipsis |
| 53 | low | The fallback card pluralized `class` as "classs". | **fixed**, test added |
| 54 | medium | Dispatch's layout is sparse: the system box is ~8,500 × 4,300 units and the dense code sits in one region, so the home view shows mostly empty slabs and an edge hairball between a few open components. | open (pending.md): tighter packing in a `nestgrid-v2`, edge bundling |
| 55 | low | Very long dashed edges alias into a cross-hatch at high zoom (dispatch). | open (pending.md) |
| 56 | low | Headed Chromium cannot be launched from the agent's sandbox (`spawn UNKNOWN`). | worked around: headless Chromium with hardware ANGLE (D3D11) on the real GPU (ADR-0038) |
| 57 | low | Headless e2e uses SwiftShader, where frame rates are meaningless; e2e does not assert fps. | by design: fps is measured in the M9 bench on the GPU |

## P6

| # | Severity | Issue | Status |
|---|---|---|---|
| 58 | high | The P6 plan asked for `initialize`/`initialized`, `ping` and logging; MCP 2026-07-28 removed the handshake, `ping`, `logging/setLevel` and sessions (stateless, per-request `_meta`, `server/discover`). | **resolved**: pinned 2026-07-28 and dual-era (a legacy `initialize` still works); logging to stderr per the deprecation (ADR-0039) |
| 59 | medium | The official Python MCP SDK depends on httpx → certifi (MPL-2.0). | **resolved**: stdlib server |
| 60 | medium | The MCP Inspector's tree includes Vite 8 → lightningcss (MPL-2.0). | **resolved**: run via `npx`, not a dependency (ADR-0045) |
| 61 | medium | Conformance: the Inspector sends numeric tool arguments (`from=2` → 2), and `from` was typed as a string. | **fixed**: epoch arguments accept integers |
| 62 | low | Inspector `--strict`: a nullable `type: ["string","null"]` (`viewer_scene.root_id`) is less portable across model providers. | **fixed**: optional string (absent = whole epoch) |
| 63 | medium | The first `ad2v_locate` on dispatch took 2.3 s (BM25 build 3.35 s): one SQL query per module through the versioned `nodes` view, and re-stemming. | **fixed**: one query, memoized stems (0.33 s), built in a background thread at startup |
| 64 | low | The P5 viewer's "accept suggestion" command omitted the file argument (`ad2v suggestions accept <id>` fails). | **fixed**: `ad2v suggestions accept <file> <id> --manifest ad2v.yaml` |
| 65 | low | `ad2v.mcp.__init__` imported the function `app_tools`, shadowing the submodule of the same name. | **fixed**: `make_app_tools` |
| 66 | low | In app mode, a deterministic card counts only the loaded part of a subtree ("3 components, 15 modules" when more exist below). | open (pending.md): ask the server for the digest |
| 67 | low | For "which endpoint is not in the spec?", `ad2v_status` lists by qualified name, so containers come before the route (MRR 0.25); `ad2v_locate` ranks it first. | open: rank status results by kind specificity |
| 68 | low | Weight tuning improved the tuning set but lowered held-out MRR (0.94 → 0.84 locate-only) on 8 questions: noise-level overfitting. | accepted and reported (ADR-0043); needs a larger question set (pending.md) |
| 69 | low | `diff` intent in the MCP App loads both whole epochs (the classifier needs every node). | accepted (ADR-0041); fine up to dispatch size (~5 MB per epoch) |

