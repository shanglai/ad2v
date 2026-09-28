# The ad2v file format, version 0.4

Status: **draft, normative**. The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.

An `.ad2v` file is a single SQLite 3 database. It describes a software system from two sides, the
**code** in a repository and the **specs** (spec-driven development documents), as one graph of
nodes and edges. It also holds glyphs for rendering, workflows for replay, and the deterministic
**pairing** of spec items with code: links, per-node statuses and roll-ups. Since v0.3 a file holds
a **history**: a chain of epochs (one per extraction) with content-addressed deduplication, rename
lineage between consecutive epochs, and the `stale` status. Viewers, agents (via MCP) and diff tools
read it. Producers ("extractors") write it.

Companion documents:

- [`glyph-grammar-v0.2.md`](glyph-grammar-v0.2.md): how nodes become shapes (normative, unchanged in v0.3 and v0.4).
- [`visual-tokens-v0.2.md`](visual-tokens-v0.2.md): how statuses become line styles and colors
  (status → style normative, palettes informative; unchanged in v0.3 and v0.4).
- [`spec-markdown-convention.md`](spec-markdown-convention.md): the Markdown spec convention (normative for extractors).
- [`../../schema/ad2v-v0.4.sql`](../../schema/ad2v-v0.4.sql): DDL (normative).
- [`../../schema/ir-v0.4.schema.json`](../../schema/ir-v0.4.schema.json): JSON Schema of the IR (normative).

### Changes from v0.3

v0.4 adds the **informative LLM layer** (§11) and nothing normative changes shape. `ad2v validate`
rejects other format versions (re-extract; there is no migration).

| area | change |
|---|---|
| storage | new `source_blobs` (file texts by content hash, class I), `llm_results` (content-addressed LLM cache), `llm_runs`, `llm_run_results`, `link_judgments`, `link_suggestions`, `spec_extractions`; `summaries` and `narrations` gain `result_id` (§11.3) |
| views | `node_status_effective`: normative status plus LLM overlays that can only upgrade implemented/verified to `drift` (§11.3) |
| pairing | new deterministic method `manifest_link` from `pairing.links` (human-confirmed suggestions); `pairing.rejected` (§6.1, §11.5) |
| spec IDs | the grammar accepts a reserved `-X` range (`REQ-X001`) for LLM-proposed items; `.ad2v-extracted/` is never extracted (§3.6, §11.8) |
| history | a callee rename no longer changes its callers (`call_masked_hash`, `call_sites`, evidence `callee_renamed`, §6.7, ADR-0026) |
| config | the `llm:` section of ad2v.yaml has its own `llm_config_hash` and never enters `config_hash` or an epoch id (§11.1) |

### Changes from v0.2

v0.3 is not backward compatible with v0.2 files, and there is no migration. `ad2v validate` rejects
other format versions with a message to re-extract. The logical model (nodes, edges, derived
tables) keeps its v0.2 shape: readers that query the `nodes`, `edges`, `unresolved_refs` and
`test_results` **views** and the derived tables see the same columns as in v0.2.

| area | change |
|---|---|
| storage | base facts are content-addressed `*_versions` rows referenced per epoch by `epoch_*` membership rows; `nodes`, `edges`, `unresolved_refs`, `test_results` become views of the v0.2 shape (§5, ADR-0017) |
| column classes | new class **V** (volatile): span lines and edge line lists. Deterministic, but ignored by `ad2v diff` and excluded from version keys (§1, §5.2) |
| epochs | new `change_kind` (N), `pinned`, `label`, `materialized` (I). `seq` is UNIQUE. `rules_hash`/`config_hash` reference the stored rules and manifest (§5.1) |
| derived data | glyphs, workflows, links, statuses exist only for **materialized** epochs (head + pinned); others are computed on demand (§5.3) |
| history | new tables `id_lineage` (renames, §6.6), `link_state` (per-epoch link status incl. `stale`, §6.7), `code_fact_versions` (workflow inputs), `parse_cache` (§10.1) |
| statuses | `stale` is produced (§6.7). Evidence kinds `spec_changed_since`, `code_changed_since`, `code_changed_unverified`, `retested`, `reannotated`, `fingerprint_mismatch`, `both_changed`, `descendants_changed`, `lineage_ambiguous` |
| annotations | `# ad2v: REQ-012@<fp8>` records which spec text the code was checked against (§3.6, §6.7) |
| entry points | `cli_command` for `if __name__ == "__main__":` blocks; `event_consumer` for Celery tasks and beat, APScheduler, `schedule`; `attrs.trigger` on every port. Nested Click commands are named by their group path (§3.3, §3.5, ADR-0021) |
| pairing | `pairing.orphan_policy` (`auto` / `strict` / `off`), part of `config_hash`; `meta.spec_coverage` (§6.2, ADR-0022) |
| narrations | `mode` (containment / call_depth) is part of the primary key (§5.4) |
| dump | `--epoch <id|head|all>`; views are dumped, physical storage tables are not (§8) |
| tools | `extract --into`, `history`, `diff`, `log`, `pin`/`unpin`, `prune`, `materialize` (§10) |

---

## 1. Principles

1. **Column classes.** Every table and column is **N** (normative: deterministic; the same inputs
   produce the same value in every conforming producer), **I** (informative: produced by an LLM, by
   runtime observation, by the wall clock, or file-management state such as pins), or **V**
   (volatile: deterministic, but moves with unrelated edits, like line numbers). Informative rows
   that come from an LLM MUST carry `model`, `model_version`, `prompt_hash`, `input_hash` and
   `confidence`. The DDL enforces this with `CHECK` constraints. V columns are part of the
   normative dump but are ignored when comparing epochs (§8.2) and never enter a version key.
2. **Stable identity.** A node's `id` depends on what the node *is* (side, kind, qualified name),
   never on its content. Change is tracked separately by `content_hash` and `subtree_hash`, and
   renames across epochs by lineage (§6.6).
3. **Cross-platform determinism.** Paths use `/`. Content is hashed after LF normalization and BOM
   stripping. All iteration is sorted. Timestamps never enter hashes.
4. **One file, canonical dump.** Two producers agree when their normative canonical dumps (§8) are
   byte-identical. SQLite file bytes are *not* compared.
5. **Relative levels.** There are no global levels (L1/L2/L3). Depth is the depth in the
   `contains` hierarchy and MAY differ between branches. `level_hint` is presentation metadata only.
6. **Knowledge never grants capability.** Producers read the repository. They MUST NOT import,
   execute or evaluate repository code. Test results are *ingested* from files; producers never run
   tests. `ad2v history` reads commits with `git archive`; it never checks out or runs anything.
7. **Additive evolution.** Later versions MAY add tables, columns, node kinds, edge kinds, attrs
   keys and risk flags. They MUST NOT change the meaning of an existing column or value.
8. **History is a pure function of the inputs.** An epoch's logical content (its view rows and
   derived rows) MUST equal what a fresh single-epoch extraction of the same inputs produces, except
   for the history-dependent parts that are defined in terms of the parent epoch: `id_lineage`,
   `link_state` and the link and node statuses they change (§6.6, §6.7), and the layout (§12.1).

## 2. Normalization and hashing (normative)

