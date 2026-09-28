# The ad2v file format, version 0.2

Status: **draft, normative**. The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.

An `.ad2v` file is a single SQLite 3 database. It describes a software system from two sides, the
**code** in a repository and the **specs** (spec-driven development documents), as one graph of
nodes and edges. It also holds glyphs for rendering, workflows for replay, and the deterministic
**pairing** of spec items with code: links, per-node statuses and roll-ups. Viewers, agents (via MCP)
and diff tools read it. Producers ("extractors") write it.

Companion documents:

- [`glyph-grammar-v0.2.md`](glyph-grammar-v0.2.md): how nodes become shapes (normative).
- [`visual-tokens-v0.2.md`](visual-tokens-v0.2.md): how statuses become line styles and colors
  (status → style normative, palettes informative).
- [`spec-markdown-convention.md`](spec-markdown-convention.md): the Markdown spec convention (normative for extractors).
- [`../../schema/ad2v-v0.2.sql`](../../schema/ad2v-v0.2.sql): DDL (normative).
- [`../../schema/ir-v0.2.schema.json`](../../schema/ir-v0.2.schema.json): JSON Schema of the IR (normative).

### Changes from v0.1

v0.2 is not backward compatible with v0.1 files, and there is no migration. `ad2v validate` rejects
files older than 0.2 with a message to re-extract. The changes:

| area | change |
|---|---|
| kinds | new spec kind `spec_root`: one synthetic root per file, parent of every `spec_doc` (§3.2) |
| identity | behavior qualified names are **content-anchored** `@<kind>#<sha8(header)>` instead of ordinals (§3.3, ADR-0011) |
| epochs | new columns `config_hash`, `test_results_hash`. `rules_hash` is now over the merged, canonicalized rules (overlay-aware). All of them enter the epoch id (§2, ADR-0012) |
| tables | new `workflow_step_nodes`, `node_status`, `status_rollup`, `test_results`. `meta.class` added. `links.method` added, `links.confidence` now NOT NULL. `links` is populated (§5, §6) |
| attrs | behavior `severity`, `severity_rank`, `severity_reach` (§3.8). Function `params`, `var_kwargs`. `spec_endpoint` `base_path`, `path_params`, `query_params`, `required_query` |
| projection | containment projection is the default, and call-depth becomes a mode (§7, ADR-0013) |
| dump | `--normative-only`. The determinism guarantee is stated for normative rows (§8) |

---

## 1. Principles

1. **Normative vs. informative.** Every table and column is either **N** (normative: deterministic;
   the same inputs produce the same value in every conforming producer) or **I** (informative:
   produced by an LLM, by runtime observation, or by the wall clock). Informative rows that come
   from an LLM MUST carry `model`, `model_version`, `prompt_hash`, `input_hash` and `confidence`.
   The DDL enforces this with `CHECK` constraints.
2. **Stable identity.** A node's `id` depends on what the node *is* (side, kind, qualified name),
   never on its content. Change is tracked separately by `content_hash` and `subtree_hash`.
3. **Cross-platform determinism.** Paths use `/`. Content is hashed after LF normalization and BOM
   stripping. All iteration is sorted. Timestamps never enter hashes.
4. **One file, canonical dump.** Two producers agree when their normative canonical dumps (§8) are
   byte-identical. SQLite file bytes are *not* compared.
5. **Relative levels.** There are no global levels (L1/L2/L3). Depth is the depth in the
   `contains` hierarchy and MAY differ between branches. `level_hint` is presentation metadata only.
6. **Knowledge never grants capability.** Producers read the repository. They MUST NOT import,
   execute or evaluate repository code. Test results are *ingested* from files; producers never run
   tests.
7. **Additive evolution.** Later versions MAY add tables, columns, node kinds, edge kinds, attrs
   keys and risk flags. They MUST NOT change the meaning of an existing column or value.

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
| `content_hash` | For nodes with a source span: `sha256_hex(normalized text of lines span_start_line..span_end_line)` (lines joined with `\n`). For files (modules, `spec_doc`): the whole normalized file. For nodes without text (system, `spec_root`, container, component, resources, ports): `sha256_hex(canonical_json({"kind","name","attrs"}))`. |
| `subtree_hash` | `sha256_hex(join("\n", [content_hash] + ["<child_id>:<child_subtree_hash>" for children sorted by id]))`, where children are nodes whose `parent_id` is this node. |
| Tree hashes | `repo_tree_hash`, `spec_tree_hash`, `test_results_hash` = `sha256_hex(join("\n", ["<path>\t<content_hash(file)>" sorted by path]))` over the files read (test results: file paths relative to the repo if inside it, else the file name). |
| `rules_hash` | `sha256_hex(canonical_json(merged rules))`: the built-in rules deep-merged with the manifest's `rules_overlay` (maps merge, lists and scalars replace). Comments and formatting do not count; content does. |
| `config_hash` | `sha256_hex(canonical_json(parsed ad2v.yaml))`, `{}` when there is no manifest. |

