# ad2v: agent development to viz

**Comprehension debt** is what builds up when agents merge code faster than people can understand
it. ad2v compares a **repository** with its **SDD specs** (spec-driven development) and writes
**one SQLite file**, `*.ad2v`, that describes both sides as a single graph. The file also records
how the spec items and the code pair up. Readers of that file:

- a **viewer**: a zoomable isometric 2.5D map (like C4, with more levels) in dark and light themes.
  Glyph shape = node kind. Line style = status: spec-only items are dotted, implemented solid,
  verified glowing (dark) or haloed (light), drift carries a warning badge, orphan code is dashed,
  and code in a language no active extractor reads is thin, dotted and hollow with a "∅" badge
  (`not_evaluable`). A **Legend** button explains every status.
  Workflows replay step by step with a detail slider that follows the zoom.
- **any MCP host's model** (Claude, ChatGPT, VS Code, …) through `ad2v mcp`: read-only tools that
  find components and explain them, with answers that point at node ids. Hosts with MCP Apps show
  the map inline in the conversation.

Like mermaid.js, ad2v is an open **format** plus reference implementations. License: Apache-2.0.

Current version: **0.7.0.dev0** (a development pre-release; not published on PyPI). Code is read by
**language extractors** and frameworks are recognized by **framework packs**, both plug-ins behind a
stable public API (`ad2v.api`, api 1.0, entry-point groups `ad2v.extractors` / `ad2v.frameworks`).
The built-in Python extractor and Python framework pack use the same API; third-party plug-ins are
opt-in ([plug-in guide](docs/plugins.md)).

## Status of the series

| phase | scope | status |
|---|---|---|
| P1 | format spec v0.1, SQLite schema, IR, deterministic extractors (Python code, Gherkin / OpenAPI / Markdown specs), static workflows, canonical dump | done ([report](docs/reports/P1.md)) |
| P2 | spec↔code pairing, single-epoch statuses, structural drift, roll-ups, risk severity, visual tokens (light + dark), format v0.2 | done ([report](docs/reports/P2.md)) |
| P3 | content-addressed multi-epoch storage, parse cache, git history, epoch diff, lineage, `stale`, entry-point recognizers, orphan policy, format v0.3 | done ([report](docs/reports/P3.md)) |
| P4 | bring-your-own-model LLM layer (informative only): semantic judge, link suggestions, summaries, narrations, prose-spec extraction, evaluation; format v0.4 | done ([report](docs/reports/P4.md)) |
| P5 | three.js viewer: deterministic layout, LOD map, status styling, replay, epoch diff; `ad2v view` | done ([report](docs/reports/P5.md), [demo](docs/reports/P5-demo.html)) |
| P6 | MCP server (stdlib, protocol 2026-07-28) + the map as an MCP App; deterministic retrieval | done ([report](docs/reports/P6.md), [setup](docs/mcp.md)) |
| P6.1 | real-repo readiness: route recall (factories, `add_api_route`, Starlette, Flask), spec discovery, spec-kit / Kiro / custom presets, `ad2v specs` bootstrap, replay camera, opaque "dim the rest" | done ([report](docs/reports/P6.1.md)) |
| P7 | verified quickstart, settings prefixes, retrieval v2, the viewer's own chat agent (BYOM, `ad2v view --chat`), thinking per task, schema digests, judge roll-up, viewer UX v2, format v0.5 | done ([report](docs/reports/P7.md), [quickstart](docs/quickstart.md)) |
| P8 | extractor plug-in API (`ad2v.api`, entry points, opt-in, conformance kit, out-of-tree examples), blind retrieval eval harness, packaging (not published), CI workflows, security review, sanitization, dogfood procedure | done ([report](docs/reports/P8.md), [plug-ins](docs/plugins.md), [security](docs/security.md)) |
| P8.1 | `not_evaluable`: a status and legend for code in a language no active extractor reads; format v0.6 | done ([report](docs/reports/P8.md) §13, ADR-0066) |
| **P9** | brownfield onboarding: `ad2v init`, Spanish and English team formats (requirement tables, user stories, Spanish EARS and Gherkin), titles, non-functional requirements, issue 95, the spec side of the map, wider default excludes, fresh-clone install fix | **done** ([report](REPORT.md), ADR-0067..0072) |

Extraction makes **no LLM calls**. Every row it writes is *normative* (or *volatile*: deterministic
line numbers): the same inputs (code, specs, rules, manifest, test results) give the same normative
dump on any platform. The optional LLM layer (`ad2v llm`) writes only *informative* rows with full
provenance, never touches an epoch id, and a model can only *suggest*: a human confirms by editing
committed files (`ad2v.yaml`, spec files).

