# REPORT: ad2v P2 (pairing, statuses, severity, visual tokens, format v0.2)

**Summary.** All seven milestones are done. ad2v now pairs spec items with code deterministically
(annotation, route match with path normalization, manifest, exact-slug name match). It derives
link statuses, one effective status per node and roll-ups, ingests JUnit results for `verified`,
scores risky behaviors with a rules-driven severity, and ships dark and light visual tokens that
pass WCAG contrast checks and a "status without color" test. Format → **v0.2**. There are still no
LLM calls anywhere. **128 tests pass.** The normative dump is identical across repeated runs, a
CRLF+BOM copy, a renamed checkout and an unrelated edit.

Environment: Windows 11, Python 3.12.3, pip + venv. The P1 report was moved to
[`docs/reports/P1.md`](docs/reports/P1.md). This file is also at `docs/reports/P2.md`.

## 1. Milestones

| Milestone | Scope | State |
|---|---|---|
| M1 | Schema v0.2 (`spec_root`, `workflow_step_nodes`, `meta.class`, `links.method`, `node_status`, `status_rollup`, `test_results`, epoch `config_hash`/`test_results_hash`), `--normative-only`, `validate` rejects < 0.2, format spec v0.2 + regenerated N/I appendix | done |
| M2 | Pairing: `annotation`, `route_match` (servers base path, prefix map, positional params, `//`, trailing `/`, optional case folding), `manifest`, `name_match` | done |
| M3 | Link statuses (`missing`, `specified`, `implemented`, `verified`, structural `drift`, scoped `orphan`, `needs_review`), precedence, `node_status`, `status_rollup`, state machine in the spec | done |
| M4 | JUnit XML ingestion (stdlib), documented pytest matching rules, `ad2v status`, extract summary with status counts and top-10 severity | done |
| M5 | Severity with rules-file weights + overlay (`rules_hash` of merged rules), `inspect --top-risk`, content-anchored behavior ids, containment projection (default) | done |
| M6 | `visual-tokens-v0.2.md`, `schema/themes/{dark,light}.json`, contrast + color-alone tests, `ad2v preview-tokens` | done |
| M7 | Fixture extension (JUnit, param-name mismatch, `as_of` drift, ambiguous `/health`, manifest pairing, rules overlay), `expected.yaml`, performance re-check, docs | done |

**Commit.** There is a single final commit (per the session rules): **hash: see `git log -1`**. Files
changed (69):

- **Moved/renamed:** `REPORT.md` → `docs/reports/P1.md`, `schema/ad2v-v0.1.sql` →
  `schema/ad2v-v0.2.sql`, `docs/spec/glyph-grammar-v0.1.md` → `-v0.2.md`. Deleted and replaced:
  `docs/spec/ad2v-format-v0.1.md` → `ad2v-format-v0.2.md`, `schema/ir-v0.1.schema.json` →
  `ir-v0.2.schema.json`.
- **New source:** `src/ad2v/{pairing,severity,junit,rules,tokens,preview}.py`.
- **Changed source:** `cli, ddl, dump, glyphs, ids, ir, manifest, pipeline, resources, store,
  validate, workflows, __init__`, `extract/code/python.py`, `extract/code/rules/python.yaml`,
  `extract/spec/{__init__,openapi}.py`.
- **New schema:** `schema/themes/{dark,light}.json`.
- **Docs:** `docs/spec/visual-tokens-v0.2.md`, ADRs 0011–0016 (new), ADRs 0009 and 0010
  (amended), `docs/dependencies.md`, `docs/reports/P2-tokens.html`, `README.md`, `status.md`,
  `issues.md`, `pending.md`, `REPORT.md`, `docs/reports/P2.md`.
- **Fixture:** `ad2v.yaml`, `rules-overlay.yaml`, `expected.yaml`, `specs/openapi.yaml`,
  `test-results/junit.xml`, `api/recon_api/{main,routes}.py`, `api/tests/{test_matching,test_routes}.py`,
  `worker/recon_worker/health.py`.
- **Tests:** `test_pairing.py`, `test_severity_rules_junit.py` and `test_tokens.py` are new. The
  other test files were updated.
- **Build:** `pyproject.toml` (version 0.2.0, themes in package data, a per-file lint exception for
  the HTML template).

## 2. Tests

