# ad2v: context for a new Claude session

You are picking up **ad2v** after twelve phases of work (P1–P10, plus P6.1 and P8.1). This file brings you up to date:
goals, standing rules, architecture, decisions, findings, open issues, and the developer's open
questions (at the end). Read it fully before acting. Then read `status.md`, the latest
`REPORT.md`, and any ADR you need (`docs/adr/`).

Snapshot: 2026-10-08, after the P10 commit (see `git log -1`). Everything up to P9
(`8d817e3`) is on `origin/master` and `origin/main`. P10 is pushed the same way at the end of the
phase, fast-forward only (REPORT.md §11).
- Repo: `<repo-root>` (the working directory of every session; GitHub `<github-owner>/ad2v`, private).

---

## 1. What ad2v is

**Comprehension debt** builds up when agents merge code faster than people can understand it.
ad2v (agent development to viz) compares a **repository** with its **SDD specs** (spec-driven
development) and writes **one SQLite file** (`*.ad2v`, format v0.6). The file describes both sides
as one graph across a history of epochs (commits). Readers:

- the **viewer**: a three.js isometric 2.5D map (like C4 with more levels), in dark and light
  themes;
- **any MCP host's model** (Claude, ChatGPT, VS Code…) through `ad2v mcp`. Hosts with MCP Apps
  render the map inline.

Like mermaid.js, ad2v is an open **format** plus reference implementations, licensed Apache-2.0.
Version **0.7.0** (set for the first PyPI release; nothing is published yet).
Principles:

- **The LLM suggests; a human confirms.** Confirmation means editing committed files:
  `ad2v.yaml` for links, or moving a proposed spec file into the spec tree.
- **The data layer splits by origin.** Deterministic data is **normative**: structure, pairing,
  statuses, roll-ups, severity, lineage, diff and layout. LLM data is **informative**: judge,
  suggestions, summaries and narrations, with full provenance. Informative data never enters an
  epoch id.

## 2. Standing rules (the developer set these across phases; keep them)

1. **One commit per phase, at the very end.** Update `status.md` after every milestone, so an
   interrupted session can resume from it.
2. **End every phase with `REPORT.md`** at the root **and** a copy in `docs/reports/P#.md`. Move
   the previous root report to `docs/reports/` first.
3. **Every report includes an "Accrued cost per phase" table** (P1…Pn): cloud and LLM spend.
   Claude's own usage is not metered per phase; the account is on Max with extra usage disabled,
   so say so. Totals so far: P1–P3 $0, P4 $0.592 (Vertex AI, gemini-3.8-flash, 125 calls), P5 $0,
   P6 $0, P6.1 $0, P7 $0.385 (Vertex, 163 calls), P8 $0, P8.1 $0, P9 $0, P10 $0, **total $0.977**.
   Also count CI runs triggered by pushes (about 18 billed minutes each, ubuntu jobs). The developer explicitly asked for this at the end of each phase.
4. **No copyleft dependencies**, transitive ones included, on both the Python and npm sides:
   GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA, OFL-only fonts.
   - **`certifi` (MPL-2.0) is banned**, which rules out `httpx`, `requests`, provider SDKs and
     the official Python MCP SDK.
   - The npm license gate (`viewer/scripts/check-licenses.mjs`) runs in every build and must stay
     green.
   - Update `docs/dependencies.md` whenever dependencies change.
   - Tools that are run but not depended on (build, twine, pip-audit, gitleaks, actionlint, the MCP
     Inspector) run outside the tree (pipx / a throwaway venv / npx / a standalone binary) and are
     listed under "Tools run outside the tree". Never AGPL tools (e.g. trufflehog).
5. **Randomness** uses seed 987654. Layout and ordering use none. Exception: security tokens use
   `secrets` (the chat token, ADR-0057).
6. **No LLM calls and no cloud resources** unless the developer approves them for that phase.
   That includes CI minutes while the repo is private (P8: ubuntu on push/PR only; Windows/macOS on
   manual dispatch).
   P4's and P7's live runs were approved (P7: cap $2.00, project `<your-gcp-project>`, ADC only, labels
   `project=ad2v` / `ad2v_task`, STOP and ask before the first real call with static and
   calibrated estimates); P5, P6 and P6.1 had none.
7. **Never add write actions to the viewer or to MCP.** Accepting suggestions, LLM runs,
   materialize, prune and extract stay CLI steps; show the copyable command instead.
8. **Clean up at the end of a phase:** bench clones (`bench/`, gitignored), Playwright browsers
   installed only for the session (or say in the report why they were kept), npx caches of tools
   used once, and scratch files. `node_modules/` stays gitignored.
9. If context runs low, finish the current milestone, skip the rest, and mark them "not done" in
   the report.
10. **Record every decision the prompt didn't fix as an ADR.** The next number is **0082**.
11. **Environment:** Windows 11, Python 3.12 (`.venv`), Node 24 / npm 11, git; everything must be
    cross-platform. Python 3.11 is the declared minimum (CI runs it).
