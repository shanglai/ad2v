# ad2v: agent development to viz

**Comprehension debt** is what builds up when agents merge code faster than people can understand
it. ad2v compares a **repository** with its **SDD specs** (spec-driven development) and writes
**one SQLite file**, `*.ad2v`, that describes both sides as a single graph. Readers of that file:

- a **viewer**: a dark, zoomable isometric 2.5D map (like C4, with more levels). Glyph shapes come
  from a fixed grammar. Spec-only items are dotted, implemented items solid, verified items glow
  blue. Drift is amber and orphan code is red dashed. Workflows replay step by step with a detail
  slider.
- a **conversational agent** (via MCP), whose answers point to node IDs and camera paths.

Like mermaid.js, ad2v is an open **format** plus reference implementations. License: Apache-2.0.

## Status of the series

| phase | scope | status |
|---|---|---|
| **P1** | format spec v0.1, SQLite schema, IR, deterministic extractors (Python code, Gherkin / OpenAPI / Markdown specs), static workflows, canonical dump | **done** (this repo) |
| P2 | spec↔code pairing, structural diff (missing / orphan / stale), Merkle incremental runs, epochs | planned |
| P3 | bring-your-own-model LLM layer: semantic judge, summaries, narrations, all with provenance | planned |
| P4 | three.js viewer | planned |
| P5 | MCP server + MCP App | planned |

P1 makes **no LLM calls**. Every row it writes is *normative*: the same inputs (code, specs and
extractor rules) give the same canonical dump on any platform.

## Quickstart

Requires Python ≥ 3.11. `uv` works too (`uv sync --extra dev`).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

(On macOS/Linux, use `.venv/bin/python`.) Then extract the bundled fixture:

```bash
ad2v extract --repo fixtures/payments-recon --spec fixtures/payments-recon/specs --out recon.ad2v
```

## CLI

```text
ad2v extract --repo <path> [--spec <path>] [--manifest ad2v.yaml] --out project.ad2v
ad2v dump    project.ad2v --canonical [--out project.jsonl]
ad2v inspect project.ad2v [--node <id|qualified_name>] [--kind loop] [--risk io_in_loop]
ad2v validate project.ad2v
```

- `extract` prints counts per kind, ports, risky behaviors, workflows, unresolved spec references
  and the elapsed time.
- `dump --canonical` writes sorted JSONL (UTF-8, LF on every OS). Use it to check determinism, not
  the SQLite bytes.
- `validate` checks the format version, foreign keys, glyph coverage, the IR JSON Schema, and that
  ids and Merkle hashes recompute.

The extractor only **reads** the repository. It never imports or runs repository code.

## Documents

- [Format spec v0.1](docs/spec/ad2v-format-v0.1.md) (normative: the product)
- [Glyph grammar v0.1](docs/spec/glyph-grammar-v0.1.md)
- [Spec Markdown convention](docs/spec/spec-markdown-convention.md)
- [DDL](schema/ad2v-v0.1.sql) and [IR JSON Schema](schema/ir-v0.1.schema.json)
- [ADRs](docs/adr/) and [dependencies and licenses](docs/dependencies.md)
- [REPORT.md](REPORT.md), [status](status.md), [issues](issues.md), [pending](pending.md)

## Optional manifest (`ad2v.yaml`)

```yaml
system: {name: payments-recon}
containers:
  - {name: api, paths: [api], kind: service, replicas: 2}
  - {name: worker, paths: [worker], kind: worker}
exclude: [migrations]          # added to the default excludes
behavior: {emit_all: false}    # true: emit loop/retry/... nodes even without risk flags
workflows: {max_depth: 12, max_steps: 5000}
spec_ids: {test_name_prefixes: [REQ, CMP]}
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

After editing `schema/ad2v-v0.1.sql`, regenerate the spec's column table with
`python -m ad2v.ddl`. A test fails if you forget.
