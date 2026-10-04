# Status

## P7 (done): verified quickstart, settings prefixes, retrieval v2, chat agent, LLM refinements, UX v2

Single final commit at the end. P6.1 report: docs/reports/P6.1.md. Context: docs/claude-context.md.
Cloud: only mapper-cat-3, ADC, labels project=ad2v; no real LLM call before M8 approval; cap $2.00.

| Milestone | Scope | State |
|---|---|---|
| M1 | Verified quickstart (docs/quickstart.md + tests/test_quickstart.py) | done: every local command run; draft deleted; 10 guard tests (slow) + 1 cloud skip; CLI fix: specs bootstrap --from is repo-relative (ADR-0052); doc fixes: history range, suggestions --manifest, manifest auto-load, UI names, .ad2v/ gitignore |
| M2 | Settings prefixes (issue 70) + retrieval v2 + eval sets | done: path_constants + opt-in resolve_settings_defaults (ADR-0053), fixture audit route 3 modes, template 23 -> 0 unresolved; retrieval v2 (ADR-0054): propagation, ids, tests factor, resource words, status order; sets 40/10/20 frozen; MRR P6 25: 0.888 -> 1.00, fixture40 0.813 -> 0.912, presets 0.642 -> 0.85, template 0.529 -> 0.762; 280 pytest |
| M3 | Chat backend (ad2v view --chat, SSE, tools in-process, security) | done: format v0.5 + in-place upgrade (ADR-0055); src/ad2v/chat (agent, schemas, http); provider chat() for vertex/openai/fake; Server.call_tool; ad2v view --chat/--manifest/--chat-budget-usd; 17 chat tests (scripts 5.3, security, SSE, converters); ADR-0056/0057; 299 pytest |
| M4 | Chat UI (panel, meter, follow, citations) | done: ui/chat.ts (ChatPanel, TurnCard, SSE), ui/markdown.ts (DOM-only, node links only), meter + estimate + Follow + Ctrl+Enter/Esc; chat intents without cards; e2e chat 3/3 both themes (real ad2v view --chat, fake provider); P7-screens chat-follow |
| M5 | Viewer UX v2 (labels, edge declutter, portals, dashes, issue 71, nestgrid-v2) | done (screenshots of dispatch + re-taken sets in M7 run): model/declutter.ts (labels priority+hysteresis, edge modes all/selection/aggregated + limit 150, merged portals), per-segment dash scale, issue 71 marker + zoom to step, suggestions badge + hint, contents list; nestgrid-v2 (ADR-0062): dispatch density 0.498 -> 0.552, root 4.8x smaller, stability 100% both, v1 stays default; vitest 49, e2e ux-v2 2/2 |
| M6 | LLM refinements (thinking, schema digest, judge roll-up) | done: llm.tasks.<task>.thinking mapped per model family (3.8 Flash: low/medium/high, no minimal/budget), in params_hash (ADR-0058); schema digest (sqlalchemy/sql/pydantic, judge slice <=40 lines; fixture models.py + schema.sql, classify_run -> db.save_classifications) (ADR-0059); judge_rollups + effective view, containers not judged (12 -> 11 jobs); prune --drop-llm-cache bug fixed (ADR-0060); 310 pytest |
| M7 | Tests and gates, dispatch perf | done: pytest 320 + 1 cloud skip (95% cov; new modules 90-100%), vitest 49, eslint/tsc/ruff clean, builds + license gate, test:mcp (Inspector 38/38, App e2e 10/10), Playwright tour 2, replay-camera 2, dim 3, chat 3, ux-v2 2; dispatch in-process tools p95 <= 72 ms (targets 150/300), viewer 59.9 fps median (p5 59.5), first render 1.31 s v1 / 0.87 s v2, declutter 716 -> 50 edges; P7-screens 34 files; final retrieval MRR P6-25 0.98, fixture40 0.90, presets 0.85, template 0.76 |
| M8 | Live Vertex run (approval required, cap $2.00) | done (approved): 163 calls, $0.385 actual (plan $0.44 static / $0.72 calibrated); judge default acc 0.8 k 0.64 $0.066 vs low acc 0.9 k 0.81 $0.019, REQ-009 caught by both; summarize+narrate low $0.186 (-60%/call vs P4); chat 5 q $0.078 (Q1 hit the step cap -> fix: forced answer on the last step + unanswered turns dropped from history; Q1+Q2 re-run $0.028); bootstrap 1 call $0.007, faithful; dispatch summarize+narrate re-estimate $10.60 (P4 ~$24.5) |
| M9 | Docs | done: README, quickstart (chat, settings prefixes, thinking), mcp.md, format spec v0.5 (changes, 3.9 digest, 6.1 prefixes, 11.4 roll-up, 13.1a/13.3), dependencies (no new deps), issues (closed 42 43 55 67 70 71; new 77-83), pending, claude-context; ADR-0052..0062; REPORT.md + docs/reports/P7.md |

