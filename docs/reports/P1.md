# REPORT: ad2v P1 (format spec v0.1, IR, deterministic extractor)

Reviewer summary: P1 is complete. The format spec, schema, IR, the Python/Gherkin/OpenAPI/Markdown
extractors, static workflows with projection, fixture, CLI and tests are done. No LLM calls exist
anywhere. **66 tests pass.** The canonical dump is byte-identical across repeated runs, a CRLF+BOM
copy and a renamed checkout. Adding an unrelated function creates exactly one new id and changes no
existing id.

Environment: Windows 11, Python 3.12.3, pip + venv (`uv` was not installed; see ADR-0008).

## 1. Milestones

| Milestone | Scope | State | Commit |
|---|---|---|---|
| M1 | IR, SQLite schema v0.1, ids/hashing, store, canonical dump, format spec | done | `f0eb889` |
| M2 | Glyph grammar v0.1 + `glyphs.py` | done | `ac9803c` |
| M3 | tree-sitter Python extractor, `CodeExtractor` protocol, `rules/python.yaml` | done | `9586d56` |
| M4 | Gherkin, OpenAPI 3.x, Markdown/EARS spec extractors + convention doc | done | `485139a` |
| M5 | Static workflows, spec workflows, `project()` + ADRs 0002–0009 | done | `db94e08` |
| M6 | `fixtures/payments-recon` + `expected.yaml` golden tests | done | `833a1fb` |
| M7 | CLI, `validate`, determinism / ID-stability / rules-hash tests, perf smoke, docs, this report | done | in final commit |

Changes that landed in M7 on top of earlier milestones: read-only file access for readers,
`epochs.rules_hash` (ADR-0010), `model` added to the `summaries`/`narrations` primary keys, a
generated per-column N/I appendix in the format spec, the setuptools build backend (ADR-0008), and
the `direct_calls_touch` rule (issue 3).

## 2. Tests

`pytest`: **66 passed, 0 failed** (~8–16 s on this machine). `ruff check` and `ruff format --check`
are clean.

| test file | tests | covers |
|---|---|---|
| `test_ids.py` | 11 | normalization, id/hash formulas, Merkle order independence |
| `test_store.py` | 6 | write/read, dump determinism, FK and LLM-provenance CHECKs |
| `test_glyphs.py` | 3 | closed shape set, modifiers roll-up, gateway trapezoid |
| `test_python_extractor.py` | 14 | structure, imports/calls, resources, risks, ports, spec refs, never executes code, CRLF/BOM, syntax errors |
| `test_spec_extractors.py` | 4 | Markdown/EARS, Gherkin (Background, Outline, Rule, duplicates), OpenAPI spans/refs |
| `test_workflows.py` | 5 | projection invariant (500 seeded random traces), trace order/parallel/cycles/limits |
| `test_fixture_golden.py` | 10 | `expected.yaml` fully satisfied |
| `test_determinism_and_cli.py` | 10 | determinism, ID stability, rules hash, validate, CLI, LF-only stdout |
| `test_schema_doc.py` | 3 | every DDL column marked N/I; spec appendix in sync |

Line coverage (pytest-cov), total **94%**:

| module | coverage |
|---|---|
| `ids.py` | 100% |
| `glyphs.py` | 100% |
| `store.py`, `dump.py` | 100% |
| `workflows.py` (incl. `project`) | 98% |
| `extract/code/python.py` | 94% |
| `extract/spec/markdown.py` / `gherkin.py` / `openapi.py` | 100% / 97% / 95% |
| `validate.py` | 91% |
| `pipeline.py` | 84% (mostly the `.git` HEAD reader branches) |
| `ddl.py` | 78% (the regeneration entry point is not under test) |

Confirmed passing:

- **Determinism** (`test_extract_twice_identical`, `test_crlf_bom_copy_identical`,
  `test_checkout_directory_name_does_not_matter`): two runs, a copy with every text file converted to
  CRLF and BOMs added, and a copy under a different directory name all give identical canonical
  dumps.
- **ID stability** (`test_id_stability_after_adding_unrelated_function`): after a function is
  inserted in the middle of `matching.py`, the only new id is that function's. No id disappears. The
  `subtree_hash` changes for exactly the four ancestors (module, component, container, system),
  and siblings keep their `content_hash` even though their lines moved.
