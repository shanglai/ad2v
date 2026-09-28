# The ad2v file format, version 0.1

Status: **draft, normative**. The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.

An `.ad2v` file is a single SQLite 3 database. It describes a software system from two sides, the
**code** in a repository and the **specs** (spec-driven development documents), as one graph of
nodes and edges, along with glyphs for rendering and workflows for replay. Viewers, agents (via
MCP) and diff tools read it. Producers ("extractors") write it.

Companion documents:

- [`glyph-grammar-v0.1.md`](glyph-grammar-v0.1.md): how nodes become shapes (normative).
- [`spec-markdown-convention.md`](spec-markdown-convention.md): the Markdown spec convention (normative for extractors).
- [`../../schema/ad2v-v0.1.sql`](../../schema/ad2v-v0.1.sql): DDL (normative).
- [`../../schema/ir-v0.1.schema.json`](../../schema/ir-v0.1.schema.json): JSON Schema of the IR (normative).

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
4. **One file, canonical dump.** Two producers agree when their canonical dumps (§8) are
   byte-identical. SQLite file bytes are *not* compared.
5. **Relative levels.** There are no global levels (L1/L2/L3). Depth is the depth in the
   `contains` hierarchy and MAY differ between branches. `level_hint` is presentation metadata only.
6. **Knowledge never grants capability.** Producers read the repository. They MUST NOT import,
   execute or evaluate repository code.
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
| Epoch id | `"e_" + sha256_hex((parent_epoch_id or "") + "|" + repo_tree_hash + "|" + spec_tree_hash + "|" + rules_hash)[:20]` |
| `content_hash` | For nodes with a source span: `sha256_hex(normalized text of lines span_start_line..span_end_line)` (lines joined with `\n`). For files (modules, `spec_doc`): the whole normalized file. For nodes without text (system, container, component, resources, ports): `sha256_hex(canonical_json({"kind","name","attrs"}))`. |
| `subtree_hash` | `sha256_hex(join("\n", [content_hash] + ["<child_id>:<child_subtree_hash>" for children sorted by id]))`, where children are nodes whose `parent_id` is this node. |
| Tree hashes | `repo_tree_hash` / `spec_tree_hash` = `sha256_hex(join("\n", ["<path>\t<content_hash(file)>" sorted by path]))` over the files that the extractor read. `rules_hash` = the same tree hash over the extractor's rules files (`{"python.yaml": content_hash}` in v0.1). Extraction output depends on the rules, so they are an input of the epoch like code and specs. |

## 3. The IR

The IR is the logical model. `schema/ir-v0.1.schema.json` defines its JSON form, and the tables in
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

### 3.2 Node kinds (closed enum, v0.1)

| group | kinds |
|---|---|
| Structural | `system`, `container` (deployable/service), `component` (package/directory), `module` (source file), `class`, `function` (incl. methods and nested functions) |
| Ports | `http_route`, `mcp_tool`, `cli_command`, `event_consumer` |
| Resources | `datastore`, `queue`, `external_service`, `llm_endpoint`, `ui` |
| Behavior | `loop`, `retry`, `fan_out`, `transaction`, `llm_call` |
| Spec | `spec_doc`, `spec_component`, `requirement`, `scenario`, `scenario_step`, `spec_endpoint` |

Spec kinds have `side = spec`. All other kinds have `side = code`.

### 3.3 Qualified names

| kind | qualified_name | example |
|---|---|---|
| `system` | the system name (manifest `system.name`, else repo directory name) | `payments-recon` |
| `container` | `container:<name>` | `container:api` |
| `component` | directory path | `api/recon_api` |
| `module` | file path | `api/recon_api/matching.py` |
| `class` | `<module path>::<Class>` (nested: `Outer.Inner`) | `api/recon_api/db.py::Run` |
| `function` | `<module path>::<name>`; methods `::<Class>.<name>`; nested `::<outer>.<inner>` | `api/recon_api/matching.py::match_batch` |
| `http_route` | `http:<container>:<METHOD> <full path>` | `http:api:GET /v1/reconciliations/{run_id}` |
| `mcp_tool` | `mcp:<container>:<tool name>` | `mcp:api:reconciliation_summary` |
| `cli_command` | `cli:<container>:<command name>` | `cli:worker:run-nightly` |
| `event_consumer` | `event:<container>:<handler qualified name>` | `event:worker:worker/recon_worker/events.py::handle_statement_uploaded` |
| resources | `<kind>:<resource name>` (§3.7) | `datastore:env:RECON_DB_URL` |
| behavior | `<enclosing function qname>@<kind>#<n>`: `n` is the 1-based ordinal of that behavior kind among *all candidates* in the function, in source order | `api/recon_api/matching.py::match_batch@loop#1` |
| `spec_doc` | spec file path | `components.md` |
| `spec_component`, `requirement` | the explicit spec ID when present (`CMP-001`, `REQ-012`), else `<spec path>::<name>` | `REQ-012` |
| `scenario` | `<spec path>::<feature name>::<scenario name>` (`#2`, `#3`… appended to duplicates) | `features/recon.feature::Statement reconciliation::Start a run` |
| `scenario_step` | `<scenario qname>::step[<n>]`, 1-based | `...::Start a run::step[2]` |
| `spec_endpoint` | `<METHOD> <path>` | `POST /v1/reconciliations` |