## Quickstart

Requires Python ≥ 3.11. `uv` works too (`uv sync --extra dev`).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

(On macOS/Linux, use `.venv/bin/python`.) Then extract the bundled fixture, with its test results:

```bash
ad2v extract --repo fixtures/payments-recon --spec fixtures/payments-recon/specs --test-results fixtures/payments-recon/test-results/junit.xml --out recon.ad2v
```

```bash
ad2v status recon.ad2v --side spec
```

To follow a repository over time, extract git history into one file (one epoch per commit whose
inputs changed) and compare epochs:

```bash
ad2v history --repo . --spec specs --commits HEAD~20..HEAD --into project.ad2v
```

```bash
ad2v diff project.ad2v --from parent --to head --format md
```

Open the map in a browser. The server binds 127.0.0.1 only and never writes the file:

```bash
ad2v view recon.ad2v
```

To browse history in the viewer, materialize the epochs you want to see first:

```bash
ad2v materialize project.ad2v --epochs last:5
```

A self-contained demo (the fixture's 8-epoch history, with demo LLM rows from the offline `fake`
provider) opens from disk: [`docs/reports/P5-demo.html`](docs/reports/P5-demo.html).

Ask about the map from Claude (or any MCP host). Add this server to the host's configuration; see
[docs/mcp.md](docs/mcp.md) for Claude Desktop, Claude Code and VS Code:

```bash
python -m ad2v mcp --root path/to/maps
```

## CLI

```text
ad2v init     --repo <path> [--write <file> [--force]] [--format yaml|json] [--check <ad2v.yaml>]   # propose a manifest
ad2v extract  --repo <path> [--spec <path> ...] [--no-spec-autodetect] [--manifest ad2v.yaml] [--test-results junit.xml ...]
              (--out project.ad2v | --into project.ad2v) [--no-cache]
ad2v history  --repo <path> --commits <rev-range> --into project.ad2v [--spec <rel> ...] [--manifest <rel>]
              [--test-results <rel> ...] [--no-cache]
ad2v diff     project.ad2v [--from <epoch>] [--to <epoch>] [--format table|json|md]
ad2v log      project.ad2v [--format table|json]
ad2v pin      project.ad2v <epoch> [--label v1.2]      ad2v unpin project.ad2v <epoch>
ad2v prune    project.ad2v --keep-last N [--keep-pinned]
ad2v materialize project.ad2v (--epoch <epoch> | --epochs last:N)   # last N + pinned
ad2v layout   project.ad2v [--algorithm nestgrid-v1|nestgrid-v2]   # v2: experimental shelf packing
ad2v view     project.ad2v [--port 0] [--no-browser]
              [--chat --manifest ad2v.yaml [--chat-budget-usd 0.25]]  # chat with your own model
ad2v mcp      (--file project.ad2v | --root <dir>) [--http [--port N]] [--no-warm]   # MCP server, read-only
ad2v status   project.ad2v [--epoch <epoch>] [--side spec|code] [--status stale] [--all] [--format table|json]
ad2v inspect  project.ad2v [--epoch <epoch>] [--node <id|qualified_name>] [--kind loop] [--top-risk N]
ad2v dump     project.ad2v [--epoch <id|head|all>] [--normative-only] [--out project.jsonl]
ad2v validate project.ad2v [--epoch <epoch>]
ad2v preview-tokens --out tokens.html
```

Without `--spec`, specs are found from `spec_root` in ad2v.yaml, else auto-detected (`specs/`,
`spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`, `docs/sdd/`, a root `openapi.yaml`); `extract`
prints what it used. Markdown specs may follow the ad2v convention, spec-kit, Kiro, a
requirements table, user stories (Spanish or English), or your own regexes
([convention §2, §6–7](docs/spec/spec-markdown-convention.md)).

**Existing project?** `ad2v init --repo <path>` reads the repository and runs nothing. It
proposes an `ad2v.yaml`: spec folders, containers and their languages, test-name prefixes,
non-functional prefixes, and route prefixes left empty for you to fill in. It writes only with
`--write` ([quickstart §2b](docs/quickstart.md)).

An `<epoch>` is an epoch id, `head`, `parent`, a pin label, or a commit SHA prefix (≥ 7 chars).

LLM layer (bring your own model; `fake` for offline use, `vertex`, or any OpenAI-compatible server):