12. **Sanitization:** no local absolute paths, usernames, emails or the GCP project id in tracked
    files; use `<repo-root>`, `<github-owner>`, `<your-gcp-project>` (P8 M6). Write "the owner" in
    public-facing docs.
13. **Blind eval:** never open, list or grep `AD2V_BLIND_EVAL` or `fixtures/retrieval-eval/blind/`;
    never write blind questions (docs/blind-eval.md).

## 2a. Immutable decisions since P7 (from the owner, P8)

1. **Nothing is published** until the owner decides: no PyPI/TestPyPI upload, public demo, launch
   posts, repo visibility change, GitHub Pages, tags or releases, or name registration. The owner
   is signing an agreement with the employer first.
2. **Split by access:** public, Apache-2.0: core, Python extractor, TypeScript extractor (P9),
   viewer, MCP server. Private, separate repos later: a Java extractor and an "enterprise pack"
   (framework detection, audit evidence reports). Do not create those repos or private code.
3. That split relies on the **plug-in API** (P8): language extractors and framework detectors are
   plug-ins, so private ones live outside this repo without forking it.
4. The earlier P8 launch plan (PyPI release, public demo, README marketing, layout default switch)
   is cancelled; nestgrid-v2 stays behind its flag (pending.md).
    - Tooling caveat: shell heredocs have mangled backslashes and quotes several times (issues
      15, 24). For non-trivial edits, use the editor tool or a script file.

## 3. Phase history

| phase | commit | scope | outcome |
|---|---|---|---|
| P1 | `f0eb889`…`4b8dbf8` | format v0.1, SQLite schema, IR, deterministic extractors (Python code; Gherkin, OpenAPI and Markdown specs), static workflows, canonical dump, CLI, validate | determinism by canonical dump; `payments-recon` fixture with golden `expected.yaml` |
| P2 | `63718b2` | spec↔code pairing, statuses, structural drift, roll-ups, risk severity, visual tokens (light and dark); format v0.2 | token and glyph grammar specs |
| P3 | `ecb6972` | multi-epoch storage (versions + integer membership), parse cache, `history` over git, epoch diff, lineage, `stale`, entry-point recognizers, orphan policy; format v0.3 | dispatch: 1.16× size growth over 9 epochs |
| P4 | `128729b` | BYOM LLM layer (informative only): judge, link suggestions, summaries, narrations, prose-spec extraction, offline eval; format v0.4 | live Vertex run $0.592; judge accuracy 0.818, kappa 0.699 |
| P5 | `aeef69a` | viewer: deterministic layout `nestgrid-v1` (Python, persisted grids), three.js LOD map, status styling, replay, epoch diff overlay, `ad2v view` | dispatch 60 fps (Intel UHD), first render 0.86 s; 12 screenshots |
| P6 | `fe17661` | MCP server (stdlib, protocol 2026-07-28, dual-era), 13 agent tools + 20 app-only tools, map as an MCP App (`ui://ad2v/map`), deterministic retrieval + eval | Inspector 38/38; App e2e 10/10; dispatch tool p95 ≤ 37 ms |
| P6.1 | `b7e1726` | real-repo readiness: route recall, spec discovery, spec-kit/Kiro/custom presets, `ad2v specs bootstrap/review/approve`, replay camera, opaque "dim the rest", floor contrast | fixture export endpoint missing → implemented; dispatch 286/290 route paths corrected; dispatch 59.9 fps with dim |

| P7 | `27c24c6` | verified quickstart, settings prefixes, retrieval v2 (70-question eval), the viewer's own chat (`ad2v view --chat`), thinking per task, schema digests, judge roll-up, viewer UX v2, nestgrid-v2 (flag), format v0.5 | template 23 -> 0 unresolved; MRR P6-25 0.89 -> 0.98; live judge catches REQ-009 (low: acc 0.9, k 0.81, $0.0017/call); summaries -60%/call; dispatch 59.9 fps |