**Spec IDs are the qualified names of spec nodes.** Behavior ordinals count *all* candidates,
including those not emitted, so changing `behavior.emit_all` never renames a node.

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
| `annotated_as` | any node → spec node | explicit spec ID reference (§3.6). The only spec↔code link in v0.1. Also used spec → spec (a Gherkin scenario tagged `@REQ-012`), see ADR-0005. |

`provenance` is `deterministic` for every edge a v0.1 extractor writes.

### 3.5 Attributes (well-known keys)

| kind | keys |
|---|---|
| `container` | `container_kind` (manifest `kind`), `replicas`, `paths`, `declared` (bool) |
| `function` | `async` (bool), `decorators` (list of dotted names), `is_test` (bool) |
| `http_route` | `method`, `path`, `framework`, `handler` (qname) |
| `mcp_tool` | `tool_name`, `framework`, `handler` |
| `cli_command` | `command`, `framework`, `handler` |
| `event_consumer` | `framework`, `handler`, `source` (subscription name if resolvable) |
| resources | `library`, `resource_name`, `name_source` (`literal`, `env`, `unknown`) |
| behavior | `risk` (sorted list of risk flags), `construct` (`for`, `while`, `comprehension`, `decorator`, `call`, `with`…), `library` |
| `requirement` | `text`, `ears` (`event`, `state`, `unwanted`, `optional`, `ubiquitous`, or `null`), `trigger`, `system`, `response`, `precondition` |
| `scenario` | `keyword`, `tags`, `background` (bool), `examples` (count) |
| `scenario_step` | `keyword`, `keyword_type`, `text` |
| `spec_endpoint` | `method`, `path`, `operation_id`, `summary` |
| `spec_doc` | `format` (`markdown`, `gherkin`, `openapi`), `prose` (Markdown only: unparsed text) |

**Risk flags** (`attrs.risk`): `io_in_loop`, `llm_in_loop`, `unbounded_retry`, `fan_out`,
`nested_loop_io`, `slow_io_in_transaction` (an addition, see ADR-0006). By default, behavior nodes
are emitted only when they have at least one risk flag. Set `behavior.emit_all: true` to emit all.

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
(`reason = 'not_found'`), which marks it as a future *dangling reference*.

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
A client built from another client inherits its resource (`sessionmaker(bind=engine)`). A touch on a
client whose resource is still `unknown` may be named from the call's own arguments
(`publisher.publish(TOPIC, ...)`).

**What counts as a touch** (an IO edge): a call to a method of a client bound to a resource, unless
the rule lists the method in `pure_methods`; or a library-level call, unless the rule lists it as a
constructor or `pure`. For datastore libraries, library-level calls do not count
(`direct_calls_touch: false`) unless listed in `touch_functions`: `sqlalchemy.inspect()` is not IO,
while `session.execute()` is. The rules file `extract/code/rules/python.yaml` is versioned (`rules_version`,
echoed in `meta` and `epochs.attrs_json` with its content hash).

## 4. Containers

If a manifest declares `containers`, a file belongs to the container with the longest path prefix
that matches its path. Without declared containers, every top-level directory that contains
`pyproject.toml`, `setup.py` or `Dockerfile` is a container named after the directory. Files that
match no container go to a fallback container named after the system, with `paths: ["."]`. It is
created only if such files exist. When no container is found, this fallback is the repo root.

## 5. Tables

See the DDL for types and constraints. Every data table has `epoch_id`. A v0.1 producer writes one
epoch.

| table | class | notes |
|---|---|---|
| `meta(key, value)` | mixed | `format_version` N (`0.1`), `rules_version` N, `system_name` N; `generator`, `generator_version`, `repo_root_name`, `created_at` I |
| `epochs` | N except `created_at` (I) | `repo_commit` is read from `<repo>/.git` without running git; NULL if absent |
| `nodes` | N | §3.1 |
| `edges` | N; `model…confidence` I | §3.4 |
| `unresolved_refs` | N | §3.6 |
| `glyphs` | N | glyph grammar |
| `workflows` | N; `model…confidence` I | `source` ∈ `static`, `runtime`, `llm_inferred` |
| `workflow_steps` | N | §7 |
| `links` | N/I | empty in v0.1 producers; §6 |
| `summaries` | `node_id`, `length` N; rest I | `length` ∈ `label`, `card`, `deep`; keyed by `(node_id, length, model)` so several models can coexist |
| `narrations` | span columns N; `text`/provenance I | spans refer to fine step `seq`; keyed by `(workflow_id, detail_level, span_start, model)` |
| `layout` | N | `(node_id, lod, algorithm)` → box `x,y,z,w,h,d` |
| `tours`, `tour_stops` | mixed | guided camera paths |

