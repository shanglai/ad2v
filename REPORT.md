# P7 report: verified quickstart, settings prefixes, retrieval v2, the viewer's own chat, LLM refinements, viewer UX v2

All nine milestones are done. One commit, hash: see `git log -1`. Format **v0.5**. Version stays
0.6.0; P8 is the launch.

## 1. Accrued cost per phase

| phase | cloud / LLM spend | notes |
|---|---|---|
| P1 | $0 | local only |
| P2 | $0 | local only |
| P3 | $0 | local only |
| P4 | $0.592 | Vertex AI, gemini-3.8-flash, 125 calls |
| P5 | $0 | local only |
| P6 | $0 | local only |
| P6.1 | $0 | local only (fake provider) |
| **P7** | **$0.385** | Vertex AI, gemini-3.8-flash, 163 calls (M8, approved, cap $2.00) |
| **total** | **$0.977** | |

Claude's own usage is not metered per phase. The account is on the Max plan with extra usage
disabled, so this phase had no Claude cost beyond the subscription.

## 2. Milestones

| # | scope | result |
|---|---|---|
| M1 | verified quickstart | **done**: every local command run; `docs/quickstart.md` + `tests/test_quickstart.py` (slow); one CLI fix (ADR-0052) |
| M2 | settings prefixes + retrieval v2 | **done**: template 23 → 0 unresolved; MRR on P6's 25 questions 0.888 → 0.98 (ADR-0053, ADR-0054) |
| M3 | chat backend | **done**: `ad2v view --chat`, SSE, in-process tools, security, format v0.5 (ADR-0055–0057) |
| M4 | chat UI | **done**: panel, meter, estimate, Follow, citation chips, safe Markdown |
| M5 | viewer UX v2 | **done**: labels, edge declutter, portals, dashes, issue 71, nestgrid-v2 behind a flag (ADR-0061, ADR-0062) |
| M6 | LLM refinements | **done**: thinking per task, schema digest, judge roll-up (ADR-0058–0060) |
| M7 | tests and gates | **done**: everything green; dispatch performance within targets |
| M8 | live run | **done**: $0.385 of a $0.72 calibrated plan; REQ-009 caught; chat finding fixed and re-run |
| M9 | docs | **done** |

Changed files, grouped:

- **Python, new:**
  - `src/ad2v/chat/{agent,http,schemas}.py`;
  - `src/ad2v/extract/code/schema_digest.py`;
  - `src/ad2v/upgrade.py`;
  - `src/ad2v/llm/prompts/chat.v1.md`.
- **Python, changed:**
  - extraction and pairing: `extract/code/python.py` + `rules/python.yaml` (settings prefixes,
    `retrieval:` v2 keys, `settings_bases`), `pipeline.py` (`*.sql` inputs, digest), `pairing.py`,
    `manifest.py`;
  - retrieval and tools: `mcp/locate.py`, `mcp/evaluate.py`, `mcp/tools.py` (status order),
    `mcp/protocol.py` (`call_tool`);
  - LLM layer: `llm/config.py` (tasks, thinking), `llm/runner.py`, `llm/judge.py`,
    `llm/providers/*` (chat, function calling, thinking);
  - CLI, server and storage: `view.py`, `cli.py`, `cli_specs.py`, `bootstrap.py`, `layout.py`
    (v2), `store.py`, `admin.py`, `dump.py`, `ir.py`, `resources.py`, `ddl.py`.
- **Schema:** `schema/ad2v-v0.5.sql`, `schema/ir-v0.5.schema.json` (renamed),
  `docs/spec/ad2v-format-v0.5.md`.
- **Viewer:**
  - new: `ui/chat.ts`, `ui/markdown.ts`, `ui/intent.ts`, `model/declutter.ts`;
  - changed: `render/scene.ts`, `render/ribbons.ts`, `ui/app.ts`, `app-main.ts`,
    `data/LocalFileSource.ts`, `style.css`.
- **Fixtures:**
  - payments-recon: `settings.py`, `models.py`, `api/sql/schema.sql`, `classify.py` → `db.py`,
    the openapi audit endpoint, `expected*.yaml`;
  - `fixtures/sdd-presets/expected-questions.yaml`;
  - `fixtures/retrieval-eval/fastapi-template.yaml`.