- **Rules hash** (`test_rules_file_change_changes_rules_hash`): editing the rules file changes
  `rules_hash`, the epoch id and the dumped `epochs` row. A CRLF-only change does not.
- **Projection invariant**: property tests use a seeded PRNG (987654), not `hypothesis`, because
  `hypothesis` is MPL-2.0 (ADR-0002).

## 3. Fixture extraction summary (`fixtures/payments-recon`)

14 code files (272 lines) and 3 spec files give 94 nodes and 162 edges in about 0.2 s.

| kind | n | kind | n | kind | n |
|---|---|---|---|---|---|
| system | 1 | http_route | 4 | loop | 2 |
| container | 2 | mcp_tool | 1 | retry | 1 |
| component | 3 | cli_command | 2 | fan_out | 1 |
| module | 14 | event_consumer | 1 | transaction | 0 (not risky) |
| class | 1 | datastore | 1 | llm_call | 1 |
| function | 22 | queue | 2 | spec_doc | 3 |
| | | external_service | 1 | spec_component | 3 |
| | | llm_endpoint | 1 | requirement | 8 |
| | | | | scenario | 4 (incl. Background) |
| | | | | scenario_step | 11 |
| | | | | spec_endpoint | 4 |

**Risky behaviors** (all five planted patterns found; no others):

| node | risk |
|---|---|
| `matching.py::match_batch@loop#1` | `io_in_loop` (N+1, found transitively through `db.fetch_ledger_entry` → `session.execute`) |
| `classify.py::classify_unmatched@loop#1` and its `@llm_call#1` | `llm_in_loop` |
| `bank_client.py::fetch_statement@retry#1` | `unbounded_retry` (tenacity, no `stop=`) |
| `bank_client.py::fetch_all_statements@fan_out#1` | `fan_out` (`asyncio.gather(*genexpr)`) |

The `with session.begin()` in `record_run` is detected as a candidate but not emitted, because it
has no risk. `behavior.emit_all: true` emits non-risky candidates. That is tested for loops and
fan-outs, not specifically for this transaction.

**Resources** are named from environment variables: `datastore:env:RECON_DB_URL`,
`external_service:env:BANK_API_URL`, `llm_endpoint:env:RECON_CLASSIFIER_MODEL`,
`queue:env:RECON_EVENTS_TOPIC` (publishes) and `queue:env:RECON_UPLOADS_SUBSCRIPTION` (consumes).

**Ports**: 4 HTTP routes (router prefix `/reconciliations` combined with the `include_router`
prefix `/v1`), the MCP tool `reconciliation_summary`, the Typer commands `run-nightly` and
`listen-uploads`, and the Pub/Sub event consumer `handle_statement_uploaded`.

**Workflows**: 11 in total: 8 static code workflows (one per port) and 3 spec workflows (one per
scenario, with the Background step first). `POST /v1/reconciliations` traces through fan-out →
retry → bank API, then the N+1 loop → ledger DB, then `record_run` → DB writes (12 steps). None is
truncated.

**How the P2 candidates appear today**:

- **Dangling ref**: `# ad2v: REQ-099` on `db.py::record_run` is kept in the node's `spec_ref` and
  written to `unresolved_refs(src=record_run, ref='REQ-099', reason='not_found')`. No edge is
  written. The `extract` summary prints it.
- **Missing candidate**: `spec_endpoint POST /v1/reconciliations/{run_id}/approve` (OpenAPI,
  `x-ad2v-refs: [REQ-007]`) and the scenario "Approve a reconciliation run" (`@REQ-007`) have no
  `http_route` with the same `(method, path)`.
- **Orphan candidate**: `http_route GET /internal/debug/stats` has no `spec_endpoint` and no
  annotation.
- Resolved annotations: 7 code functions → REQ-001..006 via `annotated_as`, including the test
  `test_req_003_*` from its name. Scenarios, endpoints and the feature → requirements/component.

## 4. Performance smoke

Shallow clones in `bench/` (gitignored), measured on this Windows 11 laptop, Python 3.12.3. The
clones were **deleted after measuring**.

