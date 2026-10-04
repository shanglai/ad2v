# P8 report: release readiness without release, plus the extractor plug-in API

ad2v 0.7.0.dev0, format v0.5 (plug-in identity added within v0.5). Phase dates: 2026-10-04.
Previous report: [docs/reports/P7.md](docs/reports/P7.md). This report is also at
[docs/reports/P8.md](docs/reports/P8.md).

Nothing was published: no PyPI/TestPyPI upload, tag, release, Pages site, visibility change or
public demo. No cloud resources, no LLM calls (fake provider only), no CI minutes (the workflows are
written and statically checked, not run).

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
| **P8** | **$0** | no cloud, no LLM, no CI minutes |
| **total** | **$0.977** | |

Claude's own usage is not metered per phase: the account is on the Max plan with extra usage
disabled, so it adds no per-phase cost that could be reported here.

## 2. Milestones

| milestone | state | notes |
|---|---|---|
| M1 extractor plug-in API | **done** | `ad2v.api` 1.0; entry points; opt-in; identity in the epoch; Python extractor and framework pack as plug-ins with no behavior change (dumps compared, §4); conformance kit; two out-of-tree examples installed in a temp venv |
| M2 blind retrieval eval | **done** | harness, template with 2 dummy questions, docs, no-leak tests; no blind content written or read |
| M3 packaging, not publishing | **done** | 0.7.0.dev0; wheel and `pip install .` verified in clean venvs; quickstart guard against the installed wheel; `twine check` passed; `release.yml` disabled; `docs/RELEASING.md` |
| M4 CI | **done (written, not run)** | `ci.yml` (ubuntu on push/PR, all OS on manual dispatch), static checks in place of actionlint (not installed) |
| M5 security review | **done** | `docs/security.md`, `SECURITY.md`; 11 findings fixed, 5 open (low, or inherent and documented) |
| M6 sanitization inventory | **done** | tracked files fixed with placeholders; history reported by type and count; no secrets (gitleaks not installed; regex scan) |
| M7 dogfood readiness | **done** | `docs/dogfood.md` + `scripts/dogfood_counts.py` |

## 3. The plug-in interfaces (ADR-0063, ADR-0064, ADR-0065)

**Public module:** `ad2v.api` (`src/ad2v/api.py`). It re-exports the existing internal model
(`Graph`, `Node`, `Edge`, `UnresolvedRef`, `CodeFacts`, `Event`, `Layout`, `SourceFile`,
`Config`, `NODE_KINDS`, `EDGE_KINDS`, `node_id()`, `content_hash()`) plus:

```python
API_VERSION = "1.0"
EXTRACTOR_GROUP = "ad2v.extractors"
FRAMEWORK_GROUP = "ad2v.frameworks"

class Extractor(Protocol):
    api_version: str; name: str; version: str
    languages: tuple[str, ...]
    file_patterns: tuple[str, ...]          # globs on file name or repo-relative path
    rules_files: tuple[Path, ...]           # YAML; canonical hash enters the epoch identity
    node_kinds: frozenset[str]; edge_kinds: frozenset[str]   # besides Layout's
    def extract(self, ctx: ExtractContext) -> ExtractOutput: ...

@dataclass
class ExtractContext:
    graph: Graph            # empty, holds the system node; add nodes/edges; graph.unresolved
    layout: Layout          # container_for(path), parent_for_module(path)
    files: FileAccessor     # read-only, exactly the claimed files, pre-read and normalized
    config: Config
    rules: Mapping[str, Any]                 # effective: own files + attached packs (+ overlay)
    cache: Mapping[tuple[str, str], Any]     # earlier parse-cache payloads
    warnings: list[str]; def warn(msg): ...

@dataclass
class ExtractOutput:
    facts: CodeFacts        # events, wrappers, entry_ports, files_read
    cache_entries: dict[str, tuple[str, Any]]; timings: dict[str, float]; stats: dict[str, int]

class FrameworkPack(Protocol):
    api_version: str; name: str; version: str
    attaches_to: tuple[str, ...]; frameworks: tuple[str, ...]
    file_patterns: tuple[str, ...]          # extra inputs for the hook (e.g. "*.sql")
    rules_files: tuple[Path, ...]           # fragments pack-merged into the extractor's rules
    node_kinds: frozenset[str]; edge_kinds: frozenset[str]
    def post_extract(self, ctx: FrameworkContext) -> None: ...

@dataclass
class FrameworkContext:
    extractor: str; graph: Graph; files: FileAccessor; config: Config
    rules: Mapping[str, Any]; facts: CodeFacts; warnings: list[str]
```