| Rule | Definition |
|---|---|
| Text decoding | Strip one leading UTF-8 BOM (`EF BB BF`), decode UTF-8 with U+FFFD replacement, then replace `\r\n` and lone `\r` with `\n`. |
| Paths | Relative to the repo root (code side) or the spec root (spec side); `/` separators; no leading `./`. The root itself is `""`. |
| `sha256_hex(s)` | Lowercase hex SHA-256 of the UTF-8 bytes of `s`. |
| Canonical JSON | `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Every `*_json` column holds canonical JSON. |
| Node id | `"n_" + sha256_hex(side + "|" + kind + "|" + qualified_name)[:20]` |
| Workflow id | `"w_" + sha256_hex(side + "|" + entry_node_id + "|" + source)[:20]` |
| Link id | `"l_" + sha256_hex((spec_node_id or "") + "|" + (code_node_id or "") + "|" + method)[:20]` |
| Epoch id | `"e_" + sha256_hex(join("|", [parent_epoch_id or "", repo_tree_hash, spec_tree_hash, rules_hash, config_hash, test_results_hash]))[:20]` |
| Version key | `"v_" + sha256_hex(canonical_json(normative payload))[:20]`. Node payload: every N field of §3.1 (no span lines). Edge payload: `src`, `kind`, `dst`, `weight`, `provenance`, `attrs` without `lines`. Other versions: the row's N columns in DDL order. |
| `content_hash` | For nodes with a source span: `sha256_hex(normalized text of lines span_start_line..span_end_line)` (lines joined with `\n`). For files (modules, `spec_doc`): the whole normalized file. For nodes without text (system, `spec_root`, container, component, resources, ports): `sha256_hex(canonical_json({"kind","name","attrs"}))`. |
| `body_hash` | Functions and classes: `content_hash` of the span with the defined name masked in the `def`/`class` line. Used as the rename-invariant **fingerprint** of §6.6–6.7; other nodes use `content_hash`. |
| `subtree_hash` | `sha256_hex(join("\n", [content_hash] + ["<child_id>:<child_subtree_hash>" for children sorted by id]))`, where children are nodes whose `parent_id` is this node. |
| Tree hashes | `repo_tree_hash`, `spec_tree_hash`, `test_results_hash` = `sha256_hex(join("\n", ["<path>\t<content_hash(file)>" sorted by path]))` over the files read (test results: file paths relative to the repo if inside it, else the file name). |
| `rules_hash` | `sha256_hex(canonical_json(merged rules))`: the built-in rules deep-merged with the manifest's `rules_overlay` (maps merge, lists and scalars replace). Comments and formatting do not count; content does. |
| `config_hash` | `sha256_hex(canonical_json({"effective": {"orphan_policy": …}, "manifest": parsed ad2v.yaml or {}}))`. Effective settings whose default is not visible in the manifest are included, so changing a default changes the hash. |

Every input that can change the output (code, specs, rules, manifest, test results) enters the
epoch id. Because the parent id enters it too, the same inputs appended after different histories
give different epoch ids.

**Test results carry forward.** When an extraction gets no test-result files, the epoch inherits
the parent's test results and `test_results_hash`. Results are **fresh** in an epoch when files were
given and their hash differs from the parent's (§6.7).

## 3. The IR

The IR is the logical model of one epoch. `schema/ir-v0.4.schema.json` defines its JSON form, and
the views and tables in §5 store it.

### 3.1 Node

| field | class | meaning |
|---|---|---|
| `id` | N | stable id (§2) |
| `side` | N | `code` or `spec` |
| `kind` | N | closed enum (§3.2) |
| `name` | N | display name |
| `qualified_name` | N | canonical name, unique per (side, kind) (§3.3) |
| `parent_id` | N | parent in the `contains` (code) / `declares` (spec) hierarchy; NULL for roots |
| `path` | N | source file (repo- or spec-root-relative) |
| `span_start_line`, `span_end_line` | V | source location (1-based, inclusive). Spec nodes point into spec files. |
| `content_hash`, `subtree_hash` | N | §2 |
| `level_hint` | N | optional hint: `system`, `container`, `component`, `code`, `port`, `resource`, `behavior`, `spec` |
| `attrs` | N | kind-specific JSON object (§3.5) |
| `spec_ref` | N | sorted list of explicit spec IDs attached to this node (§3.6) |

### 3.2 Node kinds (closed enum, unchanged from v0.2)

| group | kinds |
|---|---|
| Structural | `system`, `container` (deployable/service), `component` (package/directory), `module` (source file), `class`, `function` (incl. methods and nested functions) |
| Ports | `http_route`, `mcp_tool`, `cli_command`, `event_consumer` |
| Resources | `datastore`, `queue`, `external_service`, `llm_endpoint`, `ui` |
| Behavior | `loop`, `retry`, `fan_out`, `transaction`, `llm_call` |
| Spec | `spec_root`, `spec_doc`, `spec_component`, `requirement`, `scenario`, `scenario_step`, `spec_endpoint` |

Spec kinds have `side = spec`. All other kinds have `side = code`. Each side has exactly one root:
`system` (code) and `spec_root` (spec, written when specs are extracted). Resources are children of
`system`, and every `spec_doc` is a child of `spec_root`.

### 3.3 Qualified names

| kind | qualified_name | example |
|---|---|---|
| `system` | the system name (manifest `system.name`, else repo directory name) | `payments-recon` |
| `spec_root` | the system name (the id differs from `system` because side and kind differ) | `payments-recon` |
| `container` | `container:<name>` | `container:api` |
| `component` | directory path | `api/recon_api` |
| `module` | file path | `api/recon_api/matching.py` |
| `class` | `<module path>::<Class>` (nested: `Outer.Inner`) | `api/recon_api/db.py::Run` |
| `function` | `<module path>::<name>`; methods `::<Class>.<name>`; nested `::<outer>.<inner>` | `api/recon_api/matching.py::match_batch` |
| `http_route` | `http:<container>:<METHOD> <full path>` | `http:api:GET /v1/reconciliations/{id}` |
| `mcp_tool` | `mcp:<container>:<tool name>` | `mcp:api:reconciliation_summary` |
| `cli_command` | `cli:<container>:<command path>`: the command name, prefixed by the names of the nested Click groups above it (not the root group) and separated by spaces | `cli:worker:run-nightly`, `cli:dispatch:plugins list` |
| `cli_command` (main block) | `cli:<container>:__main__:<module path>` | `cli:worker:__main__:worker/recon_worker/cli.py` |
| `event_consumer` | `event:<container>:<handler qualified name>` for subscriptions; `event:<container>:<trigger>:<handler qualified name>` for scheduled and task entry points (§3.5) | `event:worker:celery_beat:worker/tasks.py::nightly` |
| resources | `<kind>:<resource name>` (§3.7) | `datastore:env:RECON_DB_URL` |
| behavior | `<enclosing qname>@<kind>#<anchor>[~n]`, see below | `api/recon_api/matching.py::match_batch@loop#81dc075c` |
| `spec_doc` | spec file path | `components.md` |
| `spec_component`, `requirement` | the explicit spec ID when present (`CMP-001`, `REQ-012`), else `<spec path>::<name>` | `REQ-012` |
| `scenario` | `<spec path>::<feature name>::<scenario name>` (`#2`, `#3`… appended to duplicates) | `features/recon.feature::Statement reconciliation::Start a run` |
| `scenario_step` | `<scenario qname>::step[<n>]`, 1-based | `...::Start a run::step[2]` |
| `spec_endpoint` | `<METHOD> <path>` as written in the spec (without the `servers` base path) | `POST /reconciliations` |

**Behavior anchors (content-anchored identity, ADR-0011).** The anchor is
`sha256_hex(normalized header)[:8]`, where the header is whitespace-normalized (runs of whitespace →
one space, trimmed) and chosen per construct:

| construct | header text |
|---|---|
| `for` loop | the iterable expression (`transactions`) |
| `while` loop | the condition |
| comprehension | the iterable of its first `for` clause |
| retry / transaction decorator | the whole decorator (`@retry(wait=...)`) |
| `Retrying(...)` call, `llm_call` | the call expression |
| `asyncio.gather`-style fan-out | the argument list (`(*[f(x) for x in xs])`) |
| executor `map` / `submit` fan-out | the call expression |
| `with X.begin():` transaction | the with-item expression |

When two candidates of the same kind in the same enclosing scope have identical headers, the second
one gets `~2`, the third `~3`, and so on, in source order. Anchors count all candidates, including
the ones not emitted, so changing `behavior.emit_all` never renames a node. The normalized header is
stored in `attrs.header`; lineage uses it to follow a behavior whose header was edited (§6.6).

**Spec IDs are the qualified names of spec nodes.**

### 3.4 Edges

`(src, kind, dst)` is unique within an epoch. Repeated occurrences increase `weight`. `attrs.lines`
(sorted, deduplicated; class V) records the source lines of occurrences on the `src` side when known.

| kind | from → to | meaning |
|---|---|---|
| `contains` | code parent → code child | hierarchy (mirrors `parent_id`) |
| `declares` | spec parent → spec child | spec hierarchy (mirrors `parent_id`) |
| `imports` | module → module | repo-internal import |
| `calls` | function/module/port → function/class/module | resolved call; port → handler (a main-block port calls its module) |
| `reads`, `writes` | function/module → `datastore` | access classified by method / SQL verb; unknown access defaults to `reads` with `attrs.access = "default"` |
| `publishes`, `consumes` | function/module → `queue` | |
| `exposes` | container → port | the container serves the port |
| `invokes_external` | function/module → `external_service` | |
| `invokes_llm` | function/module → `llm_endpoint` | |
| `annotated_as` | any node → spec node | explicit spec ID reference (§3.6). Also spec → spec (a Gherkin scenario tagged `@REQ-012`), see ADR-0005. Code → spec edges are the input of the `annotation` pairing method (§6.1). |

`provenance` is `deterministic` for every edge a v0.3+ extractor writes.

### 3.5 Attributes (well-known keys)

| kind | keys |
|---|---|
| `container` | `container_kind` (manifest `kind`), `replicas`, `paths`, `declared` (bool) |
| `function` | `async` (bool), `decorators` (list of dotted names), `is_test` (bool), `params` (names in order, without `self`/`cls`), `var_kwargs` (bool: has `**kwargs`), `body_hash` (§2), `spec_ref_fingerprints` (§3.6) |
| `class` | `body_hash`, `spec_ref_fingerprints` |
| `http_route` | `method`, `path`, `framework`, `handler` (qname) |
| `mcp_tool` | `tool_name`, `framework`, `handler` |
| `cli_command` | `command`, `framework`, `handler`, `trigger` (`click`, `main`), `group` (Click group qname, nested commands) |
| `event_consumer` | `framework`, `handler`, `source` (subscription name if resolvable), `trigger` (see below) |
| resources | `libraries`, `resource_name`, `name_source` (`literal`, `env`, `unknown`) |
| behavior | `risk` (sorted list of risk flags), `construct`, `library`, `touches`, `header` (§3.3), `severity`, `severity_rank`, `severity_reach` (§3.8) |
| `requirement` | `text`, `ears` (`event`, `state`, `unwanted`, `optional`, `ubiquitous`, or `null`), `trigger`, `system`, `response`, `precondition` |
| `scenario` | `keyword`, `tags`, `background` (bool), `examples` (count), `rule` |
| `scenario_step` | `keyword`, `keyword_type`, `text` |
| `spec_endpoint` | `method`, `path`, `operation_id`, `summary`, `tags`, `base_path` (path of `servers[0].url`), `path_params`, `query_params`, `required_query` (parameter names; local `$ref`s resolved) |
| `spec_doc` | `format` (`markdown`, `gherkin`, `openapi`), `prose` (Markdown only: unparsed text), `base_path` (OpenAPI) |

