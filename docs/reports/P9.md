# P9 report: brownfield onboarding (`ad2v init`, Spanish SDD presets, issue 95, the spec side of the map)

P9 makes ad2v work on an existing project that was not built for it. The example: specs in
`sdd/`, written in Spanish as requirement tables, user stories and Gherkin; a Python backend and
a TypeScript frontend with no `ad2v:` annotations; SQL; Terraform. The path from "never seen
this repo" to "a useful map" is now `ad2v init` → review the proposed `ad2v.yaml` → `extract`.
It is fully deterministic and makes no LLM call.

The P8 + P8.1 report moved to [docs/reports/P8.md](docs/reports/P8.md) (one copy). This report is
also at [docs/reports/P9.md](docs/reports/P9.md).

## 1. Accrued cost per phase

| phase | cloud / LLM spend | what |
|---|---|---|
| P1 | $0 | |
| P2 | $0 | |
| P3 | $0 | |
| P4 | $0.592 | Vertex AI, gemini-3.8-flash, 125 calls (approved live run) |
| P5 | $0 | |
| P6 | $0 | |
| P6.1 | $0 | |
| P7 | $0.385 | Vertex AI, 163 calls (approved live run) |
| P8 | $0 | |
| P8.1 | $0 | |
| **P9** | **$0** | no cloud, no LLM (the bootstrap cycle used the `fake` provider) |
| **total** | **$0.977** | |

**CI minutes (GitHub Actions, private repository).** `ci.yml` runs on pushes to `main` and
`master`, so each branch push is one run. That gives about 18 billed ubuntu minutes per run (the
P8 estimate).

| pushes | runs | estimate | note |
|---|---|---|---|
| Step 0: `master`, `master:main` (P8.1) | 2 | ~36 min by the rule | both runs **failed after ~12 s** at `pip install -e .` (§2), so the real billed time is a few minutes (per-job minimum) |
| final: `master`, `master:main` (P9) | 2 | ~36 min | |
| **P9 total** | **4** | **~72 min (upper bound)** | no manual all-OS dispatch |

**Claude usage** is not observable per phase. The account is on the Max plan with extra usage
disabled, so this phase added no metered Claude cost.

## 2. Step 0: P8.1 committed and pushed

- Gates before committing: pytest 386 passed + 2 skipped, Vitest 51, ruff, ESLint, tsc, both
  license gates, and `test:mcp` (parity 6/6, Inspector 38/38, App e2e 10/10). The sanitization
  scan was clean.
- Commit **`d5038d5`**: "P8.1: not_evaluable status for code in languages no active extractor
  reads (format v0.6, ADR-0066)".
- Pushes: `origin/master` and `origin/main`, both **fast-forward** `b7e1726..d5038d5`. No force.
- **Both CI runs failed** in about 12 seconds. A fresh checkout has no `viewer/dist`, and
  `pyproject.toml` mapped the viewer packages onto it, so `pip install -e .` stopped. Any fresh
  clone hit the same failure. Fixed in P9 (ADR-0067, §3 M5). It was verified on a fresh copy of
  the tree in a throwaway venv:
  - `pip install -e .` works without a viewer build, and `extract` runs;
  - `AD2V_REQUIRE_VIEWER=1 python -m build --wheel` fails without the build and passes with it
    (112 files, viewer and app included).
  The P9 push is the first CI run with the fix.

## 3. Milestones

| milestone | state | notes |
|---|---|---|
| M1 `ad2v init` | **done** | `init.py`, `cli_init.py`; `--write [--force]`, `--format yaml|json`, `--check`; ADR-0071 |
| M2 team presets | **done** | `table`, `stories` (Spanish + English), Spanish EARS, Spanish Gherkin (native), titles, NFR; ADR-0069 |
| M3 issue 95 | **done** | `component_out_of_scope`; test titles in unread languages (`test_in_unread_language`, never verified); ADR-0070; issue closed |
| M4 spec side of the map | **done** | steps off the map, scenario roll-up, labels, word-boundary truncation, NFR badge, step lists, spec replay; stability 1.0000; ADR-0072 |
| M5 default excludes | **done** | wider defaults, SQL kept under `migrations/`/`alembic/`, IaC not `not_evaluable`; ADR-0068. Also the fresh-clone install fix (ADR-0067) |
| M6 `fixtures/brownfield-es` | **done** | written from the prompt alone; goldens `expected-init.txt`, `expected.yaml`; in `determinism_check.py` |
| M7 docs, gates, report | **done** | quickstart §2b (guarded by a test), convention, format spec notes (no bump), dogfood, README, claude-context, issues, pending, dependencies |

