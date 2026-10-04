# ad2v: context for a new Claude session

You are picking up **ad2v** after seven phases of work (P1–P6.1). This file brings you up to date:
goals, standing rules, architecture, decisions, findings, open issues, and the developer's open
questions (at the end). Read it fully before acting. Then read `status.md`, the latest
`REPORT.md`, and any ADR you need (`docs/adr/`).

Snapshot: 2026-10-03, after the P6.1 commit (see `git log -1`). P6 (`fe17661`) is pushed to
`origin/master`; P6.1 is committed locally and not pushed.
- Repo: `C:\Users\David\Documents\projects\agents\ad2v` (GitHub `shanglai/ad2v`).
- `origin/main` still holds only the initial commit. All work is on `master`.

---

## 1. What ad2v is

**Comprehension debt** builds up when agents merge code faster than people can understand it.
ad2v (agent development to viz) compares a **repository** with its **SDD specs** (spec-driven
development) and writes **one SQLite file** (`*.ad2v`, format v0.4). The file describes both sides
as one graph across a history of epochs (commits). Readers:

- the **viewer**: a three.js isometric 2.5D map (like C4 with more levels), in dark and light
  themes;
- **any MCP host's model** (Claude, ChatGPT, VS Code…) through `ad2v mcp`. Hosts with MCP Apps
  render the map inline.

Like mermaid.js, ad2v is an open **format** plus reference implementations, licensed Apache-2.0.
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
   P6 $0, P6.1 $0, **total $0.592**. The developer explicitly asked for this at the end of each phase.
4. **No copyleft dependencies**, transitive ones included, on both the Python and npm sides:
   GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA, OFL-only fonts.
   - **`certifi` (MPL-2.0) is banned**, which rules out `httpx`, `requests`, provider SDKs and
     the official Python MCP SDK.
   - The npm license gate (`viewer/scripts/check-licenses.mjs`) runs in every build and must stay
     green.
   - Update `docs/dependencies.md` whenever dependencies change.
5. **Randomness** uses seed 987654. Layout and ordering use none.
6. **No LLM calls and no cloud resources** unless the developer approves them for that phase.
   P4's live run was approved; P5, P6 and P6.1 had none (P6.1's bootstrap uses the `fake`
   provider only).
7. **Never add write actions to the viewer or to MCP.** Accepting suggestions, LLM runs,
   materialize, prune and extract stay CLI steps; show the copyable command instead.
8. **Clean up at the end of a phase:** bench clones (`bench/`, gitignored), Playwright browsers
   installed only for the session (or say in the report why they were kept), npx caches of tools
   used once, and scratch files. `node_modules/` stays gitignored.
9. If context runs low, finish the current milestone, skip the rest, and mark them "not done" in
   the report.
10. **Record every decision the prompt didn't fix as an ADR.** The next number is **0052**.
11. **Environment:** Windows 11, Python 3.12 (`.venv`), Node 24 / npm 11, git; everything must be
    cross-platform.
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
| P6.1 | `git log -1` | real-repo readiness: route recall, spec discovery, spec-kit/Kiro/custom presets, `ad2v specs bootstrap/review/approve`, replay camera, opaque "dim the rest", floor contrast | fixture export endpoint missing → implemented; dispatch 286/290 route paths corrected; dispatch 59.9 fps with dim |

**Next, as planned by the developer:**
- **P7:** the standalone viewer's own chat agent (BYOM), LLM refinements (reasoning budget, judge
  gaps), and viewer UX v2 (denser layout, edge bundling, labels).
- **P8:** open-source launch preparation.

## 4. Architecture

### 4.1 Python (`src/ad2v/`)

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
- **Serving:** `view.py` (`ad2v view`: 127.0.0.1, GET/HEAD, strict CSP); `mcp/` (P6, below).

### 4.2 The file (format v0.4)

- **Column classes:** N (normative), I (informative: LLM, wall clock, pins), V (volatile line
  numbers).
- **Epochs:** content-addressed. An epoch id covers the inputs: code, specs, rules, manifest and
  test results.
- **Derived tables exist only for *materialized* epochs:** `node_status`, `status_rollup`,
  `glyphs`, `links`, `workflows`, `workflow_steps`, `workflow_step_nodes`, `layout`,
  `layout_grids`. `ad2v materialize --epochs last:N` prepares a file for history browsing.
- **LLM tables:** `llm_results`, `llm_runs`, `link_judgments`, `link_suggestions`, `summaries`,
  `narrations`; the `node_status_effective` view.
- The spec is `docs/spec/ad2v-format-v0.4.md`: §11 the LLM layer, §12 layout and viewer, §13 MCP
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