- **Tests:**
  - Python: `test_quickstart`, `test_settings_prefix`, `test_retrieval_v2`, `test_chat`,
    `test_upgrade`, `test_thinking`, `test_schema_digest_rollup`;
  - viewer: `tests/chat.test.ts`, `tests/declutter.test.ts`;
  - e2e: `e2e/chat.spec.ts`, `e2e/ux-v2.spec.ts`.
- **Docs:**
  - ADR-0052 to ADR-0062;
  - `docs/quickstart.md` (the draft is deleted);
  - `README.md`, `docs/mcp.md`, `docs/dependencies.md`, `issues.md`, `pending.md`, `status.md`,
    `docs/claude-context.md`;
  - `docs/reports/P7-screens/` (32 files); `docs/reports/P5-demo.html` rebuilt.

Gates:
- **Python:** pytest **320 passed + 1 cloud skip**, 95% total coverage; new modules: chat 95–100%,
  schema_digest 95%, upgrade 90%, locate 97%, layout 99%. ruff check and format pass.
- **Viewer:** Vitest **49**, ESLint and tsc pass; `build`, `build:app` (1.01 MB, no wasm),
  `build:demo` and the license gate pass.
- **MCP:** `npm run test:mcp`: parity, **Inspector 38/38**, App e2e **10/10**.
- **Playwright:** P5 tour 2/2, replay camera 2/2, dim 3/3, chat 3/3, UX v2 2/2.
- **Determinism:** fixture and preset dumps match, with LF and CRLF+BOM inputs.

## 3. The quickstart

Every local command of the draft was run against a copy of `payments-recon`, the P3 history
scenario and the three preset fixtures.

| discrepancy | resolution |
|---|---|
| `specs bootstrap --from docs` resolved against the current directory, unlike `--spec-root` in the same command; run elsewhere it picked up ad2v's own `docs/adr/*` | **CLI fixed** (ADR-0052): `--from` is relative to `--repo`; sources outside the repository are refused |
| `history --commits HEAD~20..HEAD` fails on a repository with fewer than 21 commits | guide: explains it and offers `--commits HEAD` |
| `suggestions accept/reject` need `--manifest` (they edit it) | guide fixed |
| `<repo>/ad2v.yaml` is read automatically | guide: `--manifest` only for a manifest elsewhere |
| viewer step names differed from the UI | guide uses "Normative status", "Replay a workflow…", "Compare with parent", "Dim" |
| `specs bootstrap --plan` writes its cache to `<repo>/.ad2v/` | guide: add `.ad2v/` to `.gitignore` |
| (none) | new section "Your SDD format": ad2v / spec-kit / Kiro / custom / prose, each with an example and its `ad2v.yaml` |

**Guard test:** `tests/test_quickstart.py` (marker `slow`, 10 tests plus 1 cloud skip) runs each
step through the real CLI. It covers extract with and without `--spec`, status, inspect,
validate, history, log, diff, materialize, `extract --into`, `view` (the URL answers 200),
`llm plan`, `suggestions list`, `specs bootstrap --plan` / `review`, the three presets, and an MCP
`tools/list` over stdio. Paths are `pathlib`, so it runs on Windows and POSIX; the guide shows
both.

## 4. Settings prefixes (issue 70, ADR-0053)

Fixture: `api/recon_api/settings.py` adds `Settings(BaseSettings).AUDIT_PREFIX = "/v1" +
"/reconciliations"`, the router `audit = APIRouter(prefix=settings.AUDIT_PREFIX)` and the route
`GET /{run_id}/audit`.

| mode | route | link |
|---|---|---|
| off (default) | `http:api:GET /{run_id}/audit`, `path_unresolved`, tail `/{run_id}/audit` | `needs_review` (`unresolved_route_path`) |
| `pairing.path_constants: {"settings.AUDIT_PREFIX": "/v1/reconciliations"}` | `GET /v1/reconciliations/{run_id}/audit` | `implemented` + `prefix_from_path_constants` |
| `pairing.resolve_settings_defaults: true` | the same path | `implemented` + `prefix_from_settings_default` ("a default; the environment can override it at run time") |