`FileAccessor`: `paths`, iteration over `SourceFile`s, `read_text(path)`, `content_hash(path)`,
`source(path)`; anything outside the set raises `FileAccessError` and is recorded.
`api_compatible(plugin_api, core_api)` implements the policy below.

**Entry-point groups:** `ad2v.extractors` and `ad2v.frameworks`; the entry point loads to a
zero-argument class or factory. The built-ins are registered in `pyproject.toml` and in an internal
registry (source checkouts work without metadata): `python = ad2v.extract.code.plugin:PythonPlugin`
(version 1.0.0) and `python-frameworks = ad2v.extract.code.plugin:PythonFrameworksPack` (1.0.0).

**Compatibility policy:** semver on `MAJOR.MINOR`. Minor releases only add (optional fields and
attributes with defaults, kinds, helpers). Breaking = removing or renaming anything in `ad2v.api`,
changing a signature or a field's meaning, the pack-merge rules, the accessor contract or the identity
inputs, or making an optional attribute required. The core accepts its own major (plug-in minor ≤
core minor) and the previous major (with a deprecation note); deprecations last at least one minor
release and until the next major.

**Opt-in:** only the built-ins are active. Others need `ad2v.yaml` `extractors: {enabled: [name]}`
or `--extractor <name>` (repeatable) on `extract`/`history`; enabling an uninstalled name is an
error; disabled plug-ins are never imported by `extract`/`history`, and `extractors list` imports
them only with `--inspect`; names that shadow a built-in or are registered twice are refused.
`extractors.*` is excluded from `config_hash` (the identity enters through the rules).

**Identity and isolation:** every active plug-in's `{kind, name, version, api_version, rules_hash,
attaches_to | effective_rules_hash}` is stored under `plugins` in the epoch rules, so it is part of
`rules_hash` and the epoch id; a plug-in change is a `change_kind = rules` epoch. Additive within
v0.5 (no DDL change; ADR-0065). Parse-cache key: `extractor_version = name@version[:cache
version]`, `rules_hash` = the extractor's effective rules hash (GC updated). Each extractor writes
its own graph, merged in name order; third-party plug-ins run with exception isolation and a
timeout (`--plugin-timeout`, default 600 s), and a failure is printed, recorded in
`epochs.attrs.plugin_failures` and skipped (`--strict` makes it fatal; a failing pack hook runs on a
copy, so it leaves nothing behind). `extract` prints one line per plug-in with version, api and
rules hash.

**What did not fit cleanly (reported, not changed):**

1. `python.yaml` still holds the language-agnostic `severity:` and `retrieval:` sections (the epoch
   rules keep the P7 top-level layout). They belong in core rules before a second real extractor
   (issue 89).
2. Framework recognition in the Python extractor is parameterized by rules: a pack can add
   constructors, decorators, methods, settings bases, but not a new recognition *algorithm* that
   needs the syntax tree; the hook sees the finished graph and file text (issue 90). Click group
   resolution, Celery beat dictionaries and Starlette route lists stay code in `python.py`.
3. The schema-digest hook re-parses Python with `ast` (as in P7).
4. `CodeFacts.events` / `wrappers` are Python-shaped; an extractor that returns none gets no code
   workflows traced.
5. Cross-extractor references (a routes file naming a Python handler) can only be expressed as
   computed node ids; the core does not resolve them.

## 4. Proof of no behavior change

The "before" dumps were captured before any code was touched, with the P7 code at `27c24c6`: `ad2v
dump --normative-only --epoch all` of 9 scenarios, then the same script after the refactor.

| scenario | epochs | rows | result |
|---|---|---|---|
| payments-recon, with JUnit results | 1 | 1,039 | identical, epoch id / rules hash masked |
| payments-recon, without results (settings prefixes off) | 1 | 1,035 | identical, masked |
| payments-recon, settings prefixes via `path_constants` | 1 | 1,035 | identical, masked |
| payments-recon, settings prefixes via the resolver | 1 | 1,035 | identical, masked |
| P3 history scenario (8 commits), LF | 8 | 8,369 | identical, masked |
| P3 history scenario, CRLF + BOM | 8 | 8,369 | identical, masked |
| sdd-presets spec-kit | 1 | 239 | identical, masked |
| sdd-presets kiro | 1 | 138 | identical, masked |
| sdd-presets custom | 1 | 88 | identical, masked |

How: byte comparison first; the dumps were the same length but not byte-identical, because every
epoch id and rules hash changes: the epoch rules now include the plug-in identity records, which is
the intended effect (ADR-0065). The comparison then replaced each P8 epoch id and rules hash with the
P7 value of the same `seq` (2 substitutions per single-epoch file, 9 for the history files) and
compared the sorted rows: **identical for all 9 scenarios, 23 epochs, 21,347 rows.**
(`rules_versions.rules_json`, where the `plugins` key lives, is not part of the normative dump.)
Supporting checks: pack-merging `python.yaml` + `python-frameworks.yaml` reproduces the P7
`python.yaml` canonical hash (`40e0c803…`, pinned by a test), so the Python extractor's effective
rules and its parse-cache rules hash are unchanged; `scripts/determinism_check.py` shows LF and
CRLF+BOM give identical dumps for 4 fixtures; P7's existing goldens all pass.

## 5. Out-of-tree example plug-ins

`examples/plugins/routes-dsl-extractor` (`ad2v-routes-dsl` 0.1.0, extractor `routes-dsl`: `*.routes`
files → `module` + `http_route` nodes, `# ad2v: REQ-…` refs) and
`examples/plugins/bottle-framework-pack` (`ad2v-bottle-pack` 0.1.0, framework pack `bottle`: one
route recognizer, `bottle.Bottle`, as a rules fragment). Both import only `ad2v.api`.

