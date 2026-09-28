# REPORT: ad2v P3 (multi-epoch storage, incremental extraction, diff, lineage, stale, format v0.3)

**Summary.** All seven milestones are done. One `.ad2v` file now holds a **history**: a chain of
epochs whose base facts are content-addressed and deduplicated, behind views shaped exactly like
v0.2. The file also has:
- a file-level parse cache;
- `ad2v history` over git commits;
- deterministic rename **lineage**, and **`stale`** with `# ad2v: REQ-012@<fp8>` re-annotation;
- `ad2v diff` (table / json / ≤ 60-line markdown);
- `log`, `pin`, `prune` with GC, and `materialize`.

The P2 carry-overs are fixed: the orphan policy, and rules-driven entry points for main blocks,
Celery, APScheduler, `schedule` and nested Click. The format is now **v0.3**. There are no LLM
calls and no cloud resources. **161 tests pass**, coverage is 95%, and ruff is clean.

Performance:
- **dispatch, 20 commits:** 9 epochs in **1.16× the size of one epoch** (target ≤ 2.5×).
- **incremental epoch:** **0.51×** of a cold extraction from a fresh export (target ≤ 0.60), or
  0.86× of a warm cold run.
- **parse-cache hit rate:** 99.5%.

The bench found two crashes (issues 25, 26) and two performance problems (issues 28, 30). The
top-10 review found a false #1 caused by a name-resolution bug (issue 27). All are fixed, and the
bugs have regression tests.

Environment: Windows 11, Python 3.12.3, pip + venv. The P2 report is at
[`docs/reports/P2.md`](docs/reports/P2.md); this file is also at `docs/reports/P3.md`.

## 1. Milestones

| Milestone | Scope | State |
|---|---|---|
| M1 | Storage v0.3: `*_versions` + `(seq, vid)` membership, views `nodes`/`edges`/`unresolved_refs`/`test_results` of the v0.2 shape, V column class, epochs `change_kind`/`pinned`/`label`/`materialized`, derived rows only for head + pinned (`epoch_materialized`), `code_fact_versions`, `link_state`, `id_lineage`, narrations `mode` in the PK, `dump --epoch <id\|head\|all>`, format spec v0.3 | done |
| M2 | `extract --into`, parse cache (zlib local facts keyed by path/content/rules/extractor version), `--no-cache`, hit rate in the summary, "no changes" for identical inputs, test results carried forward, `ad2v history` (git archive into a temp dir, incremental between commits) | done |
| M3 | Lineage (`same_content` on name-masked fingerprints, `anchored_header` Jaccard ≥ 0.6 with ties → `needs_review`, `same_route`), stale rules, `REQ@fp8` re-annotation | done |
| M4 | `ad2v diff` (table/json/md ≤ 60 lines), `log`, `pin`/`unpin`, `prune` (re-parent, GC, VACUUM), `materialize`, example `examples/github-action/ad2v-diff.yml` | done |
| M5 | History fixture: a scripted temp git repo (8 commits) asserted by `fixtures/payments-recon/expected-history.yaml`, incl. a CRLF+BOM determinism variant | done |
| M6 | Performance on dispatch (20 commits) and full-stack-fastapi-template (10 commits, plus the last 10 Python-touching commits) | done; clones deleted |
| M7 | `pairing.orphan_policy` (auto/strict/off), entry-point recognizers with `attrs.trigger`, dispatch top-10 re-run | done |

**Commit.** There is a single final commit (per the session rules): **hash: see `git log -1`**.
Files changed:

- **Moved/renamed:** root `REPORT.md` (P2) → `docs/reports/P2.md` (already identical, root copy
  removed, now replaced by this report); `schema/ad2v-v0.2.sql` → `ad2v-v0.3.sql`;
  `schema/ir-v0.2.schema.json` → `ir-v0.3.schema.json`; `docs/spec/ad2v-format-v0.2.md` →
  `ad2v-format-v0.3.md` (rewritten).
- **New source:** `src/ad2v/{admin,diff,gitsource,history,materialize}.py`,
  `src/ad2v/extract/code/python_local.py`.
- **Changed source:** `cli, ddl, dump, ir, junit, manifest, pairing, pipeline, resources, store,
  validate, workflows, __init__`, `extract/code/python.py`, `extract/code/rules/python.yaml`,
  `extract/spec/__init__.py`.