| P8 | `4d5740b` | extractor plug-in API (`ad2v.api` 1.0, entry points, opt-in, identity in the epoch, built-ins as plug-ins, conformance kit, out-of-tree examples), blind retrieval eval harness, packaging (0.7.0.dev0, not published), CI workflows (written, not run), security review, sanitization inventory, dogfood procedure | 9 fixture dump scenarios identical with epoch id / rules hash masked; examples pass the kit in a temp venv; wheel verified in a clean venv; 11 security fixes; 382 pytest |
| P8.1 | `d5038d5` | status `not_evaluable` for code in a language no active extractor reads (language-scope inventory, `ad2v:` comment markers, legend in the viewer), format v0.6 + upgrade | polyglot fixture; Python-only dumps unchanged except epoch id / rules hash / format version / recorded precedence; 388 pytest; first push, first CI runs (both failed: fresh-clone install, fixed in P9) |
| P9 | `git log -1` | brownfield onboarding: `ad2v init` (deterministic manifest proposal), team SDD presets `table` and `stories` (Spanish and English), Spanish EARS and Gherkin, titles, non-functional requirements, issue 95 (`component_out_of_scope`, test titles in unread languages), spec side of the map (steps off the map, scenario roll-up, `id · title` labels, word-boundary truncation), wider default excludes with SQL kept under `migrations/`, optional viewer packages (fresh-clone install) | `fixtures/brownfield-es`: zero-config 1 command (endpoints missing, 5 orphans) vs init 2 commands + 1 edit (endpoints implemented, 0 orphans); layout stability 1.0000; 428 pytest, Vitest 53, Playwright 29 |
| P10 | `git log -1` | infrastructure layer: Terraform plan JSON (`--infra-plan [ENV=]file`, format 1.x) and static `.tf` (python-hcl2, `infra_root`), secrets allowlist, the env-var bridge (`deploys`, `provides_env`, `wires`; `infra_status` deployed/undeployed/wired/unwired/in_use/infra_orphan/ambiguous per environment), a deterministic C4 view (Architecture tab, `ad2v c4` Structurizr/JSON, `ad2v_architecture`, `c4` intent), zero-config warning, test-name prefixes derived from spec ids, format v0.7 | brownfield-es: backend/frontend deployed, worker undeployed, EXPORT_BUCKET unwired, archive bucket orphan, dev differs; planted secrets absent from file and dump; 2,000-resource plan parsed in 0.14 s; dumps of no-infra fixtures unchanged after masking |

**Next, as planned by the owner:** **P11: the TypeScript extractor**, after the developer's
evaluation-project results. Do not start it without the owner's prompt. Open questions for P11
and for a later NFR-vs-infra check are in REPORT.md §10.

## 4. Architecture

### 4.1 Python (`src/ad2v/`)

- **Plug-in API (P8, ADR-0063..0065):**
  - `api.py` is the only public import surface for plug-ins (`Extractor`, `FrameworkPack`,
    `ExtractContext`, `ExtractOutput`, `FrameworkContext`, `FileAccessor`, the IR model re-exported;
    `API_VERSION = "1.0"`; accepts the current and previous major).
  - Entry-point groups **`ad2v.extractors`** and **`ad2v.frameworks`**; `plugins.py` does
    discovery (`importlib.metadata` + an internal registry of built-ins), opt-in
    (`ad2v.yaml` `extractors.enabled`, `--extractor`), identity records in the epoch rules
    (`plugins` key → `rules_hash` → epoch id), isolated runs (per-extractor graphs merged in name
    order; third-party timeouts, exception isolation, `--strict`).
  - Built-ins: `extract/code/plugin.py`: `python` 1.0.0 (`rules/python.yaml`) and
    `python-frameworks` 1.0.0 (`rules/python-frameworks.yaml` = the old `ports:` section, pack-merged;
    schema digests as its hook). Bump their `version` when output can change.
  - Conformance kit: `testing/conformance.py`, CLI `ad2v extractor check <name> --fixture <dir>`;
    `ad2v extractors list`. Examples: `examples/plugins/{routes-dsl-extractor,bottle-framework-pack}`.
  - Parse cache key: `extractor_version = name@version[:cache version]`, `rules_hash` = the
    extractor's effective rules hash.
- **Extraction:**
  - `extract/` holds the code (Python, tree-sitter) and spec (Gherkin, OpenAPI, Markdown)
    extractors; `extract/spec/presets.py` (P6.1) reads spec-kit, Kiro and custom Markdown;
  - `specroots.py` (P6.1) resolves where specs are (`--spec` > `spec_root` > auto-detect);
  - `bootstrap.py` + `cli_specs.py` (P6.1): `ad2v specs bootstrap/review/approve`;
  - `rules.py` and `extract/code/rules/python.yaml` hold the rules, hashed into `rules_hash`;
  - `manifest.py` reads the optional `ad2v.yaml`.
- **Graph, storage, statuses:**
  - `ir.py` (node and edge kinds, statuses), `ids.py` (stable ids from side, kind and qualified
    name);
  - `store.py` (SQLite, versions, epochs);
  - `pipeline.py` (extract), `history.py` / `gitsource.py` (git history via `git archive`; no
    checkout, never runs code), `materialize.py` (derived tables);
  - `pairing.py` (links and statuses), `severity.py`, `workflows.py` (traces and containment
    projection);
  - `diff.py`, `admin.py` (pin, prune, GC), `validate.py`, `dump.py`.
- **Layout:** `layout.py` (`nestgrid-v1`: nested grids, persisted `layout_grids`, 20% headroom,
  ports on the east and south edges, 765/765 boxes stable across history).
- **LLM layer:** `llm/` (providers `fake`, `vertex`, `openai_compatible` over stdlib urllib;
  `runner.py` with cache, budget and plan; tasks judge, suggest, summarize, narrate,
  extract-prose; fencing of untrusted input).
- **Blind eval (P8):** `mcp/blind.py`, `ad2v eval blind` (aggregates only; `AD2V_BLIND_EVAL`).
- **Security (P8):** `store.foreign_schema_objects` (writers and the MCP server refuse triggers /
  altered views; `trusted_schema = OFF`), `validate` size/depth/schema checks, repository-supplied
  paths contained; threat model `docs/security.md`.
