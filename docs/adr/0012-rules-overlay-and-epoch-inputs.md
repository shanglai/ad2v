# ADR-0012: Rules overlay, canonical rules_hash, and all inputs in the epoch id

- Status: accepted (P2). Amends ADR-0010. Overlay decided in the P2 prompt (P1 open question 6).
- Decisions:
  1. `ad2v.yaml` may declare `rules_overlay: <path>` (relative to the manifest). It is deep-merged
     over the built-in rules: mappings merge key by key, and everything else, **including lists**,
     replaces. Replacing lists keeps merges predictable: an overlay that wants to extend
     `pure_methods` restates the whole list.
  2. `rules_hash = sha256(canonical_json(merged rules))`. In P1 it was a tree hash of the rules
     file's normalized text. Hashing the parsed, merged content means comments, key order and YAML
     formatting no longer change the hash. Semantic changes and overlays do (tested). The P1 test
     that expected a comment-only edit to change the hash was inverted accordingly.
  3. P2 adds two more inputs that change the output: the **manifest** (pairing components, path
     prefix map, containers…) and the **test results** (they decide `verified`). Two new normative
     `epochs` columns record them: `config_hash = sha256(canonical_json(parsed manifest or {}))` and
     `test_results_hash` (a tree hash over the ingested files). Both enter the epoch id:
     `e_ + sha256(parent|repo|spec|rules|config|test_results)[:20]`.
- Consequences: the invariant "same epoch id ⇔ same normative output" now holds for every
  input the producer reads. P3's incremental reuse must invalidate: all code-side results on a
  `rules_hash` change, pairing results on a `config_hash` change, and link statuses (only) on a
  `test_results_hash` change.