**Entry points (ADR-0021).** Besides HTTP routes, MCP tools, Typer/Click commands and queue
subscriptions, the rules (`ports.entry_points` in `rules/python.yaml`) recognize:

| construct | port | `trigger` |
|---|---|---|
| `if __name__ == "__main__":` (either operand order) | `cli_command`, handler = the module, span = the `if` block | `main` |
| `@app.task`, `@shared_task` (Celery) | `event_consumer` | `celery_task` |
| `app.conf.beat_schedule = {…: {"task": "<dotted name>"}}` | `event_consumer` for the resolved task function | `celery_beat` |
| `scheduler.add_job(fn, …)`, `@scheduler.scheduled_job(…)` (APScheduler) | `event_consumer` | `apscheduler` |
| `schedule.every(…)….do(fn)` | `event_consumer` | `schedule` |
| Click commands and groups | `cli_command` | `click` |

Entry points start workflows (§7), so they raise the `reach` of the behaviors they lead to (§3.8).

**Risk flags** (`attrs.risk`): `io_in_loop`, `llm_in_loop`, `unbounded_retry`, `fan_out`,
`nested_loop_io`, `slow_io_in_transaction` (ADR-0006). By default, behavior nodes are emitted only
when they have at least one risk flag. Set `behavior.emit_all: true` to emit all.

### 3.6 Explicit spec references

A spec ID matches `[A-Z][A-Z0-9]*-X?[0-9]+`; the `-X` range is reserved for LLM-proposed items (§11.8). Explicit references come from:

1. a comment `# ad2v: ID[, ID…]` inside a function/class span, or directly above a definition or its
   decorators (contiguous comment block); a comment elsewhere attaches to the module;
2. a docstring line `ad2v: ID[, ID…]`;
3. the name of a test function (`test_*` in `test_*.py` / `*_test.py`) that contains
   `<prefix>_<digits>` for a configured prefix (default `REQ`, `CMP`): `test_req_012_x` → `REQ-012`;
4. Gherkin tags `@ID` on features and scenarios;
5. OpenAPI operation extension `x-ad2v-refs: [ID, …]`.

In comments and docstrings an ID MAY carry a **spec fingerprint**, `ID@<fp8>`, where `fp8` is the
first 8 hex digits of the spec node's `content_hash` the author checked the code against
(`# ad2v: REQ-012@1a2b3c4d`). The fingerprints are recorded in the node's
`attrs.spec_ref_fingerprints` (`{ID: fp8}`), and `spec_ref` holds the bare ID. `ad2v inspect FILE
--node REQ-012` shows the spec node's current `content_hash`.

Every reference is recorded in the node's `spec_ref`. When a spec node has qualified name `ID`, an
`annotated_as` edge is written. Otherwise a row is written to `unresolved_refs`
(`reason = 'not_found'`), and the node gets the status `needs_review` (§6.4).

### 3.7 Resource naming

A resource is named by the first match, in order:

1. a string literal that contains `://`, with credentials, query and fragment stripped. Datastores
   keep `scheme://host[:port][/path]`. External services, queues and LLM endpoints keep
   `scheme://host[:port]`. For f-strings, only the literal prefix before the first `{...}` is used;
2. an environment-variable read (`os.environ[...]`, `os.getenv(...)`, `os.environ.get(...)`),
   giving `env:<VAR>` (a default value is ignored);
3. for libraries whose rule sets `name_from_literal` (queues), a plain string literal;
4. otherwise `<library>:unknown`.

Arguments are searched first in the rule's `name_kwargs` (for which any literal counts, e.g.
`model=`), then in positional arguments. Constants are followed through module scope and imports.
A client built from another client inherits its resource (`sessionmaker(bind=engine)`). A touch on
a client whose resource is still `unknown` may be named from the call's own arguments
(`publisher.publish(TOPIC, ...)`).

**What counts as a touch** (an IO edge): a call to a method of a client bound to a resource, unless
the rule lists the method in `pure_methods` (for SQLAlchemy this includes the query builders
`select`, `join`, `filter`, `where`, …); or a library-level call, unless the rule lists it as a
constructor or `pure`. For datastore libraries, library-level calls do not count
(`direct_calls_touch: false`) unless listed in `touch_functions`: `sqlalchemy.inspect()` is not IO,
while `session.execute()` is.

### 3.8 Risk severity (normative, ADR-0014)

Every behavior node gets `attrs.severity` (float), `attrs.severity_reach` (int) and
`attrs.severity_rank` (int, 1 = worst):

```
severity     = round((max base over the node's risk flags + sum of nesting bonuses) * reach_factor, 4)
reach        = number of distinct code-side workflows whose steps include the node
reach_factor = unreachable                                             if reach = 0
             = min(cap, reachable + per_extra_workflow * (reach - 1))  otherwise
rank         = position in the order (-severity, node id), starting at 1
```

The default weights are `base` = {llm_in_loop 5, unbounded_retry 4, io_in_loop 3,
slow_io_in_transaction 3, fan_out 2}, `nesting_bonus` = {nested_loop_io 2}, and `reach` =
{unreachable 1.0, reachable 1.5, per_extra_workflow 0.1, cap 2.5}. They live in the rules
(`severity:`), so they are covered by `rules_hash` and an overlay can change them.

## 4. Containers

If a manifest declares `containers`, a file belongs to the container with the longest path prefix
that matches its path. Without declared containers, every top-level directory that contains
`pyproject.toml`, `setup.py` or `Dockerfile` is a container named after the directory. Files that
match no container go to a fallback container named after the system, with `paths: ["."]`. It is
created only if such files exist. When no container is found, this fallback is the repo root.

## 5. Storage

See the DDL for types and constraints. Appendix A has the column-by-column N/I/V marks, generated
from the DDL.

### 5.1 Epochs

An **epoch** is one extraction. Epochs form a chain through `parent_epoch_id` (NULL only for the
first kept epoch) and are numbered by `seq` (1, 2, 3… in append order; gaps appear after `prune`).
`meta.head_epoch` names the newest epoch, which MUST be the one with the highest `seq`.

| column | class | meaning |
|---|---|---|
| input hashes | N | §2. `rules_hash` and `config_hash` reference `rules_versions` / `config_versions`, which store the merged rules and the manifest, so any epoch can be re-derived without the source tree |
| `repo_commit` | N | the git commit the epoch was extracted from: given by `ad2v history`, else read from `<repo>/.git` without running git (NULL if absent) |
| `change_kind` | N | which input hashes changed vs. the parent: `initial` (no parent), `code` (repo tree), `spec`, `code+spec`, `rules`, `config`, `tests_only` (only test results), `mixed` (any other combination) |
| `pinned`, `label` | I | file-management state: a pinned epoch stays materialized and survives `prune --keep-pinned`; the label is a unique name usable wherever an epoch is expected |
| `materialized` | I | 1 when the derived rows are present (§5.3) |
| `attrs_json` | N | configuration echo, pairing warnings, unmatched test cases, spec coverage, test-result counts and whether they were carried or fresh |

An epoch is written only when at least one input hash differs from the head's. Otherwise the
extraction reports "no changes" and the file is not modified.

### 5.2 Base facts: versions and membership

Base facts are stored once per distinct content:

| versions (content-addressed by `version_key`, §2) | membership (per epoch) | view (v0.2 shape) |
|---|---|---|
| `node_versions` | `epoch_nodes(seq, vid, span_start_line, span_end_line)` | `nodes` |
| `edge_versions` | `epoch_edges(seq, vid, lines_json)` | `edges` (re-attaches `attrs.lines`) |
| `unresolved_ref_versions` | `epoch_unresolved_refs(seq, vid)` | `unresolved_refs` |
| `test_result_versions` | `epoch_test_results(seq, vid)` | `test_results` |
| `code_fact_versions` | `epoch_code_facts(seq, vid)` | (none: read by `materialize`) |

Each version row has an integer surrogate `vid` (class I: file-local, never exposed by the views)
and its content key `version_key` (UNIQUE). Membership rows are `(seq, vid)` pairs in `WITHOUT
ROWID` tables, so an unchanged node costs one small row per epoch. The volatile columns (span
lines, edge line lists) live in the membership rows, so a node whose lines moved shares its
version with the previous epoch. Within one epoch a node id, an edge `(src, kind, dst)` and a code
fact `(fact_kind, subject_id)` appear at most once.

Readers MUST use the views. A view row carries the epoch's `epoch_id` and has exactly the columns of
the v0.2 table of the same name; filtering a view by `epoch_id` gives one epoch's IR.

`code_fact_versions` stores the extractor's workflow inputs that are not in the graph: per-function
call and touch **events** (targets and enclosing behaviors, without lines), retry **wrappers**, and
**entry** bindings (port id → sorted list of handler ids). With them, workflows and everything
downstream can be recomputed from the file alone.

Node references in membership-based rows are not SQL foreign keys (membership rows carry no node
ids). `ad2v validate` checks them instead: edge endpoints, unresolved-ref sources, test-result nodes,
and every node column of the derived tables MUST name a node of the same epoch.

### 5.3 Derived tables and materialization

