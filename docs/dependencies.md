# Dependencies and licenses

Policy: **no copyleft dependencies** (GPL, LGPL, AGPL, MPL, EPL, CDDL…), including transitive,
development and build-time dependencies. ad2v itself is Apache-2.0.

Checked on 2026-09-28 (P1, re-checked in P2–P6) from installed package metadata (`License-Expression` / classifiers), versions
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

Standard library: `sqlite3`, `hashlib`, `json`, `argparse`, `pathlib`, `urllib.parse`,
`xml.etree.ElementTree` (JUnit ingestion, P2), `html` (token preview, P2).

**P2 added no dependency.** JUnit XML is parsed with the standard library, as the P2 prompt required
(no lxml). `defusedxml` (PSF-2.0, not copyleft) was considered as hardening against malicious XML
and deferred: test-result files come from the user's own CI, and Python 3.12's bundled expat already
limits entity-expansion attacks (see issues.md).

**P3 added no dependency.** Multi-epoch storage, the parse cache (`zlib`), history (`zipfile`,
`tempfile`, `subprocess`) and the diff use the standard library only. `ad2v history` runs the
**git** command-line tool as an external program (`git rev-list`, `git diff-tree`, `git ls-tree`,
`git show`, `git archive`); git (GPL-2.0) is neither linked nor imported nor redistributed, and only
`ad2v history` needs it. Everything else works without git.

**P4 added no dependency.** The LLM layer talks to providers with `urllib.request` (standard
library) and validates outputs with the existing `jsonschema`. Provider SDKs were rejected: they
depend on `requests` or `httpx`, which bring in **`certifi` (MPL-2.0)**. The Vertex provider gets an
OAuth access token by running the **gcloud CLI** as an external program (`gcloud auth
application-default print-access-token`); gcloud is not linked, imported or redistributed, and only
the `vertex` provider needs it (CI can pass a token in `AD2V_ACCESS_TOKEN`).

**P5 added no Python dependency.** `ad2v view` uses `http.server` and `webbrowser` from the
standard library. `certifi` stays banned. The layout is pure Python.

**P6 added no Python dependency.** The MCP server is written on the standard library
(`json`, `http.server`, `threading`, `secrets`, `sqlite3`), because the official Python MCP SDK
depends on `httpx`, which brings in **`certifi` (MPL-2.0)**. The retrieval eval reuses PyYAML.

## Viewer (npm, P5)

The viewer in `viewer/` has its own npm tree. `npm run build` and `npm run build:demo` run
`scripts/check-licenses.mjs`. It walks **every** installed package (direct, transitive and
development), evaluates SPDX expressions and **fails the build** on GPL, LGPL, AGPL, MPL, EPL,
CDDL, CC-BY-SA or OFL, and on any font file in the build output. Last run (2026-09-28): 158
packages (MIT 123, Apache-2.0 18, ISC 7, BSD-2-Clause 6, BSD-3-Clause 3, BlueOak-1.0.0 1). The
full list is written to `viewer/scripts/licenses.json` (gitignored).

| package | version | license | kind | why |
|---|---|---|---|---|
| three | 0.180.0 | MIT | runtime (bundled) | WebGL rendering |
| sql.js | 1.14.2 | MIT | runtime (bundled, incl. wasm) | SQLite in the browser |
| vite | 7.3.6 | MIT | build | bundler (Vite 8 rejected, see below) |
| vite-plugin-singlefile | 2.3.3 | MIT | build | single-file demo |
| typescript | 6.0.3 | Apache-2.0 | build | strict type checking |
| eslint, @eslint/js | 10.x | MIT | dev | lint |
| typescript-eslint | 8.71.0 | MIT | dev | lint |
| vitest | 4.1.11 | MIT | dev | unit tests |
| @playwright/test | 1.63.0 | Apache-2.0 | dev | e2e screenshots, perf bench |
| @types/three, @types/sql.js, @types/node | | MIT | dev | types |
| @modelcontextprotocol/ext-apps (P6) | 2.0.3 | MIT | runtime (bundled in the MCP App) | MCP Apps client in the iframe; `AppBridge` for the e2e test host |
| ↳ @modelcontextprotocol/core, /client (peers) | 2.2.0 | MIT | bundled / dev | JSON-RPC protocol classes |
| ↳ zod, @standard-schema/spec | 4.6.5 / 1.x | MIT | bundled | schema validation (jitless: no `unsafe-eval`) |

After P6: **166 packages** (MIT 131, Apache-2.0 18, ISC 7, BSD-2-Clause 6, BSD-3-Clause 3,
BlueOak-1.0.0 1). The MCP App build (`build:app`) is also checked for a 2 MB budget and for any
embedded wasm: it is 988 KB, with no wasm.

**MCP Inspector** (`@modelcontextprotocol/inspector` 2.8.0, Apache-2.0/MIT) is used for protocol
conformance **through `npx`, outside the project tree**. Its dependencies include Vite 8 and
therefore `lightningcss` (MPL-2.0), which the gate would reject in our tree. It is a development
tool that runs from npm's cache and is not redistributed.

No font ships: labels use the system UI font through Canvas 2D. three's example fonts are in
`node_modules` but are never imported. The license check reports them as info.

Playwright downloads Chromium builds into `%LOCALAPPDATA%\ms-playwright` for the e2e tests. They
are development tools, not redistributed.

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
| google-genai, google-cloud-aiplatform, openai, httpx, requests | Apache-2.0 / MIT, but depend on **certifi (MPL-2.0)** | replaced by stdlib `urllib` (ADR-0027) |
| vite 8 | MIT, but depends on **lightningcss (MPL-2.0)** | Vite 7 instead (ADR-0035) |
| mcp (official Python MCP SDK) | MIT, but depends on **httpx → certifi (MPL-2.0)** | stdlib server (ADR-0039) |
| @modelcontextprotocol/inspector as a devDependency | Apache-2.0/MIT, but its tree has **lightningcss (MPL-2.0)** | run via `npx` only (ADR-0045) |
| troika-three-text and SDF fonts | MIT; bundled fonts are often **OFL** | Canvas 2D labels with the system font (ADR-0035) |

## Fixture-only names

`fixtures/payments-recon` *mentions* fastapi, sqlalchemy, httpx, tenacity, litellm, mcp, typer and
google-cloud-pubsub. That code is only parsed, never installed or run, so these packages are **not**
dependencies.

## Benchmarks

The performance measurements (P1–P3, P5, P6) used shallow clones of third-party repositories in `bench/`
(gitignored): dispatch (Apache-2.0) and full-stack-fastapi-template (MIT). They were deleted after
the measurements. Nothing from them is redistributed.