- **Docs:** ADRs 0017–0025 (new), `docs/spec/visual-tokens-v0.2.md` (`stale` no longer
  "reserved"), `docs/dependencies.md`, `README.md`, `status.md`, `issues.md`, `pending.md`,
  `REPORT.md`, `docs/reports/P3.md`.
- **Example:** `examples/github-action/ad2v-diff.yml` (not wired to any repository).
- **Fixture:** `expected.yaml` (main-block port), `expected-history.yaml` (new).
- **Tests:** `test_history.py`, `test_p3_units.py`, `history_scenario.py` are new;
  `test_store.py` rewritten; `test_schema_doc.py`, `test_fixture_golden.py`,
  `test_determinism_and_cli.py` updated.
- **Build:** `pyproject.toml` (version 0.3.0).

## 2. Tests

**161 passed, 0 failed** (`pytest`, ~40–60 s on this machine; the history tests build git repos).
`ruff check` and `ruff format --check` are clean.

| file | tests | covers |
|---|---|---|
| `test_history.py` (new) | 13 | the 8-commit history epoch by epoch against `expected-history.yaml` (statuses, links + evidence, lineage, change kinds); fingerprint → `fingerprint_mismatch` on a first epoch; diffs 2→3, 4→5, 1→8 (composed lineage); **every epoch's views equal a fresh single-epoch extraction** of that commit; derived rows materialized on demand equal stored ones; **determinism**: two runs and a CRLF+BOM variant give identical `dump --epoch all --normative-only` (commit SHAs masked, ADR-0025); re-running history is a no-op; cache hits; prune + GC + validate; CLI (`history`, `log`, `diff` in 3 formats, `pin`/`unpin`, `materialize`, `prune`); `extract --into`; **incremental export equals a full export** (deleted dirs, glob-like names, `export-ignore` fallback) |
| `test_p3_units.py` (new) | 16 | orphan policy auto/strict/off + YAML `off` + in `config_hash`; entry points: main block (both operand orders), Celery tasks + beat, APScheduler + `schedule`, **nested Click with colliding names**, reach raised by entry points; **port with two handlers**; **function-local import shadows a module def**; cached == uncached extraction (graph and epoch id); stale cache versions ignored; `parse_refs` / `find_node`; lineage: Jaccard threshold, ties → `ambiguous`, `same_route`, `same_content` needs a unique match |
| `test_store.py` (rewritten) | 10 | views have exactly the v0.2 columns; version dedup across epochs (shared versions, spans per epoch); dump determinism; narrations `mode` in the key; FKs (membership → versions / epochs); `change_kind`; `open_rw` refuses other formats |
| `test_determinism_and_cli.py` | 11 | P2 coverage + corruption now includes a tampered `node_versions` payload and **a dangling edge endpoint** (checked by `validate`, not FKs) |
| others | 111 | P1/P2 suites (pairing, severity/rules/JUnit, tokens, golden fixture incl. the new main-block port, extractor, workflows, ids, glyphs, spec extractors, schema-doc sync incl. exactly 3 V columns) |

Coverage (line), total **95%**. **New modules:** `admin` 99%, `python_local` 96%, `materialize`
95%, `history` 93%, `diff` 91%, `gitsource` 91%, all ≥ 90%. Rewritten or extended modules:
`dump` 100%, `workflows` 99%, `store` 96%, `python.py` 94%, `pipeline` 91%, `validate` 89%.

## 3. History fixture

`tests/history_scenario.py` builds a temporary git repo from `fixtures/payments-recon` with fixed
author and dates, and makes these commits. `expected-history.yaml` asserts each epoch.

