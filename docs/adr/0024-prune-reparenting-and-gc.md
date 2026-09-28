# ADR-0024: Prune re-parents kept epochs; garbage collection

- Status: accepted (P3)
- Decisions:
  1. `prune --keep-last N [--keep-pinned]` never deletes the head. Every kept epoch is re-parented
     to its nearest kept ancestor, so the chain stays connected and `diff` still works across the
     gap.
  2. **Epoch ids are not recomputed** after re-parenting, although the id formula includes the
     parent. An id names the extraction that happened, and ids referenced elsewhere (pins, CI
     comments) must stay valid. The validator therefore checks the chain order, not the id formula,
     for the parent link.
  3. **Lineage rows are kept** and still refer to the original parent. The validator checks their
     old ids only when the parent is the immediately preceding `seq`. After a prune the old ids may
     name nodes that no kept epoch has, and that is expected.
  4. **GC** deletes version rows that no membership row references, rules and manifests no epoch
     references, and parse-cache rows whose `(path, content_hash, rules_hash)` matches no module
     node of a kept epoch. Then `VACUUM` (outside the transaction) returns the space to the OS.
