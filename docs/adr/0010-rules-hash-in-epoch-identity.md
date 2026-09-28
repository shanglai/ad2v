# ADR-0010: The extractor rules are an input of the epoch (`epochs.rules_hash`)

- Status: accepted (P1, M7)
- Context: extraction output depends on three inputs, not two: the code, the specs, **and**
  `extract/code/rules/python.yaml` (library → resource classification, pure methods, port
  frameworks). Suppose two runs on the same repository with different rules files produce different
  graphs, but share `repo_tree_hash`, `spec_tree_hash` and the epoch id. The file would then claim
  determinism it doesn't have, and P2's incremental reuse could wrongly reuse stale results.
- Decision:
  - `epochs.rules_hash` (normative column) = `tree_hash({rules file name: content_hash(normalized text)})`,
    currently over `{"python.yaml": ...}`. Normalization (LF, no BOM) is the same as for code, so a
    CRLF checkout of the rules gives the same hash.
  - The epoch id includes it:
    `e_ + sha256(parent | repo_tree_hash | spec_tree_hash | rules_hash)[:20]`.
  - The canonical dump includes the column, so dumps from different rules differ visibly.
  - `rules_version` (a human-maintained label) stays in `meta` and `epochs.attrs_json`, but it is not
    trusted for identity.
- Consequences: P2's Merkle reuse must invalidate all code-side results when `rules_hash` changes,
  since classification can change anywhere. When more languages arrive, their rules files join the
  same tree hash.
- Test: `tests/test_determinism_and_cli.py::test_rules_file_change_changes_rules_hash`.