## 4. `ad2v init`

**Detectors:**
- **Spec folders.** By name: `specs/`, `spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`,
  `docs/sdd/`, `requirements/`, `docs/requirements/`, `specification(s)/`. By content: any folder
  whose files a reader recognizes. Each candidate is scored, with the evidence (files per
  format), and nested candidates are folded into their parent.
- **Format per file.** ad2v, spec-kit, kiro, table, stories, gherkin, openapi, or prose. Prose
  files are listed as candidates for `specs bootstrap`.
- **Prefixes.** Spec id prefixes become `test_name_prefixes`. Non-functional prefixes are
  detected from ids, or from a table type column.
- **Containers.** Project manifests at depth ≤ 3, with their language and whether an active
  extractor reads it. A components hint when spec component names match container names.
- **Excludes.** Default or generated folders actually present, with the files and code files each
  one drops.
- **SQL.** SQL files are listed, with a warning when an exclude would drop them.
- **IaC.** Terraform, Pulumi, CloudFormation, Kubernetes and Helm: reported, plus a commented
  `# infra:` hint.
- **Test results.** JUnit XML files and pytest configuration, with a suggested `--test-results`.
- **Route prefixes.** The Python extractor runs with the proposed containers. The prefix
  expressions it cannot resolve become `path_constants` with **empty** values.

**Verbatim output on `fixtures/brownfield-es`** (also the golden `expected-init.txt`):

```text
ad2v init: fixtures/brownfield-es

Spec folders (score; evidence = files per format):
  sdd/  score 15  (gherkin 1, openapi 1, prose 1, stories 1, table 1)  proposed
Spec files:
  sdd/api/openapi.yaml: openapi
  sdd/contexto.md: prose
  sdd/features/conciliacion.feature: gherkin
  sdd/historias.md: stories
  sdd/requerimientos.md: table
Prose no preset reads (candidates for `ad2v specs bootstrap`):
  sdd/contexto.md
Spec id prefixes: HU, RF, RNF
Containers:
  backend (src/backend/, pyproject.toml): python, read by the python extractor
  frontend (src/frontend/, package.json): typescript, no active extractor: not_evaluable
Excluded folders (files dropped; code files of them):
  dist: 2 (2 code)  [default]
  node_modules: 1 (1 code)  [default]
SQL files (schema digests):
  src/db/migrations/V2__indices.sql
  src/db/schema.sql
Infrastructure as code (detected; not mapped until P10):
  terraform: infra/
Test results:
  pytest config: src/backend/pyproject.toml (run `pytest --junitxml <file>`)
Route prefixes the extractor cannot resolve (3 route(s)): settings.API_PREFIX; fill in pairing.path_constants

Next:
  ad2v init --repo fixtures/brownfield-es --write <a file outside the repo>
  ad2v extract --repo fixtures/brownfield-es --manifest <a file outside the repo> --out brownfield-es.ad2v
  ad2v specs bootstrap --repo fixtures/brownfield-es --from sdd/contexto.md --plan
  ad2v view brownfield-es.ad2v

# ---- proposed ad2v.yaml ----
# ad2v.yaml proposed by `ad2v init` (review it; nothing here is guessed).
# Keep it outside the repository while you try it: `ad2v extract --manifest <this file>`.
# one container per project manifest found (language: read by an extractor?)
containers:
  - {kind: service, name: backend, paths: [src/backend]}  # python, pyproject.toml; read
  - {kind: service, name: frontend, paths: [src/frontend]}  # typescript, package.json; not read: shown as not_evaluable
pairing:
  orphan_policy: auto  # auto | strict | off
  # route prefixes the extractor cannot resolve: fill in the values (empty = ignored)
  path_constants:
    "settings.API_PREFIX": ""
spec_ids:
  test_name_prefixes: [CMP, FR, HU, REQ, RF, RNF]  # test_rf_001_… links to RF-001
  nonfunctional_prefixes: [RNF]
# team formats found (they are auto-detected too; listed to keep the choice stable)
spec_markdown:
  - {glob: sdd/historias.md, preset: stories}
  - {glob: sdd/requerimientos.md, preset: table}
spec_root: [sdd]
system: "brownfield-es"
# infra: terraform in infra (detected; not mapped until P10)
```

