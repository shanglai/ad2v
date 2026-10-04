# P6.1 report: real-repo readiness

All seven milestones are done. One commit (hash: see `git log -1`), not pushed. Version stays
0.6.0.

## 1. Accrued cost per phase

| phase | cloud / LLM spend | notes |
|---|---|---|
| P1 | $0 | local only |
| P2 | $0 | local only |
| P3 | $0 | local only |
| P4 | $0.592 | Vertex AI, gemini-3.8-flash, 125 calls (the approved live run) |
| P5 | $0 | local only |
| P6 | $0 | local only |
| **P6.1** | **$0** | no LLM calls, no cloud resources; the bootstrap used the `fake` provider |
| **total** | **$0.592** | |

Claude's own usage is not metered per phase. The account is on the Max plan with extra usage
disabled, so this phase had no Claude cost beyond the subscription.

## 2. Milestones

| # | scope | result |
|---|---|---|
| M1 | route recall | factories, `add_api_route`/`add_url_rule`/`add_route`, Starlette `Route`/`Mount`/`app.mount`, include chains with prefixes; `path_unresolved` → `needs_review` |
| M2 | spec discovery | `--spec` (repeatable) > `spec_root` > auto-detect; printed; in `config_hash` |
| M3 | SDD presets | spec-kit, Kiro, custom (plus ad2v); namespaced and sub-ids; ambiguous refs → `needs_review` |
| M4 | `ad2v specs bootstrap/review/approve` | CLI only, `--yes` required, `-X` ids, staleness and clash checks; fake provider |
| M5 | replay camera | `frameStep`: every step ≥ 90% on screen and ≥ 40 px, in both themes |
| M6 | dim the rest, contrast, perf | opaque blend (0.7), Dim toggle, body tokens, all contrast pairs ≥ 3:1; dispatch 59.9 fps |
| M7 | docs | 6 ADRs, README, format and convention specs, quickstart draft, issues, pending, claude-context |

Changed files, grouped:

- **Extractor:**
  - `src/ad2v/extract/code/python.py`, `rules/python.yaml`, `python_local.py` (version
    `python-local-3`);
  - `src/ad2v/extract/spec/presets.py` (new), `extract/spec/__init__.py`, `markdown.py`;
  - `src/ad2v/ids.py`.
- **Pipeline:** `pipeline.py`, `pairing.py`, `specroots.py` (new), `manifest.py`, `gitsource.py`,
  `cli.py`, `cli_specs.py` (new), `bootstrap.py` (new), `llm/prose.py`, `llm/api.py`,
  `tokens.py`.
- **Viewer:** `render/scene.ts`, `render/billboards.ts`, `render/style.ts`, `ui/app.ts`,
  `style.css`; e2e `replay-camera.spec.ts` and `dim.spec.ts` (new); `tests/theme.test.ts`.
- **Themes:** `schema/themes/{dark,light}.json` (`body.*`, `dim.factor`, `replay.highlight`, two
  stroke tokens and the dark edge).
- **Fixtures:**
  - `fixtures/payments-recon/api/recon_api/factory.py` (new), `specs/openapi.yaml`,
    `expected.yaml`;
  - `fixtures/sdd-presets/{spec-kit,kiro,custom}` (new, with goldens).
- **Tests:**
  - new: `test_routes_p61.py` (5), `test_specroots.py` (5), `test_presets.py` (9),
    `test_bootstrap.py` (3);
  - updated: `test_tokens.py` (+2), `test_llm.py`, `test_p3_units.py`,
    `llm_recordings/suggest.json`.
- **Docs:**
  - ADR-0046 to ADR-0051;
  - `README.md`, `docs/spec/ad2v-format-v0.4.md` §3.6, `docs/spec/spec-markdown-convention.md`
    §6–8;
  - `docs/quickstart-draft.md`, `docs/dependencies.md`, `docs/claude-context.md`;
  - `issues.md`, `pending.md`, `status.md`;
  - `docs/reports/P6.1-screens/`, and `docs/reports/P5-demo.html` (rebuilt).