Every input that can change the output (code, specs, rules, manifest, test results) enters the
epoch id.

## 3. The IR

The IR is the logical model. `schema/ir-v0.2.schema.json` defines its JSON form, and the tables in
§5 store it.

### 3.1 Node

| field | class | meaning |
|---|---|---|
| `id` | N | stable id (§2) |
| `side` | N | `code` or `spec` |
| `kind` | N | closed enum (§3.2) |
| `name` | N | display name |
| `qualified_name` | N | canonical name, unique per (side, kind) (§3.3) |
| `parent_id` | N | parent in the `contains` (code) / `declares` (spec) hierarchy; NULL for roots |
| `path`, `span_start_line`, `span_end_line` | N | source location (1-based, inclusive). Spec nodes point into spec files. |
| `content_hash`, `subtree_hash` | N | §2 |
| `level_hint` | N | optional hint: `system`, `container`, `component`, `code`, `port`, `resource`, `behavior`, `spec` |
| `attrs` | N | kind-specific JSON object (§3.5) |
| `spec_ref` | N | sorted list of explicit spec IDs attached to this node (§3.6) |

### 3.2 Node kinds (closed enum, v0.2)

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
| `cli_command` | `cli:<container>:<command name>` | `cli:worker:run-nightly` |
| `event_consumer` | `event:<container>:<handler qualified name>` | `event:worker:worker/recon_worker/events.py::handle_statement_uploaded` |
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
the ones not emitted, so changing `behavior.emit_all` never renames a node. Inserting an unrelated
loop no longer renames the other loops in the function.

**Spec IDs are the qualified names of spec nodes.**

### 3.4 Edges

`(src, kind, dst)` is unique. Repeated occurrences increase `weight`. `attrs.lines` (sorted,
deduplicated) records the source lines of occurrences on the `src` side when known.

| kind | from → to | meaning |
|---|---|---|
| `contains` | code parent → code child | hierarchy (mirrors `parent_id`) |
| `declares` | spec parent → spec child | spec hierarchy (mirrors `parent_id`) |
| `imports` | module → module | repo-internal import |
| `calls` | function/module/port → function/class | resolved call; port → handler |
| `reads`, `writes` | function/module → `datastore` | access classified by method / SQL verb; unknown access defaults to `reads` with `attrs.access = "default"` |
| `publishes`, `consumes` | function/module → `queue` | |
| `exposes` | container → port | the container serves the port |
| `invokes_external` | function/module → `external_service` | |
| `invokes_llm` | function/module → `llm_endpoint` | |
| `annotated_as` | any node → spec node | explicit spec ID reference (§3.6). Also spec → spec (a Gherkin scenario tagged `@REQ-012`), see ADR-0005. Code → spec edges are the input of the `annotation` pairing method (§6.1). |

`provenance` is `deterministic` for every edge a v0.2 extractor writes.

### 3.5 Attributes (well-known keys)

| kind | keys |
|---|---|
| `container` | `container_kind` (manifest `kind`), `replicas`, `paths`, `declared` (bool) |
| `function` | `async` (bool), `decorators` (list of dotted names), `is_test` (bool), `params` (names in order, without `self`/`cls`), `var_kwargs` (bool: has `**kwargs`) |
| `http_route` | `method`, `path`, `framework`, `handler` (qname) |
| `mcp_tool` | `tool_name`, `framework`, `handler` |
| `cli_command` | `command`, `framework`, `handler` |
| `event_consumer` | `framework`, `handler`, `source` (subscription name if resolvable) |
| resources | `libraries`, `resource_name`, `name_source` (`literal`, `env`, `unknown`) |
| behavior | `risk` (sorted list of risk flags), `construct`, `library`, `touches`, `severity`, `severity_rank`, `severity_reach` (§3.8) |
| `requirement` | `text`, `ears` (`event`, `state`, `unwanted`, `optional`, `ubiquitous`, or `null`), `trigger`, `system`, `response`, `precondition` |
| `scenario` | `keyword`, `tags`, `background` (bool), `examples` (count), `rule` |
| `scenario_step` | `keyword`, `keyword_type`, `text` |
| `spec_endpoint` | `method`, `path`, `operation_id`, `summary`, `tags`, `base_path` (path of `servers[0].url`), `path_params`, `query_params`, `required_query` (parameter names; local `$ref`s resolved) |
| `spec_doc` | `format` (`markdown`, `gherkin`, `openapi`), `prose` (Markdown only: unparsed text), `base_path` (OpenAPI) |

