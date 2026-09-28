-- ad2v file format v0.1 -- SQLite DDL
-- Normative reference: docs/spec/ad2v-format-v0.1.md
-- Column classes: N = normative (deterministic), I = informative (LLM/runtime/wall-clock).
-- Every JSON column holds canonical JSON (sorted keys, no whitespace, UTF-8).

PRAGMA foreign_keys = ON;

-- Key/value metadata. Keys: format_version (N), generator (I), generator_version (I),
-- repo_root_name (I), created_at (I), repo_manifest (N), rules_version (N).
CREATE TABLE meta (
    key   TEXT PRIMARY KEY, -- N
    value TEXT NOT NULL   -- N/I (class depends on the key, see spec §5)
);

CREATE TABLE epochs (
    epoch_id        TEXT PRIMARY KEY,           -- N  e_ + sha256(parent|repo_tree_hash|spec_tree_hash|rules_hash)[:20]
    parent_epoch_id TEXT REFERENCES epochs(epoch_id), -- N
    repo_commit     TEXT,                       -- N  git HEAD if <repo>/.git is readable, else NULL
    repo_tree_hash  TEXT NOT NULL,              -- N
    spec_tree_hash  TEXT NOT NULL,              -- N
    rules_hash      TEXT NOT NULL,              -- N  tree hash of the normalized extractor rules files
    attrs_json      TEXT NOT NULL DEFAULT '{}', -- N  extraction config echo (rules/manifest hashes)
    created_at      TEXT                        -- I  excluded from canonical dump
);

CREATE TABLE nodes (
    epoch_id        TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    id              TEXT NOT NULL,              -- N  n_ + sha256(side|kind|qualified_name)[:20]
    side            TEXT NOT NULL CHECK (side IN ('code','spec')), -- N
    kind            TEXT NOT NULL,              -- N  closed enum, see spec §3.2
    name            TEXT NOT NULL,              -- N
    qualified_name  TEXT NOT NULL,              -- N
    parent_id       TEXT,                       -- N  NULL for roots
    path            TEXT,                       -- N  repo- or spec-root-relative, forward slashes
    span_start_line INTEGER,                    -- N  1-based, inclusive
    span_end_line   INTEGER,                    -- N  1-based, inclusive
    content_hash    TEXT NOT NULL,              -- N
    subtree_hash    TEXT NOT NULL,              -- N
    level_hint      TEXT,                       -- N  optional presentation hint
    attrs_json      TEXT NOT NULL DEFAULT '{}', -- N
    spec_ref_json   TEXT NOT NULL DEFAULT '[]', -- N  sorted list of explicit spec IDs
    PRIMARY KEY (epoch_id, id),
    FOREIGN KEY (epoch_id, parent_id) REFERENCES nodes(epoch_id, id)
);
CREATE INDEX idx_nodes_parent ON nodes(epoch_id, parent_id);
CREATE INDEX idx_nodes_kind   ON nodes(epoch_id, kind);
CREATE INDEX idx_nodes_side   ON nodes(epoch_id, side);
CREATE INDEX idx_nodes_qname  ON nodes(epoch_id, qualified_name);