Derived tables keep their v0.2 shape and are keyed by `epoch_id`: `glyphs`, `workflows`,
`workflow_steps`, `workflow_step_nodes`, `links`, `node_status`, `status_rollup`. Their rows exist
only for **materialized** epochs: the head and every pinned epoch. When a new head is written, the
previous head's derived rows are dropped unless it is pinned. `epoch_materialized(epoch_id,
table_name)` lists what is present, and `epochs.materialized` is 1 exactly when every derived table
is listed.

`ad2v materialize --epoch X` writes the derived rows of any epoch from its stored base facts,
`link_state` and `id_lineage`; `dump`, `diff` and `status` compute them in memory when they are not
stored. Materialized and in-memory rows MUST be identical.

### 5.4 Other tables

| table | class | notes |
|---|---|---|
| `meta(key, value, class)` | per row | `class='N'`: `format_version` (`0.3`), `head_epoch`, `rules_version`, `system_name`, `spec_coverage` (`present`/`none`, of the head). `class='I'`: `generator`, `generator_version`, `repo_root_name`, `created_at` |
| `id_lineage` | N | renames between an epoch and its parent (§6.6) |
| `link_state` | N | per-epoch final link status and history evidence (§6.7) |
| `parse_cache` | I | file-level cache (§10.1) |
| `summaries` | `node_id`, `length` N; rest I | `length` ∈ `label`, `card`, `deep`; keyed by `(node_id, length, model)` |
| `narrations` | span columns N; `text`/provenance I | spans refer to fine step `seq`; keyed by `(workflow_id, mode, detail_level, span_start, model)`, where `mode` is the projection mode (§7) |
| `layout` | N | `(node_id, lod, algorithm)` → box `x,y,z,w,h,d` |
| `tours`, `tour_stops` | mixed | guided camera paths |

## 6. Pairing and statuses (normative)

### 6.1 Pairing methods

A **link** relates one spec node and one code node. It is found by one of five deterministic
methods (`links.method`). All of them run, and a pair found twice by different methods gives two links:

| method | rule |
|---|---|
| `annotation` | every `annotated_as` edge code → spec (comments, docstrings, test names; §3.6) |
| `route_match` | `http_route` ↔ `spec_endpoint` with equal `(METHOD, normalized path)` |
| `manifest_link` | `pairing.links: [{spec: REQ-007, code: <qualified name>}]` in `ad2v.yaml`: a human-confirmed pair (an accepted suggestion, §11.5). The code name resolves by kind in the order function, class, ports, module, component, container; a missing target gives `missing` |
| `manifest` | `pairing.components: {CMP-001: api}` in `ad2v.yaml`: spec component (by spec ID) → container (`container:<name>` or bare name) or component (directory path) |
| `name_match` | `spec_component` not listed in the manifest ↔ container or component whose **slugs are exactly equal** (lowercase, runs of non-alphanumerics → `-`, trimmed). No fuzzy matching (that is P4) |

**Path normalization** for `route_match`: (1) prepend the path part of OpenAPI `servers[0].url` to
spec paths; (2) apply the longest matching `pairing.path_prefix_map` entry (on a `/` segment
boundary, to both sides); (3) replace each `{param}` with a positional `{}`; (4) collapse `//`; (5)
strip a trailing `/` (except the root); (6) lowercase the whole path only if
`pairing.case_insensitive: true` (default false; parameters are already `{}`). The parameter names
are kept. If they differ (`{id}` vs `{run_id}`), the pair still links, with evidence
`param_name_mismatch`. If more than one candidate exists on either side, every candidate link gets
`needs_review` with evidence `ambiguous`.

Rows with `method = 'none'` record unpaired items: `missing` and `specified` spec items
(`code_node_id` NULL), and `orphan` code items (`spec_node_id` NULL). `method = 'llm'` is reserved
for P4.

### 6.2 Link statuses

| status | rule |
|---|---|
| `missing` | a spec item with a deterministic implementation signature has no pair: a `spec_endpoint` with no route, or a `spec_component` listed in `pairing.components` whose target does not exist |
| `specified` | a `requirement`, `scenario` or unlisted `spec_component` with no link. Absence cannot be proven statically, so it is "planned", not "missing" |
| `implemented` | paired, and no linked test passed |
| `verified` | paired, and at least one **linked test** has `outcome = passed` in the test results in effect. A linked test is a test function (`attrs.is_test`) whose `spec_ref` contains the spec item's ID or any ID in the spec item's own `spec_ref` (e.g. an endpoint's `x-ad2v-refs`). With no test results, nothing is `verified`. A failing linked test adds evidence `tests_failed` and leaves the link `implemented` |
| `drift` | structural only: a paired route ↔ endpoint where (a) the number of `in: path` parameters the endpoint declares differs from the route template's, or (b) a `required: true` query parameter is not a parameter of the handler (skipped if the handler takes `**kwargs`). Evidence: `path_param_count` / `required_query_param_missing`. Semantic drift is P4 |
| `orphan` | only for ports, containers and components with no link, no linked ancestor container/component and, for ports, no linked handler, **and only when the orphan policy assigns orphans** (below). Functions, classes and modules are never orphan |
| `needs_review` | ambiguous pairing; ambiguous lineage (§6.6); or (node-level only) a node that carries an unresolved reference |
| `stale` | a previously agreed link whose spec or code changed since (§6.7) |

**Orphan policy** (`pairing.orphan_policy` in `ad2v.yaml`, ADR-0022; recorded in `config_hash`):

| policy | orphans assigned |
|---|---|
| `auto` (default) | only when the epoch has at least one spec item (`requirement`, `scenario`, `spec_component`, `spec_endpoint`). With none, `meta.spec_coverage = 'none'` and unpaired code keeps status `none`: "no specs" is not "every port is undocumented" |
| `strict` | always (the v0.2 behavior) |
| `off` | never |

YAML 1.1 reads a bare `off` as `false`; producers MUST treat `false` as `off`.

### 6.3 State machine

```
                  pair found (annotation|route|manifest|name)          passing linked test
 specified ───────────────────────────────────────► implemented ───────────────────────────► verified
 missing  ──────────────────(pair found)──────────────────┘ ▲ │ ▲                                 │
   ▲                                                         │ │ └──── test now fails ──────────────┘
   │ pair removed                               drift fixed │ │ structural mismatch /
   │                                                         │ ▼ semantic disagreement (P4, provenance=llm)
 implemented / verified / drift ────────────────────────── drift
 implemented/verified ── spec changed since agreement ─────────────────────────► stale (§6.7)
 verified ── code changed, no fresh passing test ──────────────────────────────► stale (§6.7)
 stale ── re-annotated with the current fingerprint, or fresh passing test ───► implemented / verified
 any paired status ── several candidates / ambiguous lineage / judge below threshold (P4) ──► needs_review
 code without any pair (orphan policy permitting) ──► orphan ──(pair found)──► implemented
```

P4: semantic judgments write links with `provenance = 'llm'`, `method = 'llm'`, full provenance
columns and `confidence < 1`.

### 6.4 Effective node status

`node_status` has exactly one row per node:

1. **Own reasons**: the statuses of the node's links (either side). A port with no links of its own
   takes its handler's links (`via_handler`). A node with an unresolved reference gets
   `needs_review`, and so does a node with an ambiguous lineage candidate (`lineage_ambiguous`).
2. If there are own reasons, the status with the highest precedence wins:
   **`drift` > `needs_review` > `missing` > `orphan` > `stale` > `verified` > `implemented` > `specified` > `none`**.
3. Otherwise the node **inherits** its parent's effective status if that is `verified`,
   `implemented` or `specified` (reason `inherited`). Otherwise its status is `none` (no coverage
   applies; rendered neutrally, never red).

`reasons_json` = `{"precedence": [...], "reasons": [{"status", "kind", ...}, ...]}`.
`status_rollup` counts effective statuses over all descendants, for far-zoom glyphs.

### 6.5 Test results

`--test-results <junit.xml>` (repeatable) parses JUnit XML with the standard library. Test cases are
matched to test functions by these rules (reference: `src/ad2v/junit.py`): parametrization suffixes
`[...]` are dropped; `classname` is split into a module path (dots → `/`, `.py`) and trailing class
names, trying the longest module first; a module matches when it equals an extracted module path or
is a `/`-suffix of one (the pytest rootdir may differ); a `file` attribute breaks ties. Exactly one
candidate gives a match. Zero or several give an **unmatched** case, which is reported (in
`epochs.attrs_json.unmatched_tests` and the CLI summary), never an error. The outcome is `failed` if
there is a `<failure>` or `<error>`, `skipped` if there is a `<skipped>`, and `passed` otherwise.
When several results map to one test, the worst wins. Without result files, the parent's results
carry forward (§2).

### 6.6 Lineage (renames between consecutive epochs)

When an epoch has a parent, node ids present only in the parent ("removed") and only in the new
epoch ("added") are matched in three passes. Each id is matched at most once; earlier passes win.

1. **`same_content`**: a removed and an added node of the same kind with the same fingerprint
   (`body_hash` for functions and classes, else `content_hash`; §2), when that `(kind, fingerprint)`
   is unique among the removed and among the added nodes. Score 1.0. A renamed function whose body
   is unchanged is a `same_content` match.
2. **`anchored_header`**: behavior nodes of the same kind in the same enclosing scope (after
   applying pass-1 renames to the scope) whose `attrs.header` token sets (lowercase `[a-z0-9]+`) have
   a Jaccard similarity ≥ 0.6. The score is the similarity. Pairs are taken by descending score.
   When the best score for a node is tied between candidates, none is applied: the tied pairs are
   stored with method `ambiguous`, and the added node gets `needs_review` evidence
   `lineage_ambiguous`.
3. **`same_route`**: an `http_route` pair with the same container, method and normalized path
   (§6.1) whose qualified name changed (e.g. the path parameter was renamed), when unique.

Unmatched ids stay removed / added. Rows go to `id_lineage(epoch_id, old_id, new_id, method,
score)`. `ad2v diff` composes lineage along the parent chain, so a node renamed twice between two
distant epochs is reported once, as a rename.

### 6.7 Stale (history rules)

Structural pairing (§6.1–6.2) first gives every link its structural status in the new epoch. Then,
for each link with both sides present, the producer looks up the parent's `link_state` row of the
same `(spec node, code node, method)`, with ids mapped through lineage. Change is judged on
fingerprints (§6.6), so a pure rename is not a change. A change to a **test function** is never a
code-side change: tests are verification evidence, not the implementation. With `fp` the link's
spec fingerprint on the code side (§3.6) and `sh8` the first 8 hex digits of the spec node's
current `content_hash`, the first matching rule applies:

| # | condition (structural status ∈ {implemented, verified} unless noted) | final status | evidence |
|---|---|---|---|
| 0 | structural status is not implemented/verified | structural | |
| 1 | `fp` present and `fp ≠ sh8` | `stale` | `fingerprint_mismatch` |
| 2 | `fp = sh8`, and the parent status was `stale` or the spec changed | structural | `reannotated` |
| 3 | the spec and the code both changed | structural | `both_changed` |
| 4 | the spec changed | `stale` | `spec_changed_since` (with the agreement epoch) |
| 5 | the code changed and the parent was `verified` (or `stale` for `code_changed_unverified`) | `verified` if structural is verified and test results are fresh, else `stale` | `retested` / `code_changed_unverified` |
| 6 | the code changed and the parent was `stale` for another reason | `stale` | the parent's reason, carried |
| 7 | the code changed (parent implemented) | structural | `code_changed_since` |
| 8 | nothing changed and the parent was `stale` | `verified` if the reason was `code_changed_unverified`, structural is verified, results are fresh and the spec is unchanged since the agreement; else `stale` | `retested` / carried |
| 9 | nothing changed | structural | |

A link without a parent row gets its structural status, except rules 1–2 (fingerprint) still apply.
When the content of both sides is unchanged, the node was not renamed, and a `subtree_hash`
changed, evidence `descendants_changed` is added without a status change.

The result is stored in `link_state(epoch_id, link_id, …, status, history_json, agreed_epoch_id,
agreed_spec_hash, agreed_code_hash)`: the last epoch where the link was implemented or verified and
the hashes at that agreement. `link_state` is a base fact: materializing an epoch replays it onto
freshly computed structural links, so an epoch whose parent was pruned can still be materialized.

## 7. Workflows

A **static workflow** is written for each entry port (`http_route`, `mcp_tool`, `cli_command`,
`event_consumer`). The trace is a depth-first walk:

1. step 0: `[port]` at depth 0;
2. step 1: the port's handlers at depth 1. A port bound to several handlers (the same route declared
   twice) gets **one** workflow whose step 1 holds all handlers, sorted by id, as parallel targets;