- **Serving:** `view.py` (`ad2v view`: 127.0.0.1, GET/HEAD, strict CSP, Host checked on every
  request; with `--chat` also
  `/api/chat/*` behind a token, Host and Origin checks); `mcp/` (P6, below).
- **Chat (P7):** `chat/agent.py` (ChatService: turn loop, ≤ 6 steps, last step forced to
  `ad2v_answer`, citation check, budget meter, `llm_results` task `chat`), `chat/http.py`
  (security, SSE), `chat/schemas.py` (MCP schema → Vertex / OpenAI tool declarations); providers
  have `chat()` with function calling (Gemini thought signatures kept verbatim).
- **P7 extraction:** `extract/code/schema_digest.py` (SQLAlchemy / SQL DDL / Pydantic →
  `datastore.attrs.schema_digest`, `route.attrs.schema_models`); settings prefixes in
  `extract/code/python.py` (`path_constants`, opt-in Settings defaults); `upgrade.py` (v0.4 → v0.5 → v0.6).

### 4.2 The file (format v0.6; v0.4 and v0.5 readable, upgraded in place on write)

- **Column classes:** N (normative), I (informative: LLM, wall clock, pins), V (volatile line
  numbers).
- **Epochs:** content-addressed. An epoch id covers the inputs: code, specs, rules, manifest and
  test results.
- **Derived tables exist only for *materialized* epochs:** `node_status`, `status_rollup`,
  `glyphs`, `links`, `workflows`, `workflow_steps`, `workflow_step_nodes`, `layout`,
  `layout_grids`. `ad2v materialize --epochs last:N` prepares a file for history browsing.
- **LLM tables:** `llm_results` (tasks incl. `chat`), `llm_runs`, `link_judgments`,
  `judge_rollups` (v0.5), `link_suggestions`, `summaries`, `narrations`; the
  `node_status_effective` view (judged drift or a roll-up drift).
- The spec is `docs/spec/ad2v-format-v0.7.md`: §11 the LLM layer, §12 layout and viewer, §13 MCP
  and retrieval rules.

### 4.3 Viewer (`viewer/`: Vite 7, TypeScript strict, three 0.180, sql.js)

- **Data:** every query goes through `DataSource`, which has two implementations:
  - `LocalFileSource` runs sql.js over the whole file;
  - `RemoteSliceSource` (P6) calls the MCP app tools through the host bridge.
- **`scene(epoch, rootId, depth)`** returns a slice: the roots; the ancestors of the focus node
  and their children; the focus node's subtree to `depth`; and its direct neighbors with their
  ancestors.
  - The standalone viewer loads `scene(epoch, null, -1)` (the whole epoch). App mode loads
    slices and merges more on demand.
- **Rendering:** `render/scene.ts` (`MapScene`):
  - orthographic isometric camera with no rotation;
  - LOD from the on-screen footprint (8 / 40 / 160 px, hysteresis ×0.8), off-screen culling;
  - instanced glyph bodies (6–8 draw calls), screen-space ribbons for outlines, edges and
    overlays, Canvas 2D label atlas (no fonts shipped).
  - Bodies come from theme tokens (`body.neutral`, `body.tint` 0.08, `body.open_recede` 0.55)
    through `render/style.ts` `bodyColor()`, mirrored by `tokens.body_color()`; glow in the dark
    theme, halo in the light theme.
  - Replay: `frameStep()` keeps each step ≥ 90% on screen and ≥ 40 px (a ring below that);
    `setEmphasis()` + `dim.factor` 0.7 blend everything else toward the background, opaquely
    (ADR-0050, ADR-0051). A "Dim" toggle sits in the replay bar.
- **UI and builds:**
  - `ui/app.ts`: the app, in "full" and "app" modes, with replay (fine playhead, detail slider),
    diff overlay and panel cards;
  - builds: `dist/` (served by `ad2v view`, shipped in the wheel), `demo-dist/` → frozen
    `docs/reports/P5-demo.html`, and `app-dist/app.html` (the MCP App, 988 KB, no wasm, no
    network).
  - The App uses `@modelcontextprotocol/ext-apps` 2.0.3 (MIT).

### 4.4 MCP (`src/ad2v/mcp/`, P6)

- `protocol.py`: the dual-era JSON-RPC core.
  - Modern requests carry per-request `_meta`; a legacy `initialize` starts a session.
  - It serves `server/discover`, tools, resources, cancellation, `resultType` and
    `ttlMs`/`cacheScope`.
  - Logging is deprecated in 2026-07-28, so all logs go to stderr.
- Transports: `stdio.py` (reader thread plus worker thread) and `http.py` (Streamable HTTP,
  127.0.0.1, Origin and Host checks, header validation, legacy sessions).
- Files: `files.py` (`--file` or `--root`, strict containment, read-only `mode=ro` +
  `query_only`).