**128 passed, 0 failed** (`pytest`, 7–17 s on this machine). `ruff check` and `ruff format --check`
are clean.

| file | tests | covers |
|---|---|---|
| `test_pairing.py` (new) | 19 | path normalization (7 cases), slug, route match + `param_name_mismatch`, required-query drift, `**kwargs` exemption, path-param-count drift, ambiguity → `needs_review`, manifest (found / target missing / unknown id), name match (single / ambiguous), `specified`, `missing`, orphan scope (ports/containers/components only; functions/modules `none`), port via handler, `verified` needs a passing linked test and nothing is verified without results, failing test → evidence, unresolved ref → `needs_review`, precedence order, roll-up counts |
| `test_severity_rules_junit.py` (new) | 15 | severity formula (7 cases incl. cap and max-not-sum), rank tie-break, deep-merge semantics, overlay → hash + weights, manifest overlay must exist, JUnit matching rules (class, param suffix, rootdir suffix, ambiguity, `file` tiebreak), worst outcome wins, malformed/missing XML errors, test results move the epoch, `--normative-only` drops LLM rows/columns |
| `test_tokens.py` (new) | 13 | **contrast**: status strokes ≥ 3:1 on background and surface, text ≥ 4.5:1, badge glyph ≥ 4.5:1, ramp/edges ≥ 3:1, in both themes; **no two statuses differ by color alone**; normative mapping; glow vs halo; WCAG math; preview self-contained (no external refs, no scripts) and complete (10 shapes × 9 statuses) |
| `test_fixture_golden.py` | 16 | `expected.yaml`: counts, statuses per named item, link evidence, roll-ups, top-3 severity, test matching, overlay in `rules_hash`, `spec_root` hierarchy |
| `test_python_extractor.py` | 18 | P1 coverage + anchored ids, **inserted loop keeps other ids**, whitespace-insensitive anchors, function params, query builders are not IO |
| `test_workflows.py` | 8 | **projection property tests, both modes** (500 call-depth traces + 300 containment traces on random trees, seed 987654), examples, ancestry, step nodes, traces |
| `test_determinism_and_cli.py` | 11 | determinism (normative dump), ID stability **plus identical links/statuses after an unrelated edit, with roll-ups changing only on ancestors**, validate (7 corruption kinds + old format), CLI (`status`, `--top-risk`, `--normative-only`, `preview-tokens`), rules hash |
| others | 28 | ids (incl. link id and all six epoch inputs), store (incl. CHECKs on LLM links), glyphs, spec extractors, schema-doc sync |

Coverage (line), total **95%**. New modules: `pairing` 98%, `junit` 98%, `severity` 100%,
`rules` 100%, `tokens` 100%, `preview` 100%. Extended modules: `dump` 100%, `store` 100%,
`workflows` 99%, `validate` 93%. All new modules are ≥ 90%.

Confirmed:
- **Determinism**: two runs, a copy with every text file (including `junit.xml`) converted to CRLF
  and BOMs added, and a copy under another directory name all give **identical normative dumps**.
  After an unrelated function is added, the only new id is that function's, the `links` and
  `node_status` rows of all existing nodes are identical, and `status_rollup` changes only on the
  four ancestors.
- **Projection**: the partition invariant holds in both modes. Increasing the depth never merges
  steps. In containment mode, each coarse step highlights exactly its members' depth-k ancestors.
- **Contrast**: passes for both themes. The test caught a real bug during the session: a light
  badge at 3.46:1 whose earlier fix had silently not applied (issue 20).

## 3. Fixture results (`fixtures/payments-recon`, with `test-results/junit.xml`)

16 code files, 3 spec files, 1 JUnit file → 105 nodes, 185 edges, 13 workflows (10 code + 3 spec).

**Spec side** (effective status, main reason):

