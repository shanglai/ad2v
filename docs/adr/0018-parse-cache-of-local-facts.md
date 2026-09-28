# ADR-0018: The parse cache stores local facts; hits still parse

- Status: accepted (P3). **Deviation** from the prompt's "hits skip tree-sitter parsing".
- Context: the cache unit is the file, keyed by `(path, content_hash, rules_hash,
  extractor_version)`, and global passes always recompute. Profiling a warm extraction of dispatch
  (84k LOC) before designing the cache gave: parse 14%, per-file local passes ~41%, global passes
  ~36%, IO ~9%.
- Decisions:
  1. **What is cached:** each file's *local facts*: definitions (qualified names, parents, spans,
     byte ranges of the relevant syntax nodes, decorators, bases, `body_hash`, params), import
     operations, and explicit spec references with their fingerprints. These are the outputs of the
     per-file passes that do not look at any other file. They are stored as zlib-compressed
     canonical JSON in `parse_cache.payload_blob`, versioned by `LOCAL_EXTRACTOR_VERSION`.
  2. **Hits still parse the file.** The global passes (import resolution across modules, call and
     resource resolution, ports, entry points, behaviors) walk syntax trees. Serializing trees
     would be larger and slower than re-parsing (tree-sitter parses dispatch in ~1 s). A hit
     re-attaches cached byte ranges to the fresh tree with `find_node`. So a hit skips the ~41%
     local share, not the 14% parse share.
  3. **The cache is informative.** A test asserts that a cached and an uncached extraction produce
     identical graphs and epoch ids, and that entries with another extractor version are ignored.
     `--no-cache` bypasses it. GC drops entries whose file content no kept epoch contains.
  4. **Fine-grained timers** (`code.parse`, `code.local_facts`, `code.apply_local`,
     `code.global_walk`, and the pipeline stages) are recorded in the result for the bench.
  5. **`history` exports incrementally.** The prompt says "git archive and temp dirs". The first
     commit is exported in full; each later commit rewrites only the paths `git diff-tree` reports,
     with `git archive <commit> -- <paths>`, so `export-ignore` still applies. When a commit's
     `.gitattributes` uses `export-*`, that commit gets a full export. Re-exporting every commit made
     each epoch read ~1,000 freshly written files. On this Windows machine that first read costs
     ~4 s on dispatch (antivirus scanning, issue 13), more than the whole cached extraction. A test
     checks that an updated tree equals a fresh export byte for byte.
- Consequences: the incremental speed-up is bounded by the global share. Caching global results
  needs call-graph-closure invalidation, which is out of scope for P3 (REPORT §8).