| repo (commit) | .py files | LOC | nodes / edges | workflows (steps) | build, median of 5 | SQLite write, median of 5 | .ad2v size |
|---|---|---|---|---|---|---|---|
| fastapi/full-stack-fastapi-template (`cb740b6`) | 43 | 2,918 | 251 / 594 | 26 (116) | 0.16 s | 0.39 s | 0.66 MB |
| Netflix/dispatch (`dd2837e`) | 717 | 84,041 | 5,352 / 12,329 | 301 (10,540) | 3.65 s | 1.86 s | 11.42 MB |

- Both were deterministic across two runs (identical dumps) and passed `ad2v validate` with 0
  problems. No workflow hit `max_steps`.
- **Variance**: build time is stable (dispatch 3.2–3.9 s). SQLite write time is not (dispatch
  1.8–7.2 s). End-to-end first runs occasionally took much longer (13–40 s on the small repo in one
  session), which points to the filesystem/antivirus on new files rather than the extractor (issue
  13). Peak Python heap for dispatch was about 100 MB (tracemalloc, which itself slows the run).
- Findings on dispatch: 290 HTTP routes, 11 CLI commands, 7 resources, 158 `io_in_loop` (21 also
  `nested_loop_io`), 1 `unbounded_retry`, 1 `fan_out`.

**Precision of `io_in_loop`, stated honestly.** Before the `direct_calls_touch` fix, a 6-loop
sample had 4 true positives. Both false positives came from `sqlalchemy.inspect()`. After the fix,
a seeded sample of **10 of the 158 flagged loops were all true positives** (per-item service or DB
calls such as `tag_service.get_or_create(db_session=…)` inside a `for`). **10/10 is a small sample:
the Wilson 95% lower bound on precision is ≈ 0.72.** **Recall has not been measured.** There is no
labeled set of loops, and known gaps (issues 5–7: instance-attribute clients, untyped parameters,
app factories) certainly cause misses. A labeled corpus is in `pending.md`.

## 5. Deviations from the prompt

| # | deviation | ADR | rationale |
|---|---|---|---|
| 1 | `hypothesis` not used; seeded randomized property tests instead | 0002 | `hypothesis` is MPL-2.0 (copyleft) |
| 2 | Extra normative table `unresolved_refs` | 0003 | dangling references cannot be FK-valid edges; a placeholder node would pollute the map |
| 3 | Gherkin Feature is always `spec_component`; `@REQ-x` tags are *references*, not definitions; `annotated_as` also spec → spec | 0005 | one definition per ID keeps identity independent of file order |
| 4 | Extra risk flag `slow_io_in_transaction` | 0006 | otherwise transactions could never be emitted by default |
| 5 | Ports are children of their container (`exposes` + `calls port→handler`); port qualified names include the container | 0004 | notches stay visible on collapsed containers; same route in two services |
| 6 | Build backend setuptools (not hatchling); argparse CLI; no `uv` | 0008 | hatchling depends on `pathspec` (MPL-2.0); `uv` not installed |
| 7 | `epochs.rules_hash` column, included in the epoch id and canonical dump | 0010 | output depends on the rules file; the prompt's hashes covered only code and specs |
| 8 | `workflows.attrs_json`, `glyphs.variant/size_weight/has_interior`, `layout.algorithm`, `tours.workflow_id` columns | 0001, glyph grammar | needed to encode truncation, the class/function variants, size channel, LOD, and deterministic layouts |
| 9 | `summaries`/`narrations` primary keys include `model` | spec §5 | several models' outputs must coexist without a key change in P3 |
| 10 | Workflow projection is by **call depth** (not containment) | 0009 | gives the partition invariant by construction; a containment projection can be added |

Everything else follows the prompt, including all six principles, the closed kind/edge enums (plus
the flag above) and the required tables.

## 6. Open questions and decisions needed for P2 (ranked)

1. **Pairing policy for routes vs. endpoints.** Exact `(method, path)` match, or normalize path
   templates (`{id}` vs `{run_id}`, trailing slashes, mount prefixes that differ from the OpenAPI
   `servers` base path)? The fixture needs only exact matching, but real repos won't. Decide before
   writing `links`.
