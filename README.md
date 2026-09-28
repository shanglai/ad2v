# ad2v: agent development to viz

**Comprehension debt** is what builds up when agents merge code faster than people can understand
it. ad2v compares a **repository** with its **SDD specs** (spec-driven development) and writes
**one SQLite file**, `*.ad2v`, that describes both sides as a single graph. The file also records
how the spec items and the code pair up. Readers of that file:

- a **viewer**: a zoomable isometric 2.5D map (like C4, with more levels) in dark and light themes.
  Glyph shape = node kind. Line style = status: spec-only items are dotted, implemented solid,
  verified glowing (dark) or haloed (light), drift carries a warning badge, orphan code is dashed.
  Workflows replay step by step with a detail slider that follows the zoom.
- a **conversational agent** (via MCP), whose answers point to node IDs and camera paths.

Like mermaid.js, ad2v is an open **format** plus reference implementations. License: Apache-2.0.

## Status of the series

| phase | scope | status |
|---|---|---|
| P1 | format spec v0.1, SQLite schema, IR, deterministic extractors (Python code, Gherkin / OpenAPI / Markdown specs), static workflows, canonical dump | done ([report](docs/reports/P1.md)) |
| P2 | spec↔code pairing, single-epoch statuses, structural drift, roll-ups, risk severity, visual tokens (light + dark), format v0.2 | done ([report](docs/reports/P2.md)) |
| P3 | content-addressed multi-epoch storage, parse cache, git history, epoch diff, lineage, `stale`, entry-point recognizers, orphan policy, format v0.3 | done ([report](docs/reports/P3.md)) |
| **P4** | bring-your-own-model LLM layer (informative only): semantic judge, link suggestions, summaries, narrations, prose-spec extraction, evaluation; format **v0.4** | **done** ([report](REPORT.md)) |
| P5 | three.js viewer | planned |
| P6 | MCP server + MCP App | planned |

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

## CLI

```text
ad2v extract  --repo <path> [--spec <path>] [--manifest ad2v.yaml] [--test-results junit.xml ...]
              (--out project.ad2v | --into project.ad2v) [--no-cache]
ad2v history  --repo <path> --commits <rev-range> --into project.ad2v [--spec <rel>] [--manifest <rel>]
              [--test-results <rel> ...] [--no-cache]
ad2v diff     project.ad2v [--from <epoch>] [--to <epoch>] [--format table|json|md]
ad2v log      project.ad2v [--format table|json]
ad2v pin      project.ad2v <epoch> [--label v1.2]      ad2v unpin project.ad2v <epoch>
ad2v prune    project.ad2v --keep-last N [--keep-pinned]
ad2v materialize project.ad2v --epoch <epoch>
ad2v status   project.ad2v [--epoch <epoch>] [--side spec|code] [--status stale] [--all] [--format table|json]
ad2v inspect  project.ad2v [--epoch <epoch>] [--node <id|qualified_name>] [--kind loop] [--top-risk N]
ad2v dump     project.ad2v [--epoch <id|head|all>] [--normative-only] [--out project.jsonl]
ad2v validate project.ad2v [--epoch <epoch>]
ad2v preview-tokens --out tokens.html
```

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
  `verified`, `implemented`, `specified`) with their reasons.
- `prune` keeps the last N epochs (and pinned ones), garbage-collects and vacuums.
- `dump --normative-only` is the determinism contract: sorted JSONL, UTF-8, LF on every OS.
- `validate` checks the format version (0.3), foreign keys and node references, version keys, the
  epoch chain, glyph and status coverage, the IR JSON Schema, and that ids, link ids, Merkle hashes
  and roll-ups recompute.
- `preview-tokens` writes one self-contained HTML page: every glyph × every status, dark and light
  (see [`docs/reports/P2-tokens.html`](docs/reports/P2-tokens.html)).

The extractor only **reads** the repository and ingests test-result files. It never imports or runs
repository code or tests.

## Documents

- [Format spec v0.4](docs/spec/ad2v-format-v0.4.md) (normative: the product; §11 the LLM layer)
- [Glyph grammar v0.2](docs/spec/glyph-grammar-v0.2.md) and [visual tokens v0.2](docs/spec/visual-tokens-v0.2.md)
- [Spec Markdown convention](docs/spec/spec-markdown-convention.md)
- [DDL](schema/ad2v-v0.4.sql), [IR JSON Schema](schema/ir-v0.4.schema.json), [themes](schema/themes/)
- [ADRs](docs/adr/) and [dependencies and licenses](docs/dependencies.md)
- [REPORT.md](REPORT.md) (P4), [P3 report](docs/reports/P3.md), [P2 report](docs/reports/P2.md), [P1 report](docs/reports/P1.md), [status](status.md), [issues](issues.md), [pending](pending.md)

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
rules_overlay: rules-overlay.yaml  # deep-merged over the built-in rules (changes rules_hash)
llm:                              # informative only: never in config_hash or an epoch id
  provider: vertex                # fake | vertex | openai_compatible
  project: my-gcp-project
  location: global
  model: gemini-3.8-flash
  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}
  budget_usd: 1.00
```

Without a manifest, each top-level directory that has `pyproject.toml`, `setup.py` or `Dockerfile`
is a container.

## Development

```bash
.venv/Scripts/python -m pytest --cov=ad2v
```

```bash
.venv/Scripts/ruff check src tests
```

After editing `schema/ad2v-v0.4.sql`, regenerate the spec's column table with
`python -m ad2v.ddl`. A test fails if you forget.
