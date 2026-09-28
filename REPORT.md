# REPORT: ad2v P5 (the viewer)

P5 adds a deterministic layout (`nestgrid-v1`, computed in Python and stored in the file) and a
three.js viewer:

- a level-of-detail isometric map;
- status styling from the theme tokens;
- effective and suggestion overlays;
- workflow replay with a fine playhead;
- epoch diff;
- `ad2v view`, which serves on 127.0.0.1 only.

P5 made **no LLM calls and used no cloud resources**. The viewer never triggers an LLM call.

Commit: one commit at the end of the phase ("hash: see `git log -1`"). Version 0.5.0, format v0.4
(adds the `layout_grids` table).

## Accrued cost per phase

| phase | cloud / LLM spend | notes |
|---|---|---|
| P1 | $0.00 | no cloud |
| P2 | $0.00 | no cloud |
| P3 | $0.00 | no cloud (bench clones only) |
| P4 | $0.592 | Vertex AI, gemini-3.8-flash, 125 billed calls (live M9 run) |
| P5 | $0.00 | no LLM calls, no cloud resources |
| **total** | **$0.592** | |

**Claude usage** (the agent building ad2v) is not metered per phase from inside the session.
- This account is on the **Max** plan with **extra usage disabled**, so the sessions add no
  incremental dollar cost beyond the subscription.
- At the end of P5 the plan meters read 11% of the 5-hour window and 44% of the weekly
  all-models window.

## 1. Milestones

| # | scope | state |
|---|---|---|
| M1 | `nestgrid-v1` layout in Python, `layout_grids`, `ad2v layout`, `materialize --epochs last:N` | done |
| M2 | `viewer/` (Vite 7, TypeScript strict, ESLint), `DataSource` + `LocalFileSource` (sql.js), `ad2v view` (127.0.0.1), wheel packaging, single-file demo | done |
| M3 | three.js iso map, LOD with hysteresis (8 / 40 / 160 px, ×0.8), navigation, perf HUD, `window.__ad2vPerf` | done |
| M4 | edges at LOD, portals, status styles from tokens, effective toggle with count, themes, suggestions, links | done |
| M5 | panel timeline (cards), chat placeholder "Conversational agent arrives with MCP (P6)" | done |
| M6 | replay on the fine trace with a detail slider, TypeScript projection parity with Python | done |
| M7 | epoch scrubber, diff overlay and changes card, diff tokens | done |
| M8 | tests and gates, Playwright e2e in both themes, 12 screenshots | done |
| M9 | performance on dispatch `dd2837e` | done; targets met |

Changed files, grouped:

- **Python:**
  - `src/ad2v/layout.py` (new), `src/ad2v/view.py` (new);
  - `cli.py` (`layout`, `view`, `materialize --epochs`);
  - `pipeline.py` (layout after extract and materialize);
  - `store.py` and `admin.py` (`layout_grids` in the epoch tables);
  - `tokens.py` (`OVERLAY_BADGES`, `token()`);
  - `__init__.py`, `pyproject.toml` (0.5.0, `ad2v._viewer` package data).
- **Schema:** `schema/ad2v-v0.4.sql` (`layout_grids`), and `schema/themes/{dark,light}.json`
  (AI and suggestion badges, the `diff` block, `link.*`).
- **Viewer:**
  - `viewer/src/` (`data/`, `model/`, `render/`, `ui/`, `theme.ts`, `main.ts`), about 3,100 lines;
  - `viewer/scripts/` (license gate, fixtures, demo publish);
  - `viewer/e2e/`;
  - config files (`package.json`, lockfile, tsconfig, Vite, ESLint, Playwright).
- **Tests:**
  - Python: `tests/test_layout.py`, `tests/test_view.py`, `tests/test_tokens.py`;
  - viewer: `viewer/tests/*.test.ts`, with fixtures `projections.json` and `styles.json` (the
    demo `.ad2v` is generated and gitignored).
- **Docs:**
  - format spec §12 and the principle 8 exception;
  - visual tokens §6;
  - ADR-0034 to ADR-0038;
  - `README.md`, `docs/dependencies.md`, `issues.md`, `pending.md`, `status.md`;
  - `docs/reports/P5-demo.html`, `docs/reports/P5-screens/`, `docs/reports/P4.md` (moved from the
    root).

## 2. Tests