```text
ad2v llm plan  project.ad2v [--manifest ad2v.yaml] [--tasks judge,suggest,summarize,narrate,extract-prose]
               [--epoch head|all] [--count-tokens]
ad2v llm run   project.ad2v --max-cost-usd 0.50 --yes [--manifest ad2v.yaml] [--tasks ...] [--no-llm-cache]
               [--spec-root specs] [--mode call_depth --workflow <id>]
ad2v llm eval  project.ad2v --expected expected-judgments.yaml
ad2v llm show-prose project.ad2v
ad2v suggestions list|accept|reject project.ad2v [<id> --manifest ad2v.yaml]
ad2v specs bootstrap --from docs/ [--plan | --yes --max-cost-usd 0.50] [--manifest ad2v.yaml]
ad2v specs review                      # proposals: source, model, overlap, staleness, id clashes
ad2v specs approve <proposal> [--to specs/sub] [--force-stale]
```

- `plan` lists the calls still needed after cache hits, with token and USD estimates; `run` refuses
  to start without a budget and `--yes`, and stops before exceeding it. Results are cached by the
  exact input, so re-running is free.
- The judge's verdicts appear in `node_status_effective` (an LLM `drift` can only upgrade
  implemented/verified; nothing the model says can clear a problem). `suggestions accept` appends
  the pair to `pairing.links` in ad2v.yaml; the next extract makes it a normative `manifest_link`.
- Prose-spec extraction writes a proposal to `specs/.ad2v-extracted/`; moving it into the spec tree
  is the approval.
- Repository content is sent to the model as fenced, untrusted data; outputs are strict JSON checked
  deterministically (cited lines must exist, echoed injections are rejected).

- `extract --out` writes a fresh single-epoch file; `--into` appends a new head epoch, reusing the
  file's parse cache (the summary shows the hit rate), or reports "no changes" when no input changed.
- `history` exports each commit with `git archive` (never checks out, never runs code) and appends
  one epoch per commit.
- `diff` reports added/removed/renamed nodes (renames follow lineage), status transitions
  (including `stale`), risk changes, spec changes and workflow changes. `--format md` fits a PR
  comment (≤ 60 lines); see [`examples/github-action/ad2v-diff.yml`](examples/github-action/ad2v-diff.yml).
- `status` lists effective statuses (`drift`, `needs_review`, `missing`, `orphan`, `stale`,
  `verified`, `implemented`, `not_evaluable`, `specified`) with their reasons. `not_evaluable`
  (format v0.6): specified and built in a language no active extractor reads (TypeScript, Java, Go,
  …); annotate such code with `// ad2v: REQ-001` comments so the pairing still shows. `extract`
  prints which languages were not read.
- `prune` keeps the last N epochs (and pinned ones), garbage-collects and vacuums.
- `dump --normative-only` is the determinism contract: sorted JSONL, UTF-8, LF on every OS.
- `validate` checks the format version (0.4 to 0.6), schema objects (no triggers, no foreign
  tables or views), text sizes and JSON depth, foreign keys and node references, version keys, the
  epoch chain, glyph and status coverage, the IR JSON Schema, and that ids, link ids, Merkle hashes
  and roll-ups recompute.
- `view` serves the built viewer on 127.0.0.1 (GET/HEAD only, strict CSP). The viewer is
  read-only and never calls an LLM. Actions that change state are shown as CLI commands to copy.
  It shows materialized epochs only. `extract` and `materialize` also write the deterministic
  layout (`nestgrid-v1`, format spec §12), which keeps boxes in place across epochs.
- `extractors list` shows the installed extractor and framework-pack plug-ins (built-in, enabled,
  disabled); `extractor check <name> --fixture <dir>` runs the conformance kit. `extract` and
  `history` print each active plug-in with its version and rules hash; `--extractor <name>` enables
  an installed third-party plug-in for one run (or list it in `ad2v.yaml` under
  `extractors.enabled`), `--strict` makes a failing plug-in fatal.
- `eval blind` scores a private retrieval question set (path in `AD2V_BLIND_EVAL`) and prints
  aggregates only ([blind eval](docs/blind-eval.md)).
- `preview-tokens` writes one self-contained HTML page: every glyph × every status, dark and light
  (see [`docs/reports/P2-tokens.html`](docs/reports/P2-tokens.html)).

The extractor only **reads** the repository and ingests test-result files. It never imports or runs
repository code or tests.

## Documents

