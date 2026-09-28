# ADR-0020: Lineage fingerprints and the stale rules

- Status: accepted (P3)
- Context: the prompt fixes the lineage methods (`same_content`, `anchored_header` with Jaccard ≥
  0.6 and ties to needs_review evidence, `same_route`), the `stale` semantics, and the
  `# ad2v: REQ-012@<fp8>` re-annotation. Several details were open.
- Decisions:
  1. **Fingerprint = `body_hash` for functions and classes**, the content hash of the span with the
     defined name masked in the `def`/`class` line; `content_hash` for other kinds. `content_hash`
     includes the `def` line, so a pure rename would otherwise never be `same_content`, and the
     renamed function's links would go stale for a rename.
  2. **Change is judged on fingerprints**, with ids mapped through lineage. A rename is not a change.
  3. **Test functions are exempt from code-side change.** A test linked to a requirement is
     verification evidence, not the implementation. Editing a test must not make the requirement's
     link to it stale; if the test fails, the structural status already says so.
  4. **`descendants_changed`** is evidence only, added when both sides' content is unchanged, the
     code node was not renamed, and a `subtree_hash` changed. Without the last two conditions it
     fired on every rename and every direct edit, and duplicated the stronger evidence.
  5. **Ambiguous `anchored_header` ties** are stored as `id_lineage` rows with method `ambiguous`
     (the CHECK allows it) and never applied. The added node gets `needs_review` with evidence
     `lineage_ambiguous` (candidate id and score). Keeping them as rows lets `diff` and a reviewer
     see the candidates.
  6. **Stale rules** are the ordered table of spec §6.7. Notable choices:
     - spec and code both changed → keep the structural status, evidence `both_changed`: the
       author evidently touched both, and a stale here would mostly be noise;
     - code changed after `implemented` → evidence `code_changed_since`, status unchanged (nothing
       was verified, so nothing is invalidated); after `verified` → `stale`
       (`code_changed_unverified`) unless fresh passing results arrive in the same epoch (`retested`);
     - a stale carries forward until cleared by re-annotation with the current fingerprint
       (`reannotated`), or, for `code_changed_unverified` with an unchanged spec, by a fresh
       passing run;
     - a fingerprint that does not match the spec's current `content_hash` is `stale`
       (`fingerprint_mismatch`) even without history, e.g. on the first epoch.
  7. **`link_state` is a base fact** (ADR-0017): the final status, history evidence and the last
     agreement (epoch, spec hash, code hash) per link and epoch. Materializing an epoch replays it
     instead of recomputing history, so pruning the parent does not change an epoch's statuses.
- Consequences: in the history fixture, `REQ-002` goes stale in epoch 2 because `match_batch`'s own
  body changed (its call site to the renamed helper). That is correct under these rules and is
  documented in `expected-history.yaml`: the rename of the helper itself does not cause it.