| suite | result |
|---|---|
| Python (pytest) | **215 passed**. New modules: `layout.py` 99%, `view.py` 96% coverage. ruff clean. |
| Viewer unit (Vitest) | **34 passed**: DataSource, projection parity, LOD, tree, edges, text helpers, tokens |
| Viewer e2e (Playwright, Chromium + SwiftShader) | **2 passed** (dark, light), 12 screenshots, no console errors |
| Lint / types | ESLint clean (src, tests, e2e, scripts); `tsc --noEmit` clean |
| License gate | OK (see §5) |

- **Projection parity.** The TypeScript `project()` equals Python's `workflows.project()` for
  **every code workflow at every containment depth** of the demo file, and the detail levels
  match. A further test checks that the playhead always lies inside the containing coarse step at
  every level.
- **Layout stability.** On the P3 history scenario (8 epochs), 765/765 boxes of surviving nodes
  keep their position (**100%**). Layout is byte-identical across runs and with CRLF inputs.
- **Token and style parity.** `STATUS_STYLES`, `OVERLAY_BADGES` and dash patterns in TypeScript
  equal `tokens.py` (via `styles.json`).
- **Every status in both themes.** The rendered outline uses the token stroke, the correct line
  style, hollow fill, weight, emphasis (glow in dark, halo in light) and badge.

## 3. How to open it

- **Demo:** `docs/reports/P5-demo.html` (4.26 MB, one self-contained file). Open it from disk; it
  needs no server.
  - It holds the fixture's 8-epoch history.
  - Its LLM rows come from the offline **fake** provider, and the UI says so.
- **Your own file:**

  ```bash
  ad2v view project.ad2v
  ```

  It prints the `http://127.0.0.1:<port>/` URL and opens the browser; use `--no-browser` and
  `--port` to control this. To browse history, first run
  `ad2v materialize project.ad2v --epochs last:5`.

Screenshots (`docs/reports/P5-screens/`, `dark-*` and `light-*`):

| # | file | shows |
|---|---|---|
| 1 | `*-1-system.png` | System view: spec region (west) and code system; api container red dashed (orphan, with warning badge); worker; roll-up bars |
| 2 | `*-2-container-api.png` | Inside `container:api` at open LOD; modules, ports and edges; panel card with summary, suggestion and copyable `ad2v suggestions accept …` command |
| 3 | `*-3-matching-risky-loop.png` | `matching.py` with the `match_batch` IO-in-loop risk visible and its card |
| 4 | `*-4-replay-two-levels.png` | Replay of `POST /v1/reconciliations`: step 4/7 at level 2 after starting at level 1, same fine playhead; step cards show the narration of both levels |
| 5 | `*-5-effective-req003-ai-drift.png` | Effective status on: REQ-003 shows drift with the **AI** badge; the card reads "normative: verified, effective (AI): drift", with the judge's evidence lines |
| 6 | `*-6-diff-epoch-2-3.png` | Diff #2 → #3: the changes card lists 3 status transitions (verified → stale), with the scrubber in compare mode |

## 4. Performance on dispatch

Setup: Netflix/dispatch at `dd2837e` (717 files, 84,041 lines, 5,374 nodes, 12,406 edges, 331
workflows).
- Extract plus layout: 5.1 s.
- The file is 17.7 MB.
- The bench served it through `ad2v view` and drove the page with 10 s of real wheel and drag
  input.
- The GPU was an **Intel UHD integrated GPU (ANGLE Direct3D 11)**, in headless Chromium with
  hardware ANGLE (ADR-0038).

| metric | target | dispatch | fixture |
|---|---|---|---|
| first render (from navigation) | < 3 s | **0.86 s** | 0.80 s |
| fps median / p5 over 10 s pan+zoom | ≥ 45 median (dispatch), 60 (fixture) | **59.9 / 59.5** | 59.9 / 59.5 |
| visible nodes, draw calls (home / ×4 / ×16) | | 344 / 346 / 336 nodes; 7 / 7 / 6 calls; 27k / 27k / 26k triangles | 28 / 20 / 12 nodes; 8 calls |
| JS heap | | 50–75 MB | 8–14 MB |

**All targets are met**, and frame rate is capped by vsync.

The bench found two real bugs on dispatch, both fixed before the numbers above:
- the camera's fixed distance and clip planes cut off the map;
- the minimum zoom could not fit an 8,500-unit map.