Gates, all green:
- pytest 266 passed;
- ruff check and format;
- Vitest 39, ESLint, `tsc`;
- `build`, `build:app` (993 KB, no wasm), `build:demo`, and the license gate;
- `npm run test:mcp`: parity, Inspector 38/38, App e2e 10/10;
- Playwright: P5 tour 2/2, replay camera 2/2, dim 3/3;
- determinism: the payments-recon dump, and the preset dumps with LF and CRLF+BOM inputs.

Coverage of new modules: specroots 97%, presets 94%, bootstrap 95%, cli_specs 91%.

## 3. Route recall

**Fixture.** `factory.py` adds `GET /reconciliations/{run_id}/export` through
`create_app()` → `runs.add_api_route(...)` → `app.include_router(runs, prefix=RUNS_PREFIX)`, with
an f-string prefix.

| | http routes | export endpoint |
|---|---|---|
| P6 extractor | 6 | `missing` |
| P6.1 | 7 | `implemented` |

`container:api` roll-up: drift 1, implemented 10, needs_review 2, none 27, orphan 3, verified 8.

**Bench** (shallow clones, deleted afterwards):

| repo | routes before → after | paths changed | `path_unresolved` |
|---|---|---|---|
| full-stack-fastapi-template `cb740b6` | 23 → 23 | 0 | **23** |
| Netflix/dispatch `dd2837e` | 290 → 290 | **286** | 0 |

- **Template.** Every router is included under `settings.API_V1_STR`, a pydantic
  `BaseSettings` default that the environment can override. ad2v keeps the correct tail and flags
  the route; it does not guess the prefix (ADR-0046, issue 70). Five sampled, all correctly
  flagged with the right tail:
  - `GET /items`, `POST /items`, `PUT /items/{id}`;
  - `POST /private/users`, `GET /users/me`.
