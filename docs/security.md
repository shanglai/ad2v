# ad2v threat model

Scope: ad2v 0.7.0.dev0 (P8). ad2v reads a repository and its specs and writes one SQLite file; a
viewer, a chat and an MCP server read that file on the user's machine. Nothing runs repository
code. Everything listens on 127.0.0.1 only. The optional LLM layer is bring-your-own-model and
spends the user's money.

Severity scale (ad2v's own context, not CVSS): **high**: code execution or data exfiltration
without the user's deliberate action; **medium**: spending money, disclosure of local data
or integrity loss, triggered by opening untrusted input; **low**: denial of service of a local tool,
or an issue that needs the user to opt into something unsafe; **info**: hardening.

Reporting: `SECURITY.md`. Findings of the P8 review: §9.

## 1. A malicious `.ad2v` file

Threat: someone sends a crafted file. Opening it in `ad2v view`, the MCP App or `ad2v mcp` must not
run script, write files or exfiltrate; `ad2v validate` must say it is not conformant.

| attack | mitigation | test |
|---|---|---|
| XSS in any rendered text (names, qualified names, paths, attrs, summaries, narrations, evidence, rationales, labels, meta) | the viewer never uses `innerHTML` (DOM `textContent` only; the chat Markdown renderer builds nodes and links only to node ids); labels are drawn on a canvas; strict CSP in `ad2v view` (`script-src 'self' 'wasm-unsafe-eval'`, no inline script, `object-src`, `base-uri`, `form-action`, `frame-ancestors` all `'none'`); the MCP App runs in the host's sandboxed iframe and makes no requests | `viewer/e2e/hostile.spec.ts`: payloads in every free-text column and JSON leaf, in both viewer modes; no script runs, no element is injected, payloads appear as text, no page error |
| huge strings | the viewer truncates labels; `validate` flags any text value over 1 MiB (source blobs exempt) | e2e: a 100,000-character name renders; `tests/test_security.py` (2 MiB name rejected) |
| deep nesting | `validate` flags JSON nested deeper than 64 levels (scanned without parsing) and survives a `RecursionError` | `test_security.py` (5,000 levels) |
| wrong format version | readers accept 0.4/0.5 only; writers 0.5 (0.4 upgraded) | `test_security.py` (`9.9` rejected) |
| extra tables, views, triggers; a built-in view redefined | `validate` lists every trigger, unknown object and changed view; readers open `mode=ro` (+ `query_only` in MCP), so triggers cannot fire; writers (`extract --into`, `llm run`, …) refuse a file with triggers or altered views; the MCP server refuses to serve it; every connection sets `PRAGMA trusted_schema = OFF` | `test_security.py`: read-only insert fails, node count unchanged, `open_rw` and `extract --into` refuse, MCP refuses |

Residual risk: **low**. The standalone viewer runs SQL (sql.js) over the whole file in the page; a
file whose views were redefined to be pathological (recursive CTEs) can hang that browser tab. The
viewer does not compare the schema with the format's before querying (the MCP server and the Python
tools do).

## 2. The local server (`ad2v view`)