Install (done in a fresh temporary venv, then deleted):

```bash
python -m venv <tmp>/venv && <tmp>/venv/Scripts/python -m pip install . examples/plugins/routes-dsl-extractor examples/plugins/bottle-framework-pack
```

`ad2v extractors list` (installed, nothing enabled):

```text
ad2v plug-in API 1.0; groups: ad2v.extractors, ad2v.frameworks
kind       name               version       api  distribution            state
extractor  python             1.0.0         1.0  ad2v 0.7.0.dev0         built-in
framework  python-frameworks  1.0.0         1.0  ad2v 0.7.0.dev0         built-in -> python
extractor  routes-dsl         (not loaded)  -    ad2v-routes-dsl 0.1.0   disabled
framework  bottle             (not loaded)  -    ad2v-bottle-pack 0.1.0  disabled
```

With `--inspect`: `routes-dsl 0.1.0 api 1.0` and `bottle 0.1.0 api 1.0 -> python`.

Conformance kit (`ad2v extractor check`, installed): **routes-dsl PASS 8/8** (determinism: second
run and CRLF+BOM identical, 10 rows; id stability 7/7 ids kept; schema valid; no file opened outside
its set; no side effects; kinds as declared), **bottle PASS 8/8** (12 rows, 8/8 ids), and the
built-ins `python` and `python-frameworks` PASS 8/8 on `sdd-presets/kiro`.

Real extracts: the routes fixture enables `routes-dsl` in its own `ad2v.yaml`; `ad2v extract` prints
the three plug-in lines, emits 3 routes that pair with its OpenAPI spec (3 implemented, the
unimplemented `POST /v1/orders/{id}/cancel` correctly `missing`) and validates. The Bottle fixture
gives no routes without the pack and `GET /health`, `GET /hello/<name>` with `--extractor bottle`.
The same examples run in-process in `tests/test_plugins.py` and installed in the CI `plugins` job.

## 6. Tests