- `pytest`: 266 tests (`-m mcp`: 25).
- Viewer: Vitest 39 (incl. contrast checks); `npm run test:mcp` covers parity, Inspector
  conformance and the App e2e.
- Playwright: the P5 tour (2), the App (10), replay camera (2), dim (3).
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
- **Licenses:**
  - npm has 166 packages (MIT 131, Apache-2.0 18, ISC 7, BSD 9, BlueOak 1).
  - The MCP Inspector can't be a dependency (its tree includes lightningcss, MPL), so it runs via
    `npx`.

## 7. Open issues (from `issues.md`; numbers refer to it)

- **Extractor recall:**
  - #4: `io_in_loop` recall is unmeasured.
  - #5: clients stored on `self` are not tracked.
  - #70: routes under a `settings.*` prefix are `path_unresolved` (pair as `needs_review`).
  - #8: f-string URLs are named by their literal prefix only.
  - #10: duplicate definitions; the first one wins.
  - #32: nested loops over the same IO are both flagged.
  - #33: incremental speed-up is bounded (≈ 0.5×).
- **LLM:**
  - #41: plan estimates need per-model calibration.
  - #42: richer judge slices (callers, data shapes).
  - #43: container and component links are judged on a digest only.
- **Viewer:**
  - #54: sparse layout on big repos; a `nestgrid-v2` (shelf or squarified packing, same
    slot-stability rule) is wanted.
  - #55: dash aliasing.
  - Edge bundling, label collisions, overlapping portal chips.
  - #71: a replay step not visible at the current LOD highlights its ancestor; #73 first render
    1.2 s; #74 first-replay p5 dip.
- **MCP:**
  - #66: app-mode cards count only the loaded slice.
  - #67: `ad2v_status` sorts by name, not specificity.
  - #68: the question set is too small to tune on.
  - Not implemented: `subscriptions/listen`; a web-host sandbox-proxy test; any remote deployment
    (out of scope, with a checklist in `docs/mcp.md`).
- **Language support:** code extraction is **Python only**.

## 8. How inputs are found (P6.1)

`ad2v extract --repo <code dir> [--spec <dir> ...] [--manifest ad2v.yaml] --out x.ad2v`.
No folder layout is required.

- **Code:** every `*.py` under `--repo`, minus `exclude` globs (defaults plus `ad2v.yaml`), minus
  the spec roots.
- **Spec roots** (ADR-0047): `--spec` (repeatable) > `spec_root` in ad2v.yaml (str or list) >
  auto-detect (`specs/`, `spec/`, `docs/specs/`, `.kiro/specs/`, root `openapi.*`).
  `--no-spec-autodetect` disables it. `extract` and `history` print the roots and their source.
  `project/` with `project/specs/` and no flags → "spec roots (auto-detected): specs/".
- **Spec files:** Gherkin, OpenAPI 3, and Markdown read with one preset each (ADR-0048): the ad2v
  convention, spec-kit (`<feature>:FR-001`), Kiro (`ORDEREXPORT-1`, `ORDEREXPORT-1.2`), or
  `custom` regexes from `spec_markdown` rules. Markdown with no recognized structure stays a
  `spec_doc` with prose.
- **Prose without a convention** (ADR-0049): `ad2v specs bootstrap --from <paths> --plan`, then
  `--yes --max-cost-usd N` (real model calls; P6.1 tested with `fake` only), `ad2v specs review`,
  `ad2v specs approve <file>`. Proposals use `-X` ids in `<spec root>/.ad2v-extracted/`.
- **`ad2v.yaml`** optionally sets: `system`, `containers`, `exclude`, `spec_root`,
  `spec_markdown`, `spec_ids` (`test_name_prefixes`), `pairing`, `orphan_policy`,
  `rules_overlay`, `workflows`, `llm`.

## 9. Where things are

- Reports: `REPORT.md` (P6.1), `docs/reports/P1.md`–`P6.md`, `P6.1.md`.
- Screenshots: `docs/reports/P5-screens/`, `P6-screens/`, `P6.1-screens/`.
- Demo: `docs/reports/P5-demo.html`, rebuilt in P6.1 with the current viewer.
- Tracking: `status.md`, `issues.md`, `pending.md`.
- Docs: `docs/adr/`, `docs/spec/`, `docs/dependencies.md`, `docs/mcp.md`,
  `docs/quickstart-draft.md` (not verified end-to-end).
- Fixtures: `fixtures/payments-recon/` (code, `specs/`, goldens, `expected-questions.yaml`),
  `fixtures/sdd-presets/{spec-kit,kiro,custom}`. The viewer demo file
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

Next is P7 (see pending.md "After P6.1" first). Do not start it without the developer's prompt.
