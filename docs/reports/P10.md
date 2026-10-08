# P10 report: the infrastructure layer, the env-var bridge, and a deterministic C4 view

P10 lets ad2v answer questions that cross spec, code and infrastructure:
- "Which Cloud Run service runs this component?"
- "The code reads `EXPORT_BUCKET`: does any deployment provide it?"
- "What does the architecture look like, per environment, and which requirements does each part
  carry?"

ad2v never runs Terraform. It reads a plan JSON the human supplies (primary) or the `.tf` files
statically (fallback, and the only source in `history`). Only allowlisted attributes and env var
*names* are stored. The results appear in three places:
- an **Architecture** tab (C4) in the viewer;
- a Structurizr / JSON export;
- MCP (`ad2v_architecture`, `ad2v_show` intent `c4`).

The P9 report stays at [docs/reports/P9.md](docs/reports/P9.md). This report is also at
[docs/reports/P10.md](docs/reports/P10.md). The full infra guide is [docs/infra.md](docs/infra.md).

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
| P9 | $0 | |
| **P10** | **$0** | no cloud, no LLM (`fake` provider only); OpenTofu ran offline with local providers |
| **total** | **$0.977** | |

**CI minutes (GitHub Actions, private repository).** Each branch push is one `ci.yml` run, about
18 billed ubuntu minutes (P8 estimate).

| pushes | runs | estimate |
|---|---|---|
| P10 final: `master`, `master:main` | 2 | ~36 min |

The developer pushed P9 between phases (2 runs, ~36 min; not counted here). No manual all-OS
dispatch.

**Claude usage** is not observable per phase. The account is on the Max plan with extra usage
disabled, so this phase added no metered Claude cost.

## 2. Milestones

| milestone | state | notes |
|---|---|---|
| M1 zero-config warning + derived test prefixes | **done** | ADR-0073 |
| M2 infra from a plan JSON | **done** | format 1.x; GCP + AWS core types; per-environment plans; carry-forward; real OpenTofu plan verified; ADR-0074 |
| M3 static `.tf` fallback | **done** | python-hcl2 8.1.4 (MIT) + lark (MIT) + regex (Apache-2.0 AND CNRI-Python), pinned; `infra_root`; plan wins, static fills gaps; history reads infra; ADR-0075 |
| M4 format v0.7 | **done** | infra side, 4 edge kinds, `epochs.infra_hash`, `change_kind: infra`, `infra_status` + C4 tables, upgrade 0.6 → 0.7 (chained from 0.4), masked dump proof; ADR-0077, ADR-0078 |
| M5 env-var bridge | **done** | env reads (os.environ / getenv / BaseSettings), `deploys` a/b/c + ambiguity + many-to-many, `provides_env` / `wires`, per environment; brownfield fixture + plans; ADR-0080 |
| M6 C4 view | **done** | derived tables + slot-persistent layout, Architecture tab (env selector, cards, open in map, selection sync, infra badges), Structurizr / JSON export, MCP tool + intent + overview + retrieval; ADR-0079 |
| M7 `init` + docs | **done** | `infra_root` proposal, plan command and warning, `infra.deploys` placeholders, `--check`; docs/infra.md, quickstart 5b (guarded), security §8b, format spec v0.7 §14, dogfood rows, README, claude-context, issues, pending, dependencies; ADR-0081 |
| M8 tests and gates | **done** | §9 |
| M9 report, commit, push | **done** | this report; commit and push in §11 |

## 3. M1: zero-config before and after (brownfield-es)

**Before (P9):** a zero-config `extract` printed no warning. RF-002 and RF-003 were `specified`
(`RF` was not a test-name prefix).

**After:** the same command ends with:

```text
WARNING: This map was built without configuration; 4 things may be wrong. Run `ad2v init`.
  - route prefixes the extractor cannot resolve: settings.API_PREFIX (endpoints may look missing and routes orphaned; set pairing.path_constants)
  - one fallback container, but project manifests exist below the root: src/backend, src/frontend, src/worker (declare containers)
  - spec id prefixes not in the configured test-name prefixes: HU, RF, RNF (derived from the specs for this run; list them in spec_ids.test_name_prefixes)
  - infrastructure as code found: infra (set infra_root, and pass --infra-plan for deployment facts)
```