| spec item | status | why |
|---|---|---|
| REQ-001 | verified | annotated `start_run` + passing `test_req_001_start_run_returns_run_result` |
| REQ-002 | verified | annotated `match_batch` + passing `test_req_002_…` |
| REQ-003 | verified | annotated `amounts_match` + passing `test_req_003_…` |
| REQ-004 | implemented | annotated `classify_unmatched`; its linked test **failed** (evidence `tests_failed`) |
| REQ-005, REQ-006 | implemented | annotations, no linked tests |
| REQ-007, REQ-008 | specified | no deterministic pair (absence not provable) |
| `POST /reconciliations` | verified | route match + REQ-001 test via `x-ad2v-refs` |
| `GET /reconciliations/{run_id}` | implemented | route match with evidence `param_name_mismatch` (`run_id` vs `id`) |
| `GET /reconciliations/{run_id}/unmatched` | **drift** | OpenAPI requires query `as_of`; handler `list_unmatched(run_id)` lacks it |
| `POST /reconciliations/{run_id}/approve` | **missing** | no route |
| `GET /health` | **needs_review** | two candidate routes (`http:api:…` and `http:worker:…`) |
| CMP-002 (Nightly worker) | implemented | `pairing.components: {CMP-002: worker}` |
| CMP-001, the Gherkin feature, 4 scenarios | specified | no rule pairs them |

**Code side**:

| code item | status | why |
|---|---|---|
| `container:api` | **orphan** | no spec component maps to it (CMP-001 "Reconciliation API" ≠ slug "api") |
| `container:worker` | implemented | manifest pairing |
| `http:api:GET /internal/debug/stats` | **orphan** | no endpoint, no annotation, unlinked container |
| `http:api:GET /v1/reconciliations/{run_id}/unmatched` | drift | see above |
| `http:api:GET/worker:GET /v1/health` | needs_review | ambiguous |
| `http:api:POST /v1/reconciliations` | verified | |
| `mcp:api:reconciliation_summary` | implemented | via its annotated handler (REQ-006) |
| worker CLI commands, event consumer | implemented | inherited from `container:worker` |
| `db.py::record_run` | needs_review | dangling `# ad2v: REQ-099` |
| `db.py::fetch_ledger_entry` and other un-annotated api functions | none | never orphan |

**Roll-ups** (descendant counts): `container:api` = {drift 1, implemented 7, needs_review 2, none 24,
orphan 3, verified 8}; `container:worker` = {implemented 16, needs_review 1}.

**Top-3 severity** (the overlay raises `unbounded_retry` base 4 → 6):

| rank | node | severity |
|---|---|---|
| 1 | `bank_client.py::fetch_statement@retry#297043df` (unbounded retry, 1 workflow) | 9.0 = 6 × 1.5 |
| 2 | `classify.py::classify_unmatched@llm_call#67251e28` (LLM in loop) | 7.5 = 5 × 1.5 |
| 3 | `classify.py::classify_unmatched@loop#bc51e9e6` (LLM in loop) | 7.5 (tie broken by id) |

The N+1 loop in `match_batch` is 4th (3 × 1.7 = 5.1; reached by 3 workflows). `rules_hash` equals
the hash of built-in + overlay, and differs from the built-in-only hash (asserted).

**Test-result matching**: 5 test cases, **4 matched** (3 passed, 1 failed): `test_req_003_…`,
`test_req_002_…`, `test_req_001_…` passed and `test_req_004_…` failed. **1 unmatched**:
`api.tests.test_legacy::test_removed_export_endpoint[csv]` (`not_found`; the module does not exist).
It is reported in the summary and in `epochs.attrs_json.unmatched_tests`, not raised as an error.

## 4. Performance re-check vs P1

Same commits as P1, measured on this laptop, medians of 5 runs. The clones were deleted afterwards.

| repo | P1 build / write / size | P2 build / write / size | Δ |
|---|---|---|---|
| fastapi/full-stack-fastapi-template (`cb740b6`, 2,918 LOC) | 0.16 s / 0.39 s / 0.66 MB | 0.16 s / 0.12 s / 0.85 MB | build ±0; size +29% |
| Netflix/dispatch (`dd2837e`, 84,041 LOC) | 3.65 s / 1.86 s / 11.42 MB | 3.51 s / 0.93 s / 16.13 MB | build ±0; size +41% |

Pairing and severity add no measurable build time. Write times are noisy on this machine (P1 issue
13) and are not a real improvement. The size growth comes from the new derived tables, mostly
`workflow_step_nodes` (issue 19). Both files are deterministic across runs and pass `validate`.

Status counts: neither repo has specs or annotations, so every port, container and component is
`orphan` and everything else is `none`. Template: 42 orphan (2 containers, 14 components, 23 routes,
3 CLI commands) and 209 none. Dispatch: 462 orphan and 4,882 none. This is correct per the rules,
but a spec-less map is all red dashes at the port level (issue 18).

