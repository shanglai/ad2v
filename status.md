# Status

## P3 (done): multi-epoch storage, incremental extraction, epoch diff, stale, lineage

Single final commit at the end of the session (no per-milestone commits). Report: `REPORT.md`
(copy in `docs/reports/P3.md`).

| Milestone | Scope | State |
|---|---|---|
| M1 | Storage v0.3: `*_versions` + integer `(seq, vid)` membership, v0.2-shaped views, derived tables for materialized epochs, `epoch_materialized`, `id_lineage`, `link_state`, narrations `mode`, V column class, `dump --epoch`, spec v0.3 | done |
| M2 | Incremental: `extract --into`, parse cache (local facts), no-change detection, `history` over git commits (incremental export) | done |
| M3 | Lineage (same_content / anchored_header / same_route) + `stale` rules + `# ad2v: REQ@fp` | done |
| M4 | `ad2v diff` (table/json/md), `log`, `pin`/`unpin`, `prune` + GC, `materialize`, example GitHub Action | done |
| M5 | History fixture in a temp git repo + `expected-history.yaml` | done (tests/test_history.py) |
| M6 | Performance on dispatch (20 commits) and template (10 commits, plus the last 10 Python-touching commits) | done; bench clones deleted |
| M7 | `pairing.orphan_policy` (auto/strict/off) + entry-point recognizers (main, celery, apscheduler, schedule, nested click) + function-local import fix | done |

ADRs 0017–0025. 161 tests, coverage 95% (new modules ≥ 91%), ruff clean.

## P2 (done)

Single commit `63718b2`. Report: `docs/reports/P2.md`.

## P1 (done)

M1–M6 committed separately (`f0eb889` … `833a1fb`), M7 in `4b8dbf8`. Report: `docs/reports/P1.md`.
