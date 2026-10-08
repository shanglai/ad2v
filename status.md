# Status

## P10 (done): infrastructure layer (plan JSON + static .tf), env-var bridge, C4 view

One commit at the end, then push master + fast-forward main (never force). ADRs from 0073. No LLM calls,
no cloud, never run terraform/tofu on repository code. Never read outside this repository.

| step | scope | state |
|---|---|---|
| M1 | zero-config warning + spec-derived test prefixes | done: unconfigured.py (4 conditions: unresolved route prefixes via CodeFacts.diagnostics, fallback container vs manifests below root, prefixes derived, IaC present); printed by extract, meta.unconfigured_warnings + derived_test_name_prefixes (informative), viewer banner, MCP overview line; effective test prefixes = configured + spec id prefixes (config_json effective.derived_test_prefixes when non-empty); brownfield zero-config RF-002/003 specified -> implemented (only golden change); python extractor records an unresolved include_router prefix even when the router does not resolve; tests/test_unconfigured.py 4 |
| M2 | plan JSON input | done (tests in M8): infra/plan.py (format_version 1.x; planned_values + configuration + resource_changes actions/after_unknown; never reads variables/prior_state/outputs/timestamp), infra/infra.yaml (GCP + AWS core types, allowlist, env locations; in epoch rules `infra`), model.py (allowlisted attrs, sensitive_values dropped, env var sources reference/secret/literal/unknown, module var/output resolution, ECS env_from, website_of); --infra-plan [ENV=]file (repeatable) --infra-env; carry-forward of plan nodes; change_kind infra; fixtures/infra/{gcp,aws}/plan.json (modules, for_each, count, unknown, sensitive, planted secrets); real plan from OpenTofu 1.13.1 (null/random/terraform_data, -refresh=false, checksum-verified zip in scratch) parses: module vars resolved |
| M3 | static .tf fallback | done (tests in M8): python-hcl2 8.1.4 (MIT) + lark 1.3.1 (MIT) + regex (Apache-2.0 AND CNRI-Python), pinned, license gate green (14 dists); infra/static.py (one level of local modules, remote modules recorded, count/for_each -> multiplicity unresolved, locals followed, var defaults never stored); infra_root in ad2v.yaml; one static env per root; plan wins, static fills undeclared gaps (filled_from_static) |
| M4 | format v0.7 (infra side) | done: side infra + 9 kinds, edges references/wires/deploys/provides_env, epochs.infra_hash ('' = none; in epoch id only when set), change_kind infra, derived infra_status + c4_elements + c4_relations (+ c4_layout), schema/ad2v-v0.7.sql + ir-v0.7 schema + format spec renamed, upgrade 0.6->0.7 (rebuild epochs/node_versions, views recreated, epoch_materialized completed), glyph shapes; open_rw upgrades 0.6 files (was refused: found by the new test); masked dump proof vs P9 (git archive 8d817e3): payments-recon, kiro, stories, polyglot identical after masking epoch id / rules hash (+infra key) / format version / infra_hash; spec-kit, custom, table differ only by M1's derived prefixes (SC, BILL, CAL+RNF) and config_hash; new derived rows: c4_* only |
| M5 | env-var bridge | done: infra/envreads.py (os.environ/getenv + BaseSettings fields with env_prefix/alias), infra/bridge.py (deploys a/b/c + ambiguity, provides_env, infra_status per env; website buckets as static hosts), brownfield-es: infra/main.tf (Cloud Run backend, Cloud SQL, Pub/Sub, secret, orphan bucket, frontend website bucket), src/worker (undeployed), Settings reads EXPORT_BUCKET (unwired), fixtures/infra/brownfield-es/{prod,dev}.json (dev: no frontend via count=0, no EVENTS_TOPIC); expected.yaml infra section + test_brownfield static/plans |
| M6 | C4 view (Architecture tab) | done (tests in M8): c4.py (derive per env: system, persons from story actors, externals, units/static sites with deployed containers, data row, code containers undeployed/ambiguous/unknown; coverage roll-up via links; NFR list; unwired env vars; relations aggregated: calls/reads/writes/publishes/consumes/invokes, wires/references, person uses), derived c4_elements/c4_relations, c4_layout (rows persons/units/data/external + system slab, slots kept across epochs), `ad2v c4 --format structurizr|json`; MCP ad2v_architecture + c4 intent + overview infra counts/findings; DataSource c4/infraStatus in both sources (parity 6/6 incl. new methods, 22 app tools); viewer Map | Architecture tabs, env selector, element card (runs, unwired, coverage, NFR note, open in map), selection sync both ways, infra badges on map labels (toggle), infra tokens in both themes; demo fixture carries the GCP plan; e2e architecture 2/2 + P10-screens |
| M7 | init + docs for infra | done: init proposes infra_root (+ name matches), prints the plan command and warning, infra.deploys placeholders for ambiguity, --check entries; ADR-0073..0081; docs/infra.md, quickstart 5b (guard test), security §8b (S17-S19), format spec v0.7 (changes + §14), dogfood infra rows, README, claude-context, issues 103-110, pending, dependencies |
| M8 | tests, gates, perf | done: tests/test_infra.py 19 (plan readers incl. real OpenTofu plan, key-order/BOM invariance, hostile/size limits, static limits, typing, planted secrets (all PLANTED values absent from .ad2v bytes + dump), bridge priorities/ambiguity/many-to-many, wired/unwired, no-infra no-claims, C4 + Structurizr golden, layout slots + 2-epoch stability, history static, init infra, manifest containment), test_unconfigured 4, test_upgrade v0.6->v0.7, test_mcp architecture/c4/overview/retrieval, test_tokens infra contrast, test_brownfield bridge (static + plans); vitest 56 (architecture helpers); e2e architecture 2/2 + App c4 intent; test:mcp parity 6/6, Inspector 38/38, App 12/12; determinism 10 fixtures (+ brownfield-es-infra, payments-recon-infra); perf: 2000-resource plan parse 0.14 s, extract 1.96 s, file +4.0 MB, c4.load 47 ms, C4 first render 58 ms fixture / 557 ms with 2004 elements |
| M9 | report, commit, push | done: REPORT.md + docs/reports/P10.md; final gates: pytest 460 + 2 skip (cov 95%, new modules 92-99%; one flaky chat socket abort in one full run, 3/3 alone), Vitest 56, Playwright 33 + 1 skip, test:mcp parity 6/6 / Inspector 38/38 / App 12/12, ruff, ESLint, tsc, both license gates, determinism 10 fixtures; commit + push below |

