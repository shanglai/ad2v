# ADR-0026: A callee rename does not change its callers

- Status: accepted (P4). Carry-over fix decided in the P4 prompt (§2).
- Context: in the P3 history fixture, renaming `amounts_match` → `amounts_equal` made REQ-002
  stale, because the caller `match_batch` changed at its call site. That is noise.
- Decisions:
  1. The extractor records, per function, `attrs.call_masked_hash` and `attrs.call_sites`. The
     first is the body hash with the defined name **and every resolved repo callee name token**
     masked. The second is the resolved callee ids in source order.
  2. `history.same_code(old, new, lineage)` treats two versions as the same code if their
     fingerprints are equal, or if their call-masked hashes are equal and the old callee ids,
     mapped through this transition's lineage, equal the new ones. That is the prompt's "replace
     the callee name token with its lineage-stable id", done without storing text.
  3. When this rule makes the code "unchanged", the link gets evidence `callee_renamed`, and
     `descendants_changed` is not added (the subtree hash moved only because of the call site).
- Consequences: `expected-history.yaml` epoch 2 has REQ-002 **verified** with evidence
  `callee_renamed`, and epoch 7 still makes it stale (a real loop edit). Only attrs of function
  nodes change; no id changes.