The output is identical across runs and for LF vs CRLF+BOM inputs (tested). The proposal
round-trips through YAML exactly and loads as a valid manifest as written.

**Known false positives and negatives** (by design or by test; not measured on real
repositories yet):
- FN: a container whose manifest is deeper than 3 levels (monorepo `packages/a/b/c/`) is not
  proposed (issue 102).
- FN: route prefixes are found for Python routes only (the only extractor).
- FN: a spec folder whose Markdown no reader recognizes (pure prose in an unusual folder) is not
  a candidate. Named folders still are, and their prose is listed for bootstrap.
- FP: a `docs/` folder with one table that has an `ID` column whose values fit the spec-id
  grammar would be proposed as a spec root. The score and evidence make that visible.
- FP: `.feature` files under third-party test data would be proposed. Excludes (`vendor/`,
  `node_modules/`) remove the usual cases.
- The `generated` exclude is proposed by folder name only (`generated/`, `__generated__/`).

## 5. Presets: counts, Spanish EARS, titles, NFR

| fixture | presets | requirements | EARS matched / raw | GWT criteria | Gherkin | NFR |
|---|---|---|---|---|---|---|
| `sdd-presets/table` (es + en) | table ×2 | 11 (8 es, 3 en) | 10 / 1 (event 2, state 1, unwanted 1, ubiquitous 6) | 0 | — | 4 (`RNF-001`, `RNF-002`, `CAL-001` by Tipo, `EXP-3` by Type) |
| `sdd-presets/stories` (es + en) | stories ×2 | 10 (4 stories + 6 criteria; 7 es, 3 en) | 3 / 7 (stories and GWT criteria are not EARS) | 3 | — | 0 |
| `brownfield-es` | table, stories | 22 (14 table, 8 stories) | 16 / 6 (event 1, state 1, unwanted 2, ubiquitous 12) | 1 | 1 feature, 4 scenarios (1 Background), 11 steps (Dado 4, Cuando 3, Entonces 3, Y 1) | 4 (`RNF-001..004`) |
| `polyglot` | ad2v | 4 | 4 / 0 | 0 | — | 0 |