- Agent tools:
  - `tools.py` defines 13: `ad2v_files`, `overview`, `search`, `locate`, `get_node`,
    `neighborhood`, `status`, `links`, `risks`, `workflow`, `diff`, `show`, `llm_plan`;
  - `index.py` holds the per-epoch index (LRU);
  - `locate.py` is BM25F with kind priors, a status boost and prefix expansion; its weights
    come from the `retrieval:` rules.
  - Free text from the repository or an LLM is wrapped as `untrusted_text`.
- `app_tools.py` + `slices.py`: 20 app-only `viewer_*` tools (`_meta.ui.visibility = ["app"]`,
  listed only for clients that declare MCP Apps), mirroring `DataSource` with identical results.
- `evaluate.py`: retrieval eval and tuning.
- Run it with `python -m ad2v mcp --root <dir>` (or `--file`, or `--http`). Host setup is in
  `docs/mcp.md`.

### 4.5 Tests and gates

- `pytest`: 462 collected (460 pass + 1 cloud skip + 1 symlink skip on Windows); `-m mcp`, `-m slow`
  (the quickstart guard, which runs step 2b `ad2v init` and step 5b infra on copies of
  `fixtures/brownfield-es`). P10: `test_infra.py` (plan/static readers, planted secrets, bridge,
  C4, history), `test_unconfigured.py`, `test_envreads.py`.
- Viewer: Vitest 56; `npm run test:mcp` covers parity (incl. `c4`, `infraStatus`), Inspector
  conformance (38/38, 14 agent tools) and the App e2e (12, incl. the `c4` intent).
- Playwright: the P5 tour (2), the App (10), replay camera (2), dim (3), chat (3, against a real
  `ad2v view --chat` with the fake provider), UX v2 (2), hostile file (2, P8: no script runs in
  either viewer mode), scope (2, P8.1), spec side (4, P9: payments-recon and brownfield-es),
  architecture (2, P10; plus `perf-c4.spec.ts`, which runs only with `AD2V_C4_PERF`).
- CI (P8, written, never run): `.github/workflows/ci.yml` (ubuntu on push/PR; all OS on manual
  dispatch) and `release.yml` (disabled). Gates: `scripts/check_python_licenses.py`,
  `scripts/determinism_check.py`, npm license gate, ruff, ESLint, tsc, Vitest, conformance kit.
- ESLint, `tsc`, ruff and the license gate are all clean.
- Coverage of new modules is ≥ 90%.

## 5. Key decisions (ADR index; read the file before changing anything it covers)

- **0001–0016 (P1, P2):**
  - 0001: one SQLite file per project, determinism by canonical dump;
  - 0002: seeded tests instead of hypothesis (MPL);
  - 0003: dangling spec references go in `unresolved_refs`;
  - 0004: containers, components and ports;
  - 0005: where spec ids are defined vs. referenced;
  - 0006: the `slow_io_in_transaction` flag;
  - 0007: static resolution heuristics;
  - 0008: tooling (setuptools; hatchling rejected because of pathspec, MPL);
  - 0009 and 0013: workflow trace and containment projection, the default;
  - 0010 and 0012: rules as an epoch input, canonical `rules_hash`;
  - 0011: content-anchored behavior identity;
  - 0014: deterministic risk severity;
  - 0015: pairing details;
  - 0016: visual tokens and themes.
- **0017–0025 (P3):**
  - 0017: versioned storage;
  - 0018: parse cache;
  - 0019: test results carry forward;
  - 0020: lineage and `stale`;
  - 0021: rules-driven entry points;
  - 0022: orphan policy;
  - 0023: diff semantics;
  - 0024: prune and GC;
  - 0025: dump scope.
- **0026–0033 (P4):**
  - 0026: a callee rename doesn't change its callers;
  - 0027: BYOM over stdlib HTTP;
  - 0028: LLM storage, isolation and cache;
  - 0029: untrusted input, validated outputs;
  - 0030: task details;
  - 0031: reserved `-X` spec ids for LLM-proposed items;
  - 0032: plan, run and the budget guard;
  - 0033: fixture and live config.
- **0034–0038 (P5):**
  - 0034: layout `nestgrid-v1` in Python, persisted;
  - 0035: Vite 7 (Vite 8 pulls lightningcss, MPL), canvas labels, additive glow, the license
    gate;
  - 0036: `DataSource`, `ad2v view`, read-only;
  - 0037: presentation rules;
  - 0038: demo data, screenshots and the performance method.
- **0039–0045 (P6):**
  - 0039: MCP 2026-07-28, dual-era, stdlib;
  - 0040: MCP Apps 2026-01-26, `ui://ad2v/map`;
  - 0041: two tool surfaces, `DataSource` mirror, scene slices;
  - 0042: agent tools are compact, read-only and fenced;
  - 0043: deterministic retrieval with weights in the rules;
  - 0044: app-mode UX;
  - 0045: testing (Inspector via npx, `AppBridge` test host).
