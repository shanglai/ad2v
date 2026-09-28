# Status

## P4 (done): BYOM LLM layer

Single final commit at the end. Root REPORT.md (P3) removed; it is at docs/reports/P3.md.

| Milestone | Scope | State |
|---|---|---|
| M1 | Callee-rename fingerprint fix (call_masked_hash + call_sites, `callee_renamed` evidence, expected-history epoch 2 REQ-002 verified); `src/ad2v/llm/` config + providers (fake / vertex / openai_compatible, stdlib HTTP, bounded retry); `llm:` excluded from config_hash | done |
| M2 | Format v0.4: source_blobs, llm_results, llm_runs, llm_run_results, link_judgments, link_suggestions, spec_extractions, summaries/narrations.result_id, view node_status_effective | done (spec text pending, docs phase) |
| M3 | Judge: context.py, judge.py, prompt, fixture plants (REQ-003 tolerance 5, REQ-009, REQ-010, decoy, operations.md), goldens updated | done |
| M4 | Suggestions: BM25, suggest task, manifest_link, append-only ad2v.yaml edits, CLI | done |
| M5 | Summaries (bottom-up, deterministic labels, mention validation) | done |
| M6 | Narrations (containment eager, call_depth on demand, refinement context) | done |
| M7 | Prose extraction (REQ-X range, .ad2v-extracted excluded, cycle test) | done |
| M8 | Offline eval harness (`ad2v llm eval`) + recordings in tests/llm_recordings | done (202 tests) |
| M9 | Live Vertex run on the fixture (approved): gemini-3.8-flash, global, mapper-cat-3; 125 billed generateContent calls, $0.592; eval accuracy 0.818, kappa 0.699, stability 11/11; dispatch plan only | done |

## P3 (done, commit ecb6972): multi-epoch storage, incremental extraction, epoch diff, stale, lineage

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