| seq | commit (step) | change_kind | lineage | status changes (effective, spec side unless noted) | evidence |
|---|---|---|---|---|---|
| 1 | baseline | initial | — | REQ-001/002/003 verified, REQ-007 specified, `POST …/approve` missing | — |
| 2 | rename `amounts_match` → `amounts_equal` (identical body) | code | `same_content` | REQ-003 **stays verified** across the rename; REQ-002 → **stale** (the caller `match_batch` changed its call site, a real edit) | `code_changed_unverified` on REQ-002 ↔ `match_batch` |
| 3 | REQ-003 text: "one cent" → "two cents" | spec | — | REQ-003 → **stale**, and `amounts_equal` and its test (code side) → stale | `spec_changed_since` |
| 4 | add the approve route | code | — | `POST …/approve` missing → **implemented**; REQ-007 specified → implemented; REQ-003 stays stale | — |
| 5 | change `start_run`'s body (same test results) | code | — | REQ-001 → **stale** (verified code changed, no fresh run); its test link stays verified (tests are exempt) | `code_changed_unverified` |
| 6 | new passing JUnit run only | tests_only | — | REQ-001 → **verified**, REQ-002 → verified; REQ-003 **stays stale** (a test run cannot clear a spec change) | `retested` |
| 7 | edit a loop header in `match_batch` (`transactions` → `transactions[:]`) | code | `anchored_header` (score 1.0) | the renamed loop is followed, not reported as removed + added; REQ-002 → **stale** again (`match_batch`'s body changed, no fresh run) | `code_changed_unverified` |
| 8 | `# ad2v: REQ-003@<fp8>` on `amounts_equal` and its test | code | — | REQ-003 → **verified**, `amounts_equal` verified | `reannotated` |

`ad2v diff --format md` from epoch 2 to 3, verbatim (16 lines):

```markdown
### ad2v: epoch #2 (3fd2f144) → #3 (b80a4d66) (spec)

0 added, 0 removed, 0 renamed, 3 modified nodes; 3 status transitions (3 worse); 0 new risky behaviors; 2 spec items changed; 0 workflows changed.

| transition | nodes |
|---|---|
| `verified -> stale` | 3 |

**Needs attention**
- `api/recon_api/matching.py::amounts_equal`: verified → **stale**
- `api/tests/test_matching.py::test_req_003_amounts_within_one_cent_match`: verified → **stale**
- `REQ-003`: verified → **stale**

Spec items: 0 added, 0 removed, 2 changed (CMP-001, REQ-003)

<sub>ad2v diff: deterministic, no LLM. Qualified names point into the .ad2v map.</sub>
```

From epoch 4 to 5, verbatim (13 lines):

```markdown
### ad2v: epoch #4 (669e8bd9) → #5 (e396302a) (code)

0 added, 0 removed, 0 renamed, 2 modified nodes; 2 status transitions (2 worse); 0 new risky behaviors; 0 spec items changed; 0 workflows changed.

| transition | nodes |
|---|---|
| `verified -> stale` | 2 |

**Needs attention**
- `api/recon_api/routes.py::start_run`: verified → **stale**
- `REQ-001`: verified → **stale**

<sub>ad2v diff: deterministic, no LLM. Qualified names point into the .ad2v map.</sub>
```

The whole-history diff (1 → 8) reports the two renames once each, by composing lineage along the
chain (`amounts_match → amounts_equal`, `same_content`; the loop, `anchored_header`), and the
approve route and handler as added.

## 4. Performance

Measured on shallow clones (deleted afterwards), Windows 11, one run each after warm-up runs;
times are noisy on this machine (P1 issue 13), so medians are reported. **Cold** is a
single-epoch `extract --out --no-cache` of the head commit **reading a freshly exported tree**, the
same condition as every `history` epoch. Numbers for a second, warm run are given too.

| | Netflix/dispatch (`dd2837e`, 84,041 LOC, 5,374 nodes) | full-stack-fastapi-template, last 10 commits (`cb740b6`) | template, last 10 commits touching `*.py` (`10dd26c`) |
|---|---|---|---|
| commits walked / epochs written / no-ops | 20 / 9 / 11 | 10 / 1 / 9 | 68 / 10 / 58 |
| single-epoch size | 14.98 MB | 0.82 MB | 0.83 MB |
| history size (naive: epochs × single) | **17.42 MB** (134.8 MB) | 0.82 MB | 1.02 MB (8.27 MB) |
| **dedup ratio** vs one epoch (target ≤ 2.5×) | **1.16×** | 1.00× | 1.23× |
| growth per incremental epoch | 0.31 MB | — | 0.021 MB |
| cold extraction (fresh export / warm) | 14.3 s / 8.5 s | 0.54 s / 0.37 s | 0.42 s / 0.36 s |
| **incremental epoch, median** (target ≤ 60% of cold) | **7.26 s = 0.51×** (0.86× warm) | — (no Python change) | **0.21 s = 0.51×** (0.60× warm) |
| no-op commit (inputs identical), median | 0.51 s (1.4 s wall incl. git) | 0.07 s (0.32 s wall) | 0.06 s (0.28 s wall) |
| **parse-cache hit rate** (incremental epochs) | **99.5%** (5,664 / 5,694 files) | — | 96.6% (400 / 414) |
| size after `prune --keep-last 5` (+ GC + VACUUM) | 15.57 MB (4 epochs removed) | 0.82 MB (nothing to remove) | 0.92 MB (5 removed) |

On the template, only 1 of the last 10 commits touches Python (the rest are release notes and
dependency bumps), so 9 are correct no-ops. I added the last 10 Python-touching commits (a
contiguous range of 68 commits) to get a meaningful incremental measurement. All bench files passed
`ad2v validate`, including the pruned ones.

**Profile: parse vs local vs global** (dispatch). Cold, fresh export: read inputs 6.4 s, **parse
0.82 s**, **local passes 2.33 s** (local facts 2.04 + apply 0.28), **global passes 2.72 s** (global
walk 1.87 + specs/refs 0.09 + workflows/severity 0.10 + lineage/pairing/status 0.36), write 1.94 s.
The shares are read 9% (on a fresh tree; it is much slower than a warm read), parse 9%, local 30%,
global 28%, write 25%.

The mean incremental epoch (dispatch, 8 epochs) takes 6.9 s:

| phase | seconds |
|---|---|
| read inputs | 0.91 (median 0.6; the 2nd epoch still paid 3.4 s for fresh files) |
| load parent graph | 0.41 |
| parse | 0.65 |
| local facts (hits) | 0.09 |
| apply local | 0.33 |
| global walk | 1.56 |
| other code-extraction steps | 0.35 |
| specs / workflows / lineage + pairing | 0.62 |
| write | 2.02 |

The cache removes the local share almost entirely (2.04 → 0.09 s). Parse (kept on purpose,
ADR-0018), the global passes and the write are what is left: ~70% of an incremental epoch. Going
further needs call-graph-closure invalidation (out of scope, pending.md).

**What changed during M6.**

| | before | after | fix |
|---|---|---|---|
| dispatch history size (9 epochs) | 67.6 MB = **3.42×** | 17.4 MB = 1.16× | integer `(seq, vid)` membership in WITHOUT ROWID tables instead of text ids + 2 indexes (ADR-0017, issue 28); drop the old head's derived rows before writing (issue 29) |
| dispatch single epoch | 19.75 MB | 14.98 MB | same |
| dispatch incremental epoch, median | 11.0 s (wall 17.2 s) | 7.3 s (wall 7.6 s) | export only changed paths between commits (ADR-0018 §5, issue 30) |
| dispatch history, 20 commits, wall | ~5 min | ~2 min | same |

The first dispatch run also crashed on two bugs, now fixed: nested Click commands with the same
name (issue 25), and a port with two handlers (issue 26).

## 5. Dispatch top-10 before / after the entry-point recognizers

The new recognizers found 3 main-block ports and 38 Click commands with a trigger on dispatch
(nested groups included). dispatch has no Celery, APScheduler or `schedule` code: its scheduler is
a project-specific `@scheduler.add(every(...))` decorator. Reach only grows from entry points,
so no severity went down.

**The review found a bug first.** The first P3 run put `cli.py::install_plugins@loop` at **#1**
(9.5, reach 5). The workflows reaching it were `signals process`, `signals consume`,
`server slack`, `scheduler start` and `plugins install`. The first four do
`from dispatch.common.utils.cli import install_plugins` *inside* the function, and that import was
hoisted to module scope, where the Click command `cli.py::install_plugins` wins. I fixed it:
function-local imports now bind in the function's scope (issue 27, regression test), and the loop
now has reach 1 and rank #5. The table below is after the fix.

| P3 # | sev | reach | node (`src/dispatch/…`) | P2 # (sev) | why it moved | verdict (manual read) |
|---|---|---|---|---|---|---|
| 1 | 8.5 | 3 | `database/manage.py::setup_fulltext_search@loop` | 2 (7.5) | reach 1 → 3: newly recognized CLI commands reach it | real IO in a loop (trigger sync per table), **low impact**: one-time setup (same as P2) |
| 2 | 8.0 | 2 | `incident_cost/service.py::calculate_incident_response_cost_with_cost_model@loop` | 1 (8.0) | unchanged; pushed down by #1 | **genuine**: nested per-event participant lookups |
| 3 | 7.5 | 1 | `cli.py::consume_signals@loop` | 9 (5.0, reach 0) | the `signals consume` Click command (nested group) is now an entry point | **genuine**: per-org → per-project → per-plugin DB work and plugin calls |
| 4 | 7.5 | 1 | `cli.py::process_signals@loop#f8a665a9` (`for organization`) | — (5.0, reach 0) | `signals process` recognized | **intended worker loop**; per-signal flow + commit per instance is by design, but it is the production hot path |
| 5 | 7.5 | 1 | `cli.py::install_plugins@loop` | — (5.0, reach 0) | `plugins install` recognized (was a false #1, see above) | **genuine N+1** (per plugin and per plugin event lookups, commit per plugin), low impact: install time |
| 6 | 7.5 | 1 | `cli.py::process_signals@loop#3cbc87c7` (`while True`) | — (5.0, reach 0) | as #4 | **same body as #4 flagged twice** (issue 32); an intended polling loop |
| 7 | 7.5 | 1 | `notification/service.py::filter_and_send@loop` | — (5.0, reach 0) | reached from a newly recognized CLI workflow | **genuine**: one search-filter DB query per notification × filter, then a send |
| 8 | 5.7 | 5 | `entity/service.py::find_entities@loop` | 5 (5.4) | reach 4 → 5 | **genuine N+1**: `get_by_value_or_create` per entity (same as P2) |
| 9 | 5.7 | 5 | `definition/service.py::create@loop` | 3 (5.7) | unchanged; pushed down | **genuine N+1**: `term_service.get_or_create` per term |
| 10 | 5.7 | 5 | `entity_type/service.py::create@loop#ab21…` | 6 (5.4) | reach 4 → 5 | **genuine**: `find_entities` per signal instance |

Left the top-10:
- `term/service.py::create@loop` (P2 #4, 5.7) is now #11. It is tied at 5.7, and ties go by node id.
- `entity_type/service.py::create@loop#cfb9…` (P2 #7, 5.4 → 5.7) is now #12.
- `dispatch_aws/plugin.py::…consume@loop` (P2 #8, 5.0) is #22. It is called through
  `plugin.instance`, which is still unresolved (issue 31).
- `task/scheduled.py::sync_tasks@loop` (P2 #10, 5.0) is #23. The project's own scheduler
  decorator is not recognized; a rules overlay could add it.

**Verdict: 10/10 do IO in a loop, and 7/10 are the kind of N+1 or nested DB work a reviewer should
look at** (#2, #3, #5, #7, #8, #9, #10). #1 and #5 run at setup or install time. #4 and #6 are one
intended polling worker counted twice.

The recognizers did what P2 issue 17 asked: the CLI-driven signal consumers moved from reach 0
(#9, below everything reachable) into the top 5. The scheduled `sync_tasks` did not, because
dispatch's scheduler is custom.

## 6. Orphan policy on spec-less repositories

Same commits as P2. Neither repo has specs or annotations.

| repo | P2 (before) | P3 `strict` (P2 behavior) | **P3 `auto` (default)** |
|---|---|---|---|
| full-stack-fastapi-template (`cb740b6`) | 42 orphan / 209 none | 45 orphan / 209 none (+3 main-block ports) | **0 orphan / 254 none**, `meta.spec_coverage = none` |
| Netflix/dispatch (`dd2837e`) | 462 orphan / 4,882 none | 492 orphan / 4,882 none (+30 newly recognized CLI ports) | **0 orphan / 5,374 none**, `meta.spec_coverage = none` |

Under `auto`, a spec-less map shows no red. Adding the first spec item turns the policy on, and
`ad2v diff` then reports the resulting orphans as status transitions. `strict` keeps the P2
behavior, and `off` never assigns orphans. The effective policy is part of `config_hash`
(ADR-0022).

## 7. Deviations and interpretations

| # | deviation / interpretation | ADR |
|---|---|---|
| 1 | **Parse-cache hits still parse.** The prompt says hits skip tree-sitter parsing. They skip the per-file local passes (30% of cold), not parsing (9%), because the global passes walk syntax trees. Re-parsing is cheaper than serializing trees | 0018 |
| 2 | Membership rows use integer surrogates `(seq, vid)` in WITHOUT ROWID tables. Node references in edges, test results and derived tables are therefore **validator checks, not SQL FKs** (views cannot be FK targets either) | 0017 |
| 3 | Workflow inputs that are not in the graph (events, retry wrappers, entry bindings) and `link_state` are stored as base facts, so any epoch re-materializes from the file alone, even after its parent is pruned | 0017, 0020 |
| 4 | Test results carry forward when none are given. Only **fresh** results (given, and with a different hash) can clear a code-side stale (`retested`) | 0019 |
| 5 | Change is judged on name-masked fingerprints (`body_hash`), so a pure rename is neither a change nor a stale. Test functions are exempt from code-side change | 0020 |
| 6 | Stale details: spec and code both changed keeps the structural status (`both_changed`); a code change after `implemented` is evidence only; a fingerprint mismatch is stale even on a first epoch; `descendants_changed` only without rename or own change | 0020 |
| 7 | Ambiguous `anchored_header` ties are stored as `id_lineage` rows with method `ambiguous` (never applied) plus `needs_review` evidence | 0020 |
| 8 | Entry points reuse existing kinds (`cli_command` / `event_consumer` + `attrs.trigger`), with no new node kinds. Main-block handler = the module. Nested Click commands are named by group path; a port may bind several handlers (one workflow) | 0021 |
| 9 | The effective orphan policy enters `config_hash`; YAML `off` read as `false` is accepted | 0022 |
| 10 | `diff` compares an epoch with an ancestor only; lineage composed along the chain; md capped at 60 lines | 0023 |
| 11 | `prune` re-parents without recomputing epoch ids; lineage old ids are validated only against an immediately preceding epoch | 0024 |
| 12 | `pinned`/`label`/`materialized` and `vid` are class I; the dump shows logical tables (views + non-storage tables) only; the CRLF determinism test masks commit SHAs | 0025 |
| 13 | `history` exports the first commit in full, then only changed paths (still `git archive`, into one temp dir); full export when `export-*` attributes are used | 0018 |
| 14 | Performance: "cold" is measured on a fresh export (the condition every history epoch reads), with warm numbers alongside; the template got a second measurement over its last 10 Python-touching commits | n/a |

## 8. Open questions for P4

1. **The semantic judge's IR slice.** For a link (spec item, code node), what does the judge see?
   My proposal: the spec text; the code node's own span; the signatures (not bodies) of its direct
   callees in the port's workflow; and the resources it touches (from `workflow_steps`). Snippet
   budget: cap the code span at ~150 lines, with the head and tail kept, and callee signatures at
   ~40 lines. Open points:
   - Are those caps right? Dispatch has handlers over 300 lines.
   - Does a route's judge also see its OpenAPI schema?
   - How is a `stale` link re-judged? Should the judge receive the diff since `agreed_epoch_id`?
2. **LLM caching by `version_key`.** Node versions are content-addressed, so a judgment keyed by
   `(spec version_key, code version_key, prompt_hash, model, model_version)` can be reused in every
   epoch where both versions are unchanged, and costs then scale with change. But if the prompt
   includes callee signatures, the key must also cover them: a closure hash over the slice's
   version keys. That is the same call-graph-closure question as incremental global passes. Should
   the key be the hash of the **exact serialized slice** (simple, always correct) rather than of
   version keys?
3. **Where `input_hash` rows live.** Derived tables hold rows only for materialized epochs, but
   LLM output is expensive and must not be recomputed when an epoch is re-materialized or a
   parent is pruned. Proposal:
   - store LLM results as a content-addressed base fact, e.g.
     `llm_results(input_hash PK, prompt_hash, model, model_version, output_json, confidence,
     created_at)`, all informative;
   - have `links` (`provenance='llm'`), `summaries` and `narrations` reference it by `input_hash`;
   - let GC keep the rows any kept epoch references.

   Open points: should `prune` keep unreferenced LLM rows as a cache, since they are costly? And
   does `dump --normative-only` keep excluding them entirely? (It should.)
4. **Epoch identity vs LLM configuration.** LLM rows are informative, so the model, prompts and
   thresholds must stay out of the epoch id. But `needs_review` from a judge below threshold
   changes node statuses. Should judged statuses live in a separate informative status layer, so
   the normative `node_status` stays reproducible without the LLM?
5. **Narrations per mode.** `mode` is now in the narrations key. Should P4 write both modes, or
   only `containment` (the default) and generate `call_depth` on demand?

(For reference only: P4 will use Vertex AI in a GCP project via ADC. **No cloud project was
touched in P3.**)

## 9. Dependencies

**No dependency was added in P3.** Storage, the parse cache (`zlib`), history (`zipfile`,
`tempfile`, `subprocess`) and the diff use the standard library only. `ad2v history` runs the
**git CLI** as an external program (`rev-list`, `diff-tree`, `ls-tree`, `show`, `archive`). git is
not linked, imported or redistributed, and only `history` needs it. The runtime, development and
build dependency set is unchanged from P2: all MIT / BSD / Apache-2.0 / PSF-2.0, with setuptools as
the build backend. There is **no copyleft** anywhere, including transitive and build-time
dependencies. The bench clones (dispatch: Apache-2.0; template: MIT) were deleted after measuring.
Details: [`docs/dependencies.md`](docs/dependencies.md).