**Top-10 severity.** The template has **no risky behaviors**, as in P1, so its top-10 list is empty.
To give a real verdict, I ran the same check on dispatch and read each of the 10 loops:

| # | sev | node | manual verdict |
|---|---|---|---|
| 1 | 8.0 | `incident_cost/service.py::calculate_incident_response_cost_with_cost_model@loop` | **genuine**: nested per-event DB lookup (`participant_service.get_…` per event per activity) |
| 2 | 7.5 | `database/manage.py::setup_fulltext_search@loop` | real IO in loop (one trigger sync per table), but **low impact**: one-time setup |
| 3 | 5.7 | `definition/service.py::create@loop` | **genuine** N+1: `term_service.get_or_create` per term |
| 4 | 5.7 | `term/service.py::create@loop` | **genuine** N+1: `definition_service.upsert` per definition |
| 5 | 5.4 | `entity/service.py::find_entities@loop` | **genuine** N+1: `get_by_value_or_create` per entity |
| 6 | 5.4 | `entity_type/service.py::create@loop#ab21…` | **genuine**: `find_entities` (queries) per signal instance |
| 7 | 5.4 | `entity_type/service.py::create@loop#cfb9…` | **genuine** N+1: `signal_service.get` per signal |
| 8 | 5.0 | `dispatch_aws/plugin.py::…consume@loop` | intended SQS long-poll `while True`. The real concern is the per-message DB work nested inside |
| 9 | 5.0 | `cli.py::consume_signals@loop` | **genuine** nested per-org/project/plugin DB work |
| 10 | 5.0 | `task/scheduled.py::sync_tasks@loop` | **genuine**: per-task DB create/update inside per-document loop |

Verdict: **10/10 do IO in a loop, and 8/10 are the kind of N+1 a reviewer should look at.** #2 is
low-impact setup, and #8 is an intended poll loop. The first run had a **false positive at #3**:
`database/service.py::apply_filter_specific_joins`, where `query.join(...)` only builds SQL, but
its reach of 52 workflows amplified it. I fixed it in the rules (SQLAlchemy query-builder methods
are pure, with a regression test), and dispatch's risky count went 160 → 152. Caveat: #8–#10 have
reach 0 (scheduled or CLI entry points the extractor does not recognize), so they rank below loops
that are probably less important in production (issue 17). Recall is still unmeasured (P1 issue 4).

## 5. The behavior-id change (ADR-0011)

Behavior nodes are now named `<enclosing>@<kind>#<sha256(normalized header)[:8]>[~n]` instead of
`#<ordinal>`. **In the fixture, all 5 emitted behavior nodes changed ids, and no other id changed
because of this.** The full old → new id table is in ADR-0011. (Other fixture ids changed because
the fixture itself changed: `{id}` in a route, new `/health` routes and tests, and spec-endpoint
names without the `/v1` base path now that `servers` carries it. Those are intended fixture edits.)

Why it is safe now: there are no external `.ad2v` consumers, and P3 has not yet stored epochs, so
no stored link or history refers to the old ids. From now on, inserting or deleting an unrelated
construct no longer renames its siblings (tested). Editing a loop's *header* still renames it, and
that is acceptable (ADR-0011).

## 6. Deviations from the prompt