**Risk flags** (`attrs.risk`): `io_in_loop`, `llm_in_loop`, `unbounded_retry`, `fan_out`,
`nested_loop_io`, `slow_io_in_transaction` (ADR-0006). By default, behavior nodes are emitted only
when they have at least one risk flag. Set `behavior.emit_all: true` to emit all.

### 3.6 Explicit spec references

A spec ID matches `[A-Z][A-Z0-9]*-[0-9]+`. Explicit references come from:

1. a comment `# ad2v: ID[, ID…]` inside a function/class span, or directly above a definition or its
   decorators (contiguous comment block); a comment elsewhere attaches to the module;
2. a docstring line `ad2v: ID[, ID…]`;
3. the name of a test function (`test_*` in `test_*.py` / `*_test.py`) that contains
   `<prefix>_<digits>` for a configured prefix (default `REQ`, `CMP`): `test_req_012_x` → `REQ-012`;
4. Gherkin tags `@ID` on features and scenarios;
5. OpenAPI operation extension `x-ad2v-refs: [ID, …]`.

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
the rule lists the method in `pure_methods`; or a library-level call, unless the rule lists it as a
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

## 5. Tables

See the DDL for types and constraints. Every data table has `epoch_id`. A v0.2 producer writes one
epoch. P3 will store several epochs with content-addressed dedup, behind views shaped like these
tables. v0.2 readers MUST NOT assume that one file holds one full snapshot per epoch.

| table | class | notes |
|---|---|---|
| `meta(key, value, class)` | per row | `class='N'`: `format_version` (`0.2`), `rules_version`, `system_name`. `class='I'`: `generator`, `generator_version`, `repo_root_name`, `created_at` |
| `epochs` | N except `created_at` (I) | input hashes (§2). `repo_commit` is read from `<repo>/.git` without running git (NULL if absent). `attrs_json` echoes the configuration, pairing warnings and unmatched test cases |
| `nodes` | N | §3.1 |
| `edges` | N; `model…confidence` I | §3.4 |
| `unresolved_refs` | N | §3.6 |
| `glyphs` | N | glyph grammar |
| `workflows` | N; `model…confidence` I | `source` ∈ `static`, `runtime`, `llm_inferred` |
| `workflow_steps` | N | §7 |
| `workflow_step_nodes` | N (derived) | one row per (workflow, step, node), indexed on `node_id`: "which workflows pass through X" |
| `links` | N for `provenance='deterministic'` | §6.1–6.3. `confidence` = 1.0 for deterministic links |
| `node_status` | N (derived) | exactly one row per node; §6.4 |
| `status_rollup` | N (derived) | for each node with children: `{status: count}` over all descendants (not the node itself), zero counts omitted |
| `test_results` | N | ingested JUnit outcomes; §6.5 |
| `summaries` | `node_id`, `length` N; rest I | `length` ∈ `label`, `card`, `deep`; keyed by `(node_id, length, model)` |
| `narrations` | span columns N; `text`/provenance I | spans refer to fine step `seq`; keyed by `(workflow_id, detail_level, span_start, model)` |
| `layout` | N | `(node_id, lod, algorithm)` → box `x,y,z,w,h,d` |
| `tours`, `tour_stops` | mixed | guided camera paths |

Appendix A has the column-by-column N/I marks, generated from the DDL.

## 6. Pairing and statuses (normative)

### 6.1 Pairing methods

A **link** relates one spec node and one code node. It is found by one of four deterministic
methods (`links.method`). All four run, and a pair found twice by different methods gives two links:

| method | rule |
|---|---|
| `annotation` | every `annotated_as` edge code → spec (comments, docstrings, test names; §3.6) |
| `route_match` | `http_route` ↔ `spec_endpoint` with equal `(METHOD, normalized path)` |
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

### 6.2 Link statuses (v0.2)