**full-stack-fastapi-template** `cb740b6` (shallow clone, deleted): `path_unresolved` **23 → 0**
with either mechanism (23 routes). Five seeded samples (`random.Random(987654)`), read against
`app/core/config.py` (`API_V1_STR = "/api/v1"`), `app/main.py` and the routers:

| route | handler | verdict |
|---|---|---|
| `GET /api/v1/items` | `items.py::read_items` (`@router.get("/")` under `/items`) | correct |
| `POST /api/v1/private/users` | `private.py::create_user` | correct |
| `POST /api/v1/items` | `items.py::create_item` | correct |
| `GET /api/v1/users/me` | `users.py::read_user_me` | correct |
| `PUT /api/v1/items/{id}` | `items.py::update_item` | correct |

## 5. Retrieval v2 (ADR-0054)

Structural changes first:
- link propagation (λ 0.8) with a spec-side boost (1.3) for requirement questions;
- exact spec-id matching (bare, namespaced, Kiro `1.2`);
- test code ×0.5 unless the question mentions tests;
- resource kind words plus the names of the functions that touch them;
- `ad2v_status` ordered by kind priority.

Then **one** weight-tuning pass on the 48 tuning questions of the combined 70.

Frozen question files (hash of the LF working copy). Each was written before measuring, with
held-out ids drawn by seed 987654:
- `fixtures/payments-recon/expected-questions.yaml` `db64b48b777ee4ae…` (40 questions; 25 are P6's,
  unchanged);
- `fixtures/sdd-presets/expected-questions.yaml` `b7cadf59088a4ae4…` (10);
- `fixtures/retrieval-eval/fastapi-template.yaml` `a21eb162d5f5629a…` (20, code only; gold
  written from the code before any retrieval ran on it).

MRR with tools (the tool a model would call), P6 code → P7, same maps:

| set | all | tuning | held-out | recall@5 (all) |
|---|---|---|---|---|
| P6's original 25 | 0.888 → **0.980** | 0.953 → 0.971 | 0.750 → **1.000** | 0.953 → 0.960 |
| fixture 40 | 0.813 → **0.900** | 0.853 → 0.911 | 0.729 → **0.878** | 0.908 → 0.950 |
| presets 10 | 0.642 → **0.850** | 0.595 → 0.857 | 0.750 → 0.833 | 0.700 → 0.900 |
| template 20 | 0.529 → **0.762** | 0.512 → 0.660 | 0.567 → **1.000** | 0.550 → 0.750 |

By question type (fixture 40, MRR):

| type | before | after |
|---|---|---|
| requirement | 0.58 | **0.72** |
| risk | 0.83 | 1.00 |
| status | 0.81 | 1.00 |
| describe | 0.75 | 1.00 |
| where | 0.92 | 0.88 |
| flow, endpoint, diff | 1.00 | 1.00 |

Targets:
- q14 0.25 → 1.0 (status order);
- q15 0.20 → 1.0 (propagation);
- q16 0.50 → 1.0;
- q25 0.25 → 1.0 (resource words).

Tuning raised the pooled objective from 2.336 to 2.460, moving name 0.5 → 1.0, qname 0.5 → 2.0,
narration 2.0 → 3.0 and the intent scale ×1.5. Held-out questions were not used for tuning.
**Caveat:** during the structural work the eval script printed held-out rows as well, so those
numbers were visible before the final score.

Five worst questions:

| q | MRR | why |
|---|---|---|
| p04 "success criterion for charge latency?" | 0 | vocabulary: SC-001 says "complete in under 3 seconds", never "latency" |
| t03 "how does a user log in?" | 0 | test functions with "login" in their names still outrank `login_access_token` (×0.5 is not enough); "log" is 3 characters, below the prefix minimum |
| t15 "where is the database session created?" | 0 | Alembic migrations (session/database words) outrank `deps.get_db` |
| q34 "what must the worker log when a nightly run completes?" | 0.08 | no "requirement" trigger word, so no spec intent; code wins |
| t10 "database initialized with the first superuser?" | 0.08 | Alembic again |

## 6. The chat (ADR-0056, ADR-0057)