- **Dispatch.** P6 dropped the including router's own `prefix=` and ignored `app.mount("/api/v1",
  …)`, so 286 paths lacked `/api/v1/{organization}`. Five sampled, all correct against the
  source:
  - `GET /api/v1/{organization}/case_severities/{case_severity_id}` → `get_case_severity`;
  - `POST /api/v1/{organization}/incident_costs` → `create_incident_cost`;
  - `GET /api/v1/{organization}/incident_types` → `get_incident_types`;
  - `POST /api/v1/{organization}/entity_type/{case_id}` → `create_entity_type_with_case`;
  - `GET /api/v1/{organization}/search` → `search`.
- **Unchanged on dispatch.**
  - Four `/slack/*` routes are attached at runtime by a plugin loop
    (`install_plugin_events(api_router)`), so they keep the bare decorator path, unflagged.
    This is new issue 76.
  - The organization and healthcheck routes were already right.
- **`path_unresolved` cases** in tests:
  - an unfoldable prefix pairs as `needs_review` with evidence `unresolved_route_path`;
  - a partially folded f-string keeps the known tail.
  Neither ever becomes `implemented`.

## 4. Spec discovery

Order (ADR-0047):
1. `--spec`, repeatable: given but absent is an error, with no fallback.
2. `spec_root` in `ad2v.yaml`, a string or a list.
3. Auto-detection: the first of `specs/`, `spec/`, `docs/specs/`, `.kiro/specs/` that holds a
   recognized file, plus a root `openapi.*`.

`--no-spec-autodetect` turns auto-detection off.

What auto-detection found:
- `project/` + `project/specs/` with no flags → `spec roots (auto-detected): specs/`. The specs
  are not scanned as code.
- The Kiro fixture → `.kiro/specs`.
- The spec-kit fixture → `specs`.
- A repository with only prose → no spec root and coverage `none`, with a hint to use
  `ad2v specs bootstrap`.

## 5. Presets

Pinned sources (ADR-0048):
- **spec-kit**: github/spec-kit `ae5ade7234be5cb1d975f736c4e06dd46d1326d6` (v1.1.0),
  `templates/spec-template.md`.
- **Kiro**: kiro.dev/docs/specs (2026-10-02) and feature-specs (2026-08-04), checked against
  sebsto/wispr, crawlab-team/artipub and evrignaud/fim.

| fixture | preset | parsed |
|---|---|---|
| `sdd-presets/spec-kit` (2 features) | spec-kit | 2 docs, 2 components, 6 requirements (incl. `SC-001`), 3 scenarios, 9 steps |
| `sdd-presets/kiro` (`order-export`) | kiro | 1 doc, 1 component, 7 requirements (2 + 5 criteria) |
| `sdd-presets/custom` (`billing.md`) | custom | 1 doc, 2 components, 3 requirements; `skipped_ids: [bill-4]` |

Id scheme, with examples:
- spec-kit is namespaced by the feature folder: `001-payments:FR-002` is `implemented` through an
  exact `# ad2v: 001-payments:FR-002`.
- `002-refunds:FR-002` is `implemented` through the test name `test_refunds_fr_002_…`; the
  words before the prefix narrow the namespace.
- Kiro ids are synthesized: `ORDEREXPORT-1` (Requirement 1) and `ORDEREXPORT-1.2` (its second
  criterion, `ears: event`).
- `001-auth` would become `K001AUTH`. Collisions get `AUTH`, `AUTH2`.
- **The ambiguous case:** a bare `# ad2v: FR-001` matches both `001-payments:FR-001` and
  `002-refunds:FR-001`. Both links are `needs_review` with evidence `ambiguous_spec_ref`, which
  lists the two candidates. Nothing is guessed.

The output is the same with CRLF line endings and a BOM (tested for all three fixtures).

## 6. Bootstrap transcript (fake provider; trimmed)

```text
$ ad2v specs bootstrap --from docs --plan --provider fake --replay-dir ../demo-rec
spec root: specs
  yes  docs/NOTES.md  (free prose)
  no   docs/short.md  (too little prose (19 chars))
plan (no calls made): 1 call(s) (0 cached), ~492 input / ~1500 output tokens, unpriced (set llm.pricing)
run it with --yes --max-cost-usd <cap>

$ ad2v specs bootstrap --from docs --yes --max-cost-usd 0.10 --provider fake --replay-dir ../demo-rec
run: 1 call(s), $0.0000
  proposed .ad2v-extracted/notes.md  <- docs/NOTES.md
review with `ad2v specs review`, then approve with `ad2v specs approve <proposal>`

$ ad2v specs review
.ad2v-extracted/notes.md  <- docs/NOTES.md [0d7666958223]  current
  model fake-1; 2 component(s), 2 requirement(s)
  overlap 0.55: REQ-X001 ~ REQ-001

$ ad2v specs approve notes.md
approved: moved to specs/notes.md. Re-extract to parse it.

$ ad2v extract --repo . --out ../demo.ad2v
spec roots (auto-detected): specs/
...
$ ad2v status ../demo.ad2v --side spec
implemented  spec  requirement     REQ-X001        link:implemented(app/export.py::export_unmatched)
specified    spec  requirement     REQ-001         link:specified
```

Without `--yes` the command exits with code 2. `approve` refuses a stale proposal (the source
hash changed), an existing destination, and an id clash.

## 7. Viewer

**Camera rule** (ADR-0050):
- fit when the step covers more than 80% of the view, or less than 90% of it is inside;
- otherwise zoom toward 40 px, capped by the parent;
- otherwise pan.
- A step still under 40 px gets a ring of at least 44 px.

e2e, POST /v1/reconciliations; dark and light are identical:

| level | step | inside | smaller side (px) |
|---|---|---|---|
| 1 | 1–6 | 1.00 | 225.7 / 348.6 (alternating) |
| 2 | 1 | 1.00 | 44.0 (port, ring) |
| 2 | 2–7 | 1.00 | 415.7, 413.1, 159.0, 413.1, 159.0, 413.1 |

**Dim** (ADR-0051):
- `dim.factor` 0.7 blends toward the background, opaquely.
- The step, its contents and its containers stay at full color.
- The Dim toggle is in the replay bar, on by default.
- e2e: dimmed > 0 and the step is never dimmed at both levels; toggling off gives 0 dimmed;
  stopping the replay clears it.

Contrast (WCAG non-text, ≥ 3:1), worst case over all statuses:

| pair | dark P6 → P6.1 | light P6 → P6.1 |
|---|---|---|
| status stroke on its own body | 2.11 → **3.75** | 2.43 → **3.50** |
| status stroke on an open floor | 2.73 → **4.13** | 2.87 → **3.87** |
| edge on an open floor | 2.11 → **5.19** | 2.97 → **3.98** |
| step highlight on dimmed neighbors | — → **3.57** | 1.35 (halo) → **4.65** |
| status stroke on a dimmed floor | — → **5.36** | — → **4.08** |

Token changes:
- dark `edge`: #6E7D94 → #97A5BA;
- `status.none`: dark #6B7689 → #8792A6, light #7D8799 → #6E788A;
- new: `body.*`, `dim.factor`, `replay.highlight`.

The P6 numbers use P6's hard-coded bodies.

**Screenshots** (`docs/reports/P6.1-screens/`):
- `{dark,light}-replay-level{1,2}-dim.png`;
- `{dark,light}-app-path-dim.png`;
- `{dark,light}-tour-replay-two-levels.png`;
- `light-open-floor-before.png` and `light-open-floor-after.png`. "Before" is the published P5
  demo, which drew dark-theme bodies in the light theme (issue 72).

**Performance** on dispatch (ADR-0038 method): headless Chromium, ANGLE D3D11 on an Intel UHD
GPU, `ad2v view`.

| run | median fps | p5 fps |
|---|---|---|
| pan+zoom 10 s | 59.9 | 59.5 / 29.9 / 30 (3 runs) |
| replay stepping, dim on, 8 s | 59.9 | 30 when first, 59.5 when second |
| replay stepping, dim off, 8 s | 59.9 | 30 when first, 59.5 when second |

- The p5 dip follows run order, not dimming (issue 74).
- Draw calls are 6–7.
- First render: 1.17–1.22 s (target < 3 s; P5 measured 0.86 s, issue 73).

## 8. Deviations, issues, and the P7 plan

**Deviations:**
- ADR-0046: the fixture gains a new export endpoint instead of moving approve, to keep the P3
  history story. pydantic Settings defaults are not resolved.
- ADR-0048: spec-kit `SC-###` are parsed as requirements (issue 75).
- ADR-0050: the off-screen threshold is 10%, not 30%, so it agrees with the ≥ 90%-inside
  acceptance test.
- ADR-0051:
  - the replay highlight got its own token (the light halo failed contrast);
  - two status tokens and the dark edge changed.
- The demo `docs/reports/P5-demo.html` was rebuilt with the P6.1 viewer.

**Issues:**
- Closed: 7 (app factories) and 22 (factory routes show `missing`).
- Fixed in passing: 72 (dark bodies in the light demo).
- New and open:
  - 70: settings prefixes;
  - 71: an invisible replay step highlights its ancestor;
  - 73: first render 1.2 s;
  - 74: first-replay p5 dip;
  - 75: SC as requirements, accepted;
  - 76: routers never included statically.

**What changes the P7 plan:**
- `pending.md` has a new "After P6.1" list:
  - an opt-in Settings resolver;
  - Kiro `design.md`/`tasks.md` and spec-kit `plan.md`/`tasks.md` (as `implements` edges);
  - Markdown tables;
  - test-name sub-ids;
  - issue 76.
- The P7 chat agent can call `ad2v specs` only as a shown CLI command (ADR-0049 keeps writes in
  the CLI).

**Cleanup:**
- deleted: `bench/` clones, the P6 worktree, scratch scripts, `viewer/test-results`;
- deleted: the Playwright Chromium installed for this session (in `%LOCALAPPDATA%\ms-playwright`);
- the npx cache of the MCP Inspector, used by `test:mcp`, was removed afterwards.
