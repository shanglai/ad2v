# Dependencies and licenses

Policy: **no copyleft dependencies** (GPL, LGPL, AGPL, MPL, EPL, CDDL…), including transitive,
development and build-time dependencies. ad2v itself is Apache-2.0.

Checked on 2026-09-28 from installed package metadata (`License-Expression` / classifiers), versions
as resolved in the development environment.

## Runtime

| package | version | license | why |
|---|---|---|---|
| tree-sitter | 0.26.0 | MIT | parser runtime |
| tree-sitter-python | 0.25.0 (pinned) | MIT | Python grammar; the version decides node types |
| gherkin-official | 42.0.1 | MIT | Gherkin parser |
| PyYAML | 6.0.3 | MIT | manifest, rules, OpenAPI |
| jsonschema | 4.26.0 | MIT | `ad2v validate` (IR JSON Schema) |
| ↳ attrs | 26.1.0 | MIT | transitive (jsonschema) |
| ↳ jsonschema-specifications | 2025.9.1 | MIT | transitive |
| ↳ referencing | 0.37.0 | MIT | transitive |
| ↳ rpds-py | 2026.6.3 | MIT | transitive |
| ↳ typing_extensions | 4.16.0 | PSF-2.0 | transitive |

Standard library: `sqlite3`, `hashlib`, `json`, `argparse`, `pathlib`, `urllib.parse`.

## Development

| package | version | license |
|---|---|---|
| pytest | 9.1.1 | MIT |
| ↳ iniconfig | 2.3.0 | MIT |
| ↳ pluggy | 1.6.0 | MIT |
| ↳ packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| ↳ Pygments | 2.21.0 | BSD-2-Clause |
| ↳ colorama (Windows) | 0.4.6 | BSD-3-Clause |
| pytest-cov | 7.1.0 | MIT |
| ↳ coverage | 7.16.2 | Apache-2.0 |
| ruff | 0.16.9 | MIT |

## Build

| package | license | note |
|---|---|---|
| setuptools (≥ 77) | MIT | no dependencies |

## Rejected

| package | license | reason |
|---|---|---|
| hypothesis | **MPL-2.0** | copyleft; replaced by seeded randomized tests (ADR-0002) |
| hatchling | MIT, but depends on **pathspec (MPL-2.0)** | replaced by setuptools as build backend (ADR-0008) |
| click / typer | BSD / MIT | not rejected on license; argparse avoids a dependency |

## Fixture-only names

`fixtures/payments-recon` *mentions* fastapi, sqlalchemy, httpx, tenacity, litellm, mcp, typer and
google-cloud-pubsub. That code is only parsed, never installed or run, so these packages are **not**
dependencies.

## Benchmarks

The performance smoke used shallow clones of third-party repositories in `bench/` (gitignored).
They were deleted after the measurements. Nothing from them is redistributed.