Architecture:
- The model runs in the `ad2v view` process; the browser gets only the UI and a token.
- Tool calls go in-process through the MCP dispatcher (`Server.call_tool`): the same schemas,
  validation and fenced output. The tool list has no write tool.
- Declarations are generated from the MCP schemas, for Vertex `functionDeclarations` and for
  OpenAI `tools`.
- At most 6 model steps per turn. The model ends with `ad2v_answer {answer_markdown, citations,
  show}`, and the last step is forced to answer.
- Citations are checked against the turn's tool results, and echoed injections are flagged.
- Each model call is an `llm_results` row (task `chat`, format v0.5) and each turn an `llm_runs`
  row.

Security:
- 127.0.0.1 only;
- a `secrets.token_urlsafe(32)` token, delivered in the URL fragment and required as
  `X-Ad2v-Token`;
- `Host` must be `127.0.0.1|localhost:<port>`, against DNS rebinding;
- `Origin` must match and is required on POST;
- JSON only, at most 16 KB, no CORS, `OPTIONS` → 405.

A test exists for each rejection: bad Host, bad Origin, missing Origin, missing token, wrong
token, wrong content type, oversized body, OPTIONS, POST outside the API, an empty question.

**Offline eval** (fake provider, `tests/test_chat.py`, 17 tests), all pass:
- a grounded answer with `show` (the map follows);
- a hallucinated citation dropped and flagged;
- a tool-result injection echoed and flagged (not flagged when the answer doesn't echo it);
- the budget cap mid-turn, then the next turn refused;
- the iteration cap;
- a cancel;
- an approve request answered with the CLI command only;
- the adaptive estimate;
- SSE framing over chunked transfer;
- the disabled state shows the enabling command.

The UI e2e runs against a real `ad2v view --chat` server with the fake provider, in both themes.

**Live** (Vertex, thinking `low`, on the 8-epoch history map without fake LLM rows; a $0.50 cap
per session):

| question | tools called | calls | citations valid / dropped | show | tokens in / out | USD |
|---|---|---|---|---|---|---|
| 1. Which requirement is drifting and why? | status ×3, search, get_node, links, neighborhood, locate, show | 6 | 0 / 0 | focus | 17,203 / 310 | $0.0141 (**no answer: step cap**) |
| 2. Walk me through starting a reconciliation run. | status, locate, get_node, links, workflow, get_node, workflow | 4 | 12 / 0 | replay | 14,937 / 931 | $0.0147 (it also answered Q1) |
| 3. What changed between epoch 2 and 3? | diff, locate, get_node | 4 | 4 / 0 | diff | 13,682 / 555 | $0.0123 |
| 4. Where do we call the LLM inside a loop, and how risky is it? | risks, get_node ×3 | 5 | 3 / 0 | focus | 18,043 / 545 | $0.0156 |
| 5. Is there any endpoint that the spec defines but the code lacks? | status ×2, search, links ×2 | 6 | 7 / 0 | — | 25,734 / 626 | $0.0216 |
| 1, re-run after the fix | status ×3, get_node, links (+ the forced answer) | 6 | 2 / 0 | focus | 14,477 / 412 | $0.0124 |
| 2, re-run after the fix | locate, get_node, workflow ×2 | 5 | 10 / 0 | replay | 17,639 / 649 | $0.0157 |

- Every citation was valid (no hallucinated ids) and no answer was flagged.
- The first run exposed issue 77:
  - Q1 spent its 6 steps on tools;
  - the unanswered question stayed in the history, so Q2 answered both.
- **Fix:** the last step forces `ad2v_answer`, and unanswered turns are not carried. Q1 and Q2
  were re-run (11 calls, $0.028), and both answered.

Two answers, verbatim:

> **Q4.** We have LLM calls inside loops in two places in `api/recon_api/classify.py`:
>
> 1. **`classify_unmatched`** (`loop#bc51e9e6` / `llm_call#67251e28`):
>    - **Location:** `api/recon_api/classify.py` (lines 16–21).
>    - **Risk Level:** **High (Severity 7.5)**.
>    - **Exposure:** It is reached by **1 active workflow** (`GET /v1/reconciliations/{run_id}/unmatched`). Invoking the LLM iteratively for each unmatched item within an HTTP request path can lead to significant latency spikes, unbounded token/API costs, and rate limit errors during request handling.
>
> 2. **`classify_run`** (`loop#d1ff137d`):
>    - **Location:** `api/recon_api/classify.py` (lines 31–32).
>    - **Risk Level:** **Medium (Severity 5.0)**.
>    - **Exposure:** Currently reached by **0 workflows** (unreachable in production traffic paths).

> **Q1 (re-run).** Strictly speaking, no requirement node is marked with the `drift` status directly, but the spec endpoint **GET /reconciliations/{run_id}/unmatched** (and its corresponding implementation route **GET /v1/reconciliations/{run_id}/unmatched**) is currently in **drift**.
>
> The drift occurs because:
> 1. **Missing query parameter**: The route implementation (`api/recon_api/routes.py::list_unmatched`) is missing the required query parameter `as_of`.
> 2. **Failing tests**: Associated tests are failing (`api/tests/test_routes.py::test_req_004_unmatched_rows_get_a_label`).

Both are correct for this map: it has no judge rows, so its normative drift is the endpoint. Q5's
answer ("no endpoint is missing; audit is `needs_review` because of its route prefix") is also
correct at the head epoch.

## 7. LLM refinements

**Judge A/B** (fixture, 10 labeled links; containers are now rolled up, not judged):

| | P4 (default thinking) | P7 default | P7 low |
|---|---|---|---|
| accuracy | 9/11 = 0.82 | 8/10 = **0.80** | 9/10 = **0.90** |
| κ | 0.70 | 0.64 | **0.81** |
| validity | — | 1.0 | 1.0 |
| REQ-009 (planted drift) | `cannot_tell` (missed) | **drift 0.90** | **drift 0.90** |
| output tokens (11 calls) | — | 14,608 | **2,154** |
| cost per call | $0.0044 | $0.0060 | **$0.0017** |

- The two runs agree on 9 of 10 links. Default thinking also called the `{id}`/`{run_id}`
  endpoint `partial`.
- Both judged REQ-006 `conforms` where the human label is `partial` (issue 80).
- Both REQ-009 rationales cite the per-attempt re-classification. For example, from the low run:
  "classify_run iterates over every attempt … without deduplication, potentially classifying
  transactions multiple times".
- Roll-ups (low run):
  - `container:api` drift 0.99 (conforms 7, drift 2);
  - `container:worker` partial 0.95;
  - `CMP-001` drift.

**Schema digest sample** (`datastore:env:RECON_DB_URL`, as the judge sees it):

```
table classifications (sqlalchemy, api/recon_api/models.py)
  id Integer pk
  run_id String not_null -> recon_runs.run_id
  reference String not_null
  label String
  (no unique constraint besides the primary key)
table ledger (sql, api/sql/schema.sql)
  reference TEXT pk
  amount_cents INTEGER not_null
table recon_runs (sqlalchemy, api/recon_api/models.py)
  ...
table unmatched (sql, api/sql/schema.sql)
  run_id TEXT not_null -> recon_runs.run_id
  reference TEXT not_null
  unique (reference, run_id)
```

**Summaries and narrations at `low`** (fixture: 67 + 37 calls, $0.186):

| task | P4 cost per call | P7 low cost per call | change |
|---|---|---|---|
| summarize | $0.0039 | **$0.0015** | −60% |
| narrate | $0.0059 | **$0.0023** | −61% |

- Actual output was 0.48× (summarize) and 0.90× (narrate) of the static estimate; with default
  thinking in P4 it was ≈ 2.2×.
- Samples:
  - `api/recon_api/matching.py` (card): "Pairs bank transactions with ledger records and
    determines whether transaction amounts match within an accepted tolerance." The deep
    version names the 5-cent tolerance against REQ-003's one cent, and the N+1 loop.
  - The `POST /v1/reconciliations` narration, level 1: "The API receives the reconciliation
    request and begins fetching all bank statements concurrently."
- **Verdict:** accurate, specific and grounded. Quality is on par with P4 for these structural
  summaries.

**Bootstrap, live** (`specs/operations.md`, 1 call, 844 in / 1,785 out, $0.0073). The proposal,
verbatim (header comment omitted):

```markdown
# Proposed requirements from operations.md

## Component: Run export {#CMP-X001}

- [REQ-X001] When an operator requests an export of a completed run, the system shall provide a CSV file containing every matched pair and every unmatched transaction together with its probable-cause label.
  <!-- event; source lines 3-5 -->
- [REQ-X002] When an export is older than 90 days, the system shall delete the export automatically.
  <!-- event; source lines 5-6 -->

## Component: Bank statement feed {#CMP-X002}

- [REQ-X003] When the bank statement feed is more than 30 minutes late, the system shall page the on-call engineer.
  <!-- event; source lines 8-8 -->

## Component: Run approval {#CMP-X003}

- [REQ-X004] If a run has unlabelled unmatched transactions, then the system shall prevent approval of the run.
  <!-- unwanted; source lines 8-9 -->
```

It is **faithful**: every obligation in the prose became a requirement, with the right EARS
pattern and source lines. One statement was left out: "runs the reconciliation every night at
02:00 UTC" (issue 81). `ad2v specs review` reported 3 components, 4 requirements, current.

**Dispatch summarize + narrate, re-estimated** (plan only, `low`, structural, head):

| | P4 estimate | P7 static | P7 calibrated (observed factor at low) |
|---|---|---|---|
| summarize (1,690 calls) | — | $3.91 | $2.42 (×0.48) |
| narrate (1,786 calls) | — | $8.84 | $8.18 (×0.90) |
| **total** | $12.72 static, ≈ **$24.5** calibrated | $12.75 | **$10.60** (−57%) |

## 8. Cloud activity log

All calls were Vertex AI `generateContent` on project `mapper-cat-3`, location `global`, model
`gemini-3.8-flash` (reported `modelVersion` `gemini-3.8-flash`). Every request carried the labels
`project=ad2v` and `ad2v_task=<task>`. Auth was ADC through
`gcloud auth application-default print-access-token`. Pricing: $0.75 / $3.75 per 1M tokens
(introductory until 2026-12-31).

| part | task (label) | calls | tokens in / out | plan static | plan calibrated | actual |
|---|---|---|---|---|---|---|
| a1 judge, default | judge | 11 | 14,680 / 14,608 | $0.020 | $0.035 | **$0.066** |
| a2 judge, low | judge | 11 | 14,680 / 2,154 | $0.020 | $0.035 | $0.019 |
| b summarize + narrate, low | summarize, narrate | 104 | 106,537 / 28,336 | $0.208 | $0.400 | $0.186 |
| c chat, 5 questions, low | chat | 25 | 89,599 / 2,967 | $0.185 | $0.239 | $0.078 |
| c' chat, Q1 + Q2 re-run after the fix | chat | 11 | 32,116 / 1,061 | (within the chat cap) | | $0.028 |
| d specs bootstrap | extract_prose | 1 | 844 / 1,785 | $0.006 | $0.013 | $0.007 |
| **total** | | **163** | **258,456 / 50,911** | **$0.438** | **$0.721** | **$0.385** |

- Default-thinking judge output was 4.4× the static estimate, above the calibrated plan. Every
  `low` part came in under its static plan.
- **No GCP resources, API keys or IAM changes were created.** No `countTokens` calls were made:
  all plans were offline (chars/4). No other cloud calls were made.

## 9. Viewer UX v2

**Screenshots** (`docs/reports/P7-screens/`):
- the P5 tour re-taken in both themes (`tour-*`, 12);
- the App set (`app-*`, 10);
- replay levels 1 and 2 with dim, both themes (4);
- a chat turn with the map following, both themes (`*-chat-follow.png`);
- dispatch top level before and after declutter, in dark, and with nestgrid-v2 (4).

**Layout v1 vs v2** (ADR-0062):

| | nestgrid-v1 | nestgrid-v2 |
|---|---|---|
| dispatch density, all parents | 0.498 | **0.552** |
| dispatch density, top level | 0.531 | **0.604** |
| dispatch code-root extent | 8,475 × 4,341 | **2,792 × 2,775** (4.8× less area) |
| fixture density | **0.456** | 0.428 |
| stability, P3 history | 835/835 (100%) | 835/835 (100%) |
| dispatch first render | 1.31 s | **0.87 s** |

**Decision:** v1 stays the default. The rule was "unless v2 wins on both", and v2 ties on
stability and is less dense on the small fixture. v2 is opt-in:
`ad2v layout --algorithm nestgrid-v2`, then the viewer with `?layout=nestgrid-v2`.

**Performance on dispatch** (Intel UHD, ANGLE D3D11, headless, `ad2v view`):

| measure | result |
|---|---|
| pan + zoom, 10 s | **59.9 fps median / 59.5 p5**, 6 draw calls |
| replay stepping, dim on/off, both orders | 59.9 median, p5 59.5–59.9 (issue 74 not reproduced) |
| first render | 1.31 s v1 (issue 73: P5 0.86 s, P6.1 1.2 s), 0.87 s v2 |
| declutter at home | 716 edges → 50 drawn (the heaviest + touching), 666 hidden |
| in-process tools (the chat's path), 50 calls each, p50 / p95 | get_node 41/53, search 6/9, neighborhood 34/43, status 20/30, **locate 59/72**, overview 22/28, risks 2/3, links 1/1, show 0.4/0.9 ms; first locate 0.93 s |

All are within the P6 targets (< 150 / < 300 ms). Locate is slower than in P6 (37 ms): retrieval
v2 adds propagation and id matching (issue 78).

## 10. Licenses, deviations, open questions

**Licenses:** no new Python or npm dependencies. npm stays at 166 packages (MIT 131,
Apache-2.0 18, ISC 7, BSD-2-Clause 6, BSD-3-Clause 3, BlueOak 1). The license gate passes. Python
uses the stdlib only for the chat, SSE, the token (`secrets`) and the digest (`ast`).

**Deviations and decisions not fixed by the prompt (with ADRs):**
- **Format v0.5** (ADR-0055): needed for `chat` rows and roll-ups. 0.4 files upgrade in place
  when written.
- The chat ends turns through an `ad2v_answer` tool (ADR-0056). After the live run, the last
  step is forced to answer and unanswered turns leave the history; Q1 and Q2 were re-run for
  $0.028, within the approved caps.
- The seed rule's one exception is the chat token (`secrets`, ADR-0057).
- Thinking `off` maps to `low` on 3.7/3.8 Flash, which have no `minimal`; budgets are refused
  there (ADR-0058).
- `*.sql` files became epoch inputs, and a synthetic datastore holds unlinked models (ADR-0059).
- Containers were removed from judging: judge jobs went 12 → 11 and labeled links 11 → 10
  (ADR-0060). The `prune --drop-llm-cache` bug was found and fixed.
- v2 layout is behind a flag (ADR-0062).
- The settings fixture router adds a new endpoint (audit) rather than changing existing ones
  (ADR-0053).
- The live chat ran on the history map without fake LLM rows, not the demo, so the model never
  read made-up summaries.
- The demo `docs/reports/P5-demo.html` was rebuilt with the P7 viewer.

**Issues:**
- Closed: 42, 43, 55, 67, 70, 71.
- Addressed: 54 (v2 behind a flag), 68 (70-question set).
- Not reproduced: 74.
- New: 77 (fixed), 78, 79, 80, 81, 82, 83 (fixed).

**Open questions for P8 (open-source launch), ranked:**
1. The default layout: switch to nestgrid-v2 (much denser on real repos, faster first render) and
   collapse single-child chains (`dispatch > dispatch > src > dispatch`)?
2. Packaging: a wheel with the built viewer and app, version 0.7.0, CHANGELOG/CONTRIBUTING, a
   public demo map without fake rows (or with live rows from a run like M8's).
3. Retrieval on real code: de-weight migrations and tests harder (issue 79); synonyms for spec
   vocabulary.
4. Judge: a second labeled repository before claiming accuracy; return-shape context for
   `partial` (issue 80); keep `low` as the judge default? It scored better and costs 29%, but on
   only 10 links.
5. Chat: a per-turn cap in the UI, streaming text, and a local OpenAI-compatible server test.
6. Remote MCP deployment (auth, TLS) for hosts that need HTTPS.
