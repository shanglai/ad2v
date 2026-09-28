# Issues

Problems found during P1, with severity (high / medium / low).

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
| 9 | low | Behavior ordinals are per function. Inserting a new loop *before* an existing loop in the same function renumbers the later loops (their ids change). This is the documented trade-off (spec §3.3). | accepted |
| 10 | low | Duplicate definitions of the same qualified name (`if X: def f ... else: def f ...`): the first one wins, and the second body is not walked. | open |
| 11 | low | Readers used `sqlite3.connect`, which silently *creates* an empty file when given a missing path. | **fixed**: `store.open_readonly` (mode=ro, clear error) |
| 12 | low | Module-level assignments were re-bound as fresh locals during the module walk, so FastAPI routers lost their identity and `include_router` prefixes were lost. | **fixed** (covered by `test_ports`) |
| 13 | low | SQLite write time on Windows varies a lot between runs (dispatch: 1.8–7.2 s; one outlier run of the small repo took ~40 s end to end). Build time is stable. Likely the filesystem or antivirus scanning new files. | noted; report medians |
| 14 | low | On this machine `core.autocrlf=true` checks the fixture out with CRLF. Normalization makes this harmless, and a test covers it explicitly. | accepted |
| 15 | low | The Bash tool's heredoc handling occasionally failed on quoted content during development; files were written with the editor tool instead. Tooling only, no product impact. | n/a |