| status | rule |
|---|---|
| `missing` | a spec item with a deterministic implementation signature has no pair: a `spec_endpoint` with no route, or a `spec_component` listed in `pairing.components` whose target does not exist |
| `specified` | a `requirement`, `scenario` or unlisted `spec_component` with no link. Absence cannot be proven statically, so it is "planned", not "missing" |
| `implemented` | paired, and no linked test passed |
| `verified` | paired, and at least one **linked test** has `outcome = passed` in the ingested test results. A linked test is a test function (`attrs.is_test`) whose `spec_ref` contains the spec item's ID or any ID in the spec item's own `spec_ref` (e.g. an endpoint's `x-ad2v-refs`). With no test results ingested, nothing is `verified`. A failing linked test adds evidence `tests_failed` and leaves the link `implemented` |
| `drift` | structural only: a paired route ↔ endpoint where (a) the number of `in: path` parameters the endpoint declares differs from the route template's, or (b) a `required: true` query parameter is not a parameter of the handler (skipped if the handler takes `**kwargs`). Evidence: `path_param_count` / `required_query_param_missing`. Semantic drift is P4 |
| `orphan` | only for ports, containers and components with no link, no linked ancestor container/component and, for ports, no linked handler. **Functions, classes and modules are never orphan** |
| `needs_review` | ambiguous pairing; or (node-level only) a node that carries an unresolved reference |
| `stale` | reserved for P3 |

### 6.3 State machine (including P3/P4 transitions)

```
                  pair found (annotation|route|manifest|name)          passing linked test
 specified ───────────────────────────────────────► implemented ───────────────────────────► verified
 missing  ──────────────────(pair found)──────────────────┘ ▲ │ ▲                                 │
   ▲                                                         │ │ └──── test now fails ──────────────┘
   │ pair removed                               drift fixed │ │ structural mismatch (P2) /
   │                                                         │ ▼ semantic disagreement (P4, provenance=llm)
 implemented / verified / drift ────────────────────────── drift
 any paired status ── content_hash of either side changes (P3, deterministic) ──► stale ──► re-evaluated
 any paired status ── several candidates / judge below threshold (P4) ──► needs_review ──► human or judge decides
 code without any pair ──► orphan ──(pair found)──► implemented
```

P3: a change to the `content_hash` of either paired node gives `stale`. A change to `subtree_hash`
alone only adds evidence `descendants_changed` and keeps the status. P4: semantic judgments write
links with `provenance = 'llm'`, `method = 'llm'`, full provenance columns and `confidence < 1`.

### 6.4 Effective node status

`node_status` has exactly one row per node:

1. **Own reasons**: the statuses of the node's links (either side). A port with no links of its own
   takes its handler's links (`via_handler`). A node with an unresolved reference gets
   `needs_review`.
2. If there are own reasons, the status with the highest precedence wins:
   **`drift` > `needs_review` > `missing` > `orphan` > `stale` > `verified` > `implemented` > `specified` > `none`**.
3. Otherwise the node **inherits** its parent's effective status if that is `verified`,
   `implemented` or `specified` (reason `inherited`). Otherwise its status is `none` (no coverage
   applies; rendered neutrally, never red).

`reasons_json` = `{"precedence": [...], "reasons": [{"status", "kind", ...}, ...]}`.
`status_rollup` counts effective statuses over all descendants, for far-zoom glyphs.

### 6.5 Test results

`ad2v extract --test-results <junit.xml>` (repeatable) parses JUnit XML with the standard library.
Test cases are matched to test functions by these rules (reference: `src/ad2v/junit.py`):
parametrization suffixes `[...]` are dropped; `classname` is split into a module path (dots →
`/`, `.py`) and trailing class names, trying the longest module first; a module matches when it
equals an extracted module path or is a `/`-suffix of one (the pytest rootdir may differ); a `file`
attribute breaks ties. Exactly one candidate gives a match. Zero or several give an **unmatched**
case, which is reported (in `epochs.attrs_json.unmatched_tests` and the CLI summary), never an
error. The outcome is `failed` if there is a `<failure>` or `<error>`, `skipped` if there is a
`<skipped>`, and `passed` otherwise. When several results map to one test, the worst wins.

## 7. Workflows

A **static workflow** is written for each entry port (`http_route`, `mcp_tool`, `cli_command`,
`event_consumer`). The trace is a depth-first walk:

1. step 0: `[port]` at depth 0;
2. visiting function `f` at depth `d` emits `[enclosing emitted behaviors…, f's emitted retry nodes…, f]`
   at depth `d`, then walks `f`'s events in source order (pre-order by call position):
   - resolved call to `g`: visit `g` at depth `d+1` (the behavior nodes lexically enclosing the call
     are prepended to `g`'s step);
   - resource touch: emit `[enclosing emitted behaviors…, resource]` at depth `d+1`;
   - calls that are arguments of the same fan-out call are **parallel**: their callees are emitted
     as a single step (`[fan_out, g1, g2…]`) and then visited in order.
3. Recursion stops at `workflows.max_depth` (default 12). A callee already on the stack is emitted
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

In both modes, increasing `k` never merges steps. Narrations (§5) are keyed by
`(detail_level, span_start)`, so replay stays consistent at every slider position.

## 8. Canonical dump

`ad2v dump` writes one JSON line per row: `{"row":{…},"table":"<name>"}` (canonical JSON). Tables
are in name order and rows in primary-key order. `*_json` columns are decoded (nested).

- **Canonical (default)**: every `created_at` column and every `meta` row with `class = 'I'` are
  omitted.
- **`--normative-only`**: additionally omits every column marked `I` in Appendix A, every row with
  `provenance IN ('llm','runtime')` or `source IN ('llm_inferred','runtime')`, and the informative
  tables `summaries` and `narrations`.

**The determinism guarantee covers the normative dump.** Two runs on the same inputs (code, specs,
rules, manifest, test results), including from a checkout with CRLF line endings or a different
directory name, MUST produce identical normative dumps. Informative rows are reproducible only by
caching them under `input_hash`/`prompt_hash` (P4).

## 9. Conformance

A conforming v0.2 file:

- has `meta.format_version = '0.2'` and a `class` on every `meta` row;
- satisfies every foreign key and CHECK constraint in the DDL;
- has exactly one glyph and exactly one `node_status` row per node;
- has every node in `workflow_steps.node_ids_json`, and `workflow_step_nodes` equal to the rows
  derived from `workflow_steps`;
- has node, link, node-status and test-result rows that validate against `ir-v0.2.schema.json`;
- has `id = node_id(side, kind, qualified_name)` for every node, `link_id = link_id(spec, code,
  method)` for every link, `confidence = 1.0` for every deterministic link, `subtree_hash` values
  that recompute (§2), and `status_rollup` rows that recompute from `node_status`.

`ad2v validate` checks all of the above, and rejects files with `format_version` older than 0.2.

## Appendix A: column classes (normative)

Every column in the DDL is marked **N** (normative), **I** (informative) or **N/I** (depends on the row, e.g. `provenance`). This appendix is generated from the DDL comments and a test keeps it in sync.

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
| `parent_epoch_id` | N |  |
| `repo_commit` | N | git HEAD if <repo>/.git is readable, else NULL |
| `repo_tree_hash` | N |  |
| `spec_tree_hash` | N |  |
| `rules_hash` | N | sha256 of the merged, canonicalized rules (built-in + overlay) |
| `config_hash` | N | sha256 of the canonical JSON of the parsed manifest ({} if none) |
| `test_results_hash` | N | tree hash of the normalized test-result files |
| `attrs_json` | N | extraction config echo (rules/manifest hashes) |
| `created_at` | I | excluded from canonical dump |

**nodes**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `id` | N | n_ + sha256(side\|kind\|qualified_name)[:20] |
| `side` | N |  |
| `kind` | N | closed enum, see spec §3.2 |
| `name` | N |  |
| `qualified_name` | N |  |
| `parent_id` | N | NULL for roots |
| `path` | N | repo- or spec-root-relative, forward slashes |
| `span_start_line` | N | 1-based, inclusive |
| `span_end_line` | N | 1-based, inclusive |
| `content_hash` | N |  |
| `subtree_hash` | N |  |
| `level_hint` | N | optional presentation hint |
| `attrs_json` | N |  |
| `spec_ref_json` | N | sorted list of explicit spec IDs |

**edges**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `src` | N |  |
| `dst` | N |  |
| `kind` | N | closed enum, see spec §3.4 |
| `weight` | N | occurrence count |
| `attrs_json` | N |  |
| `provenance` | N |  |
| `model` | I | required when provenance='llm' |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `confidence` | I |  |

**unresolved_refs**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `src` | N | node carrying the reference |
| `ref` | N | the referenced identifier, verbatim |
| `ref_kind` | N | 'spec_id' |
| `reason` | N | 'not_found' |

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

**test_results**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `test_node_id` | N |  |
| `outcome` | N |  |
| `source_file` | N | result file name (repo-relative if inside the repo) |
| `duration_ms` | N | as recorded in the input file |

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

**narrations**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `workflow_id` | N |  |
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

<!-- END COLUMN CLASSES -->