| suite | P7 | P8 |
|---|---|---|
| pytest (collected) | 321: 320 passed, 1 cloud skip | **382: 380 passed, 2 skipped** (cloud; a symlink test that needs privileges on Windows) |
| new pytest files | | `test_plugins.py` 38, `test_security.py` 12, `test_blind_eval.py` 6, `test_ci_workflows.py` 3, `test_license_gate.py` 2 (+61) |
| Vitest | 49 | 49 |
| Playwright | 22 (21 run + 1 on-demand skip) | **24 (23 passed + 1 on-demand skip)**: `hostile.spec.ts` 2 new |
| `npm run test:mcp` | parity, Inspector, App e2e 10/10 | all passed |
| coverage | 95% | 95% (new modules 87–100%; the kit's audit-hook body runs but is not traced) |

Changed tests (none removed):

- `test_history.py::test_prune_and_gc`: its GC invariant now joins the per-plug-in
  `effective_rules_hash` (the parse-cache key changed, ADR-0065).
- `test_p3_units.py::test_cached_extraction_equals_uncached` and `::test_stale_cache_version_is_ignored`:
  `cache_entries` is grouped by (extractor version, rules hash) and the cache loader takes both.
- `test_llm.py`: the GCP project id in a Vertex URL test became `example-project` (M6).

A mistake caught before the end: the new CI-workflow checks were first written over the existing
`tests/test_workflows.py` (8 workflow-trace tests). The per-file test counts against P7 exposed it;
the original file is restored unchanged and the new checks live in `tests/test_ci_workflows.py`.

Gates: ruff check and format, ESLint, tsc, both license gates (Python: runtime closure 11 dists,
dev 20; npm: 166 packages), viewer builds, Python 3.11 `compileall`.

## 7. Dependencies

**No new dependencies** (Python or npm). The runtime closure is unchanged: tree-sitter,
tree-sitter-python, gherkin-official, PyYAML, jsonschema (+ attrs, jsonschema-specifications,
referencing, rpds-py: MIT; typing_extensions: PSF-2.0). New stdlib-only scripts:
`scripts/check_python_licenses.py`, `scripts/determinism_check.py`, `scripts/dogfood_counts.py`.

Tools run outside the tree (none added to `pyproject.toml` or `package.json`):

| tool | version | license | how |
|---|---|---|---|
| build | 1.6.1 | MIT | throwaway venv (pipx is not installed on this machine) |
| twine | 7.0.0 | Apache-2.0 | throwaway venv |
| pip-audit | 2.10.1 | Apache-2.0 | throwaway venv |
| npm audit | npm 11.17.0 | Artistic-2.0 | built into npm |
| MCP Inspector | 2.8.0 | Apache-2.0 / MIT | `npx` (in `test:mcp`) |
| Playwright Chromium | build 1243 | BSD-3-Clause / Chromium | installed for this session, deleted at the end |
| actionlint | not available | MIT | not run; static workflow tests instead |
| gitleaks | not available | MIT | not run; regex history scan instead |

## 8. Security findings (docs/security.md §9)

| # | issue | surface | severity | status |
|---|---|---|---|---|
| S1 | `ad2v.yaml` `spec_root` could point outside the repository (local files read into a shareable map) | repository-supplied paths | medium | fixed |
| S2 | `ad2v.yaml` `rules_overlay` could point outside the repository | repository-supplied paths | medium | fixed |
| S3 | an auto-detected `specs/` symlink could point outside the repository | repository-supplied paths | medium | fixed |
| S4 | `ad2v view` checked `Host` only on chat endpoints (DNS rebinding could read the map) | local server | medium | fixed |
| S5 | writers would fire triggers embedded in a hostile file | malicious `.ad2v` | medium | fixed (refuse; `trusted_schema = OFF`) |
| S6 | `validate` missed foreign tables/views/triggers, huge strings, deep JSON (and crashed on deep JSON) | malicious `.ad2v` | low | fixed |
| S7 | the MCP server served files with redefined views | MCP | low | fixed (refused) |
| S8 | `specs approve --to` accepted a destination outside the repository | CLI paths | low | fixed |
| S9 | CSP lacked `object-src`, `base-uri`, `form-action`, `frame-ancestors`; no `Referrer-Policy` | local server | info | fixed |
| S10 | the conformance kit did not detect network, subprocess or write side effects | plug-ins | low | fixed (`side_effects`) |
| S11 | `ad2v.chat` missing from the wheel (since P7) | packaging | info | fixed |
| S12 | plug-ins are not sandboxed (in-process, user privileges) | plug-ins | low | open, by design (opt-in, documented) |
| S13 | pathological views in a hostile file can hang the standalone viewer's tab | malicious `.ad2v` | low | open |
| S14 | `braces` ≤ 3.0.3 advisory in the build-only chain (`vite-plugin-singlefile`); no patched release | supply chain | low | open |
| S15 | prompt injection can bias informative LLM output | prompt injection | medium | open, inherent (no write tools, informative only) |
| S16 | a timed-out plug-in thread keeps running until exit | plug-ins | low | open |

Evidence: hostile-file tests (`tests/hostile.py`: XSS in every text column and JSON leaf, a 2 MiB
string, 5,000-level JSON, a wrong version, extra table/view/trigger, a redefined built-in view);
Playwright shows no script runs in either viewer mode; `pip-audit`: 0 known vulnerabilities (runtime
and dev); `npm audit`: 0 in runtime dependencies, 3 high (one advisory, S14) in dev.

## 9. Sanitization inventory (no values)

Types: local absolute paths containing the OS username, the OS username, the GitHub owner name, the
owner's first name in prose, personal email addresses, the GCP project id, secrets.

| type | tracked/untracked files before | after | history (15 commits, all refs) |
|---|---|---|---|
| absolute local path with username | 3 lines in 2 files (context doc 1, a P6 report config example 2) | 0 (`<repo-root>`) | 7 added lines in 3 commits |
| GitHub owner name | 1 line in 1 file (context doc) | 0 (`<github-owner>`) | 1 added line in 1 commit |
| GCP project id | 12 lines in 7 files (P4 report 4, P7 report 1, root report 1, context doc 1, status 2, a fixture LLM config 1, a test 2) | 0 (`<your-gcp-project>`; the test uses `example-project`) | 17 added lines in 4 commits |
| owner first name in new public-facing docs | 5 lines in 3 files (written this phase) | 0 ("the owner") | 0 |
| personal email in files | 0 | 0 | 0 in content; commit metadata: personal-domain address as author on 15/15 commits and committer on 14/15 (1 GitHub noreply) |
| secrets (11 patterns: cloud, OpenAI, Anthropic, GitHub, AWS, Slack keys/tokens, private keys, service-account JSON, OAuth tokens, bearer tokens, password assignments) | 0 real (3 false-positive pattern groups: a file name, minified three.js, style tokens) | 0 | 0 real (same false positives) |

Kept on purpose: generic placeholder paths in `docs/mcp.md` (`C:\Users\you\…`) and a built-in sql.js
string in the demo bundle. Also scanned: the demo's embedded map and the LLM and chat recordings
(clean). Not scanned: 64 tracked screenshots (binary). The history findings stay until the planned
fresh, squashed public repository; gitleaks was not available, so the secret scan used regexes over
`git log -p --all` and the tree. No real secret was found, so no stop was needed.

## 10. Skipped because it would cost money (estimates)

- **CI minutes** (not run; repository private). Per push/PR (ubuntu only): viewer ≈ 4 min, python
  3.12 ≈ 5, python 3.11 ≈ 5, plug-ins ≈ 3, determinism ≈ 1 → **≈ 18 billed minutes**. A manual
  all-OS dispatch adds Windows (≈ 14 min × 2) and macOS (≈ 11 min × 10) → **≈ 156 weighted
  minutes**. On a 2,000-minute private plan that is ≈ 110 pushes a month, or ≈ 12 all-OS
  dispatches. Beyond the included minutes, at GitHub's standard Linux rate (about $0.008/min at the
  time of writing; check current pricing) a push is about $0.15 and an all-OS dispatch about $1.25.
  Free once the repository is public.
