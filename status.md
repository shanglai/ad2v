# Status

## P2 (done): pairing, statuses, severity, visual tokens, format v0.2

Everything is committed in one final commit (see `git log -1`). Report: `REPORT.md` (copy in
`docs/reports/P2.md`).

| Milestone | Scope | State |
|---|---|---|
| M1 | Schema v0.2: spec_root, workflow_step_nodes, meta.class, links.method, node_status, status_rollup, test_results, epoch config/test hashes, `--normative-only`, format spec v0.2 | done |
| M2 | Pairing: annotation, route_match (normalization), manifest, name_match | done |
| M3 | Link statuses, orphan scope, effective status precedence, roll-ups | done |
| M4 | JUnit ingestion, `status` CLI, extract summary | done |
| M5 | Severity (rules weights, overlay), `inspect --top-risk`, content-anchored behavior ids, containment projection | done |
| M6 | Visual tokens (dark/light), contrast test, `preview-tokens` | done |
| M7 | Fixture extension + expected.yaml, perf re-check, docs, ADRs 0011–0016, report | done |

Quality gates: 128 tests passing, ruff clean, 95% line coverage (new modules 98–100%).
Determinism (two runs, CRLF+BOM copy, renamed checkout, unrelated edit) and projection (both
modes) property tests pass. The token contrast test passes for both themes.

## P1 (done)

M1–M6 committed separately (`f0eb889` … `833a1fb`), M7 in `4b8dbf8`. Report: `docs/reports/P1.md`.
