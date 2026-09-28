# ADR-0023: Epoch diff semantics

- Status: accepted (P3)
- Decisions:
  1. **Ancestor only.** `--from` must be an ancestor of `--to` in one file (default: parent → head).
     Lineage is defined only between consecutive epochs, and diffing unrelated epochs would need a
     second, weaker matching.
  2. **Lineage is composed** along the chain: renames A→B→C report one rename A→C, with the method of
     the last hop. `ambiguous` rows are never applied.
  3. **V columns are ignored.** A node whose only change is its lines is not `modified`. Edge
     `lines` never appear.
  4. **Derived data is computed in memory** for both epochs (`materialize.derive`), so `diff` never
     writes and works on non-materialized epochs.
  5. **Sorting:** node status transitions by badness (the node-status precedence, worst first), then
     qualified name; everything else by qualified name. A severity change is reported from 1.0 up,
     so rounding noise does not show.
  6. **`--format md` is capped at 60 lines** for pull-request comments. Each section is truncated
     with a "… and N more" line. The JSON format is complete.
  7. The GitHub Actions example (`examples/github-action/ad2v-diff.yml`) builds a two-epoch file
     (merge base, then PR head) with `ad2v history` and posts the md diff. It is an example only and
     not wired into this repository.