The raw (`ears: null`) requirements are the cases the prompt asked for:
- a table row that isn't EARS ("La pantalla de conciliación muestra …");
- the story requirements themselves (Como … quiero …);
- Dado/Cuando/Entonces criteria (kept as `gwt`);
- one criterion with a modal outside the EARS forms ("Solo un usuario con rol de aprobador puede
  aprobar").

**Title examples** (explicit wins; otherwise derived, ≤ 6 words, trailing function words cut):

| id | source | title |
|---|---|---|
| RF-001 (table) | `Título` column | Iniciar conciliación |
| RF-002 | EARS response | Emparejar cada movimiento del extracto |
| RF-003 | unwanted response | Marcarlo como pendiente |
| RF-006 | state response (*debe*) | Reintentar la descarga del extracto |
| HU-001 | story heading | Cargar un extracto |
| HU-002.1 | GWT *then* | Ve los movimientos pendientes ordenados |
| RNF-001 | response, "en menos de" cut | Conciliar 100.000 movimientos |
| EXP-1 (en) | event response | Write a CSV file |
| REQ-004 (en) | unwanted response, modal "can" cut | Return an error the client |

Two refinements came from these examples: comparatives (*menos*, *más*, *than*) and modals
(*can*, *may*, *puede*) are now trailing words. Titles stay a heuristic (issue 99).

**NFR handling.** `attrs.requirement_type = nonfunctional` comes from the id prefix
(`spec_ids.nonfunctional_prefixes`, default RNF/NFR/NF; `init` proposes the ones it finds) or
from a table type cell. Non-functional requirements pair like any other, so they usually stay
`specified`. They are counted apart in:
- `ad2v status` (a summary line);
- the MCP overview (`nonfunctional_requirements`);
- `scripts/dogfood_counts.py` (`nonfunctional_requirements_by_status`).
In the viewer they get an NFR badge, and the card explains that they are not expected to pair
with one piece of code.

## 6. Issue 95: before and after

| requirement | P8.1 | P9 | why |
|---|---|---|---|
| polyglot REQ-001 | implemented | implemented | Python, evaluated |
| polyglot REQ-002 | not_evaluable | not_evaluable | `// ad2v: REQ-002` in TypeScript (P8.1) |
| polyglot REQ-003 | **specified** | **not_evaluable** | its spec component (Web client) pairs with the all-TypeScript `web` container: `component_out_of_scope` |
| polyglot REQ-004 (new) | (would be specified) | not_evaluable | `it("REQ-004 …")` in `web/src/cart.test.ts`: `test_in_unread_language` |
| brownfield RF-007 | (specified) | not_evaluable | `Componente = Frontend` → container `frontend` (TypeScript): `component_out_of_scope` |
| brownfield RF-008 | (specified) | not_evaluable | `it("RF-008 …")` in `avance.test.ts` |
| brownfield RF-009 | (specified) | not_evaluable | component, like RF-007 |

None of them is ever `verified`: ad2v has no test results for unread languages.

## 7. The spec side of the map (ADR-0072)

What changed:
- **Steps off the map.** `scenario_step` nodes stay in the graph (ids, glyph rows, edges,
  workflows) but get no layout row. They are listed in order in the scenario's card, with the
  keyword marked. Spec scenarios are in the replay picker (a "Spec scenarios" group), start at the
  finest level, and show each step's text.
- **Statuses.** Steps are `none`. A scenario adds one `via_spec_ref` reason per (referenced
  requirement, link status), so it shows the worst status of the requirements its tags name.
- **Labels.**
  - requirement: `RF-001 · Iniciar conciliación`;
  - spec component with an id: `CMP-001 · Reconciliation API`;
  - scenario: `Start a reconciliation run [REQ-001, REQ-002]`.
  The full label is in the hover tooltip and the card. NodeRow carries `title`, `refs`, `nfr`
  and `keyword` in both data sources, and the parity test is green.
- **Truncation.** Text is cut at a word boundary with "…" everywhere: map labels (48), contents
  lists (80), the replay picker (60) and tooltip text (200). The mid-word cut is gone.
- **Cards.**
  - NFR badge and note;
  - `component_out_of_scope` note naming the component and its language ("its component
    Frontend is implemented in typescript …").

**Layout stability on the P3 history scenario:** 786/786 unchanged nodes keep their position
across epochs, **1.0000** with both `nestgrid-v1` and `nestgrid-v2` (target ≥ 0.95).

**Screenshots** (`docs/reports/P9-screens/`, dark and light, 12 files):
1. `*-1-payments-recon-scenario.png`: scenario card with 4 ordered steps and the roll-up reasons.
2. `*-2-payments-recon-component.png`: `CMP-001 · Reconciliation API`.
3. `*-3-payments-recon-replay.png`: a spec scenario replayed step by step.
4. `*-4-brownfield-nfr.png`: `RNF-001 · …` with the NFR badge and note.
5. `*-5-brownfield-scenario.png`: Spanish scenario, Dado / Cuando / Entonces.
6. `*-6-brownfield-component-out-of-scope.png`: RF-007 `not_evaluable` with the component note.

## 8. Brownfield results: zero-config vs `init`

| | zero-config | with `init` |
|---|---|---|
| commands | 1 (`extract`) | 2 (`init --write`, `extract --manifest`) |
| human edits | 0 | 1 (`"settings.API_PREFIX": "/api/v1"`) |
| tool time (3 runs, this machine) | 0.72–0.87 s | init 0.60–0.69 s + extract 0.71–0.75 s |
| spec roots | `sdd/` (auto-detected, new in P9) | `sdd/` (manifest) |
| spec items found | 22 requirements, 4 scenarios, 3 endpoints, 5 components (same) | same |
| containers | 1 fallback (`brownfield-es`) | `backend`, `frontend` |
| endpoints (3) | **missing** (route prefix lost) | **implemented** |
| code orphans | 5 (the 3 routes, the fallback container, `src`) | **0** |
| RF-002 / RF-003 | specified (`RF` is not a default test prefix) | **implemented** (`test_rf_002_…`) |
| RF-007/008/009 | not_evaluable (name match) | not_evaluable (`component_out_of_scope` / test title) |
| spec status counts | missing 3, implemented 1, not_evaluable 5, specified 25 | implemented 8, not_evaluable 5, specified 21 |

**Time to first useful map:** zero-config takes 1 command and under a second, but the map is
misleading: three spec endpoints look unbuilt, and their routes look like dead code. With `init`
it takes 2 commands and 1 edit (about 1.3 s of tool time plus reading the report). Every
endpoint and route pairs, and the backend and frontend are separate containers. The edit is the
only step a person must think about, and `init --check` keeps flagging it until it is done.

The bootstrap cycle on `sdd/contexto.md` (prose) ran with the `fake` provider:
1. plan;
2. bootstrap (a Spanish EARS proposal);
3. approve to `sdd/aprobados`.
REQ-X001 is then `specified`.

## 9. Tests, goldens, dependencies

| gate | before (Step 0) | after |
|---|---|---|
| pytest | 386 passed + 2 skipped | **428 passed + 2 skipped** (cloud skip, Windows symlink skip); `-m slow` included |
| coverage | — | total 95%; new modules: `cli_init` 100%, `team` 96%, `titles` 97%, `init` 93%, `scope` 98% |
| Vitest | 51 | **53** |
| Playwright | 26 (25 + 1 skip) | **30 (29 + 1 skip)**; new `spec-side.spec.ts` (4) |
| `test:mcp` | parity 6/6, Inspector 38/38, App 10/10 | same |
| ruff, ESLint, tsc, npm and Python license gates | clean | clean |
| determinism (LF vs CRLF+BOM) | 5 fixtures | 8 (+ `sdd-table`, `sdd-stories`, `brownfield-es`) |

**Changed goldens and expectations, with reasons:**
- `fixtures/payments-recon/expected-history.yaml`, diff 4→5: `verified → stale` goes from 2 to 3.
  The scenario tagged `@REQ-001` now rolls up REQ-001, which goes stale (ADR-0072).
- `tests/test_layout.py`: the geometry and stability checks skip `OFF_MAP_KINDS` (steps have no
  box).
- `viewer/tests/datasource.test.ts`: every node has a glyph; every node except steps has a
  layout row.
- `tests/test_scope.py`: polyglot REQ-003 `specified` → `not_evaluable`; REQ-004 added (issue 95).
- `viewer/e2e/scope.spec.ts`: "typescript 3 file(s)" (was 2; `cart.test.ts` added).
- **Normative dumps:** steps' `node_status` is now always `none`, and scenarios gain
  `via_spec_ref` reasons. No other node or link row changes. `payments-recon/expected.yaml` and
  every preset golden pass unchanged.

**Dependencies:** none added (Python or npm). `build` ran once more in a throwaway venv, and
Playwright's Chromium was used for the screenshots. Both were removed (`docs/dependencies.md`).

## 10. Open questions for P10 and P11

**P10: infrastructure.**
1. **Plan JSON vs static `.tf`.** A supplied `terraform show -json` plan has resolved values,
   modules and counts. Static `.tf` parsing (HCL) needs a license-clean parser: python-hcl2 is
   MIT, but its `lark` dependency must be checked. Which comes first, and is the static fallback
   worth a dependency?
2. **The env-var bridge.** Code reads `os.environ["DATABASE_URL"]` / `settings.X`; infra sets
   `environment { DATABASE_URL = aws_db_instance.main.endpoint }`. Should a match create an edge
   (normative, deterministic), and what happens when several resources set the same name in
   different workspaces?
3. **C4 view.** A deterministic C4 container or deployment view in its own tab. Should it be
   derived from the same graph (new `infra` side, or new kinds on the code side), and is that a
   format v0.7 change (new kinds = new CHECK constraints, ADR-0055/0066 style upgrade)?
4. **Secrets in plans.** Plan JSON can contain sensitive values. Should they be dropped at read
   time (never stored), with `sensitive: true` respected?

**P11: the TypeScript extractor.**
1. Parser: tree-sitter-typescript (MIT) through the existing plug-in API, and which frameworks
   first (Express/Fastify/Nest routes, React Router, Next.js app router)?
2. Test results for TS (Jest/Vitest JUnit reporters) to make `test_in_unread_language` links
   `verified`?
3. Once the plug-in claims `*.ts`, `not_evaluable` disappears by itself. Keep the polyglot and
   brownfield goldens as the before/after proof?

## 11. Commit

- Commit: **"P9: brownfield onboarding (`ad2v init`, Spanish SDD presets, issue 95, spec-side
  view)"**. Hash: see `git log -1`.
- Push: `origin/master` and `origin/main`, fast-forward only. The result is recorded in
  `status.md` after the push.
- Changed files, grouped:
  - **Onboarding:**
    - `src/ad2v/init.py`, `src/ad2v/cli_init.py` (new), `src/ad2v/cli.py`;
    - `src/ad2v/specroots.py` (`sdd/`);
    - `src/ad2v/extract/code/python.py` (`unresolved_prefix_exprs`, state only).
  - **Specs:**
    - `src/ad2v/extract/spec/team.py`, `titles.py` (new);
    - `markdown.py` (Spanish EARS, `(Título)`), `presets.py`, `__init__.py`;
    - `src/ad2v/llm/prose.py` (Spanish modals).
  - **Scope, pairing, layout, manifest:**
    - `src/ad2v/scope.py` (test titles), `pairing.py` (component scope, scenario roll-up,
      steps);
    - `layout.py` (`OFF_MAP_KINDS`), `manifest.py` (excludes, NFR prefixes), `pipeline.py`;
    - `src/ad2v/mcp/slices.py`, `mcp/tools.py`.
  - **Packaging:** `setup.py` (new), `pyproject.toml`, `.github/workflows/release.yml`,
    `.gitignore`.
  - **Viewer:**
    - `src/data/types.ts`, `LocalFileSource.ts`;
    - `src/model/text.ts` (`displayLabel`, `truncateWords`);
    - `src/render/billboards.ts`;
    - `src/ui/app.ts`, `ui/legend.ts`, `style.css`;
    - tests `model.test.ts`, `datasource.test.ts`; e2e `spec-side.spec.ts` (new), `scope.spec.ts`.
  - **Fixtures:**
    - `fixtures/brownfield-es/` (new);
    - `fixtures/sdd-presets/{table,stories}/` (new);
    - `fixtures/polyglot/` (`cart.test.ts`, REQ-004);
    - `fixtures/payments-recon/expected-history.yaml`.
  - **Tests:** `test_brownfield.py`, `test_team_presets.py` (new), `test_presets.py`,
    `test_scope.py`, `test_layout.py`, `test_quickstart.py` (step 2b).
  - **Scripts:** `scripts/determinism_check.py`, `scripts/dogfood_counts.py`.
  - **Docs:**
    - ADR-0067..0072;
    - `docs/quickstart.md`, `docs/spec/spec-markdown-convention.md`,
      `docs/spec/ad2v-format-v0.6.md`;
    - `docs/dogfood.md`, `docs/dependencies.md`, `docs/claude-context.md`;
    - `README.md`, `issues.md`, `pending.md`, `status.md`;
    - `REPORT.md` + `docs/reports/P9.md`, `docs/reports/P9-screens/`.

**Clean-up:**
- removed: the scratch files, the fresh-copy tree, its venv and the wheels;
- removed after the screenshots: Playwright's Chromium;
- removed: the npx MCP Inspector cache, which was used only by `test:mcp`;
- restored: earlier phases' screenshots that the full e2e run had re-taken.