## P9 (done; pushed by the developer: origin/master = origin/main = 8d817e3): brownfield onboarding (`ad2v init`, Spanish SDD presets, issue 95, spec-side view)

One commit at the end, then push (fast-forward only). ADRs from 0067. No LLM calls, no cloud. Never read
outside this repository (the owner's evaluation project lives elsewhere).

| step | scope | state |
|---|---|---|
| Step 0 | gates, sanitization, commit P8.1, push | done: gates green (pytest 386+2 skip, vitest 51, ruff, eslint, tsc, both license gates, test:mcp parity 6 / Inspector 38/38 / App 10/10); scan clean; P8.1 = d5038d5; pushed master and master:main, both fast-forward b7e1726..d5038d5 (2 pushes -> 2 CI runs). Both CI runs FAILED in ~12 s: fresh checkout has no viewer/dist, so `pip install -e .` fails (setuptools package-dir). Real bug for fresh clones too; fix in P9, verify in a local fresh clone before the final push |
| M1 | `ad2v init` | done: src/ad2v/init.py + cli_init.py (`ad2v init --repo [--write --force] [--format yaml|json] [--check]`); detectors: spec folders by name and content with scores/evidence, format per file, prose -> bootstrap, spec id prefixes, NFR prefixes, containers (markers at depth <= 3, language, read or not_evaluable), default/generated excludes with dropped counts, SQL (+ drop warning), IaC (terraform/pulumi/cloudformation/k8s/helm, reported only), JUnit/pytest config, unresolved route prefixes (extractor hook `unresolved_prefix_exprs`, never in the graph) -> empty path_constants (empty = ignored by the manifest); components hint; proposal = sorted, commented YAML, no timestamps; --check lists differences (exit 1); extract auto-detect gains sdd/ docs/sdd/; tests/test_brownfield.py 12 |
| M2 | table / stories presets, NFR, Spanish EARS, Spanish Gherkin, titles | done (viewer NFR badge with M4): extract/spec/team.py (table: id/text/title/priority/type/component headers, accent-insensitive, escaped and code pipes, continued rows reported, invalid ids skipped; stories: HU/US headings or items, Como/As a, criteria numbered/bulleted/Dado-Cuando-Entonces -> HU-001.1, actor normalized); Spanish EARS (5 forms + debe/tendrá que) in markdown.parse_ears; `(Título)` convention syntax; titles.py (explicit > GWT then > story action > EARS response > text, 6 words, stop words); NFR by prefix (spec_ids.nonfunctional_prefixes, default RNF/NFR/NF) or Tipo column, counted in status, MCP overview, dogfood_counts; fixtures sdd-presets/{table,stories} + goldens + CRLF/BOM; tests/test_team_presets.py 21 (incl. Spanish Gherkin parity) |
| M3 | issue 95 (component-mapped requirements, test titles in unread languages) | done: requirements under a spec component whose (manifest/name/manifest_link) pairing is not_evaluable -> not_evaluable, evidence component_out_of_scope; test titles in unextracted files (it/test/describe/context/suite, @DisplayName, Kotlin backtick, Go TestRF001_2) are references (source test_title, evidence test_in_unread_language), never verified; polyglot fixture + cart.test.ts + REQ-004; test_scope.py 9 |
| M4 | spec side: steps off the map, labels, word-boundary truncation | done: layout.OFF_MAP_KINDS = {scenario_step} (in the graph, glyph kept, no layout row; map_children used by the layouters and density); steps status none (reason kind step); scenarios add via_spec_ref reasons from the requirements their tags reference (deduped per ref/status); NodeRow + title/refs/nfr/keyword in both sources (LocalFileSource displayFields, slices._display; test:mcp parity green); text.ts displayLabel (`REQ-001 · title`, `CMP-001 · name`, `scenario [REQ-001, REQ-002]`) + truncateWords (word boundary + …) in billboards, contents list, replay picker; card: NFR badge + note, ordered Steps with keywords, component_out_of_scope note names component + language; replay picker has Code workflows / Spec scenarios groups, spec replay starts at the finest level and shows the step text; layout stability on the P3 history 786/786 = 1.0000 (v1 and v2); golden changes: expected-history 4->5 verified->stale 2 -> 3 (the @REQ-001 scenario), test_layout skips off-map kinds, brownfield expected.yaml + one scenario; e2e spec-side 4/4, P9-screens 12 files; title trailing words + menos/más/less/more/than/que; --no-spec-autodetect help lists sdd/ |
| M5 | default excludes, SQL under migrations | code done (tests with M1/M6): .venv*, .next, out, target, vendor, coverage, *.min.js, *.map added; migrations/ and alembic/ code excluded but their *.sql kept (code_excluded); setup.py makes viewer packages optional (fresh-clone install, CI failure) |
| M6 | fixtures/brownfield-es | done (re-checked after M4, + scenario roll-up): sdd/ (RF table w/ Componente, RNF table, 3 HU, Spanish Gherkin, OpenAPI, prose contexto.md), src/backend FastAPI + settings prefix + SQLAlchemy + test_rf_00X, src/frontend TS + it("RF-008") + node_modules/ dist/ (gitignore negations), src/db schema.sql + migrations (.sql + .py), infra/*.tf; expected-init.txt + expected.yaml (zero-config vs init); bootstrap cycle with fake provider on sdd/contexto.md (prose validator now accepts Spanish EARS) |
| M7 | docs, gates, report, commit + push | done: ADR-0067..0072; quickstart §2b (test_step2b guard), convention (table/stories/Spanish EARS/titles), format spec 'Additions within v0.6' (no bump), dogfood (init step 1, NFR row), README, claude-context, issues (95 closed; 97-102), pending, dependencies; fresh-copy install verified (editable without viewer; release build requires it); gates: pytest 428 + 2 skip (cov 95%, new modules 93-100%), Vitest 53, Playwright 29 + 1 skip, test:mcp (parity 6/6, Inspector 38/38, App 10/10), ruff, ESLint, tsc, npm + Python license gates, determinism 8 fixtures; sanitization scan clean; earlier phases' screenshots restored; e2e temp dirs now removed in afterAll; Chromium, npx Inspector cache, scratch removed; REPORT.md + docs/reports/P9.md; commit + push below |

## P8.1 (done): `not_evaluable`, a status and legend for code no active extractor reads

Requested after P8 (2026-10-07): a category for "specified and developed, but not evaluable
because the language is outside the comprehended scope" (TypeScript today). ADR-0066, format v0.6.
Report: REPORT.md §13 (copy docs/reports/P8.md). Not committed yet (P8 is `4d5740b`).

| step | state |
|---|---|
| status `not_evaluable` (ir, DDL CHECKs, IR schema, tokens, themes, preview) | done; precedence implemented > not_evaluable > specified |
| format v0.6 + in-place upgrade 0.5 -> 0.6 (links, node_status rebuilt; 0.4 -> 0.5 -> 0.6) | done; test with a rebuilt v0.5 file |
| language scope inventory (`ad2v.scope`): unextracted modules, `ad2v:` comment markers, epoch inputs, `scope` in epoch rules | done |
| pairing: implemented -> not_evaluable for unextracted code; never orphan; containers from package.json/go.mod/Cargo.toml/pom.xml/build.gradle | done |
| CLI summary line, `status --status not_evaluable`, MCP status words, dogfood_counts by language | done |
| viewer: style (dotted, hollow, thin, ∅ badge), Legend button, card note with the language | done; e2e scope.spec.ts 2/2, P8.1-screens 4 |
| fixtures/polyglot (Python API + TypeScript web), tests/test_scope.py 5, upgrade test, vitest +2 | done |
| docs: ADR-0066, format spec v0.6 (§4.1, §6.2, §6.4), visual tokens, README, quickstart, dogfood | done |
| proof: P8 vs P8.1 dumps of 5 Python-only scenarios identical except epoch id, rules hash, format version, recorded precedence | done |
| gates: pytest 388 (386 + 2 skips), vitest 51, Playwright 26 (25 + 1 skip), test:mcp (Inspector 38/38, App 10/10), ruff, eslint, tsc, builds, license gates, determinism (5 fixtures) | done |

## P8 (done): release readiness without release, plus the extractor plug-in API

Single final commit at the end. P8 report: REPORT.md (copy docs/reports/P8.md); P7 report: docs/reports/P7.md. Context: docs/claude-context.md.
Tests: pytest 382 (380 passed, 2 skipped), Vitest 49, Playwright 24 (23 + 1 on-demand skip), test:mcp passed. Cost P8 $0 (total $0.977).
Nothing is published (no PyPI/TestPyPI, tags, releases, Pages, visibility change). No cloud spend, no
LLM calls (fake provider only). Before-dumps of every fixture captured before any code change.

| Milestone | Scope | State |
|---|---|---|
| M1 | Extractor plug-in API (ad2v.api), entry points, opt-in, identity in epoch, Python extractor + framework pack as plug-ins, conformance kit, out-of-tree examples | done: ad2v/api.py (api 1.0), plugins.py (discovery, opt-in, identity, isolated runs, timeouts, --strict), built-ins python 1.0.0 + python-frameworks 1.0.0 (rules split, pack merge = P7 python.yaml hash 40e0c803), plugin identity in epoch rules (additive v0.5), parse cache key name@version, GC fix; ad2v extractors list / extractor check; ad2v.testing.conformance (7 checks); examples/plugins routes-dsl + bottle pass the kit in a temp venv and extract; 9 dump scenarios identical (epoch id / rules hash masked); ADR-0063..0065, docs/plugins.md; tests/test_plugins.py 34; 2 tests adapted (cache shape, GC invariant) |
| M2 | Blind retrieval eval harness | done: src/ad2v/mcp/blind.py + `ad2v eval blind` (AD2V_BLIND_EVAL file or dir; aggregates only: counts, sha256, MRR/recall@5/nDCG@5 + bootstrap 95% CI seed 987654 x2000; types < 5 suppressed; sanitized errors); template with 2 dummy questions; docs/blind-eval.md; .gitignore fixtures/retrieval-eval/blind/; tests/test_blind_eval.py 6 (marker-leak test incl. error paths); no blind content written or read |
| M3 | Packaging (wheel, clean venv, twine check), release.yml disabled | done: version 0.7.0.dev0 (pyproject, __init__, viewer); fixed: ad2v.chat missing from the wheel since P7, setuptools 'package would be ignored' for themes/rules/assets; wheel 107 files incl. viewer, app.html, themes, prompts, both rules files, no fixtures/bench/.ad2v/node_modules; pip install . and wheel in clean venvs (deps all MIT/PSF, no certifi); quickstart guard vs installed wheel 10 passed + 1 cloud skip; twine check PASSED (build 1.6.1, twine 7.0.0 in a throwaway venv; pipx not installed); .github/workflows/release.yml (dispatch only, typed confirm, if: false, env pypi, SHA-pinned); docs/RELEASING.md (not for now) |
| M4 | CI workflows | done (written, never run): .github/workflows/ci.yml (viewer: lint/tsc/vitest/build+build:app with npm license gate; python 3.12 + 3.11: Python license gate, ruff, pytest, determinism LF vs CRLF+BOM; cross-OS determinism compare; plug-in conformance kit on installed examples) - ubuntu on push/PR, Windows/macOS only via workflow_dispatch all_os; SHA-pinned actions, contents: read; scripts/check_python_licenses.py, scripts/determinism_check.py; tests/test_ci_workflows.py (static: pins, permissions, OS gating, release cannot publish) + test_license_gate.py; actionlint not installed (static checks instead); py3.11 compileall OK; estimate ~18 billed min per push, ~156 weighted min per all-OS dispatch |
| M5 | Security review | done: docs/security.md (8 surfaces, 16 findings: 11 fixed, 5 open low/medium-by-design), SECURITY.md (private for now); fixes: spec_root / rules_overlay / autodetect-symlink containment, approve --to containment, Host check on every view request (DNS rebinding), CSP object-src/base-uri/form-action/frame-ancestors + Referrer-Policy, writers refuse triggers/altered views, trusted_schema=OFF, validate reports foreign objects/huge strings/deep JSON, MCP refuses foreign schema, kit side_effects check; tests: tests/hostile.py (5 variants), tests/test_security.py 12 (1 symlink skip on Windows), e2e/hostile.spec.ts 2/2 (no script runs in either viewer mode); pip-audit 0 vulns; npm audit 0 runtime, 3 high build-only (braces, no fix) |
| M6 | Sanitization inventory | done: tracked + untracked-unignored files fixed with placeholders (<repo-root>, <github-owner>, <your-gcp-project>; test uses example-project; owner name in public-facing docs -> 'the owner'): local abs paths w/ username 3 lines/2 files, GitHub owner 1/1, GCP project id 12/7, owner first name in new public docs 5/3; generic placeholders (C:\Users\you) and a sql.js false positive kept; embedded demo data and recordings clean; 64 tracked images not scanned. History (15 commits, report only): abs paths w/ username 7 added lines/3 commits, GitHub owner 1/1, GCP project 17/4, commit metadata personal-domain email 15/15 authors + 14/15 committers. Secrets: gitleaks not installed; regex scan (11 patterns) over history + tree: 0 secrets (3 false-positive groups). No STOP needed |
| M7 | Dogfood procedure | done: docs/dogfood.md (setup, spec format checks incl. Gherkin / ad2v Markdown / spec-kit / Kiro / custom, external manifest with spec_root / path_constants / orphan_policy, extract + test results + history HEAD~N..HEAD + view with timings, 8 capture items, cleanup, blank results table per repo, findings template in words, no-LLM note); scripts/dogfood_counts.py (numbers only); .gitignore .venv-*/ |

## P7 (done): verified quickstart, settings prefixes, retrieval v2, chat agent, LLM refinements, UX v2

Single final commit at the end. P6.1 report: docs/reports/P6.1.md. Context: docs/claude-context.md.
Cloud: only <your-gcp-project>, ADC, labels project=ad2v; no real LLM call before M8 approval; cap $2.00.

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
| M9 | Live Vertex run on the fixture (approved): gemini-3.8-flash, global, <your-gcp-project>; 125 billed generateContent calls, $0.592; eval accuracy 0.818, kappa 0.699, stability 11/11; dispatch plan only | done |

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