Column-by-column N/I marks are in the DDL comments. The DDL is the authoritative list.

## 6. Link status vocabulary (reserved for P2+)

`links.status` ∈ `specified`, `implemented`, `verified`, `drift`, `orphan`, `stale`,
`needs_review`, `missing`.

| status | meaning | visual (glyph grammar §7) |
|---|---|---|
| `specified` | spec item exists, no code pairing yet evaluated | dotted |
| `missing` | spec item evaluated, no code implements it | dotted, dim |
| `implemented` | spec item paired with code | solid |
| `verified` | implemented and covered by a passing test/scenario mapped to it | solid, blue glow |
| `drift` | paired, but code and spec disagree | amber |
| `orphan` | code with no spec pairing (spec_node_id NULL) | red dashed |
| `stale` | a pairing whose inputs changed since it was judged (content_hash moved) | previous style, desaturated |
| `needs_review` | a probabilistic judge was below the confidence threshold | amber outline |

Intended state machine (per spec item / code item pair, per epoch):

```
            pair found              test evidence
specified ────────────► implemented ────────────► verified
    │                      │   ▲                    │
    │ no pair              │   │ judge agrees       │ content_hash of either side changes
    ▼                      ▼   │                    ▼
 missing                  drift ◄──── judge disagrees ──── stale ──► (re-judge) ──► implemented | drift | needs_review
                                   low confidence ──► needs_review ──► (human/LLM) ──► implemented | drift
code without pair ──► orphan ──(pair found)──► implemented
```

Deterministic transitions (hash changes → `stale`, no pair → `missing`/`orphan`) use
`provenance='deterministic'`. Judgments (`drift`, `needs_review`, semantic `implemented`) use
`provenance='llm'` with full provenance columns.

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

**Projection** `project(steps, k)` collapses the steps to detail level `k`. Step `i` belongs to group
`g(i) = max{ j ≤ i : depth_j ≤ k }`, or to a leading group if there is no such `j`. Groups are
contiguous and partition the trace. Each coarse step shows the nodes of its anchor step `j` and
records the fine span `[first, last]`. Narrations (§5) are keyed by `(detail_level, span_start)`, so
replay stays consistent at every slider position.

## 8. Canonical dump

`ad2v dump --canonical` writes one JSON line per row:
`{"row":{…},"table":"<name>"}` (canonical JSON). Tables are in name order and rows in primary-key
order. `*_json` columns are decoded (nested). Every `created_at` column is omitted, and the
informative `meta` keys (`created_at`, `generator`, `generator_version`, `repo_root_name`) are
omitted. Two runs on the same inputs, even from a checkout with CRLF line endings, MUST produce
identical dumps.

## 9. Conformance

A conforming v0.1 file:

- has `meta.format_version = '0.1'`;
- satisfies every foreign key and CHECK constraint in the DDL;
- has exactly one glyph per node;
- has every node in `workflow_steps.node_ids_json`;
- has node rows that validate against `ir-v0.1.schema.json`;
- has `id = node_id(side, kind, qualified_name)` for every node, and `subtree_hash` values that
  recompute (§2).

`ad2v validate` checks all of the above.

## Appendix A: column classes (normative)

Every column in the DDL is marked **N** (normative), **I** (informative) or **N/I** (depends on the row, e.g. `provenance`). This appendix is generated from the DDL comments and a test keeps it in sync.

<!-- BEGIN COLUMN CLASSES (generated by `python -m ad2v.ddl`) -->

**meta**

| column | class | note |
|---|---|---|
| `key` | N |  |
| `value` | N/I | (class depends on the key, see spec §5) |

**epochs**

| column | class | note |
|---|---|---|
| `epoch_id` | N | e_ + sha256(parent\|repo_tree_hash\|spec_tree_hash\|rules_hash)[:20] |
| `parent_epoch_id` | N |  |
| `repo_commit` | N | git HEAD if <repo>/.git is readable, else NULL |
| `repo_tree_hash` | N |  |
| `spec_tree_hash` | N |  |
| `rules_hash` | N | tree hash of the normalized extractor rules files |
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

**links**

| column | class | note |
|---|---|---|
| `epoch_id` | N |  |
| `link_id` | N | l_ + sha256(spec_node_id\|code_node_id)[:20] |
| `spec_node_id` | N | NULL for orphan code |
| `code_node_id` | N | NULL for missing spec items |
| `status` | N/I | (I when provenance='llm') |
| `provenance` | N |  |
| `evidence_json` | N/I |  |
| `confidence` | I | required when provenance='llm' |
| `model` | I |  |
| `model_version` | I |  |
| `prompt_hash` | I |  |
| `input_hash` | I |  |
| `created_at` | I | excluded from canonical dump |

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