| # | deviation / interpretation | ADR |
|---|---|---|
| 1 | Unpaired items are stored as links with `method = 'none'` (a fifth method value), and `llm` is reserved in the CHECK for P4 | 0015 |
| 2 | Extra node status **`none`** (not a link status), needed for "functions are never orphan": code no coverage applies to renders neutral | 0015, 0016 |
| 3 | Inheritance passes down only `verified`/`implemented`/`specified`. Problem statuses stay local | 0015 |
| 4 | `spec_component` is `missing` only when a manifest mapping's target does not exist. Otherwise an unpaired component is `specified` (reading "covered by name_match" as "all components" would contradict the specified-vs-missing principle) | 0015 |
| 5 | Ports inherit their handler's links (`via_handler`). Linked tests include tests for IDs in the spec item's own `spec_ref` (e.g. `x-ad2v-refs`). A failing test is evidence, not `drift` | 0015 |
| 6 | Severity formula read as `(base + bonus) × reach_factor`, with `base` = max over flags | 0014 |
| 7 | Two extra epoch inputs, `config_hash` and `test_results_hash`, both in the epoch id. `rules_hash` is over canonical merged content, so comment-only rule edits no longer change it (a P1 test was inverted) | 0012 |
| 8 | `path_prefix_map` applies to both sides, on segment boundaries. `case_insensitive` lowercases the whole path (parameters are already `{}`) | 0015 |
| 9 | `stale` placed between `orphan` and `verified` in the precedence (the prompt's list omits it) | 0015 |
| 10 | `node_status.reasons_json` is an object `{precedence, reasons}`, not a list | spec §6.4 |
| 11 | `project()` signature: `project(steps, depth, mode="containment", ancestry_map=...)`. The prompt's `project(trace, mode=…, depth=k)` has the same semantics, but the ancestry map is explicit | 0013 |
| 12 | Top-10 severity judged on dispatch as well, because the prompt's template repo has zero risky behaviors | n/a |
| 13 | Style for `stale` (clock badge) and `none` (thin) added to the tokens, so every node status renders | 0016 |

## 7. Open questions for P3 (ranked)

1. **Epoch storage layout.** With `node_versions` + `epoch_members` (decided), do `links`,
   `node_status` and `status_rollup` also dedupe by content, or stay per epoch? They are derived and
   cheap to recompute, but `workflow_step_nodes` is already the largest table (dispatch ~10.5k
   steps). Proposal: store derived tables per epoch only for the head epoch, and recompute on
   demand for history.
2. **Incremental invalidation granularity.** A `rules_hash` change invalidates all code-side
   results, a `config_hash` change invalidates pairing, and a `test_results_hash` change invalidates
   statuses only. Is the Merkle unit the module (`subtree_hash` of the module) or the function?
   Transitive IO (the fixpoint over the call graph) means one edited function can change risk flags
   in far-away loops. Reusing results needs the *call-graph closure*, not just subtree hashes.
3. **Epoch diff contract.** Which rows count as "changed" for the diff: nodes by `content_hash`,
   edges ignoring `attrs.lines`, links by `(link_id, status)`? It needs an explicit ignore-list per
   column, probably in the spec's Appendix A as a third class ("volatile").
4. **`stale` semantics with anchored ids.** A header edit renames a behavior node (a new id), so its
   old links become orphan-like instead of `stale`. Should P3 add a rename-detection pass (same
   span + similar header) that turns delete+add into "renamed", before computing `stale`?
5. **Test results across epochs.** Test results are a separate input. Should a new JUnit file with
   unchanged code create a new epoch (today: yes, a different epoch id)? Alternative: model test
   results as an overlay layer on an epoch.
6. **Narrations and projection mode.** Narrations are keyed by `(detail_level, span_start)`, but
   spans differ between containment and call-depth modes. Add `mode` to the narrations key before
   P4 writes any.

## 8. Dependencies

**No dependency was added in P2.** JUnit parsing uses `xml.etree.ElementTree`, and the preview uses
`html` (both stdlib). The runtime, development and build dependency set is unchanged from P1: all
MIT / BSD / Apache-2.0 / PSF-2.0, with setuptools as the build backend. **No copyleft** anywhere,
including transitive and build-time dependencies. Details: [`docs/dependencies.md`](docs/dependencies.md).

## 9. Visual tokens preview

**Open [`docs/reports/P2-tokens.html`](docs/reports/P2-tokens.html)**, a self-contained static page
(regenerate it with `ad2v preview-tokens --out tokens.html`). It shows all 10 base shapes × 9
statuses in dark and light side by side, a grayscale copy that proves the statuses survive without
color, and the severity ramp.

**How the light theme shows "verified" without glow.** A glow is a blur of light around the outline.
On near-black it adds a lot of luminance, but on off-white it adds almost none and disappears. The
light theme instead draws `verified` as a **saturated dark-blue outline** (`#0B47B8`, 7.6:1 on the
background, slightly thicker than `implemented`) over a **soft halo**: a 7 px, 60%-opacity light-blue
(`#8FBCFF`) stroke underneath. The halo gives the same "lit" reading as the dark theme's bloom. The
status never depends on it: `verified` = solid + emphasis, while `implemented` = solid + none. That
difference is in the non-color signature the tests check, so the status survives even in grayscale
or print.