2. **Epoch storage model.** Keep full snapshots per epoch (simple, what P1 writes, ~11 MB per
   epoch for 84k LOC), or store deltas keyed by `subtree_hash`? This affects file size and every
   reader.
3. **What does "stale" key on?** The `content_hash` of the paired nodes only, or `subtree_hash`
   (catches changes in callees and children)? `subtree_hash` is stricter but noisier.
4. **Requirement ↔ code granularity.** Link a requirement to the annotated function only, or also
   to the workflows or ports that reach it? This decides how "verified" is computed (a test that
   calls the function vs. a scenario mapped to a port).
5. **Behavior-ordinal stability.** Accept that inserting a loop before another renumbers it
   (issue 9), or switch to a content-anchored identity (e.g. ordinal among loops with the same
   iterable text)? Changing it later changes ids, so decide early.
6. **Rules governance.** Who may edit `rules/python.yaml` per project (a manifest overlay?), and
   does an overlay join `rules_hash`? ADR-0010 says yes. The overlay mechanism is not built.
7. **Monorepos without a manifest.** Is "top-level dir with pyproject/Dockerfile" good enough, or
   should P2 read workspace files (uv/poetry workspaces, docker-compose services) to infer
   containers and `replicas`?

## 7. Dependencies and licenses

Full list: [`docs/dependencies.md`](docs/dependencies.md). **No copyleft dependency in runtime,
development or build.**

- Runtime: tree-sitter (MIT), tree-sitter-python 0.25.0 (MIT), gherkin-official (MIT), PyYAML
  (MIT), jsonschema (MIT). Transitive: attrs, jsonschema-specifications, referencing, rpds-py
  (MIT), typing_extensions (PSF-2.0).
- Dev: pytest (MIT), pytest-cov (MIT), coverage (Apache-2.0), ruff (MIT). Transitive: iniconfig,
  pluggy (MIT), packaging (Apache-2.0/BSD), Pygments (BSD-2), colorama (BSD-3).
- Build: setuptools (MIT, no dependencies).
- Rejected: hypothesis (MPL-2.0), hatchling (pulls in pathspec, MPL-2.0).

## 8. Schema concerns for P2–P5

1. **Full snapshot per epoch.** `epoch_id` is in every primary key, so multi-epoch files work
   without schema changes. The cost is size: every epoch repeats every node. If P2 chooses deltas,
   it will need new tables (e.g. `node_versions`) plus views, not changes to `nodes`. That is
   allowed, but readers will have to learn the view.
2. **Link history.** `links` has one row per (epoch, link). The state machine (spec §6) is spread
   across epochs. "When did this become drift?" needs a join across epochs or a future
   `link_events` table.
3. **`workflow_steps.node_ids_json` is not indexable.** "Which workflows pass through node X?" (a
   core viewer/MCP question) needs a JSON scan. P4/P5 will probably want a derived
   `workflow_step_nodes` table.
4. **Evidence lines are noisy.** `edges.attrs.lines` shifts on unrelated edits. That is fine inside
   an epoch, but a structural diff must ignore it or it reports false changes.
5. **Informative rows in the canonical dump.** P3's LLM rows (summaries, narrations, links with
   `provenance='llm'`) will be in the dump. Dump equality across runs then holds only if LLM
   outputs are cached by `input_hash`/`prompt_hash`. The spec should say that the determinism
   guarantee covers normative rows, and that tooling may offer `--normative-only`.
6. **`meta.value` is mixed N/I per key.** It works, but a reader has to know the key list. A
   `meta.class` column would have been cleaner. It can be added without changing meanings.
7. **Layout is keyed by `(node_id, lod, algorithm)`.** Viewers with user-adjusted layouts (pinned
   nodes) will need `source='user'` rows or a separate table. `algorithm` could carry `user`, but
   that should be decided explicitly in P4.
8. **Spec-side roots have no parent.** `spec_doc` nodes are roots, and the code side has a
   `system` root. A viewer that wants one tree must synthesize a root. Adding a `spec_root` kind
   later is additive, but it changes depth numbers on the spec side.