## P6.1 (done): real-repo readiness

Single final commit at the end. P6 report is at docs/reports/P6.md. Context: docs/claude-context.md.

| Milestone | Scope | State |
|---|---|---|
| M1 | Route recall: add_api_route, factories, include_router chains, Starlette Route/Mount, Flask add_url_rule/blueprints; path_unresolved -> needs_review | done: fixture export endpoint missing -> implemented; dispatch 286/290 paths corrected (parent prefix + app.mount); template 23 routes flagged path_unresolved (settings.API_V1_STR); 245 pytest |
| M2 | Spec discovery: --spec > ad2v.yaml spec_root > auto-detect; --no-spec-autodetect; roots in config_hash | done: src/ad2v/specroots.py; printed by extract/history; 5 tests (project/ + project/specs/ auto-detected) |
| M3 | SDD Markdown presets: ad2v, spec-kit, kiro, custom; namespaced / synthesized ids; ambiguous refs -> needs_review | done: extract/spec/presets.py; fixtures/sdd-presets/{spec-kit,kiro,custom} + goldens; 9 tests incl. CRLF+BOM determinism; docs pending (M7) |
| M4 | `ad2v specs bootstrap/review/approve` (fake provider) | done: bootstrap.py + cli_specs.py; index.json, staleness, -X offsets; 3 tests; transcript recorded; 262 pytest |
| M5 | Replay camera framing (+ App replay/path) | done: MapScene.frameStep (fit / zoom-to-label-LOD capped by parent / pan) + ring for steps below label size; e2e 13 steps x 2 themes all >= 90% inside and >= 40 px |
| M6 | Dim the rest (opaque blend), light-theme floor/edge contrast, perf check | done: tokens dim.factor 0.7, body.*, replay.highlight; Dim toggle (replay bar); edges/outlines >= 3:1 on bodies and open floors (vitest + pytest); e2e dim 3 tests; dispatch 59.9 fps median, first render 1.2 s |
| M7 | Docs, quickstart draft, claude-context | done: ADR-0046..0051, README, format spec §3.6 ids, convention §6-8, quickstart draft, dependencies (no new deps), issues 7/22 closed + 70-76, pending, claude-context; demo rebuilt; REPORT.md + docs/reports/P6.1.md |

## P6 (done): MCP server (stdlib) + MCP App

Single final commit at the end. P5 report is at docs/reports/P5.md. P6 report: `REPORT.md` (copy in `docs/reports/P6.md`). ADRs 0039–0045.