RF-002 and RF-003 are now **`implemented`**: the derived prefixes link `test_rf_002_…` and
`test_rf_003_…`. The warnings are also in `meta.unconfigured_warnings`, which is informative and
not in the canonical dump. The viewer shows them as a banner and the MCP overview as a line.

The prefix was detected even without containers: the Python extractor now records an
`include_router(…, prefix=settings.X)` whose router does not resolve (run state only).

## 4. Infra input

- **Plan format:** `format_version` 1.x. The documented plan representation is "1.0", minor versions
  are backward compatible, and Terraform 1.9 and OpenTofu 1.13 emit "1.2". Any other major version
  is refused.
- **Read:**
  - `planned_values` (modules, `count`/`for_each` instances);
  - `configuration` (references, through module variables and outputs);
  - `resource_changes` (actions; `after_unknown` → `unknown`).
- **Never read:** `variables`, `prior_state`, output values, `timestamp`, `relevant_attributes`,
  `checks`.
- **Types mapped** (`src/ad2v/infra/infra.yaml`, covered by `rules_hash`):

  | kind | GCP | AWS |
  |---|---|---|
  | `deployment_unit` | `google_cloud_run_v2_service`, `google_cloud_run_service`, `google_cloud_run_v2_job`, `google_cloudfunctions2_function` | `aws_lambda_function`, `aws_ecs_service` (+ `aws_ecs_task_definition`), `aws_batch_job_definition` (+ queue), `aws_apprunner_service` |
  | `managed_datastore` | `google_sql_database_instance`, `google_firestore_database`, `google_bigquery_dataset`, `google_redis_instance` | `aws_db_instance`, `aws_rds_cluster`, `aws_dynamodb_table`, `aws_elasticache_cluster` |
  | `managed_queue` | `google_pubsub_topic`, `google_pubsub_subscription` | `aws_sqs_queue`, `aws_sns_topic` |
  | `bucket` | `google_storage_bucket` | `aws_s3_bucket` (+ website configuration) |
  | `secret_store` | `google_secret_manager_secret` | `aws_secretsmanager_secret` |
  | `network` | `google_compute_network`, `google_vpc_access_connector` | |
  | `scheduler` | `google_cloud_scheduler_job` | `aws_cloudwatch_event_rule` |
  | `infra_other` | anything else (kept, counted) | |