CREATE TABLE edges (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    src           TEXT NOT NULL,                -- N
    dst           TEXT NOT NULL,                -- N
    kind          TEXT NOT NULL,                -- N  closed enum, see spec §3.4
    weight        INTEGER NOT NULL DEFAULT 1,   -- N  occurrence count
    attrs_json    TEXT NOT NULL DEFAULT '{}',   -- N
    provenance    TEXT NOT NULL DEFAULT 'deterministic' -- N
                  CHECK (provenance IN ('deterministic','runtime','llm')),
    model         TEXT,                         -- I  required when provenance='llm'
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    confidence    REAL,                         -- I
    PRIMARY KEY (epoch_id, src, kind, dst),
    FOREIGN KEY (epoch_id, src) REFERENCES nodes(epoch_id, id),
    FOREIGN KEY (epoch_id, dst) REFERENCES nodes(epoch_id, id),
    CHECK (provenance <> 'llm' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);
CREATE INDEX idx_edges_src ON edges(epoch_id, src);
CREATE INDEX idx_edges_dst ON edges(epoch_id, dst);
CREATE INDEX idx_edges_kind ON edges(epoch_id, kind);

-- Explicit references that could not be resolved (e.g. `# ad2v: REQ-099` with no REQ-099 in the spec).
CREATE TABLE unresolved_refs (
    epoch_id TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    src      TEXT NOT NULL,                     -- N  node carrying the reference
    ref      TEXT NOT NULL,                     -- N  the referenced identifier, verbatim
    ref_kind TEXT NOT NULL,                     -- N  'spec_id'
    reason   TEXT NOT NULL,                     -- N  'not_found'
    PRIMARY KEY (epoch_id, src, ref_kind, ref),
    FOREIGN KEY (epoch_id, src) REFERENCES nodes(epoch_id, id)
);

CREATE TABLE glyphs (
    epoch_id       TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    node_id        TEXT NOT NULL,               -- N
    base_shape     TEXT NOT NULL,               -- N  glyph grammar §2
    variant        TEXT NOT NULL,               -- N  glyph grammar §3
    modifiers_json TEXT NOT NULL,               -- N  glyph grammar §4
    size_weight    INTEGER NOT NULL,            -- N  glyph grammar §6
    has_interior   INTEGER NOT NULL,            -- N  0/1, LOD 2 availability
    PRIMARY KEY (epoch_id, node_id),
    FOREIGN KEY (epoch_id, node_id) REFERENCES nodes(epoch_id, id)
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
    FOREIGN KEY (epoch_id, entry_node_id) REFERENCES nodes(epoch_id, id),
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

-- ---------------------------------------------------------------------------------------------
-- Tables below are created empty in v0.1 producers (P1). Their columns are fixed now.
-- ---------------------------------------------------------------------------------------------

-- spec<->code links. status vocabulary and state machine: spec §6.
CREATE TABLE links (
    epoch_id      TEXT NOT NULL REFERENCES epochs(epoch_id), -- N
    link_id       TEXT NOT NULL,                -- N  l_ + sha256(spec_node_id|code_node_id)[:20]
    spec_node_id  TEXT,                         -- N  NULL for orphan code
    code_node_id  TEXT,                         -- N  NULL for missing spec items
    status        TEXT NOT NULL -- N/I (I when provenance='llm')
                  CHECK (status IN ('specified','implemented','verified','drift',
                  'orphan','stale','needs_review','missing')),
    provenance    TEXT NOT NULL CHECK (provenance IN ('deterministic','runtime','llm')), -- N
    evidence_json TEXT NOT NULL DEFAULT '[]',   -- N/I
    confidence    REAL,                         -- I  required when provenance='llm'
    model         TEXT,                         -- I
    model_version TEXT,                         -- I
    prompt_hash   TEXT,                         -- I
    input_hash    TEXT,                         -- I
    created_at    TEXT,                         -- I  excluded from canonical dump
    PRIMARY KEY (epoch_id, link_id),
    FOREIGN KEY (epoch_id, spec_node_id) REFERENCES nodes(epoch_id, id),
    FOREIGN KEY (epoch_id, code_node_id) REFERENCES nodes(epoch_id, id),
    CHECK (spec_node_id IS NOT NULL OR code_node_id IS NOT NULL),
    CHECK (provenance <> 'llm' OR (model IS NOT NULL AND model_version IS NOT NULL
           AND prompt_hash IS NOT NULL AND input_hash IS NOT NULL AND confidence IS NOT NULL))
);
CREATE INDEX idx_links_spec ON links(epoch_id, spec_node_id);
CREATE INDEX idx_links_code ON links(epoch_id, code_node_id);

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
    PRIMARY KEY (epoch_id, node_id, length, model),
    FOREIGN KEY (epoch_id, node_id) REFERENCES nodes(epoch_id, id)
);

CREATE TABLE narrations (
    epoch_id      TEXT NOT NULL,                -- N
    workflow_id   TEXT NOT NULL,                -- N
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
    PRIMARY KEY (epoch_id, workflow_id, detail_level, span_start, model),
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
    PRIMARY KEY (epoch_id, node_id, lod, algorithm),
    FOREIGN KEY (epoch_id, node_id) REFERENCES nodes(epoch_id, id)
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
    FOREIGN KEY (epoch_id, tour_id) REFERENCES tours(epoch_id, tour_id),
    FOREIGN KEY (epoch_id, node_id) REFERENCES nodes(epoch_id, id)
);
