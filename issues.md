# Issues

Problems found during P1 and P2, with severity (high / medium / low).

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
| 17 | medium | Severity rewards reachability from *recognized* entry ports. Risky loops in scheduled jobs or CLI commands registered in ways the extractor does not recognize get reach 0 (dispatch: `consume_signals`, `sync_tasks`, the SQS consumer rank 8-10 with severity 5.0, while plausibly worse in production). | open (pending.md: more port frameworks, scheduler detection) |
| 18 | medium | Without specs or annotations, every port/container/component is `orphan` (dispatch: 462 orphans, 290 of them routes). Correct by the rules, but a map without specs is all red dashes at the port level. | by design; P5 viewer should offer a "no specs loaded" mode |
| 19 | low | `.ad2v` size grew ~35-40% (dispatch 11.4 → 16.1 MB) from `links`, `node_status`, `status_rollup` and `workflow_step_nodes`. `workflow_step_nodes` dominates on dispatch (~10.5k steps). | accepted; P3 content-addressed storage should dedupe |
| 20 | low | The light theme's warning badge initially failed the text-contrast requirement (3.46:1). An earlier edit silently did not apply; the new contrast test caught it. | **fixed** (`#9A5800`, 5.57:1) |
| 21 | low | JUnit XML parsed with `xml.etree` (as required, stdlib only). Hostile XML (entity expansion) is mitigated by the bundled expat's limits, not by `defusedxml`. Test-result files are the user's own CI output. | accepted; revisit if results are ever fetched from untrusted sources |
| 22 | low | Route pairing uses `(METHOD, normalized path)` only. Routes mounted through app factories or `add_api_route` are invisible (P1 issue 7), so their spec endpoints show `missing`. | open (P1 issue 7) |
| 23 | low | A failing linked test leaves a link `implemented` (not `drift`), per ADR-0015. A reviewer might expect red. The evidence `tests_failed` is recorded; the viewer can badge it. | by design |
| 24 | low | The shell tool mangled backslash escapes and some quotes in heredocs, and one edit silently failed (#20). Edits were moved to scratch scripts. Tooling only. | n/a |
