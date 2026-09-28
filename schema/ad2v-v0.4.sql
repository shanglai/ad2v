-- ad2v file format v0.4 -- SQLite DDL
-- Normative reference: docs/spec/ad2v-format-v0.4.md
-- Column classes: N = normative (deterministic), I = informative (LLM/runtime/wall-clock/file
-- management), V = volatile (deterministic, but moves with unrelated edits: ignored by `ad2v diff`
-- and excluded from version keys).
-- Every JSON column holds canonical JSON (sorted keys, no whitespace, UTF-8).
--
-- Layout (spec §5): base facts are content-addressed (`*_versions`) and referenced per epoch
-- (`epoch_*`); the v0.2-shaped VIEWS `nodes`, `edges`, `unresolved_refs`, `test_results` join
-- them back. Derived tables keep their v0.2 shape and hold rows only for materialized epochs.

PRAGMA foreign_keys = ON;

-- Key/value metadata. `class` says whether the value is normative (N) or informative (I).
-- Keys: format_version (N), head_epoch (N), system_name (N), rules_version (N),
-- spec_coverage (N: 'present' | 'none', of the head epoch), generator (I), generator_version (I),
-- repo_root_name (I), created_at (I).
CREATE TABLE meta (
    key   TEXT PRIMARY KEY, -- N
    value TEXT NOT NULL,  -- N/I (the row's `class`)
    class TEXT NOT NULL CHECK (class IN ('N','I')) -- N
);

-- ---------------------------------------------------------------------------------------------
-- Epochs and their inputs
-- ---------------------------------------------------------------------------------------------

CREATE TABLE epochs (
    epoch_id        TEXT PRIMARY KEY,           -- N  e_ + sha256(parent|repo|spec|rules|config|test_results hashes)[:20]
    parent_epoch_id TEXT REFERENCES epochs(epoch_id), -- N  NULL only for the first kept epoch
    seq             INTEGER NOT NULL UNIQUE,    -- N  1, 2, 3... in append order
    repo_commit     TEXT,                       -- N  git commit the epoch was extracted from, if known
    repo_tree_hash  TEXT NOT NULL,              -- N
    spec_tree_hash  TEXT NOT NULL,              -- N
    rules_hash      TEXT NOT NULL REFERENCES rules_versions(rules_hash), -- N
    config_hash     TEXT NOT NULL REFERENCES config_versions(config_hash), -- N
    test_results_hash TEXT NOT NULL,            -- N  tree hash of the normalized test-result files in effect
    change_kind     TEXT NOT NULL -- N  which input hashes changed vs the parent
                    CHECK (change_kind IN ('initial','code','spec','code+spec','rules','config','tests_only','mixed')),
    pinned          INTEGER NOT NULL DEFAULT 0, -- I  file-management state: kept by prune, stays materialized
    label           TEXT,                       -- I  file-management state (e.g. a release tag)
    materialized    INTEGER NOT NULL DEFAULT 0, -- I  file-management state: derived rows present
    attrs_json      TEXT NOT NULL DEFAULT '{}', -- N  config echo, pairing warnings, unmatched tests, cache stats
    created_at      TEXT                        -- I  excluded from canonical dump
);

-- The extractor rules and the manifest in effect, by hash (needed to re-materialize an epoch).
CREATE TABLE rules_versions (
    rules_hash TEXT PRIMARY KEY,                -- N
    rules_json TEXT NOT NULL                    -- N  merged, canonicalized rules
);
CREATE TABLE config_versions (
    config_hash TEXT PRIMARY KEY,               -- N
    config_json TEXT NOT NULL                   -- N  {"manifest": ..., "effective": {...}}
);

-- Which derived tables are present for which epoch.
CREATE TABLE epoch_materialized (
    epoch_id   TEXT NOT NULL REFERENCES epochs(epoch_id), -- I
    table_name TEXT NOT NULL,                   -- I
    PRIMARY KEY (epoch_id, table_name)
);

-- ---------------------------------------------------------------------------------------------
-- Base facts: content-addressed versions + per-epoch membership
-- ---------------------------------------------------------------------------------------------
-- Every `*_versions` row has an integer surrogate `vid` (storage only, never exposed by the
-- views) next to its content key `version_key`. Membership rows are `(seq, vid)` pairs in
-- WITHOUT ROWID tables, so an unchanged node costs one small row per epoch (ADR-0017).

CREATE TABLE node_versions (
    vid             INTEGER PRIMARY KEY,        -- I  storage surrogate, file-local
    version_key     TEXT NOT NULL UNIQUE,       -- N  v_ + sha256(canonical normative payload)[:20]
    node_id         TEXT NOT NULL,              -- N  n_ + sha256(side|kind|qualified_name)[:20]
    side            TEXT NOT NULL CHECK (side IN ('code','spec')), -- N
    kind            TEXT NOT NULL,              -- N  closed enum, see spec §3.2
    name            TEXT NOT NULL,              -- N
    qualified_name  TEXT NOT NULL,              -- N
    parent_id       TEXT,                       -- N  NULL for roots
    path            TEXT,                       -- N  repo- or spec-root-relative, forward slashes
    content_hash    TEXT NOT NULL,              -- N
    subtree_hash    TEXT NOT NULL,              -- N
    level_hint      TEXT,                       -- N  optional presentation hint
    attrs_json      TEXT NOT NULL DEFAULT '{}', -- N
    spec_ref_json   TEXT NOT NULL DEFAULT '[]'  -- N  sorted list of explicit spec IDs
);
CREATE INDEX idx_node_versions_node ON node_versions(node_id);

CREATE TABLE epoch_nodes (
    seq             INTEGER NOT NULL REFERENCES epochs(seq), -- N  the epoch
    vid             INTEGER NOT NULL REFERENCES node_versions(vid), -- N
    span_start_line INTEGER,                    -- V  1-based, inclusive
    span_end_line   INTEGER,                    -- V  1-based, inclusive
    PRIMARY KEY (seq, vid)
) WITHOUT ROWID;

CREATE TABLE edge_versions (
    vid           INTEGER PRIMARY KEY,          -- I  storage surrogate, file-local
    version_key   TEXT NOT NULL UNIQUE,         -- N  v_ + sha256(canonical normative payload)[:20]
    src           TEXT NOT NULL,                -- N
    dst           TEXT NOT NULL,                -- N
    kind          TEXT NOT NULL,                -- N  closed enum, see spec §3.4
    weight        INTEGER NOT NULL DEFAULT 1,   -- N  occurrence count
    attrs_json    TEXT NOT NULL DEFAULT '{}',   -- N  without the volatile `lines` key
    provenance    TEXT NOT NULL DEFAULT 'deterministic' -- N
                  CHECK (provenance IN ('deterministic','runtime','llm')),
    model         TEXT,                         -- I  required when provenance='llm'
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    confidence    REAL,                         -- I
    CHECK (provenance <> 'llm' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);

-- Membership rows carry no node ids, so edge endpoints are not FOREIGN KEYs; `ad2v validate`
-- checks that both endpoints of every edge are nodes of the same epoch.
CREATE TABLE epoch_edges (
    seq        INTEGER NOT NULL REFERENCES epochs(seq), -- N  the epoch
    vid        INTEGER NOT NULL REFERENCES edge_versions(vid), -- N
    lines_json TEXT,                            -- V  attrs.lines (source lines of occurrences)
    PRIMARY KEY (seq, vid)
) WITHOUT ROWID;

CREATE TABLE unresolved_ref_versions (
    vid         INTEGER PRIMARY KEY,            -- I  storage surrogate, file-local
    version_key TEXT NOT NULL UNIQUE,           -- N
    src         TEXT NOT NULL,                  -- N  node carrying the reference
    ref         TEXT NOT NULL,                  -- N  the referenced identifier, verbatim
    ref_kind    TEXT NOT NULL,                  -- N  'spec_id'
    reason      TEXT NOT NULL                   -- N  'not_found'
);
CREATE TABLE epoch_unresolved_refs (
    seq INTEGER NOT NULL REFERENCES epochs(seq), -- N  the epoch
    vid INTEGER NOT NULL REFERENCES unresolved_ref_versions(vid), -- N
    PRIMARY KEY (seq, vid)
) WITHOUT ROWID;

CREATE TABLE test_result_versions (
    vid          INTEGER PRIMARY KEY,           -- I  storage surrogate, file-local
    version_key  TEXT NOT NULL UNIQUE,          -- N
    test_node_id TEXT NOT NULL,                 -- N
    outcome      TEXT NOT NULL CHECK (outcome IN ('passed','failed','skipped')), -- N
    source_file  TEXT NOT NULL,                 -- N  result file name (repo-relative if inside the repo)
    duration_ms  INTEGER NOT NULL               -- N  as recorded in the input file
);
CREATE TABLE epoch_test_results (
    seq INTEGER NOT NULL REFERENCES epochs(seq), -- N  the epoch
    vid INTEGER NOT NULL REFERENCES test_result_versions(vid), -- N
    PRIMARY KEY (seq, vid)
) WITHOUT ROWID;

-- Workflow inputs from the code walk (events, retry wrappers, entry ports), needed to
-- re-materialize workflows without the source tree. fact_kind: 'events' | 'wrappers' | 'entry'
-- (an entry payload is the sorted list of handler ids bound to the port).
CREATE TABLE code_fact_versions (
    vid          INTEGER PRIMARY KEY,           -- I  storage surrogate, file-local
    version_key  TEXT NOT NULL UNIQUE,          -- N
    fact_kind    TEXT NOT NULL,                 -- N
    subject_id   TEXT NOT NULL,                 -- N  function/module id ('events','wrappers') or port id ('entry')
    payload_json TEXT NOT NULL                  -- N
);
CREATE TABLE epoch_code_facts (
    seq INTEGER NOT NULL REFERENCES epochs(seq), -- N  the epoch
    vid INTEGER NOT NULL REFERENCES code_fact_versions(vid), -- N
    PRIMARY KEY (seq, vid)
) WITHOUT ROWID;

-- Deterministic rename detection between an epoch and its parent (spec §6.6).
-- method: same_content | anchored_header | same_route | ambiguous (a tie, never applied).
CREATE TABLE id_lineage (
    epoch_id TEXT NOT NULL REFERENCES epochs(epoch_id), -- N  the newer epoch
    old_id   TEXT NOT NULL,                     -- N  node id in the parent epoch
    new_id   TEXT NOT NULL,                     -- N  node id in this epoch
    method   TEXT NOT NULL -- N
             CHECK (method IN ('same_content','anchored_header','same_route','ambiguous')),
    score    REAL NOT NULL,                     -- N  1.0, or the header Jaccard similarity
    PRIMARY KEY (epoch_id, old_id, new_id)
);
CREATE INDEX idx_lineage_new ON id_lineage(epoch_id, new_id);

-- Per-epoch link status after history rules (stale), plus the agreement it was judged against.
-- Base fact: lets any epoch be re-materialized from its own rows, even after its parent is pruned.
CREATE TABLE link_state (
    epoch_id          TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    link_id           TEXT NOT NULL,            -- N
    spec_node_id      TEXT,                     -- N
    code_node_id      TEXT,                     -- N
    method            TEXT NOT NULL,            -- N
    status            TEXT NOT NULL,            -- N  final link status in this epoch
    history_json      TEXT NOT NULL DEFAULT '[]', -- N  history evidence (spec_changed_since, ...)
    agreed_epoch_id   TEXT,                     -- N  last epoch where the link was implemented/verified
    agreed_spec_hash  TEXT,                     -- N  spec content_hash at that agreement
    agreed_code_hash  TEXT,                     -- N  code content_hash at that agreement
    PRIMARY KEY (epoch_id, link_id)
);

-- File-level parse cache (spec §4.2). Local extraction facts per file, zlib-compressed JSON.
CREATE TABLE parse_cache (
    path              TEXT NOT NULL,            -- I  repo-relative path
    content_hash      TEXT NOT NULL,            -- I
    rules_hash        TEXT NOT NULL,            -- I
    extractor_version TEXT NOT NULL,            -- I
    payload_blob      BLOB NOT NULL,            -- I
    PRIMARY KEY (path, content_hash, rules_hash, extractor_version)
);

-- ---------------------------------------------------------------------------------------------
-- v0.2-compatible views over the base facts
-- ---------------------------------------------------------------------------------------------

CREATE VIEW nodes AS
SELECT e.epoch_id, v.node_id AS id, v.side, v.kind, v.name, v.qualified_name, v.parent_id, v.path,
       m.span_start_line, m.span_end_line, v.content_hash, v.subtree_hash, v.level_hint,
       v.attrs_json, v.spec_ref_json
FROM epoch_nodes m JOIN epochs e ON e.seq = m.seq JOIN node_versions v ON v.vid = m.vid;

CREATE VIEW edges AS
SELECT e.epoch_id, v.src, v.dst, v.kind, v.weight,
       CASE WHEN m.lines_json IS NULL THEN v.attrs_json
            ELSE json_set(v.attrs_json, '$.lines', json(m.lines_json)) END AS attrs_json,
       v.provenance, v.model, v.model_version, v.prompt_hash, v.input_hash, v.confidence
FROM epoch_edges m JOIN epochs e ON e.seq = m.seq JOIN edge_versions v ON v.vid = m.vid;

CREATE VIEW unresolved_refs AS
SELECT e.epoch_id, v.src, v.ref, v.ref_kind, v.reason
FROM epoch_unresolved_refs m JOIN epochs e ON e.seq = m.seq
JOIN unresolved_ref_versions v ON v.vid = m.vid;

CREATE VIEW test_results AS
SELECT e.epoch_id, v.test_node_id, v.outcome, v.source_file, v.duration_ms
FROM epoch_test_results m JOIN epochs e ON e.seq = m.seq JOIN test_result_versions v ON v.vid = m.vid;

-- ---------------------------------------------------------------------------------------------
-- Derived tables (rows only for materialized epochs: head + pinned; spec §5.3)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE glyphs (
    epoch_id       TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    node_id        TEXT NOT NULL,               -- N
    base_shape     TEXT NOT NULL,               -- N  glyph grammar §2
    variant        TEXT NOT NULL,               -- N  glyph grammar §3
    modifiers_json TEXT NOT NULL,               -- N  glyph grammar §4
    size_weight    INTEGER NOT NULL,            -- N  glyph grammar §6
    has_interior   INTEGER NOT NULL,            -- N  0/1, LOD 2 availability
    PRIMARY KEY (epoch_id, node_id)
);

CREATE TABLE workflows (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    workflow_id   TEXT NOT NULL,                -- N  w_ + sha256(side|entry_node_id|source)[:20]
    name          TEXT NOT NULL,                -- N
    side          TEXT NOT NULL CHECK (side IN ('code','spec')), -- N
    entry_node_id TEXT NOT NULL,                -- N
    scenario_id   TEXT,                         -- N  spec-side workflows: the scenario node
    source        TEXT NOT NULL CHECK (source IN ('static','runtime','llm_inferred')), -- N
    attrs_json    TEXT NOT NULL DEFAULT '{}',   -- N  e.g. truncated, max_depth
    model         TEXT,                         -- I  required when source='llm_inferred'
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    confidence    REAL,                         -- I
    PRIMARY KEY (epoch_id, workflow_id),
    CHECK (source <> 'llm_inferred' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);

CREATE TABLE workflow_steps (
    epoch_id      TEXT NOT NULL,                -- N
    workflow_id   TEXT NOT NULL,                -- N
    seq           INTEGER NOT NULL,             -- N  0-based, contiguous
    node_ids_json TEXT NOT NULL,                -- N  nodes lit together (parallel steps share a row)
    depth         INTEGER NOT NULL,             -- N  call depth from the entry (entry = 0)
    PRIMARY KEY (epoch_id, workflow_id, seq),
    FOREIGN KEY (epoch_id, workflow_id) REFERENCES workflows(epoch_id, workflow_id)
);

-- Derived index: which workflows pass through a node.
CREATE TABLE workflow_step_nodes (
    epoch_id    TEXT NOT NULL,                  -- N
    workflow_id TEXT NOT NULL,                  -- N
    seq         INTEGER NOT NULL,               -- N
    node_id     TEXT NOT NULL,                  -- N
    PRIMARY KEY (epoch_id, workflow_id, seq, node_id),
    FOREIGN KEY (epoch_id, workflow_id, seq) REFERENCES workflow_steps(epoch_id, workflow_id, seq)
);
CREATE INDEX idx_wsn_node ON workflow_step_nodes(epoch_id, node_id);

-- spec<->code links (spec §6).
CREATE TABLE links (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    link_id       TEXT NOT NULL,                -- N  l_ + sha256(spec_node_id|code_node_id|method)[:20]
    spec_node_id  TEXT,                         -- N  NULL for orphan code
    code_node_id  TEXT,                         -- N  NULL for missing/specified spec items
    method        TEXT NOT NULL                 -- N  how the pair was found; 'none' for unpaired rows
                  CHECK (method IN ('annotation','route_match','manifest','manifest_link','name_match','none','llm')),
    status        TEXT NOT NULL -- N/I (I when provenance='llm')
                  CHECK (status IN ('specified','implemented','verified','drift',
                  'orphan','stale','needs_review','missing')),
    provenance    TEXT NOT NULL CHECK (provenance IN ('deterministic','runtime','llm')), -- N
    evidence_json TEXT NOT NULL DEFAULT '[]',   -- N/I
    confidence    REAL NOT NULL,                -- N/I  1.0 for deterministic links
    model         TEXT,                         -- I
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    created_at    TEXT,                         -- I  excluded from canonical dump
    PRIMARY KEY (epoch_id, link_id),
    CHECK (spec_node_id IS NOT NULL OR code_node_id IS NOT NULL),
    CHECK (provenance <> 'llm' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);
CREATE INDEX idx_links_spec ON links(epoch_id, spec_node_id);
CREATE INDEX idx_links_code ON links(epoch_id, code_node_id);

-- One effective status per node (both sides), derived from `links` (spec §6.4).
CREATE TABLE node_status (
    epoch_id     TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    node_id      TEXT NOT NULL,                 -- N
    status       TEXT NOT NULL                  -- N
                 CHECK (status IN ('drift','needs_review','missing','orphan','stale','verified',
                 'implemented','specified','none')),
    reasons_json TEXT NOT NULL,                 -- N  {precedence: [...], reasons: [...]} (spec §6.4)
    PRIMARY KEY (epoch_id, node_id)
);
CREATE INDEX idx_node_status_status ON node_status(epoch_id, status);

-- Counts of effective statuses over all descendants (not the node itself), for far-zoom glyphs.
CREATE TABLE status_rollup (
    epoch_id    TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    node_id     TEXT NOT NULL,                  -- N
    counts_json TEXT NOT NULL,                  -- N  {status: count}, zero counts omitted
    PRIMARY KEY (epoch_id, node_id)
);

-- ---------------------------------------------------------------------------------------------
-- Informative and presentation tables. `summaries` and `narrations` are written by `ad2v llm run`
-- (P4, spec §11); `layout`, `tours`, `tour_stops` are created empty. Their columns are fixed now.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE summaries (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    node_id       TEXT NOT NULL,                -- N
    length        TEXT NOT NULL CHECK (length IN ('label','card','deep')), -- N
    text          TEXT NOT NULL,                -- I
    model         TEXT NOT NULL,                -- I
    model_version TEXT NOT NULL,                -- I
    prompt_hash   TEXT NOT NULL,                -- I
    input_hash    TEXT NOT NULL,                -- I
    confidence    REAL NOT NULL,                -- I
    created_at    TEXT,                         -- I
    result_id     TEXT REFERENCES llm_results(result_id), -- I  the cached LLM result (NULL for label)
    PRIMARY KEY (epoch_id, node_id, length, model)
);

CREATE TABLE narrations (
    epoch_id      TEXT NOT NULL,                -- N
    workflow_id   TEXT NOT NULL,                -- N
    mode          TEXT NOT NULL CHECK (mode IN ('containment','call_depth')), -- N  projection mode
    detail_level  INTEGER NOT NULL,             -- N  projection level (workflows.project)
    span_start    INTEGER NOT NULL,             -- N  first fine step seq (inclusive)
    span_end      INTEGER NOT NULL,             -- N  last fine step seq (inclusive)
    text          TEXT NOT NULL,                -- I
    model         TEXT NOT NULL,                -- I
    model_version TEXT NOT NULL,                -- I
    prompt_hash   TEXT NOT NULL,                -- I
    input_hash    TEXT NOT NULL,                -- I
    confidence    REAL NOT NULL,                -- I
    created_at    TEXT,                         -- I
    result_id     TEXT REFERENCES llm_results(result_id), -- I  the cached LLM result
    PRIMARY KEY (epoch_id, workflow_id, mode, detail_level, span_start, model),
    FOREIGN KEY (epoch_id, workflow_id) REFERENCES workflows(epoch_id, workflow_id),
    CHECK (span_start <= span_end)
);

CREATE TABLE layout (
    epoch_id  TEXT NOT NULL,                    -- N
    node_id   TEXT NOT NULL,                    -- N
    lod       INTEGER NOT NULL CHECK (lod IN (0,1,2)), -- N
    algorithm TEXT NOT NULL,                    -- N  name@version of the deterministic layout
    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL, -- N
    w REAL NOT NULL, h REAL NOT NULL, d REAL NOT NULL, -- N
    PRIMARY KEY (epoch_id, node_id, lod, algorithm)
);

CREATE TABLE tours (
    epoch_id      TEXT NOT NULL,                -- N
    tour_id       TEXT NOT NULL,                -- N
    title         TEXT NOT NULL,                -- N/I
    source        TEXT NOT NULL CHECK (source IN ('static','runtime','llm_inferred','user')), -- N
    workflow_id   TEXT,                         -- N  optional: tour that replays a workflow
    model         TEXT,                         -- I
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    confidence    REAL,                         -- I
    created_at    TEXT,                         -- I
    PRIMARY KEY (epoch_id, tour_id),
    CHECK (source <> 'llm_inferred' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);

CREATE TABLE tour_stops (
    epoch_id    TEXT NOT NULL,                  -- N
    tour_id     TEXT NOT NULL,                  -- N
    seq         INTEGER NOT NULL,               -- N
    node_id     TEXT NOT NULL,                  -- N  camera target
    camera_json TEXT NOT NULL DEFAULT '{}',     -- N  {lod, yaw, pitch, zoom}
    text        TEXT,                           -- I
    PRIMARY KEY (epoch_id, tour_id, seq),
    FOREIGN KEY (epoch_id, tour_id) REFERENCES tours(epoch_id, tour_id)
);

-- ---------------------------------------------------------------------------------------------
-- Source text (P4): what LLM slices are cut from, so `ad2v llm` works from the file alone
-- ---------------------------------------------------------------------------------------------

-- The normalized text of every code and spec file read, by content hash (the `content_hash` of
-- its module or spec_doc node), zlib-compressed UTF-8. Deduplicated across epochs; GC keeps the
-- blobs some kept epoch's module or spec_doc node references.
CREATE TABLE source_blobs (
    content_hash TEXT PRIMARY KEY,              -- I
    text_blob    BLOB NOT NULL                  -- I
);

-- ---------------------------------------------------------------------------------------------
-- LLM layer (P4, spec §11). Every column is informative; nothing here enters an epoch id.
-- ---------------------------------------------------------------------------------------------

-- Content-addressed cache of LLM outputs. Cache key: (task, input_hash, prompt_hash, provider,
-- model, params_hash); several rows may share a key (a re-run with --no-llm-cache), the newest
-- (highest `seq`) answers lookups. Kept by `prune` unless --drop-llm-cache.
CREATE TABLE llm_results (
    result_id         TEXT PRIMARY KEY,         -- I  r_ + sha256(cache key | ordinal)[:20]
    seq               INTEGER NOT NULL UNIQUE,  -- I  insertion order
    task              TEXT NOT NULL             -- I
                      CHECK (task IN ('judge','suggest','summarize','narrate','extract-prose')),
    input_hash        TEXT NOT NULL,            -- I  sha256(canonical JSON of the exact slice)
    prompt_hash       TEXT NOT NULL,            -- I  sha256(normalized prompt template)
    provider          TEXT NOT NULL,            -- I
    model             TEXT NOT NULL,            -- I
    model_version     TEXT,                     -- I  as reported by the provider
    params_hash       TEXT NOT NULL,            -- I  sha256(canonical generation params)
    subject           TEXT NOT NULL,            -- I  what was asked about (link id, node id, ...)
    output_json       TEXT,                     -- I  the parsed output (NULL if not JSON)
    valid             INTEGER NOT NULL,         -- I  0/1: passed schema + deterministic checks
    validation_errors TEXT NOT NULL DEFAULT '[]', -- I  JSON list
    usage_json        TEXT NOT NULL DEFAULT '{}', -- I  {"input_tokens","output_tokens"}
    cost_usd_est      REAL,                     -- I  from llm.pricing (NULL if unpriced)
    latency_ms        INTEGER,                  -- I
    created_at        TEXT                      -- I
);
CREATE INDEX idx_llm_results_key ON llm_results(task, input_hash, prompt_hash, provider, model, params_hash);

CREATE TABLE llm_runs (
    run_id          TEXT PRIMARY KEY,           -- I  u_ + sha256(started_at|tasks|epoch)[:20]
    started_at      TEXT NOT NULL,              -- I
    ended_at        TEXT,                       -- I
    epoch_id        TEXT NOT NULL,              -- I
    provider        TEXT NOT NULL,              -- I
    model           TEXT NOT NULL,              -- I
    model_version   TEXT,                       -- I  last reported by the provider
    llm_config_hash TEXT NOT NULL,              -- I
    llm_config_json TEXT NOT NULL,              -- I  effective llm config (no secrets)
    tasks_json      TEXT NOT NULL,              -- I
    calls           INTEGER NOT NULL DEFAULT 0, -- I  provider calls made
    cache_hits      INTEGER NOT NULL DEFAULT 0, -- I
    input_tokens    INTEGER NOT NULL DEFAULT 0, -- I
    output_tokens   INTEGER NOT NULL DEFAULT 0, -- I
    cost_usd_est    REAL NOT NULL DEFAULT 0,    -- I
    max_cost_usd    REAL NOT NULL,              -- I
    aborted         INTEGER NOT NULL DEFAULT 0, -- I  1: stopped before exceeding the budget
    notes_json      TEXT NOT NULL DEFAULT '{}'  -- I
);
CREATE TABLE llm_run_results (
    run_id    TEXT NOT NULL REFERENCES llm_runs(run_id), -- I
    result_id TEXT NOT NULL REFERENCES llm_results(result_id), -- I
    cached    INTEGER NOT NULL,                 -- I  1: served from the cache
    PRIMARY KEY (run_id, result_id)
);

-- Semantic judge per link (§11.4). Derived and informative: rebuilt from the cache for
-- materialized epochs. `overlay`: 'drift' when verdict = drift, valid, and confidence >= the
-- configured llm.judge.min_confidence; else 'evidence'.
CREATE TABLE link_judgments (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- I
    link_id       TEXT NOT NULL,                -- I
    result_id     TEXT NOT NULL REFERENCES llm_results(result_id), -- I
    verdict       TEXT NOT NULL CHECK (verdict IN ('conforms','partial','drift','cannot_tell')), -- I
    confidence    REAL NOT NULL,                -- I
    rationale     TEXT NOT NULL,                -- I
    evidence_json TEXT NOT NULL DEFAULT '[]',   -- I
    valid         INTEGER NOT NULL,             -- I
    overlay       TEXT NOT NULL CHECK (overlay IN ('drift','evidence')), -- I
    PRIMARY KEY (epoch_id, link_id),
    FOREIGN KEY (epoch_id, link_id) REFERENCES links(epoch_id, link_id)
);

-- Link suggestions for unpaired items (§11.5). `state` comes from ad2v.yaml (pairing.links /
-- pairing.rejected), so it is reproducible.
CREATE TABLE link_suggestions (
    epoch_id       TEXT NOT NULL REFERENCES epochs(epoch_id), -- I
    suggestion_id  TEXT NOT NULL,               -- I  s_ + sha256(spec_node_id|code_node_id)[:20]
    spec_node_id   TEXT NOT NULL,               -- I
    code_node_id   TEXT NOT NULL,               -- I
    candidate_rank INTEGER NOT NULL,            -- I  1-based BM25 rank
    lexical_score  REAL NOT NULL,               -- I  BM25 score (deterministic)
    result_id      TEXT NOT NULL REFERENCES llm_results(result_id), -- I
    verdict        TEXT NOT NULL CHECK (verdict IN ('match','no_match')), -- I
    confidence     REAL NOT NULL,               -- I
    rationale      TEXT NOT NULL,               -- I
    state          TEXT NOT NULL CHECK (state IN ('open','accepted','rejected')), -- I
    PRIMARY KEY (epoch_id, suggestion_id)
);

-- Prose-spec extraction (§11.8): a proposed Markdown file, never ingested until a human moves it.
CREATE TABLE spec_extractions (
    epoch_id          TEXT NOT NULL REFERENCES epochs(epoch_id), -- I
    spec_doc_node_id  TEXT NOT NULL,            -- I
    result_id         TEXT NOT NULL REFERENCES llm_results(result_id), -- I
    output_path       TEXT NOT NULL,            -- I  spec-root-relative
    state             TEXT NOT NULL CHECK (state IN ('proposed','written','ingested')), -- I
    PRIMARY KEY (epoch_id, spec_doc_node_id)
);

-- Normative node status plus informative overlays (§11.3). The LLM can only upgrade
-- implemented/verified to drift (provenance 'llm'); it never clears or downgrades a problem
-- status. `suggested` marks an open link suggestion and never changes the status.
CREATE VIEW node_status_effective AS
SELECT s.epoch_id, s.node_id, s.status AS normative_status,
       CASE WHEN s.status IN ('implemented','verified') AND EXISTS (
                SELECT 1 FROM link_judgments j JOIN links l ON l.epoch_id = j.epoch_id AND l.link_id = j.link_id
                WHERE j.epoch_id = s.epoch_id AND j.overlay = 'drift'
                  AND (l.spec_node_id = s.node_id OR l.code_node_id = s.node_id))
            THEN 'drift' ELSE s.status END AS status,
       CASE WHEN s.status IN ('implemented','verified') AND EXISTS (
                SELECT 1 FROM link_judgments j JOIN links l ON l.epoch_id = j.epoch_id AND l.link_id = j.link_id
                WHERE j.epoch_id = s.epoch_id AND j.overlay = 'drift'
                  AND (l.spec_node_id = s.node_id OR l.code_node_id = s.node_id))
            THEN 'llm' ELSE 'deterministic' END AS provenance,
       EXISTS (SELECT 1 FROM link_suggestions g WHERE g.epoch_id = s.epoch_id AND g.state = 'open'
                 AND (g.spec_node_id = s.node_id OR g.code_node_id = s.node_id)) AS suggested,
       (SELECT json_group_array(json_object('link_id', j.link_id, 'verdict', j.verdict,
                                            'confidence', j.confidence, 'overlay', j.overlay))
          FROM link_judgments j JOIN links l ON l.epoch_id = j.epoch_id AND l.link_id = j.link_id
         WHERE j.epoch_id = s.epoch_id AND (l.spec_node_id = s.node_id OR l.code_node_id = s.node_id)
       ) AS llm_evidence_json
FROM node_status s;