| Milestone | Scope | State |
|---|---|---|
| M1 | stdlib JSON-RPC MCP server (stdio + Streamable HTTP on 127.0.0.1), pinned protocol + MCP Apps versions, file/root resolution, read-only | done (code): MCP 2026-07-28 dual-era (legacy initialize 2025-11-25/06-18/03-26), MCP Apps 2026-01-26; src/ad2v/mcp/{protocol,stdio,http,files}.py; tests pending (M5) |
| M2 | Agent tools (§3) + untrusted_text wrapping + instructions | done (code): 13 tools in mcp/tools.py, index.py, locate.py (BM25F, rules `retrieval:`); smoke-tested on the fixture |
| M3 | App tools mirroring DataSource, viewer_scene, RemoteSliceSource, parity test | done: 20 viewer_* app-only tools, scene() in both sources, standalone viewer loads via scene(); parity 6/6 (every method, every epoch, 38 roots x 3 depths) |
| M4 | MCP App build (`build:app`, ui://ad2v/map) + app-mode UI + intents | done: app-dist/app.html 988 KB (budget 2 MB, no wasm), ext-apps 2.0.3 App, 5 intents, slices on demand |
| M5 | Conformance (Inspector), Python unit tests, App e2e in test host (10 screenshots) | done: Inspector 2.8.0 via npx 37/38 (fixed: integer epoch args), 23 pytest -m mcp, 10/10 App e2e, no iframe requests |
| M6 | Retrieval eval (25 questions, 8 held out), tuned weights in rules | done: with tools R@5 .95 MRR .89 nDCG .88 (held-out .92/.75/.77); weights in rules `retrieval:` |
| M7 | docs/mcp.md client setup | done |
| M8 | Performance on dispatch | done: warm p95 get_node 28 ms, search 4, neighborhood 23, status 8, workflow 11, locate 37, overview 13 (targets 150/300); cold start 0.31 s; BM25 build 3.35 s -> 0.33 s (batched source query, memoized stems, startup warm-up); App first render 1.10 s dispatch / 0.55 s fixture (budget 1.5 s); bench/ deleted |

## P5 (done, commit aeef69a): the viewer

Single final commit at the end. Root REPORT.md (P4) removed; it is at docs/reports/P4.md. P5 report: `REPORT.md` (copy in `docs/reports/P5.md`). ADRs 0034–0038.

| Milestone | Scope | State |
|---|---|---|
| M1 | Deterministic layout `nestgrid-v1` (Python, src/ad2v/layout.py; layout_grids table; ports + slots persisted, 20% track headroom) + `ad2v layout` + `materialize --epochs last:N`; stability 765/765 on the P3 history | done |
| M2 | viewer/ (Vite 7, TS strict, ESLint), DataSource + LocalFileSource (sql.js), `ad2v view` (127.0.0.1, tested), single-file demo build, license gate (no lightningcss/MPL: Vite 7) | done |
| M3 | three.js iso map: instanced shapes, LOD+hysteresis, ribbons (screen-space dashes), canvas-atlas labels/badges, navigation, perf HUD | done (perf measured in M9) |
| M4 | LOD edges, portals, status styles from tokens (outlineFor), glow/halo, effective + suggestions toggles, themes; diff/AI/suggestion tokens | done |
| M5 | Panel timeline cards (summary/fallback, links+judge, suggestions+copy cmd, risk, workflows, history), chat placeholder | done |
| M6 | Replay (fine playhead, detail slider, narrations + fallback), TS projection parity with Python (all workflows/depths) | done |
| M7 | Epoch scrubber, diff overlay (+/−ghost/↺/from→to), changes card | done |
| M8 | Tests + e2e screenshots + license check | done: 215 pytest (layout 99%, view 96%), 34 vitest, 2 Playwright tours → 12 screenshots, license gate 158 pkgs OK, demo 4.26 MB |
| M9 | Performance on dispatch | done: dispatch dd2837e (5,374 nodes, 17.7 MB file) via `ad2v view`, Intel UHD (ANGLE D3D11): first render 0.86 s, median 59.9 fps / p5 59.5 fps, ≤ 364 visible, ≤ 7 draw calls, heap ≤ 75 MB; fixture 60 fps. Fixed: camera clip planes + min zoom scale with map extent (dispatch home view was clipped), toolbar wrap, plural. bench/ deleted |

## P4 (done, commit 128729b): BYOM LLM layer

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