- **Real-plan check: done.** I took OpenTofu 1.13.1 as the official standalone zip (SHA-256 checked
  against the release's `SHA256SUMS`) and ran it in a scratch folder: `init`, then
  `plan -refresh=false`, then `show -json`. The providers were `null` and `random` plus the
  built-in `terraform_data`, with a module under `for_each`, a sensitive variable and env-style
  objects. There were no credentials.
  - Module instances come out as expected, and references through module variables resolve
    (`module.svc["api"].terraform_data.unit` → `random_password.db`, `terraform_data.db`).
  - The static read of the same `.tf` finds the same references.
  - The plan and config are kept as `fixtures/infra/tofu-real`.
  - The binary, the provider cache and an empty `%APPDATA%\terraform.d` it created were deleted.
  - One finding: the plan's top-level `variables` hold the sensitive variable's value in clear, which
    is why ad2v never reads that key.
- **Static parser:** python-hcl2 8.1.4 (MIT). Its tree is lark 1.3.1 (MIT) and regex 2026.9.29
  (Apache-2.0 AND CNRI-Python). The license gate is green (14 distributions), both are pinned, and
  it is imported only for static reads.
- **Static limits:**
  - `count`/`for_each` are not expanded (`multiplicity: unresolved`);
  - local modules are followed one level; remote modules are recorded, never fetched;
  - variable defaults are never stored;
  - `locals` are followed, while `dynamic` and `jsonencode` are opaque;
  - files over 4 MB are skipped, and a parse error is a warning.

## 5. Planted secrets

The fixtures plant **21 distinct fake secrets**:
- **GCP plan:**
  - a root variable value and a module-variable default;
  - a sensitive output value and an output URL key;
  - a scheduler URI token;
  - secret version data;
  - before/after root passwords (in `resource_changes`) and a `prior_state` password;
  - `output_changes`;
  - an env var literal `API_KEY`.
- **AWS plan:**
  - a variable value and an output;
  - a literal password inside the ECS `container_definitions` JSON;
  - a Lambda env literal password;
  - before/after DB passwords;
  - a token in a git module source URL.
- **Static config:** a sensitive variable default.

`test_planted_secrets_never_reach_the_file_or_its_dump` extracts payments-recon with both plans
(`prod`, `dev`) and the static config as `infra_root`. It asserts that none of the 21 strings, nor
`PLANTED` itself, nor the URL credential, appears in the `.ad2v` **bytes** or in its **full dump**
(informative rows included). It passes. The same check on the MCP tools: `ad2v_architecture`
output contains no `PLANTED` (test_mcp).

## 6. Bridge and findings on `fixtures/brownfield-es`

These results use the manifest `ad2v init` proposes (`infra_root: [infra]`), with the prefix
filled. Rows are from `expected.yaml`, test_brownfield and test_infra:

| | static (`.tf` only, env `default`) | plan `prod` | plan `dev` |
|---|---|---|---|
| `container:backend` | deployed (`conciliacion-backend`, name) | deployed (name) | deployed (`conciliacion-backend-dev`) |
| `container:frontend` | deployed (website bucket `conciliacion-frontend`) | deployed | **undeployed** (bucket `count = 0`) |
| `container:worker` | **undeployed** | **undeployed** | **undeployed** |
| `Settings` (reads `API_PREFIX`, `DATABASE_URL`, `EVENTS_TOPIC`, `EXPORT_BUCKET`, `BANK_TOKEN`) | **unwired**: `EXPORT_BUCKET` | **unwired**: `EXPORT_BUCKET` | **unwired**: `EVENTS_TOPIC`, `EXPORT_BUCKET` |
| `google_storage_bucket.archivo` | **infra_orphan** | **infra_orphan** | (not in dev) |
| SQL instance, topic, secret | in_use | in_use | in_use (topic not in dev) |
| ambiguous | none | none | none |

Wires (prod): `conciliacion-backend` → `conciliacion-db` (`DATABASE_URL`), → `conciliacion-eventos`
(`EVENTS_TOPIC`); the secret `token-banco` via `BANK_TOKEN` (`secret` source).

The bridge rules are also unit-tested on small graphs:
- (a) the manifest wins and resolves an ambiguity;
- (b) name (`orders-api` ↔ `api`);
- (c) env overlap (`billing`);
- two units matching one container by name with different images → `ambiguous`;
- one unit deploying two containers, and two units with the same image deploying one (many-to-many).

## 7. The C4 view

**Fixture (prod).**
- Elements:
  - the system `brownfield-es`;
  - 3 persons from the story actors (Jefe de finanzas, Analista de conciliacion, Operador de
    tesoreria);
  - deployment unit `conciliacion-backend` (runs backend; requirements implemented 2; unwired
    `EXPORT_BUCKET`);
  - static site `conciliacion-frontend` (runs frontend; requirements not_evaluable 1);
  - code container `worker` (undeployed);
  - datastore `conciliacion-db`, queue `conciliacion-eventos`, bucket `conciliacion-archivo`
    (infra_orphan).
- Relations: 2 `wires`. Persons have no `uses` here, because no story requirement pairs with code
  (issue 108).
- The payments-recon demo (GCP plan) shows `calls` (worker → API), `invokes` (to the external
  bank API and the model endpoint), `wires` (env vars to the database and topic) and `references`
  (the scheduler → the API service).

**Layout stability:** across two epochs of the fixture (the dev plan gains the frontend bucket),
**17/17** common elements keep row, slot and position, with 1 element added. The test requires
≥ 95%. Slots are also unit-tested: a removed element leaves its slot free, and a new one takes the
lowest free slot. Rows wrap at 4 columns (persons at 5), so wide views stay readable in the App.

**Structurizr export** (`ad2v c4 bf.ad2v --env prod`, golden
`fixtures/infra/brownfield-es/expected-c4-prod.dsl`, trimmed):

```text
workspace "brownfield-es (prod)" "Generated by ad2v from the epoch graph (deterministic). Do not edit." {
  model {
    c4_3d7d2b84ebf51018ed2f = person "Jefe de finanzas" "1 user story"
    …
    c4_2d9e3f8e4c8e5a22a435 = softwareSystem "brownfield-es" {
      c4_2aaddf09fb9623345b73 = container "conciliacion-db" "" "google_sql_database_instance" {
        tags "managed_datastore,in_use,Database"
      }
      c4_57a530d1581bf9719500 = container "worker" "" "code container" {
        tags "code_container,undeployed"
      }
      c4_698f28dd26eb49fc3235 = container "conciliacion-backend" "runs backend; requirements: implemented 2" "google_cloud_run_v2_service" {
        tags "deployment_unit,in_use"
      }
      …
    }
    c4_698f28dd26eb49fc3235 -> c4_2aaddf09fb9623345b73 "wires: DATABASE_URL"
    c4_698f28dd26eb49fc3235 -> c4_ba39ba0b796fca5a16b4 "wires: EVENTS_TOPIC"
  }
  views { systemContext … container … styles { Person, Database, Queue, undeployed (dashed), infra_orphan (dotted) } }
}
```

**Screenshots** (`docs/reports/P10-screens/`, dark and light, 10 files):
1. `*-1-architecture-dev.png`: dev; the frontend and worker are undeployed (dashed).
2. `*-2-architecture-prod.png`: prod; static site, orphan bucket (dotted), wires.
3. `*-3-architecture-card.png`: the backend card (runs, unwired `EXPORT_BUCKET`, coverage, open in
   map).
4. `*-4-map-infra-badges.png`: the map with infra badges (☁ backend, ∅☁ worker) and the node card's
   infra statuses per environment.
5. `*-5-app-c4-intent.png`: the MCP App inside a test host after `ad2v_show` intent `c4`.

## 8. Format v0.7

**Changes:**
- the `infra` side and 9 kinds; edges `references`, `wires`, `deploys`, `provides_env`;
- `epochs.infra_hash` (`''` without infra; enters the epoch id only when set);
- `change_kind: infra`;
- derived `infra_status`, `c4_elements`, `c4_relations`, plus `c4_layout`;
- the rules key `infra`.

**Upgrade 0.6 → 0.7** happens in place when a file is opened for writing:
- `epochs` and `node_versions` are rebuilt (CHECK constraints) and their rows copied with
  `infra_hash = ''`;
- every view is dropped and recreated;
- the new tables are created;
- materialized epochs are marked complete for the new derived tables.
It chains from 0.4. The new test emulates a v0.6 file from a fresh one. A real gap turned up:
`extract --into` used to **refuse** a v0.6 file instead of upgrading it (issue 103, fixed).

**Masked normative-dump proof.** The old code was run from `git archive 8d817e3` (P9) and the new
code from the working tree, on the same copies of every fixture without infra. Masked fields: epoch
id, rules hash (and the `infra` key in the stored rules), format version, the empty `infra_hash`.

| fixture | result |
|---|---|
| payments-recon | identical |
| sdd-kiro | identical |
| sdd-stories | identical |
| polyglot | identical |
| sdd-spec-kit | one line differs: the epoch row's `test_ref_prefixes` gains `SC` (ADR-0073) and its `config_hash` changes |
| sdd-custom | the same with `BILL` |
| sdd-table | the same with `CAL`, `RNF` |

No link, status, node or edge row changed. Every fixture gains `c4_*` derived rows (the code-only
view, env `''`).

## 9. Performance, tests, goldens, dependencies

**Performance** (this machine; synthetic plan of 2,000 resources generated with seed 987654):

| measure | value |
|---|---|
| plan parse (2,000 resources, 0.88 MB JSON) | 0.14 s (median of 3) |
| payments-recon extract: no infra / GCP fixture plan / synthetic plan | 1.39 s (cold) / 0.72 s / 1.96 s (medians) |
| file size: no infra → with 2,000 resources | 0.75 MB → 4.74 MB (+4.0 MB, ~2 KB per resource; issue 107) |
| `c4.load` (2,005 elements) | 47 ms |
| Architecture tab first render: fixture (7 elements) / synthetic (2,004 elements) | 58 ms / 557 ms |

**Tests:**

| gate | before (P9) | after |
|---|---|---|
| pytest | 428 passed + 2 skipped | **460 passed + 2 skipped** |
| coverage | 95% | 95%; new modules: `c4` 96%, `infra/__init__` 99%, `bridge` 96%, `envreads` 99%, `model` 94%, `plan` 96%, `static` 92%, `unconfigured` 96% |
| Vitest | 53 | **56** |
| Playwright | 29 + 1 skip | **33 + 1 skip** (+ architecture 2, + perf-c4 measurement spec, runs only with `AD2V_C4_PERF`) |
| `test:mcp` | parity 6/6, Inspector 38/38, App 10/10 | parity 6/6 (incl. `c4`, `infraStatus`), Inspector 38/38, **App 12/12** (+ `c4` intent) |
| determinism (LF vs CRLF+BOM) | 8 fixtures | **10** (+ brownfield-es-infra with 2 plans, payments-recon-infra with 2 plans + `.tf`) |
| ruff, ESLint, tsc, npm and Python license gates | clean | clean |

One full-run failure was flaky: `test_chat.py::test_endpoint_security_rejections` hit a Windows
`ConnectionAborted` under load. It passes 3/3 alone, and P10 did not touch chat.

**Changed goldens and expectations:**
- `fixtures/brownfield-es/expected.yaml`:
  - zero-config RF-002/RF-003 → `implemented` (M1);
  - `init` containers + `worker` (new fixture container);
  - a new `infra` section.
- `fixtures/brownfield-es/expected-init.txt`: the third container, the infra lines (proposed
  `infra_root`, name matches, plan command and warning), and `infra_root: [infra]` in the proposal.
- `tests/test_mcp.py` (13 → 14 agent tools), `viewer/tests/mcp/parity.test.ts` (20 → 22 app
  tools), `viewer/scripts/conformance.mjs` (13 → 14).
- `viewer/tests/datasource.test.ts`: format 0.7, and infra nodes have no map layout row.
- `tests/test_upgrade.py`: the version chain now ends at 0.7.

**New dependencies:**
- Python: python-hcl2 8.1.4 (MIT), lark 1.3.1 (MIT), regex 2026.9.29 (Apache-2.0 AND CNRI-Python);
  no copyleft, no `certifi`.
- npm: none.
- OpenTofu 1.13.1 (MPL-2.0) was run once as a tool, outside the tree, and deleted
  (docs/dependencies.md).

## 10. Open questions

**P11 (the TypeScript extractor):**
1. **Env reads in TypeScript.** `process.env.X`, `import.meta.env.X` and Next.js `NEXT_PUBLIC_*`.
   Should the bridge treat build-time variables (baked into a static site) differently from
   runtime ones (a static site has no runtime env)?
2. **Frameworks first:** Express / Fastify / Nest routes or the Next.js app router, so route ↔
   OpenAPI pairing works for TS?
3. **Test results.** Jest / Vitest JUnit reporters would let `test_in_unread_language` links become
   `verified` once TS is read.
4. **Containers.** `package.json` workspaces (monorepos) as several containers: is the name match of
   the bridge enough for them?

**A later NFR-vs-infra check:**
1. **A deterministic catalog first** (recommended). Map common NFR phrasings to infra facts ad2v
   already stores:
   - availability and "always on" → `min_instances ≥ 1`;
   - encryption at rest → `encrypted`;
   - region or data residency → `location`/`region`;
   - scaling ceilings → `max_instances`.
   It is deterministic, cheap and testable. It needs a small rule language over spec text, which
   could be a pattern table in the rules.
2. **The LLM judge** only for what the catalog cannot express ("reconcile 100,000 movements in under
   five minutes" needs load data, not infra). It would be informative, per environment, with
   evidence.
3. **Should a failed check be a new `infra_status` value** (e.g. `nfr_violated`) or a link status on
   the NFR? ADR-0078 suggests the former, to keep the 10-status precedence clean.

## 11. Commit

- Commit: **"P10: infrastructure layer (plan JSON + static .tf), env-var bridge, deterministic C4
  view; format v0.7"**. Hash: see `git log -1`.
- Push: `origin/master`, then `master:main`, fast-forward only. The result is recorded in
  `status.md`.
- Changed files, grouped:
  - **Infra layer (new):**
    - `src/ad2v/infra/` (`__init__`, `infra.yaml`, `model`, `plan`, `static`, `envreads`,
      `bridge`);
    - `src/ad2v/c4.py`, `src/ad2v/unconfigured.py`.
  - **Core:**
    - `ir.py` (side, kinds, edges, statuses), `pipeline.py`, `store.py`, `upgrade.py`;
    - `manifest.py` (`infra_root`, `infra.deploys`, derived prefixes), `plugins.py` (rules key
      `infra`), `ids.py`;
    - `glyphs.py`, `layout.py` (off-map), `materialize.py`, `admin.py`, `gitsource.py`;
    - `cli.py` (`--infra-plan`, `--infra-env`, `ad2v c4`, the warning), `init.py`;
    - `extract/code/base.py` (diagnostics), `extract/code/python.py`.
  - **MCP:** `mcp/tools.py` (`ad2v_architecture`, `c4` intent, overview), `mcp/slices.py`,
    `mcp/app_tools.py`, `mcp/locate.py`.
  - **Schema:**
    - `schema/ad2v-v0.7.sql`, `schema/ir-v0.7.schema.json` (renamed from v0.6);
    - `schema/themes/{dark,light}.json` (`infra` tokens).
  - **Viewer:**
    - `src/ui/architecture.ts` (new), `src/ui/app.ts`, `src/ui/intent.ts`, `src/style.css`;
    - `src/data/{types,DataSource,LocalFileSource,RemoteSliceSource}.ts`;
    - tests and e2e (`architecture.spec.ts`, `perf-c4.spec.ts`, `app.spec.ts`), `scripts/`
      (`make_fixtures.py`, `conformance.mjs`).
  - **Fixtures:**
    - `fixtures/infra/` (gcp, aws, brownfield-es prod/dev, tofu-real, README, C4 golden);
    - `fixtures/brownfield-es` (infra, worker, settings, goldens).
  - **Tests:** `test_infra.py`, `test_unconfigured.py`, `test_envreads.py` (new); `test_brownfield`,
    `test_upgrade`, `test_mcp`, `test_tokens`, `test_quickstart`.
  - **Packaging:** `pyproject.toml` (python-hcl2, lark), `setup.py` (`ad2v.infra` + yaml).
  - **Scripts:** `scripts/determinism_check.py`.
  - **Docs:**
    - ADR-0073..0081, `docs/infra.md` (new), `docs/spec/ad2v-format-v0.7.md` (renamed + §14);
    - `docs/quickstart.md`, `docs/security.md`, `docs/dogfood.md`, `docs/dependencies.md`,
      `docs/claude-context.md`;
    - `README.md`, `issues.md`, `pending.md`, `status.md`;
    - `REPORT.md` + `docs/reports/P10.md`, `docs/reports/P10-screens/`.

**Clean-up:**
- removed: the OpenTofu binary, zip and provider cache, and the empty `terraform.d` it created;
- removed: the python-hcl2 wheel download folder, the P9 `git archive` tree, the perf temp folder
  and the scratch files;
- removed at the end: Playwright's Chromium and the npx MCP Inspector cache;
- restored: earlier phases' screenshots that the full e2e run had re-taken.