| item | mitigation | test |
|---|---|---|
| exposure | binds 127.0.0.1 only, random port by default | `test_view.py` |
| methods | GET/HEAD for files; POST only on `/api/chat/*` with `--chat`; PUT/DELETE/PATCH/OPTIONS refused, so no CORS preflight ever succeeds | `test_view.py`, `test_security.py` |
| path traversal | static paths resolved and contained in the viewer directory; the map is served only at one fixed path | `test_security.py` (`..`, `%2e%2e`, `%2f`) |
| DNS rebinding | **P8:** every request must carry `Host: 127.0.0.1:<port>` or `localhost:<port>` (it was checked only for chat before) | `test_security.py` |
| headers | CSP (§1), `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, **P8:** `Referrer-Policy: no-referrer` | `test_security.py` |

Residual risk: **low**: any local process can read the map over the port, like any local file.

## 3. The chat endpoint (spends money)

`ad2v view --chat` (ADR-0056/0057): a per-launch token from `secrets` in the URL fragment (never sent
in a request line, never logged), echoed in `X-Ad2v-Token`; `Host` and `Origin` checks; JSON only
with a 16 KiB body cap; no CORS; a session budget (`--chat-budget-usd`, default $0.25) and a per-turn
estimate; ≤ 6 model steps per turn; cancel stops before the next model call; the provider needs a
manifest with pricing. Tests: `tests/test_chat.py` (security rejections, budget mid-turn, iteration
cap, cancel). Residual risk: **low**: a local process that reads the browser's URL (or the
terminal output) can spend up to the session budget.

## 4. Prompt injection through repository or spec content

All repository and spec text sent to a model is fenced (`<untrusted-data id=…>`, content-derived ids,
closing tags neutralized), instruction-like phrases are flagged, outputs are schema-validated, and
LLM results are informative only (never in an epoch id, never a normative status). Chat answers must
cite node ids returned by the turn's own tool calls (hallucinated citations dropped and flagged); the
chat and MCP have **no write tools**: a request to change something gets the copyable CLI command
(ADR-0029, ADR-0042, ADR-0056). Tests: `test_llm.py`, `test_chat.py` (injection echoed is flagged,
write requests get the command only), `test_mcp.py` (untrusted text wrapped). Residual risk:
**medium** (inherent): a poisoned repository can still bias a summary, a judgment or a chat answer;
it cannot write, run code or leave the session budget.

## 5. The MCP server (`ad2v mcp`)

stdio by default; Streamable HTTP only on 127.0.0.1 with `Origin`/`Host` validation; `--file` or
`--root` with strict containment (absolute paths, `..`, symlinks out of the root refused; messages do
not echo resolved paths); SQLite opened `mode=ro` + `query_only`; **P8:** files with triggers or
altered views are refused; 13 read-only agent tools; repository text in results wrapped as
`untrusted_text`. Tests: `test_mcp.py` (origin/host/methods, traversal, read-only connections,
untrusted text), `test_security.py`. Residual risk: **low**.

## 6. Third-party extractor and framework plug-ins

Plug-ins are **trusted code**: they run in-process with the user's privileges (ADR-0063..0065,
`docs/plugins.md`).

| threat | mitigation | residual |
|---|---|---|
| code execution by merely installing a package | opt-in: only built-ins are active; others need `ad2v.yaml` `extractors.enabled` or `--extractor`; `extract` never imports a disabled plug-in; `extractors list` does not import them without `--inspect`; names that shadow a built-in or are registered twice are refused | a plug-in the user enables can do anything the user can (**accepted; documented**) |
| reading outside the repository | the core pre-reads exactly the claimed files and hands them over a `FileAccessor`; the conformance kit fails a plug-in that opens other files (audit hook) or asks the accessor for them | not enforced at run time (**low**: trusted code) |
| network access, subprocesses, writes | conformance kit `side_effects` check (audit hook on socket connect/resolve/bind, subprocess, write-mode opens) | not enforced at run time (**low**) |
| nondeterminism poisoning epochs | plug-in identity (name, version, api, rules hash) is part of the epoch rules and id; the kit checks two runs, a CRLF+BOM copy and id stability | a plug-in that is nondeterministic only on some inputs passes the kit (**low**) |
| crash or hang | third-party plug-ins run with exception isolation and a timeout (`--plugin-timeout`, default 600 s); a failure is printed, recorded in `epochs.attrs.plugin_failures` and skipped; `--strict` makes it fatal; a hook that fails cannot leave partial changes (it runs on a copy) | a timed-out thread keeps running until the process exits (**low**) |

Tests: `tests/test_plugins.py` (opt-in, shadowing, failures, timeouts, strict, kit catching
undeclared kinds, nondeterminism, accessor misuse, real file opens, network, subprocess, writes).

## 7. Path traversal in CLI arguments and repository-supplied paths

Paths the **user** types (`--repo`, `--spec`, `--manifest`, `--out`, `--test-results`) are the user's
choice. Paths that come from **the repository itself** must not reach outside it, because a map may be
shared:

| path | mitigation | test |
|---|---|---|
| `ad2v.yaml` `spec_root` | **P8:** must resolve inside the repository (before: `../../x` was read into the map) | `test_security.py` |
| auto-detected `specs/` etc. | **P8:** a symlink that points outside the repository is not a spec root | `test_security.py` (skipped on Windows without symlink privilege) |
| `ad2v.yaml` `rules_overlay` | **P8:** must stay inside the manifest's directory | `test_security.py` |
| `specs bootstrap --from` | repository-relative, contained (ADR-0052) | `test_bootstrap.py` |
| `specs approve <proposal>` | only files directly in `<spec root>/.ad2v-extracted/`; **P8:** `--to` must be inside the repository | `test_security.py` |
| `mcp --root` | strict containment (§5) | `test_mcp.py` |
| file walking | never follows symlinks (`os.walk(followlinks=False)`, symlinked files skipped) | `test_determinism_and_cli.py` |
| `history` | `git archive` into a temporary directory; never checks out or runs code | `test_history.py` |

## 8. Supply chain

- Runtime closure (Python): 10 dependencies, all MIT except `typing_extensions` (PSF-2.0); no
  `certifi`. `scripts/check_python_licenses.py` gates it in CI; npm has its own gate
  (`viewer/scripts/check-licenses.mjs`).
- `pip-audit` 2.10.1 (run from a throwaway virtual environment, outside the tree) on the runtime
  closure and on the dev environment: **no known vulnerabilities**.
- `npm audit`: **0** vulnerabilities in runtime dependencies; **3 high** in the dev/build chain, all
  one advisory: `braces` ≤ 3.0.3 (GHSA-vfj7-8cjw-p6xm, stack exhaustion on deeply nested brace
  patterns) via `micromatch` via `vite-plugin-singlefile` (used only to build the single-file demo
  and the MCP App). No patched `braces` exists; npm's only "fix" downgrades the plug-in to 0.9.0, a
  breaking change. The patterns come from our own build configuration, so it is not exploitable
  (**low**, open).
- CI actions pinned by full commit SHA; workflows have `contents: read`; the release workflow is
  disabled (`docs/RELEASING.md`).
- Tools used but not depended on (build, twine, pip-audit, the MCP Inspector) run outside the tree
  (`docs/dependencies.md`).

## 9. Findings of the P8 review

| # | issue | surface | severity | status |
|---|---|---|---|---|
| S1 | `ad2v.yaml` `spec_root` could point outside the repository, so a repository could make ad2v read local files into a map the user then shares | §7 | medium | fixed |
| S2 | `ad2v.yaml` `rules_overlay` could point outside the repository (read into the stored rules) | §7 | medium | fixed |
| S3 | an auto-detected `specs/` symlink could point outside the repository | §7 | medium | fixed |
| S4 | `ad2v view` checked `Host` only on chat endpoints; a DNS-rebinding page could read the served map | §2 | medium | fixed |
| S5 | writers (`extract --into`, `llm run`) would fire triggers embedded in a hostile file | §1 | medium | fixed (writers refuse; `trusted_schema = OFF`) |
| S6 | `validate` did not report extra tables, views or triggers, huge strings or deep nesting (deep JSON crashed it) | §1 | low | fixed |
| S7 | the MCP server served files with redefined views (wrong answers, errors) | §1, §5 | low | fixed (refused) |
| S8 | `specs approve --to` accepted a destination outside the repository | §7 | low | fixed |
| S9 | CSP lacked `object-src`, `base-uri`, `form-action`, `frame-ancestors`; no `Referrer-Policy` | §2 | info | fixed |
| S10 | the conformance kit did not detect network, subprocess or write side effects | §6 | low | fixed (`side_effects` check) |
| S11 | the `ad2v.chat` package was missing from the wheel (P7) | packaging | info | fixed |
| S12 | plug-ins are not sandboxed (in-process, full privileges) | §6 | low | open (by design; opt-in and documented) |
| S13 | the standalone viewer can be hung by pathological SQL views in a hostile file | §1 | low | open |
| S14 | `braces` advisory in the build-only dependency chain | §8 | low | open (no fix available) |
| S15 | prompt injection can bias informative LLM output | §4 | medium | open (inherent; informative only, no write tools) |
| S16 | a timed-out plug-in thread keeps running until the process exits | §6 | low | open |