3. visiting function `f` at depth `d` emits `[enclosing emitted behaviors…, f's emitted retry nodes…, f]`
   at depth `d`, then walks `f`'s events in source order (pre-order by call position):
   - resolved call to `g`: visit `g` at depth `d+1` (the behavior nodes lexically enclosing the call
     are prepended to `g`'s step);
   - resource touch: emit `[enclosing emitted behaviors…, resource]` at depth `d+1`;
   - calls that are arguments of the same fan-out call are **parallel**: their callees are emitted
     as a single step (`[fan_out, g1, g2…]`) and then visited in order.
4. Recursion stops at `workflows.max_depth` (default 12). A callee already on the stack is emitted
   but not expanded (cycle guard). A trace stops at `workflows.max_steps` steps and sets
   `attrs.truncated = true`.

A **spec workflow** is written for each Gherkin scenario: the Background steps come first, then the
scenario's steps, one per `workflow_step`, all at depth 0.

**Projection** (ADR-0013) `project(steps, k, mode)` collapses a trace to detail level `k`.
Both modes return `(coarse_steps, fine_span_per_coarse_step)`, and the spans are contiguous and
partition the trace.

- `mode = "containment"` (**default**, follows the viewer's zoom): the key of a step is the ordered,
  de-duplicated list of the depth-`k` ancestors (in the `contains`/`declares` hierarchy, root = depth
  0) of its nodes. A node shallower than `k` is its own key. Maximal runs of equal keys merge, and
  the coarse step highlights exactly those ancestors: the glyphs visible at that zoom.
- `mode = "call_depth"`: step `i` joins the group anchored at `max{ j ≤ i : depth_j ≤ k }`, and
  leading deeper steps form one group. The coarse step shows its anchor's nodes.

In both modes, increasing `k` never merges steps. Narrations (§5.4) are keyed by
`(mode, detail_level, span_start)`, so replay stays consistent at every slider position in both
modes.

## 8. Canonical dump and diff

### 8.1 Canonical dump

`ad2v dump [--epoch <id|head|all>]` writes one JSON line per row: `{"row":{…},"table":"<name>"}`
(canonical JSON). It dumps the **logical** tables: the views `nodes`, `edges`, `unresolved_refs`,
`test_results`, and every table that is not physical storage (`*_versions`, `epoch_*` membership,
`epoch_materialized` and `parse_cache` are not dumped). Rows are filtered to the selected epochs
(default: the head). Derived rows of an epoch that is not materialized are computed in memory, so
the dump does not depend on what is materialized. Tables are in name order and rows in key order.
`*_json` columns are decoded (nested).

- **Canonical (default)**: every `created_at` column and every `meta` row with `class = 'I'` are
  omitted.
- **`--normative-only`**: additionally omits every column marked `I` in Appendix A (including the
  epochs' `pinned`, `label`, `materialized`), every row with `provenance IN ('llm','runtime')` or
  `source IN ('llm_inferred','runtime')`, and the informative tables `summaries` and `narrations`.

**The determinism guarantee covers the normative dump.** Two runs on the same inputs (code, specs,
rules, manifest, test results), including from a checkout with CRLF line endings or a different
directory name, MUST produce identical normative dumps; for histories, the same sequence of inputs
MUST produce identical normative dumps of every epoch (`--epoch all`) except for `repo_commit`,
which names the commits. The storage layout is invisible in the dump: deduplication never changes a
view row. Informative rows are reproducible only by caching them under `input_hash`/`prompt_hash`
(P4).

### 8.2 Epoch diff

`ad2v diff FILE [--from X] [--to Y] [--format table|json|md]` (default: parent → head) compares two
epochs of one file, where `X` is an ancestor of `Y`. It ignores V columns. Node identity follows
lineage (§6.6) composed along the chain. The JSON form has these sections:

| section | content |
|---|---|
| `nodes` | `added`, `removed`, `renamed` (old → new, with the lineage method), `modified` (same node, different `content_hash`), `moved` (different `parent_id`), and counts per kind |
| `status_transitions` | node status changes sorted by badness (precedence of §6.4, worst first), link status changes with their history evidence, and counts |
| `risk` | behaviors newly risky, no longer risky, `severity` changes of at least 1.0, and the new top 10 |
| `spec` | spec items added, removed, and changed (`content_hash`) |
| `workflows` | workflows added, removed, and changed (a different trace: the node sets of the steps, with ids mapped through lineage) |
| `summary` | one line per section |

`--format md` renders at most 60 lines, for a pull-request comment; longer sections are truncated
with a count. The output is deterministic and sorted.

## 9. Conformance

A conforming v0.4 file:

- has `meta.format_version = '0.4'`, a `class` on every `meta` row, and `meta.head_epoch` naming the
  epoch with the highest `seq`;
- has a parent chain in which every epoch's parent is the previous kept epoch;
- satisfies every foreign key and CHECK constraint in the DDL, and the node references of §5.2;
- has `version_key` values that recompute from their payloads, no version row unreferenced by any
  membership row, and at most one version per id per epoch;
- has the head materialized, and `epochs.materialized` consistent with `epoch_materialized`;
- for every epoch: rows that validate against `ir-v0.4.schema.json`, `id = node_id(side, kind,
  qualified_name)` for every node, `subtree_hash` values that recompute (§2), a matching
  `contains`/`declares` edge for every `parent_id`, and lineage rows whose new ids are nodes of the
  epoch (and whose old ids are nodes of the parent, when the parent is the immediately preceding
  `seq`);
- for every materialized epoch: exactly one glyph and one `node_status` row per node, every node in
  `workflow_steps.node_ids_json`, `workflow_step_nodes` equal to the rows derived from
  `workflow_steps`, `link_id = link_id(spec, code, method)` and `confidence = 1.0` for every
  deterministic link, link statuses equal to `link_state`, and `status_rollup` rows that recompute
  from `node_status`.

`ad2v validate [--epoch X]` checks all of the above, and rejects files with another
`format_version`.

## 10. Tools and incremental extraction (normative where stated)

### 10.1 Parse cache

`ad2v extract --into FILE` appends a new head epoch to `FILE` (creating it if needed). Per-file
**local facts** (definitions, imports, spec references, byte ranges, name-masked body hashes) are
cached in `parse_cache`, keyed by `(path, content_hash, rules_hash, extractor_version)` and stored as
zlib-compressed canonical JSON. A hit skips the local passes for that file; the file is still parsed,
because the global passes (import resolution, call and resource resolution, ports, workflows,
pairing) walk syntax trees and always recompute (ADR-0018). `--no-cache` ignores the cache. The
cache is informative: a cached and an uncached extraction MUST produce identical normative dumps.
The CLI summary reports the hit rate.

### 10.2 History

`ad2v history --repo R --commits RANGE --into FILE [--spec REL] [--manifest REL] [--test-results
REL]` extracts every commit of `git rev-list --reverse RANGE` in order, each into a temporary
directory filled by `git archive` (paths are checked against zip-slip), appending one epoch per
commit whose inputs changed, with `repo_commit` set to the commit. Spec, manifest and test-result
paths are relative to the repo root in each commit.

### 10.3 Epoch management

| command | effect |
|---|---|
| `ad2v log FILE` | epochs in order: seq, id, parent, commit, change kind, pinned/label, materialized, node count |
| `ad2v pin FILE EPOCH [--label L]` / `unpin` | pin (and materialize) or unpin an epoch; labels are unique |
| `ad2v materialize FILE --epoch X` | write the derived rows of epoch X (§5.3) |
| `ad2v prune FILE --keep-last N [--keep-pinned]` | delete older epochs (never the head), re-parent every kept epoch to its nearest kept ancestor, garbage-collect version rows, rules and manifests no kept epoch references and cache rows whose file content no kept epoch contains, then `VACUUM` |

Wherever an epoch is expected, the tools accept an epoch id, `head`, `parent` (of the head), a pin
label, or a commit SHA prefix of at least 7 characters.

## 11. The LLM layer (informative, P4)

Everything in this section is **informative** (class I). It never enters an epoch id or a
normative table, and `dump --normative-only` excludes it. A normative dump is byte-identical with or
without any LLM run. Repository content given to a model is untrusted data (§11.9).

### 11.1 Configuration

The optional `llm:` section of `ad2v.yaml` (or of a file with the same shape passed with
`--manifest`) has these keys:

- `provider`: `fake` | `vertex` | `openai_compatible`;
- `project`, `location`, `model`;
- `base_url` and `api_key_env` (openai_compatible; the key comes from that env var, never from the file);
- `output_language` (BCP-47);
- `pricing.{input,output}_per_mtok` (USD per 1M tokens);
- `budget_usd`;
- `slice.*`: `code_max_lines` 150, `code_head` 100, `code_tail` 50, `callee_sig_max_lines` 40,
  `openapi_max_lines` 60, `stale_diff_max_lines` 80;
- `judge.min_confidence` 0.6;
- `suggest.top_k` 5;
- `summaries.scope` `structural` | `all`.

`llm_config_hash = sha256(canonical_json(effective llm config))` is recorded on each run and is
excluded from `config_hash`.

### 11.2 Providers, cache and runs

Providers use HTTP from the standard library, with no SDKs (ADR-0027). Every call has
`temperature 0` and `seed 987654` where supported, strict JSON output with a response schema, and
at most 4 attempts on 429/5xx. Vertex requests carry the labels `project=ad2v` and
`ad2v_task=<task>` and authenticate with an OAuth token from the gcloud CLI (never an API key).

| term | definition |
|---|---|
| `input_hash` | `sha256(canonical_json({"task", "parts": [instructions, fenced data parts…]}))`: the exact serialized slice |
| `prompt_hash` | `sha256(normalized prompt template src/ad2v/llm/prompts/<task>.v1.md)` |
| `params_hash` | `sha256(canonical_json({temperature, seed, output_language, task}))` |
| cache key | `(task, input_hash, prompt_hash, provider, model, params_hash)`; `model_version` is recorded but only known after the call |
| `result_id` | `"r_" + sha256(canonical_json([cache key…, ordinal]))[:20]`; the newest row with a key answers lookups |

`ad2v llm plan` lists the calls needed after cache hits, with token and USD estimates.
`ad2v llm run` needs `--max-cost-usd` and `--yes`. It stops before a call that would exceed the
budget and writes an `llm_runs` row. Cached outputs are re-validated on every hit (§11.9).

### 11.3 Tables and the effective status

| table | content |
|---|---|
| `source_blobs` | normalized file texts by content hash (zlib); slices are cut from them |
| `llm_results` | the cache: output, validity, validation errors, usage, estimated cost, latency |
| `llm_runs`, `llm_run_results` | run log, and which results each run produced or reused |
| `link_judgments` | per link: verdict, confidence, rationale, evidence, validity, `overlay` |
| `link_suggestions` | per candidate pair: BM25 rank and score, verdict, confidence, `state` (open / accepted / rejected) |
| `spec_extractions` | per prose document: the proposal's path and state (proposed / written / ingested) |
| `summaries`, `narrations` | as before, now with `result_id` |

The informative per-epoch tables exist for materialized epochs, are dropped with the derived
tables, and are rebuilt **from the cache only** (no call): at `extract --into` when the file holds
LLM results, and at the start of every run.

`node_status_effective(epoch_id, node_id, normative_status, status, provenance, suggested,
llm_evidence_json)` follows these rules:

- a valid judge `drift` with confidence ≥ `judge.min_confidence`, and no injection warning,
  upgrades `implemented`/`verified` to `drift` with `provenance = 'llm'`;
- `partial`, `cannot_tell` and low confidence add evidence only;
- an open suggestion sets `suggested` and never changes the status;
- the LLM can never clear or downgrade `missing`, `orphan`, `needs_review`, `stale` or a
  structural `drift`.

Viewers show the normative status by default, with a toggle for the effective status.

### 11.4 Semantic judge (`judge`)

For every link with both sides, a method other than `none`, a status of implemented, verified or
stale, and a code side that is not a test, the slice contains:

- **spec side:** the item's lines; for an endpoint, its OpenAPI operation (≤ 60 lines);
- **code side:** the node's span (a port's handler), capped at head 100 + tail 50 lines with an
  elision marker, plus an IR digest of the elided lines (calls, touches, behaviors). For a
  container or component, an IR digest;
- **callees:** the signatures of direct callees on the node's workflows (≤ 40 lines);
- **resources** reached;
- **stale links:** a unified diff of the changed side since `agreed_epoch_id` (≤ 80 lines).

The output is `{verdict: conforms|partial|drift|cannot_tell, confidence, rationale ≤ 400,
evidence: [{side, start_line, end_line, claim ≤ 160}]}`. The result is invalid when an evidence
range is outside the slice, when `drift`/`partial` lacks spec or code evidence, or when the
rationale is empty. An invalid result is stored as `cannot_tell`.

`ad2v llm eval --expected <yaml>` reports, per run, accuracy, the confusion matrix, Cohen's κ and
the validity rate. Across runs it reports stability: the share of identical verdicts.

### 11.5 Link suggestions (`suggest`)

**Items.** For each unpaired spec item (`specified`/`missing`) and each unpaired code item
(`orphan`, plus `none` ports when spec coverage is present), BM25 over names, qualified names,
docstrings, route paths and spec text gives the top-k candidates from the other side.

**The call.** One call per item returns at most 2 matches. A `match` must cite the candidate's
code lines when it has any. Matches at or above the threshold become suggestions.

**Confirmation.**
- `ad2v suggestions accept <id> --manifest ad2v.yaml` appends to `pairing.links`.
- `ad2v suggestions reject <id> --manifest ad2v.yaml` appends to `pairing.rejected`.

Both edits are append-only and keep the file's comments and order. Either one changes
`config_hash`, so the next extraction makes an accepted link normative (method `manifest_link`).
A rejected pair is never a candidate again.

### 11.6 Summaries (`summarize`)

Summaries are built bottom-up over containment. `label` is deterministic (the display name and
kind). One call per node returns `{card ≤ 240, deep ≤ 1200, mentions}`. A leaf's input is its code
span and IR digest. A parent's input is its IR digest (counts, ports, resources, risky behaviors,
roll-up) plus its children's cards and `result_id`s, so a changed leaf re-summarizes only its
ancestor chain. Mentions must be node ids present in the input.

**Scope.** `structural` (the default) covers the system, containers, components, modules, ports,
risky behaviors, and functions that are linked or are port handlers. `all` covers every code node.

### 11.7 Narrations (`narrate`)

For each code workflow and each containment depth whose projection differs from the previous one,
one call (per chunk of 40 coarse steps) returns one narration per coarse step (≤ 280 chars).
Spans come from `workflows.project()`. The input includes the enclosing coarser step's narration,
so finer levels refine coarser ones. `containment` narrations are written eagerly; `call_depth`
narrations are written on demand (`--mode call_depth --workflow X`).

### 11.8 Prose extraction (`extract-prose`)

For each Markdown `spec_doc` with free prose, the model returns structured components and EARS
requirements with their source lines. ad2v renders them as Markdown in the existing convention,
with IDs from the reserved range (`CMP-X001`, `REQ-X001`, numbered across documents in path
order). The file header states the model, prompt hash, source content hash and "REVIEW BEFORE
COMMITTING". The file goes to `<spec root>/.ad2v-extracted/<doc-slug>.md`, which extraction always
skips. **Moving or renaming the file into the spec tree is the approval**; it is then parsed like
any spec file.

### 11.9 Untrusted input

- **Fences.** Repository content is fenced as `<untrusted-data id kind source>…</untrusted-data>`.
  The id derives from the content, and fence tags inside the content are neutralized. The system
  prompt states that fenced text is data and that instructions inside it must be ignored.
- **Flags.** Outputs are validated as above. A verbatim copy of ≥ 60 chars of fenced repository
  text is flagged, and it invalidates the result when the copied text contains an instruction-like
  phrase. Instruction-like phrases anywhere in the input add an `injection_suspected` warning,
  which blocks the drift overlay.

## 12. Layout and the viewer (P5)

### 12.1 Layout `nestgrid-v1` (normative for producers that write `layout`)

The layout gives every node of a materialized epoch a box `(x, y, z, w, h, d)` in `layout`
(`lod = 0`, `algorithm = 'nestgrid-v1'`). `x, y` are on the ground plane (y grows south), `z` is
the height the box stands at and `d` its own height. The algorithm is deterministic and uses no
randomness:

1. **Region.** The code system sits at the origin. The spec root is a separate region to the west,
   `SPEC_GAP = 8` units from the code side.
2. **Children** are packed in a grid inside their parent (inner padding `PAD = 0.5`, track gap
   `GAP = 0.3`), in stable order: kind order of `ir.NODE_KINDS`, then qualified name.
3. **Leaves** get a log-bucketed side (`1 + 0.5 × ⌊log2(size_weight) / 2⌋`, at most 4). Leaves for
   resources (datastore, queue, external service, LLM endpoint, UI) stand taller.
4. **Ports** (HTTP routes, CLI commands, MCP tools, consumers, schedules) sit on the parent's east
   and south edges, `PORT_STEP = 0.6` apart. A new port goes to the shorter edge.
5. **Track sizes** are quantized to `1, 1.5, 2, 3, 4, 6, 8, 12, 16`, then ×1.25 per step on a 0.5
   grid. A track that must grow is sized for `HEADROOM = 1.2` times what it needs. Tracks never
   shrink.
6. **Height.** `z = parent.z + parent.d`.

**Grids are persisted** in `layout_grids` (N): per parent, the track sizes, each child's
`(row, col)` slot and each port's `(edge, index)`. In a new epoch a parent starts from its parent
epoch's grid, with ids mapped through `id_lineage`. Existing children keep their slot, removed
children free it, new children fill free slots in stable order, and the grid grows only by
appending a row or a column.

**History dependence.** Like `id_lineage` and `link_state`, `layout` and `layout_grids` depend on
the parent epoch. This is the one further exception to principle 8: a fresh single-epoch extraction
MAY produce a different (still valid) layout than the same epoch reached through history. Both are
deterministic functions of their inputs. On the P3 history fixture, 765 of 765 boxes of surviving
nodes stay put across all epochs.

Layout is written for the head by `extract` and by `materialize`. `ad2v layout` lays out the
epochs that lack one. `ad2v materialize --epochs last:N` materializes (and lays out) the last N
epochs plus the pinned ones. Layout rows are kept for every epoch that has them (they are not
dropped with other derived rows) and are deleted by `prune`.

### 12.2 The viewer (informative)

`viewer/` is a static web app (TypeScript, three.js, sql.js). It reads a `.ad2v` file read-only
through a `DataSource` interface. `LocalFileSource` runs SQL on the file in the browser, and a
future MCP-backed source (P6) implements the same interface.

- **Serving.** `ad2v view FILE` serves the built viewer and the file on `127.0.0.1` only, for
  GET and HEAD only, under a strict CSP (`default-src 'self'`, plus `'wasm-unsafe-eval'` for
  sql.js). The wheel ships the built viewer as `ad2v/_viewer`.
- **Scope.** The viewer shows only materialized epochs. It never triggers LLM calls and never
  writes the file or `ad2v.yaml`. Actions that change state (accept a suggestion, run the LLM
  layer) are shown as copyable CLI commands.
- **Camera and LOD.** The camera is an orthographic isometric view, with no rotation. A box's
  level of detail follows its on-screen footprint: hidden under 8 px, silhouette under 40 px,
  detail under 160 px, open above. A level drops only below 0.8 × its threshold (hysteresis).
  Boxes outside the viewport are culled.
- **Status styling** comes from the theme tokens (§6, `schema/themes/*.json`) through the same
  mapping as `tokens.py`, checked by a parity test. Effective status shows an `AI` badge when it
  comes from an LLM judgment.
- **Replay.** The playhead lives on the fine (per-call) trace. Coarser levels are projections of
  it (`workflows.project`, re-implemented in TypeScript and checked for parity with Python on
  every workflow and depth), so changing the detail level never moves the playhead.
- **Diff.** Two materialized epochs are compared through composed `id_lineage`. Nodes are shown as
  added, removed (ghosts), renamed, or status transitions.

## 13. MCP access (P6)

### 13.1 Retrieval rules (normative for `rules_hash`)

The rules file may hold a `retrieval:` section: BM25 field weights (`name`, `qname`, `code`,
`spec`, `summary`, `narration`), `status_boost`, `prefix_min` and `intents` (trigger words →
kind multipliers). It decides which components a natural-language question points at, so it is
part of the rules and of `rules_hash`, like `severity:`. It changes nothing in the extracted
graph. A consumer that ranks components by question SHOULD use the `retrieval:` section of the
rules stored with the epoch, and fall back to its own defaults when there is none (files
extracted before P6).

### 13.2 The MCP server (informative)

`ad2v mcp` exposes `.ad2v` files read-only over the Model Context Protocol (2026-07-28, with
legacy `initialize` accepted).

- **Agent tools:** `ad2v_files`, `ad2v_overview`, `ad2v_search`, `ad2v_locate`,
  `ad2v_get_node`, `ad2v_neighborhood`, `ad2v_status`, `ad2v_links`, `ad2v_risks`,
  `ad2v_workflow`, `ad2v_diff`, `ad2v_show` and `ad2v_llm_plan`.
  - They return node references `{id, label, kind, qualified_name, status}`.
  - Free text from the repository or from an LLM is wrapped as `untrusted_text`.
  - Actions that would write (materialize, accept suggestions, run the LLM layer) are returned
    as CLI commands.
- **App tools:** `viewer_*` tools mirror the viewer's `DataSource` (§12.2) for the MCP App
  `ui://ad2v/map` (MCP Apps 2026-01-26).
  - `viewer_scene(epoch, root_id, depth)` returns a slice of an epoch: every root; the root's
    ancestors and their children; its subtree to `depth`; and its direct neighbors with their
    ancestors.
  - The app renders the answers of `ad2v_show` (node ids plus a camera intent: `focus`, `fit`,
    `path`, `replay`, `diff`; never coordinates) from the file's own layout.

## Appendix A: column classes (normative)

Every column in the DDL is marked **N** (normative), **I** (informative), **V** (volatile: deterministic, ignored by `ad2v diff`) or **N/I** (depends on the row, e.g. `provenance`). This appendix is generated from the DDL comments and a test keeps it in sync.

<!-- BEGIN COLUMN CLASSES (generated by `python -m ad2v.ddl`) -->

**meta**

| column | class | note |
|---|---|---|
| `key` | N |  |
| `value` | N/I | (the row's `class`) |
| `class` | N |  |

**epochs**

| column | class | note |
|---|---|---|
| `epoch_id` | N | e_ + sha256(parent\|repo\|spec\|rules\|config\|test_results hashes)[:20] |
| `parent_epoch_id` | N | NULL only for the first kept epoch |
| `seq` | N | 1, 2, 3... in append order |
| `repo_commit` | N | git commit the epoch was extracted from, if known |
| `repo_tree_hash` | N |  |
| `spec_tree_hash` | N |  |
| `rules_hash` | N |  |
| `config_hash` | N |  |
| `test_results_hash` | N | tree hash of the normalized test-result files in effect |
| `change_kind` | N | which input hashes changed vs the parent |
| `pinned` | I | file-management state: kept by prune, stays materialized |
| `label` | I | file-management state (e.g. a release tag) |
| `materialized` | I | file-management state: derived rows present |
| `attrs_json` | N | config echo, pairing warnings, unmatched tests, cache stats |
| `created_at` | I | excluded from canonical dump |

**rules_versions**

| column | class | note |
|---|---|---|
| `rules_hash` | N |  |
| `rules_json` | N | merged, canonicalized rules |

**config_versions**

| column | class | note |
|---|---|---|
| `config_hash` | N |  |
| `config_json` | N | {"manifest": ..., "effective": {...}} |

**epoch_materialized**

| column | class | note |
|---|---|---|
| `epoch_id` | I |  |
| `table_name` | I |  |

**node_versions**

| column | class | note |
|---|---|---|
| `vid` | I | storage surrogate, file-local |
| `version_key` | N | v_ + sha256(canonical normative payload)[:20] |
| `node_id` | N | n_ + sha256(side\|kind\|qualified_name)[:20] |
| `side` | N |  |
| `kind` | N | closed enum, see spec §3.2 |
| `name` | N |  |
| `qualified_name` | N |  |
| `parent_id` | N | NULL for roots |
| `path` | N | repo- or spec-root-relative, forward slashes |
| `content_hash` | N |  |
| `subtree_hash` | N |  |
| `level_hint` | N | optional presentation hint |
| `attrs_json` | N |  |
| `spec_ref_json` | N | sorted list of explicit spec IDs |

**epoch_nodes**

| column | class | note |
|---|---|---|
| `seq` | N | the epoch |
| `vid` | N |  |
| `span_start_line` | V | 1-based, inclusive |
| `span_end_line` | V | 1-based, inclusive |

**edge_versions**

| column | class | note |
|---|---|---|
| `vid` | I | storage surrogate, file-local |
| `version_key` | N | v_ + sha256(canonical normative payload)[:20] |
| `src` | N |  |
| `dst` | N |  |
| `kind` | N | closed enum, see spec §3.4 |
| `weight` | N | occurrence count |
| `attrs_json` | N | without the volatile `lines` key |
| `provenance` | N |  |
| `model` | I | required when provenance='llm' |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |

**epoch_edges**

| column | class | note |
|---|---|---|
| `seq` | N | the epoch |
| `vid` | N |  |
| `lines_json` | V | attrs.lines (source lines of occurrences) |

**unresolved_ref_versions**

| column | class | note |
|---|---|---|
| `vid` | I | storage surrogate, file-local |
| `version_key` | N |  |
| `src` | N | node carrying the reference |
| `ref` | N | the referenced identifier, verbatim |
| `ref_kind` | N | 'spec_id' |
| `reason` | N | 'not_found' |

**epoch_unresolved_refs**

| column | class | note |
|---|---|---|
| `seq` | N | the epoch |
| `vid` | N |  |

**test_result_versions**

| column | class | note |
|---|---|---|
| `vid` | I | storage surrogate, file-local |
| `version_key` | N |  |
| `test_node_id` | N |  |
| `outcome` | N |  |
| `source_file` | N | result file name (repo-relative if inside the repo) |
| `duration_ms` | N | as recorded in the input file |

**epoch_test_results**

| column | class | note |
|---|---|---|
| `seq` | N | the epoch |
| `vid` | N |  |

**code_fact_versions**

| column | class | note |
|---|---|---|
| `vid` | I | storage surrogate, file-local |
| `version_key` | N |  |
| `fact_kind` | N |  |
| `subject_id` | N | function/module id ('events','wrappers') or port id ('entry') |
| `payload_json` | N |  |

**epoch_code_facts**

| column | class | note |
|---|---|---|
| `seq` | N | the epoch |
| `vid` | N |  |

**id_lineage**

| column | class | note |
|---|---|---|
| `epoch_id` | N | the newer epoch |
| `old_id` | N | node id in the parent epoch |
| `new_id` | N | node id in this epoch |
| `method` | N |  |
| `score` | N | 1.0, or the header Jaccard similarity |

**link_state**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `link_id` | N |  |
| `spec_node_id` | N |  |
| `code_node_id` | N |  |
| `method` | N |  |
| `status` | N | final link status in this epoch |
| `history_json` | N | history evidence (spec_changed_since, ...) |
| `agreed_epoch_id` | N | last epoch where the link was implemented/verified |
| `agreed_spec_hash` | N | spec content_hash at that agreement |
| `agreed_code_hash` | N | code content_hash at that agreement |

**parse_cache**

| column | class | note |
|---|---|---|
| `path` | I | repo-relative path |
| `content_hash` | I |  |
| `rules_hash` | I |  |
| `extractor_version` | I |  |
| `payload_blob` | I |  |

**glyphs**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N |  |
| `base_shape` | N | glyph grammar §2 |
| `variant` | N | glyph grammar §3 |
| `modifiers_json` | N | glyph grammar §4 |
| `size_weight` | N | glyph grammar §6 |
| `has_interior` | N | 0/1, LOD 2 availability |

**workflows**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `workflow_id` | N | w_ + sha256(side\|entry_node_id\|source)[:20] |
| `name` | N |  |
| `side` | N |  |
| `entry_node_id` | N |  |
| `scenario_id` | N | spec-side workflows: the scenario node |
| `source` | N |  |
| `attrs_json` | N | e.g. truncated, max_depth |
| `model` | I | required when source='llm_inferred' |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |

**workflow_steps**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `workflow_id` | N |  |
| `seq` | N | 0-based, contiguous |
| `node_ids_json` | N | nodes lit together (parallel steps share a row) |
| `depth` | N | call depth from the entry (entry = 0) |

**workflow_step_nodes**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `workflow_id` | N |  |
| `seq` | N |  |
| `node_id` | N |  |

**links**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `link_id` | N | l_ + sha256(spec_node_id\|code_node_id\|method)[:20] |
| `spec_node_id` | N | NULL for orphan code |
| `code_node_id` | N | NULL for missing/specified spec items |
| `method` | N | how the pair was found; 'none' for unpaired rows |
| `status` | N/I | (I when provenance='llm') |
| `provenance` | N |  |
| `evidence_json` | N/I |  |
| `confidence` | N/I | 1.0 for deterministic links |
| `model` | I |  |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `created_at` | I | excluded from canonical dump |

**node_status**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N |  |
| `status` | N |  |
| `reasons_json` | N | {precedence: [...], reasons: [...]} (spec §6.4) |

**status_rollup**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N |  |
| `counts_json` | N | {status: count}, zero counts omitted |

**summaries**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N |  |
| `length` | N |  |
| `text` | I |  |
| `model` | I |  |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |
| `created_at` | I |  |
| `result_id` | I | the cached LLM result (NULL for label) |

**narrations**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `workflow_id` | N |  |
| `mode` | N | projection mode |
| `detail_level` | N | projection level (workflows.project) |
| `span_start` | N | first fine step seq (inclusive) |
| `span_end` | N | last fine step seq (inclusive) |
| `text` | I |  |
| `model` | I |  |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |
| `created_at` | I |  |
| `result_id` | I | the cached LLM result |

**layout**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N |  |
| `lod` | N |  |
| `algorithm` | N | name@version of the deterministic layout |
| `x` | N |  |
| `y` | N |  |
| `z` | N |  |
| `w` | N |  |
| `h` | N |  |
| `d` | N |  |

**layout_grids**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `node_id` | N | the parent node |
| `algorithm` | N | e.g. nestgrid-v1 |
| `grid_json` | N | {"cols": [...], "rows": [...], "slots": {child: [row, col]}} |

**tours**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `tour_id` | N |  |
| `title` | N/I |  |
| `source` | N |  |
| `workflow_id` | N | optional: tour that replays a workflow |
| `model` | I |  |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |
| `created_at` | I |  |

**tour_stops**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `tour_id` | N |  |
| `seq` | N |  |
| `node_id` | N | camera target |
| `camera_json` | N | {lod, yaw, pitch, zoom} |
| `text` | I |  |

**source_blobs**

| column | class | note |
|---|---|---|
| `content_hash` | I |  |
| `text_blob` | I |  |

**llm_results**

| column | class | note |
|---|---|---|
| `result_id` | I | r_ + sha256(cache key \| ordinal)[:20] |
| `seq` | I | insertion order |
| `task` | I |  |
| `input_hash` | I | sha256(canonical JSON of the exact slice) |
| `prompt_hash` | I | sha256(normalized prompt template) |
| `provider` | I |  |
| `model` | I |  |
| `model_version` | I | as reported by the provider |
| `params_hash` | I | sha256(canonical generation params) |
| `subject` | I | what was asked about (link id, node id, ...) |
| `output_json` | I | the parsed output (NULL if not JSON) |
| `valid` | I | 0/1: passed schema + deterministic checks |
| `validation_errors` | I | JSON list |
| `usage_json` | I | {"input_tokens","output_tokens"} |
| `cost_usd_est` | I | from llm.pricing (NULL if unpriced) |
| `latency_ms` | I |  |
| `created_at` | I |  |

**llm_runs**

| column | class | note |
|---|---|---|
| `run_id` | I | u_ + sha256(started_at\|tasks\|epoch)[:20] |
| `started_at` | I |  |
| `ended_at` | I |  |
| `epoch_id` | I |  |
| `provider` | I |  |
| `model` | I |  |
| `model_version` | I | last reported by the provider |
| `llm_config_hash` | I |  |
| `llm_config_json` | I | effective llm config (no secrets) |
| `tasks_json` | I |  |
| `calls` | I | provider calls made |
| `cache_hits` | I |  |
| `input_tokens` | I |  |
| `output_tokens` | I |  |
| `cost_usd_est` | I |  |
| `max_cost_usd` | I |  |
| `aborted` | I | 1: stopped before exceeding the budget |
| `notes_json` | I |  |

**llm_run_results**

| column | class | note |
|---|---|---|
| `run_id` | I |  |
| `result_id` | I |  |
| `cached` | I | 1: served from the cache |

**link_judgments**

| column | class | note |
|---|---|---|
| `epoch_id` | I |  |
| `link_id` | I |  |
| `result_id` | I |  |
| `verdict` | I |  |
| `confidence` | I |  |
| `rationale` | I |  |
| `evidence_json` | I |  |
| `valid` | I |  |
| `overlay` | I |  |

**link_suggestions**

| column | class | note |
|---|---|---|
| `epoch_id` | I |  |
| `suggestion_id` | I | s_ + sha256(spec_node_id\|code_node_id)[:20] |
| `spec_node_id` | I |  |
| `code_node_id` | I |  |
| `candidate_rank` | I | 1-based BM25 rank |
| `lexical_score` | I | BM25 score (deterministic) |
| `result_id` | I |  |
| `verdict` | I |  |
| `confidence` | I |  |
| `rationale` | I |  |
| `state` | I |  |

**spec_extractions**

| column | class | note |
|---|---|---|
| `epoch_id` | I |  |
| `spec_doc_node_id` | I |  |
| `result_id` | I |  |
| `output_path` | I | spec-root-relative |
| `state` | I |  |

<!-- END COLUMN CLASSES -->