- [Format spec v0.6](docs/spec/ad2v-format-v0.6.md) (normative: the product; §11 the LLM layer, §12 layout and viewer, §13 MCP, retrieval and chat)
- [Glyph grammar v0.2](docs/spec/glyph-grammar-v0.2.md) and [visual tokens v0.2](docs/spec/visual-tokens-v0.2.md)
- [Spec Markdown convention](docs/spec/spec-markdown-convention.md)
- [DDL](schema/ad2v-v0.6.sql), [IR JSON Schema](schema/ir-v0.6.schema.json), [themes](schema/themes/)
- [ADRs](docs/adr/) and [dependencies and licenses](docs/dependencies.md)
- [REPORT.md](REPORT.md) (P9), [P8 + P8.1 report](docs/reports/P8.md), [P7 report](docs/reports/P7.md), [plug-in guide](docs/plugins.md), [security](docs/security.md), [blind eval](docs/blind-eval.md), [dogfood procedure](docs/dogfood.md), [releasing (not for now)](docs/RELEASING.md), [quickstart](docs/quickstart.md), [MCP setup](docs/mcp.md), [P6.1 report](docs/reports/P6.1.md), [P6 report](docs/reports/P6.md), [P5 report](docs/reports/P5.md), [P4 report](docs/reports/P4.md), [P3 report](docs/reports/P3.md), [P2 report](docs/reports/P2.md), [P1 report](docs/reports/P1.md), [status](status.md), [issues](issues.md), [pending](pending.md)

## Optional manifest (`ad2v.yaml`)

```yaml
system: {name: payments-recon}
containers:
  - {name: api, paths: [api], kind: service, replicas: 2}
  - {name: worker, paths: [worker], kind: worker}
exclude: [migrations]              # added to the default excludes
behavior: {emit_all: false}        # true: emit loop/retry/... nodes even without risk flags
workflows: {max_depth: 12, max_steps: 5000}
spec_ids: {test_name_prefixes: [REQ, CMP]}
pairing:
  components: {CMP-002: worker}    # spec component -> container or component
  path_prefix_map: {/api: ""}      # route normalization, both sides
  case_insensitive: false
  orphan_policy: auto              # auto (orphans only once specs exist) | strict | off
  links: []                        # human-confirmed pairs (accepted suggestions): manifest_link
  rejected: []                     # rejected suggestions, never proposed again
  path_constants: {"settings.API_V1_STR": "/api/v1"}   # values for unresolvable route prefixes
  resolve_settings_defaults: false # true: read literal pydantic Settings defaults (warned)
rules_overlay: rules-overlay.yaml  # deep-merged over the built-in rules (changes rules_hash)
extractors:
  enabled: []                      # third-party extractor / framework-pack plug-ins to run (opt-in)
llm:                              # informative only: never in config_hash or an epoch id
  provider: vertex                # fake | vertex | openai_compatible
  project: my-gcp-project
  location: global
  model: gemini-3.8-flash
  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}
  budget_usd: 1.00
  output_language: auto           # chat answers in the question's language
  tasks:                          # thinking per task: off | low | default | token budget (Gemini 2.5)
    judge: {thinking: default}
    summarize: {thinking: low}
    chat: {thinking: low, max_output_tokens: 2048}
```

Without a manifest, each top-level directory that has `pyproject.toml`, `setup.py` or `Dockerfile`
is a container.

## Development

```bash
.venv/Scripts/python -m pytest --cov=ad2v
```

```bash
.venv/Scripts/ruff check .
```

CI (`.github/workflows/ci.yml`) runs the tests, determinism (LF vs CRLF+BOM, across systems), both
license gates, the viewer checks and builds, and the plug-in conformance kit; while the repository
is private, Windows and macOS run only on a manual dispatch.

The viewer (Node ≥ 20) lives in `viewer/`:

```bash
cd viewer && npm ci && npm run build
```

`npm run build` type-checks, bundles into `viewer/dist` (which `ad2v view` serves and the wheel
ships) and runs the license gate. `npm run build:demo` regenerates the test fixtures and
`docs/reports/P5-demo.html`. `npm test` runs the unit tests (Vitest) and `npm run lint` runs
ESLint. `npm run e2e` (after `build:demo`) runs the Playwright tour over the demo and writes `docs/reports/P5-screens/`. It needs
`npx playwright install chromium` once.

The MCP layer (P6): `pytest -m mcp` (repository root) runs the Python protocol and tool tests,
including the retrieval eval. `npm run test:mcp` (in `viewer/`) builds the MCP App
(`npm run build:app` → `viewer/app-dist/app.html`, which the wheel ships). It then runs the parity
test (the viewer's data over the real stdio server), protocol conformance with the MCP Inspector
(via `npx`; not a dependency), and the App e2e in a test host (`docs/reports/P6-screens/`). The
retrieval eval also runs standalone:
`python -m ad2v.mcp.evaluate <file> fixtures/payments-recon/expected-questions.yaml [--tune]`.

After editing `schema/ad2v-v0.6.sql`, regenerate the spec's column table with
`python -m ad2v.ddl`. A test fails if you forget.
