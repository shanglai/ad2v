# Issues

Problems found during P1, P2 and P3, with severity (high / medium / low).

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