- **TestPyPI dry run**: free but it publishes, so it is out of scope (decision 1).
- **LLM on the dogfood repositories**: not part of dogfooding without an approved budget. If
  approved, P7's measured costs apply: judge at thinking `low` ≈ $0.0017 per link; summaries and
  narrations for a dispatch-sized repository ≈ $10.60 (P7 re-estimate).

## 11. Open questions for the reviewer, and the recommended P9 scope

Questions:

1. **Epoch-id change.** Every P8 extraction has new epoch ids (plug-in identity), so a P7 history
   file gets one `rules` epoch on its next run. Acceptable, or should the first P8 epoch of an old
   file be labeled as a "toolchain" change in the viewer?
2. **Built-in versions.** `python` and `python-frameworks` are 1.0.0 and bumped by hand. Tie them to
   `LOCAL_EXTRACTOR_VERSION` / `rules_version`, or keep them independent?
3. **Plug-in timeout default** (600 s) and **`--strict` default** (off): right for the private Java
   extractor?
4. **Tree-level hook.** Does the enterprise pack need to add *algorithms* to the Python extractor
   (issue 90)? If so, api 1.1 could expose a per-module hook with the tree-sitter tree.
5. **Blind set.** Size and repositories for the blind questions; the harness suppresses per-type
   rows below 5 questions.
6. **actionlint / gitleaks:** install them (standalone binaries, MIT) for the next session?

Recommended P9: the TypeScript extractor as a plug-in, after the dogfood results and the agreement.

