# ADR-0025: File-management columns are informative; what the dump contains

- Status: accepted (P3)
- Decisions:
  1. **`epochs.pinned`, `label`, `materialized` are class I.** They describe how the file is
     managed, not what the inputs were. Pinning an epoch must not change the normative dump, and
     `--normative-only` drops them. `vid` surrogates (ADR-0017) and the whole `parse_cache` are I
     for the same reason.
  2. **The dump shows logical tables only**: the four views plus every non-storage table, filtered
     to the selected epochs (`--epoch <id|head|all>`, default head). Storage tables (`*_versions`,
     `epoch_*` membership, `epoch_materialized`, `parse_cache`) are not dumped. Dedup is then
     invisible in the dump, and the "view content equals a fresh extraction" invariant can be tested
     as a dump comparison.
  3. **Derived rows of a non-materialized epoch are derived in memory** for the dump, so
     `dump --epoch all` does not depend on which epochs happen to be pinned.
  4. **The CRLF/BOM history determinism test masks `repo_commit`.** The same logical history
     committed with different line endings has different commit SHAs by construction. Everything
     else, including epoch ids (which hash normalized content, not commits), MUST be identical.