- **0046–0051 (P6.1):**
  - 0046: route recall (factories, `add_api_route`, Starlette, Flask) and `path_unresolved` →
    `needs_review`;
  - 0047: spec roots (`--spec` > `spec_root` > auto-detect), in `config_hash`;
  - 0048: SDD presets (spec-kit v1.1.0 pinned, Kiro), namespaced and sub-ids;
  - 0049: `ad2v specs bootstrap/review/approve` (CLI only; approval = moving the file);
  - 0050: replay camera (10% off-screen threshold, a deviation from the prompt's 30%);
  - 0051: opaque "dim the rest", body tokens, contrast fixes.
- **0052–0062 (P7):**
  - 0052: verified quickstart; `specs bootstrap --from` is repo-relative;
  - 0053: settings prefixes (`pairing.path_constants`, opt-in `resolve_settings_defaults`);
  - 0054: retrieval v2 (propagation, spec ids, tests factor, resource words, status order) and
    the 70-question eval protocol;
  - 0055: format v0.5 and the in-place upgrade;
  - 0056: the chat agent (server-side, in-process tools, `ad2v_answer`, grounding, budget);
  - 0057: chat endpoint security; the `secrets` exception to the seed rule;
  - 0058: thinking per task (3.8 Flash: low/medium/high only);
  - 0059: datastore schema digests (SQL files are epoch inputs);
  - 0060: judge roll-up for containers/components;
  - 0061: viewer UX v2 (labels, edge modes, portals, dashes, hidden replay steps);
  - 0062: nestgrid-v2 behind a flag (v1 stays the default).
- **0063–0065 (P8):**
  - 0063: the extractor plug-in API (api 1.0), interfaces, semver policy, conformance kit, and
    what did not fit cleanly;
  - 0064: discovery, opt-in, trust and isolation (timeouts, `--strict`);
  - 0065: plug-in identity in the epoch rules (additive within v0.5), parse-cache key, GC.
- **0066 (P8.1):** `not_evaluable` and the language-scope inventory; format v0.6.
- **0073–0081 (P10):**
  - 0073: zero-config warning (meta.unconfigured_warnings, banner) and test-name prefixes derived
    from spec ids (config identity);
  - 0074: infra from a plan JSON (never run terraform), typing by `infra.yaml` (in the rules),
    carry-forward, `change_kind: infra`;
  - 0075: static `.tf` fallback with python-hcl2, `infra_root`, limits, plan wins / gap fill;
  - 0076: secrets policy (allowlist, env var sources only, planted-secrets test);
  - 0077: format v0.7 (infra side, edges, `epochs.infra_hash`, upgrade 0.6 → 0.7);
  - 0078: `infra_status` is a separate dimension (not in the 10-status precedence);
  - 0079: the C4 view (derived, slot-persistent layout, Structurizr export, MCP);
  - 0080: the env-var bridge (env reads, deploys priorities, website buckets as static hosts);
  - 0081: `init` for infra (infra_root, plan command + warning, deploys placeholders).
- **0067–0072 (P9):**
  - 0067: viewer packages optional in a source install (`setup.py`), required for release builds
    (`AD2V_REQUIRE_VIEWER=1`);
  - 0068: wider default excludes; `migrations/` and `alembic/` are code-only excludes (SQL kept);
    IaC is not `not_evaluable`;
  - 0069: presets `table` and `stories`, Spanish EARS and Gherkin, titles, non-functional
    requirements;
  - 0070: issue 95, `component_out_of_scope` and test titles in unread languages (never verified);
  - 0071: `ad2v init` (deterministic, writes only with `--write`, `--check`), `sdd/` auto-detect;
  - 0072: spec side of the map (`OFF_MAP_KINDS`, scenario roll-up `via_spec_ref`, labels,
    word-boundary truncation).

## 6. Findings worth knowing

- **Performance:**
  - Dispatch (`dd2837e`; 717 files, 84k lines, 5,374 nodes) extracts in 5–8 s.
  - The viewer runs at 60 fps (59.9 median with dim on, P6.1) and first renders in 0.86 s (P5)
    / 1.2 s (P6.1, issue 73).
  - MCP tool p95 is ≤ 37 ms (warm) and cold start is 0.31 s.
  - App first render is 1.10 s; BM25 build 0.33 s (it was 3.35 s before batching one SQL query
    and memoizing the stemmer).
- **Retrieval eval:** 25 questions, 8 held out (`fixtures/payments-recon/expected-questions.yaml`).
  - Final scores with tools: recall@5 0.95, MRR 0.89, nDCG@5 0.88. Held out: 0.92 / 0.75 / 0.77.
  - Most of the gain came from structural fixes: prefix expansion, stemmed status words and an
    endpoint intent.
  - Weight tuning slightly overfit (held-out MRR −0.1, about one rank). It was kept per the
    procedure and reported.
- **LLM (P4):**
  - Reasoning tokens made output about 2–3× the static estimate, so the plan now calibrates
    after the first call.
  - The judge missed a planted drift (REQ-009) for lack of context about callers and data shapes.
- **Viewer UX:**
  - Dispatch's layout is sparse: big empty slabs at the top level and an edge hairball.
  - Very long dashed edges alias into a cross-hatch.
  - Labels collide in dense modules.
  - Portal chips overlap.
  - Replay camera and dimming were fixed in P6.1. The published P5 demo had drawn dark-theme
    bodies in the light theme (issue 72).
- **Real repos (P6.1):**
  - full-stack-fastapi-template: all 23 routes `path_unresolved` (prefix
    `settings.API_V1_STR`); tails correct.
  - dispatch: 290 routes, 286 paths corrected to `/api/v1/{organization}/…`.
- **P7 (live):** the judge at thinking `low` beat `default` (accuracy 0.9 vs 0.8, κ 0.81 vs
  0.64) at 29% of the cost; both caught REQ-009 thanks to the schema digest. Summaries and
  narrations at `low` cost ~60% less per call, and output came in under the static estimate
  (0.48× / 0.90×). The chat's first live run hit the step cap (fixed: forced last step).
- **Retrieval:** structural changes did most of the work; on real code, tests and migrations
  still crowd out app code (issue 79).
- **Licenses:**
  - npm has 166 packages (MIT 131, Apache-2.0 18, ISC 7, BSD 9, BlueOak 1).
  - The MCP Inspector can't be a dependency (its tree includes lightningcss, MPL), so it runs via
    `npx`.

- **P8:** the refactor changed no normative output (only epoch ids / rules hashes, which now
  carry plug-in identity); a P7 file gets one new `rules` epoch on its next extraction. The
  `ad2v.chat` package had been missing from the wheel since P7 (fixed). A repository's own
  `ad2v.yaml` could make ad2v read outside the repo (fixed). Blind retrieval: harness only; the
  owner supplies the questions.

## 7. Open issues (from `issues.md`; numbers refer to it)

- **Extractor recall:**
  - #4: `io_in_loop` recall is unmeasured.
  - #5: clients stored on `self` are not tracked.
  - #8: f-string URLs are named by their literal prefix only.
  - #10: duplicate definitions; the first one wins.
  - #32: nested loops over the same IO are both flagged.
  - #33: incremental speed-up is bounded (≈ 0.5×).
- **LLM:**
  - #41: plan estimates need per-model calibration.
  - #80: the judge misses "partial" when the gap is in the return shape (REQ-006).
  - #81: bootstrap omits statements now and then; the review step catches it.
- **Viewer:**
  - #82: default layout (nestgrid-v2 is denser on dispatch, less on the fixture); single-child
    chains should collapse.
  - #73: first render 1.31 s with v1 vs 0.87 s with v2 (follows the world extent).
- **MCP:**
  - #66: app-mode cards count only the loaded slice.
  - #78: in-process `ad2v_locate` p95 72 ms (within target).
  - #79: tests and migrations outrank app code on real repos.
  - Not implemented: `subscriptions/listen`; a web-host sandbox-proxy test; any remote deployment
    (out of scope, with a checklist in `docs/mcp.md`).
- **Plug-ins / security (P8):** #89 core rules still in `python.yaml`; #90 no tree-level framework
  hook; #91 the viewer does not check a file's schema before querying; #92 `braces` advisory in the
  build chain; #93 actionlint / gitleaks not run yet.
- **Language support:** code extraction is **Python only** (TypeScript is P9, as a plug-in). Since
  P8.1, code in other languages is inventoried (`ad2v.scope`) and shown as **`not_evaluable`**
  (dotted, hollow, thin, "∅" badge; Legend in the viewer); `// ad2v: REQ-001` comments link it.
  Since P9 (#95 closed), requirements under a component mapped to unread code are
  `not_evaluable` (`component_out_of_scope`), and test titles in unread files (`it("RF-008 …")`)
  are references (never verified). P9 issues: #97 (fixed), #98–#102 (pre-P9 files keep step
  layout rows; heuristic titles; IaC not mapped; init depth ≤ 3).

## 8. How inputs are found (P6.1, P7)

`ad2v extract --repo <code dir> [--spec <dir> ...] [--manifest ad2v.yaml] [--infra-plan [ENV=]plan.json ...] --out x.ad2v`.
No folder layout is required.

- **Infra (P10, docs/infra.md):** plan JSON per environment (the human runs terraform; ad2v never
  does) and/or `.tf` under `infra_root` (static, python-hcl2). Infra nodes form a third side
  (`infra`), off the map; findings are `infra_status` per environment; the Architecture tab and
  `ad2v c4` show the derived C4 view. Only allowlisted attributes and env var *names* are stored.
- **Zero config (P10):** `extract` without a manifest warns (unresolved route prefixes, fallback
  container, derived test prefixes, IaC) and recommends `ad2v init`; spec id prefixes are added
  to the test-name prefixes automatically.

- **Code:** every `*.py` under `--repo`, minus `exclude` globs (defaults plus `ad2v.yaml`), minus
  the spec roots.
- **Spec roots** (ADR-0047): `--spec` (repeatable) > `spec_root` in ad2v.yaml (str or list) >
  auto-detect (`specs/`, `spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`, `docs/sdd/`, root
  `openapi.*`). On an existing repository, start with **`ad2v init --repo <path>`** (P9): it
  finds spec folders by content, containers, prefixes, excludes, SQL, IaC and unresolved route
  prefixes, and prints a proposed manifest (`--write <file>`, `--check <file>`, `--format json`).
  `--no-spec-autodetect` disables it. `extract` and `history` print the roots and their source.
  `project/` with `project/specs/` and no flags → "spec roots (auto-detected): specs/".
- **Spec files:** Gherkin, OpenAPI 3, and Markdown read with one preset each (ADR-0048): the ad2v
  convention, spec-kit (`<feature>:FR-001`), Kiro (`ORDEREXPORT-1`, `ORDEREXPORT-1.2`),
  `table` (requirement tables, Spanish or English headers, P9), `stories` (`HU-001`, criteria
  `HU-001.1`, P9), or `custom` regexes from `spec_markdown` rules. EARS and Gherkin are read in
  Spanish too. Spec items get `attrs.title`; `RNF`/`NFR`/`NF` ids are non-functional. Markdown with no recognized structure stays a
  `spec_doc` with prose.
- **Prose without a convention** (ADR-0049): `ad2v specs bootstrap --from <paths> --plan`, then
  `--yes --max-cost-usd N` (real model calls; P6.1 tested with `fake` only), `ad2v specs review`,
  `ad2v specs approve <file>`. Proposals use `-X` ids in `<spec root>/.ad2v-extracted/`.
- **SQL DDL** (`*.sql`) is read for schema digests and is an epoch input (P7).
- **`ad2v.yaml`** optionally sets: `system`, `containers`, `exclude`, `spec_root`,
  `spec_markdown`, `spec_ids` (`test_name_prefixes`, `nonfunctional_prefixes`), `pairing` (incl. `orphan_policy`,
  `path_constants`, `resolve_settings_defaults`), `rules_overlay`, `workflows`, `llm` (incl.
  `tasks.<task>.thinking`, `output_language: auto`).

## 9. Where things are

- Reports: `REPORT.md` (P10), `docs/reports/P1.md`–`P6.md`, `P6.1.md`, `P7.md`, `P8.md` (P8 + P8.1),
  `P9.md`, `P10.md`. Infra: `docs/infra.md`.
- Screenshots: `docs/reports/P5-screens/`, `P6-screens/`, `P6.1-screens/`, `P7-screens/`,
  `P8.1-screens/`, `P9-screens/`, `P10-screens/`.
- Demo: `docs/reports/P5-demo.html`, rebuilt in P7 with the current viewer.
- Tracking: `status.md`, `issues.md`, `pending.md`.
- Docs: `docs/adr/`, `docs/spec/`, `docs/dependencies.md`, `docs/mcp.md`,
  `docs/quickstart.md` (verified; `tests/test_quickstart.py` guards it), `docs/plugins.md`,
  `docs/security.md` + `SECURITY.md`, `docs/blind-eval.md`, `docs/dogfood.md`,
  `docs/RELEASING.md` (not for now).
- Fixtures: `fixtures/payments-recon/` (code, `specs/`, goldens, `expected-questions.yaml`),
  `fixtures/sdd-presets/{spec-kit,kiro,custom,table,stories}` (+ `expected-questions.yaml`),
  `fixtures/polyglot/` (Python API + TypeScript client, P8.1/P9), `fixtures/brownfield-es/`
  (P9: Spanish SDD in `sdd/`, FastAPI backend under a settings prefix, TypeScript frontend,
  SQL, Terraform; goldens `expected-init.txt` and `expected.yaml`),
  `fixtures/retrieval-eval/fastapi-template.yaml` (questions only; the clone is not shipped). The viewer demo file
  `viewer/tests/fixtures/demo.ad2v` is gitignored; build it with `npm run fixtures`.

## 10. The developer's questions from P6, and what P6.1 did

1. **Invisible element in replay:** the camera never zoomed out, and body colors were low
   contrast. Fixed: `frameStep` (ADR-0050), body tokens and contrast tests (ADR-0051).
2. **Alpha channels:** not used. "Dim the rest" is an opaque blend toward the background
   (factor 0.7), with no sorting problems and no fps cost on dispatch (ADR-0051).
3. **Folder structure:** none is required. Spec roots are auto-detected or configured
   (ADR-0047), and spec-kit, Kiro and custom Markdown are read (ADR-0048).
4. **`project/` + `project/specs/`:** works with no flags (tested).
5. **Markdown without the convention:** use a preset or a custom regex; otherwise
   `ad2v specs bootstrap` proposes convention files for human approval (ADR-0049).

P7 answered the remaining questions: the viewer now has its own chat (`ad2v view --chat`),
FastAPI settings prefixes resolve, and the quickstart is verified.

P9 made ad2v usable on an existing project: `ad2v init`, Spanish team formats, and a readable
spec side of the map. P10 added infrastructure: Terraform read without running it, the env-var
bridge between code and deployments, and the Architecture (C4) tab. Next is **P11 (the
TypeScript extractor)**, after the developer's evaluation-project results. Do not start it
without the owner's prompt.