1. First move `severity:` and `retrieval:` from `python.yaml` into core rules (issue 89), with the
   same masked-dump proof as P8 §4.
2. A `typescript` extractor (tree-sitter-typescript, MIT) behind `ad2v.api`, in-repo but loaded as
   a built-in plug-in: modules, classes, functions, imports and calls, test detection, `ad2v:`
   annotations; events/wrappers for workflows.
3. A `typescript-frameworks` pack: Express, Fastify, NestJS controllers, Next.js route handlers,
   Prisma/TypeORM schema digests, as rules fragments plus hooks; extend the pack vocabulary if a
   tree-level hook is needed (decide question 4 first).
4. A mixed Python + TypeScript fixture with goldens; the kit on both; dogfood findings fixed first
   where they are extractor-independent.
5. Keep the API at 1.x (additive) unless the TypeScript work proves a breaking change necessary.

## 12. Commit

Hash: see `git log -1` (a committed file cannot contain its own commit hash). One commit, not pushed.

Changed files, grouped:

- **Plug-in API and core:** `src/ad2v/api.py` (new), `src/ad2v/plugins.py` (new),
  `src/ad2v/cli_plugins.py` (new), `src/ad2v/extract/code/plugin.py` (new),
  `src/ad2v/extract/code/rules/python-frameworks.yaml` (new), `src/ad2v/extract/code/rules/python.yaml`,
  `src/ad2v/pipeline.py`, `src/ad2v/rules.py`, `src/ad2v/manifest.py`, `src/ad2v/extract/files.py`,
  `src/ad2v/gitsource.py`, `src/ad2v/admin.py`, `src/ad2v/cli.py`,
  `src/ad2v/testing/__init__.py`, `src/ad2v/testing/conformance.py` (new).
- **Blind eval:** `src/ad2v/mcp/blind.py` (new), `fixtures/retrieval-eval/blind-template.yaml` (new),
  `docs/blind-eval.md` (new).
- **Security:** `src/ad2v/store.py`, `src/ad2v/validate.py`, `src/ad2v/view.py`,
  `src/ad2v/mcp/files.py`, `src/ad2v/specroots.py`, `src/ad2v/bootstrap.py`, `docs/security.md`
  (new), `SECURITY.md` (new).
- **Packaging and CI:** `pyproject.toml`, `src/ad2v/__init__.py`, `viewer/package.json`,
  `viewer/package-lock.json`, `viewer/src/app-main.ts`, `.github/workflows/ci.yml` (new),
  `.github/workflows/release.yml` (new), `docs/RELEASING.md` (new),
  `scripts/check_python_licenses.py` (new), `scripts/determinism_check.py` (new), `.gitignore`.
- **Examples:** `examples/plugins/` (new: README, routes-dsl-extractor, bottle-framework-pack, with
  fixtures).
- **Dogfood:** `docs/dogfood.md` (new), `scripts/dogfood_counts.py` (new).
- **Tests:** `tests/test_plugins.py`, `tests/test_security.py`, `tests/hostile.py`,
  `tests/test_blind_eval.py`, `tests/test_ci_workflows.py`, `tests/test_license_gate.py` (new);
  `tests/test_history.py`, `tests/test_p3_units.py`, `tests/test_llm.py`;
  `viewer/e2e/hostile.spec.ts` (new); `viewer/tests/fixtures/projections.json` (regenerated: epoch id).
- **Docs and tracking:** ADR-0063, 0064, 0065 (new), `docs/plugins.md` (new),
  `docs/spec/ad2v-format-v0.5.md`, `docs/dependencies.md`, `README.md`, `docs/claude-context.md`,
  `issues.md` (84–93), `pending.md`, `status.md`, `REPORT.md`, `docs/reports/P8.md` (new).
- **Sanitized:** `docs/reports/P4.md`, `docs/reports/P6.md`, `docs/reports/P7.md`,
  `fixtures/payments-recon/llm-vertex.yaml`; `docs/reports/P5-demo.html` rebuilt with the current
  viewer.

Cleanup: temporary venvs (plug-ins, wheel, source install, tools, final kit run), the P7 worktree
used for test counts, build artifacts in `examples/` and `build/`, the Playwright browsers installed
for this session, the MCP Inspector's npx cache entry created by `test:mcp`, the regenerated
screenshots of earlier phases (restored to their committed versions) and `viewer/test-results` were
deleted. Scratch files lived in the session scratchpad only.