Instancing keeps draw calls at 6–8 whatever the node count. `bench/` was deleted after the
measurements.

## 5. Licenses

The npm tree is checked by `viewer/scripts/check-licenses.mjs`, which runs in every build and
fails it on a violation.
- It covers **158 packages**: MIT 123, Apache-2.0 18, ISC 7, BSD-2-Clause 6, BSD-3-Clause 3,
  BlueOak-1.0.0 1.
- **No copyleft** (GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA, OFL).
- **No font files** in the build output: labels use the system font.
- three's example fonts sit unused in `node_modules`, and the gate reports them as info.
- Vite 8 was rejected because of `lightningcss` (MPL-2.0).

**Python: no dependency added.** `ad2v view` uses the standard library, and `certifi` stays out.

## 6. UX assessment (honest)

What works:
- **Fixture-sized projects read well.** The system view shows the spec region, the two containers
  and their status at a glance. Double-click or search flies into a box and the panel explains it.
- **Status survives without color.** Line style, badges and the AI marker all work in both themes.
- **Replay is correct and legible**, and the detail slider does not lose your place.
- **The diff card is the most useful single view for a reviewer.**

What feels wrong:
- **Large repositories look empty and tangled at the top.** On dispatch the home view is mostly
  empty nested slabs. A few open components carry an **edge hairball**, because every visible
  representative pair gets its own ribbon.
  - Suggestion: denser packing (`nestgrid-v2` with shelf or squarified packing and the same
    slot-stability rule).
  - Suggestion: bundle or aggregate edges per level at low zoom, and show edges only for the
    selection past a count threshold.
- **Labels collide** in dense modules. Culling hides many of them, so you often hover to learn a
  name.
  - Suggestion: show the parent's children names in the panel when a container is open.
- **Very long dashed edges alias** into a cross-hatch at high zoom (issue 55).
- **Portal chips overlap** when two edges leave a box at the same side (screenshot 3: "→ payments-recon" over "→ api"). Suggestion: stack or merge chips per side.
- **Badges cluster at the front-left corner** of open slabs, which can crowd the container label.
- **Suggestions are off by default** and the toggle is easy to miss. The `?` badge only appears
  once they are on.
- The **perf HUD** is hidden unless `?perf=1` is set, which is fine for users but undiscoverable.

## 7. Deviations and open questions

Deviations (with ADRs):

1. **Layout is history-dependent.** It is a named exception to principle 8, like `id_lineage`
   (ADR-0034, spec §12.1).
2. **Vite 7 instead of Vite 8**, for the license rule (ADR-0035).
3. **Canvas 2D labels instead of SDF text, and glow from additive ribbons instead of bloom**
   (ADR-0035).
4. **`ad2v view` details:** fixed file path, GET/HEAD only, and a CSP with `'wasm-unsafe-eval'`
   (ADR-0036).
5. **Presentation choices:**
   - neutral bodies with a light tint;
   - modifier badges hidden on open glyphs;
   - corner badges;
   - camera planes scale with the map (ADR-0037).
6. **Demo data from the fake provider.**
   - The replay screenshot covers both detail levels in one shot per theme.
   - Performance was measured headless on hardware ANGLE, because headed Chromium could not start
     in the agent sandbox (ADR-0038).
7. **Playwright browsers.** They were installed in this session (`%LOCALAPPDATA%\ms-playwright`)
   and **deleted** at the end. Reinstall them with `npx playwright install chromium` before
   `npm run e2e`.

Open questions for P6 (MCP), ranked:

1. **Slice queries.** What the MCP tools return: node, neighborhood to depth k, workflow window,
   diff slice. Should these mirror the `DataSource` methods one to one, so the viewer can swap
   `LocalFileSource` for an MCP source unchanged?
2. **MCP App iframe constraints.** CSP, whether wasm is allowed, and size limits. If wasm or a
   4 MB inline bundle is not allowed there, the App must fetch slices instead of the whole file.
3. **Camera paths from the agent.** Should answers carry node ids plus a camera "fly to" intent,
   with the viewer resolving boxes from its own layout? Coordinates would break if layout changes.
4. **Write actions.** Accepting suggestions stays CLI-only in P5. Should P6 expose it as an MCP
   tool with human confirmation, or keep it out?
5. **Multi-epoch access.** Only materialized epochs are visible today. Should the MCP server
   materialize on demand? That writes the file.
