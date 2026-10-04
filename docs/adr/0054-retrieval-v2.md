# ADR-0054: Retrieval v2: link propagation, spec ids, status order, bigger eval sets

- Status: accepted (P7)
- Context:
  - In P6, requirement questions were weak (MRR 0.68). The 25-question set was too small to tune
    on (issue 68), and `ad2v_status` sorted by name (issue 67).
  - Namespaced spec-kit ids and Kiro sub-ids (P6.1) were not searchable by id.
- Decisions, structural first (set before any tuning, values chosen a priori):
  1. **Link propagation.** When the question fires a spec intent (`requirement`), a spec item's
     score is `max(own, λ · best normatively linked code score)`; with a code intent (`where`,
     `flow`, `endpoint`), the reverse holds. λ = 0.8. A spec intent also multiplies spec items by
     `spec_side_boost` 1.3. Links come from the epoch's deterministic `links` rows (materialized
     epochs).
  2. **Spec ids.** Ids written in the question match exactly, case-insensitively: `FR-001` finds
     every `<ns>:FR-001`, `001-payments:FR-001` finds only that one, and a bare `1.2` finds Kiro
     criteria ending in `-1.2`. A match adds `id_match` 25 to the score.
  3. **Test code** (`is_test`, or a `tests/` / `test_*.py` path) is multiplied by 0.5 unless the
     question mentions tests.
  4. **Resources** add their kind words ("external service api client", …) and the names of the
     functions that read, write, publish, consume or invoke them to their code field (q25).
  5. **`ad2v_status` order** (issue 67): ports and spec endpoints, then containers and components,
     then the rest, by qualified name within a rank.
  6. All values live in the `retrieval:` rules (in `rules_hash`). A file whose stored section
     predates a key takes that key from the bundled rules, so old files get the structural
     changes. Weights stored in the file still win.
- **Eval protocol.**
  - `payments-recon` grows to 40 questions (P6's 25 unchanged). New sets: `sdd-presets` (10) and
    a code-only `full-stack-fastapi-template` set (20, pinned commit, gold written from the code
    before any retrieval ran on it).
  - Each file was frozen and hashed, and its held-out ids drawn with seed 987654 before any
    measurement.
  - **Weight tuning** ran once, after the structural changes, on the pooled 48 tuning questions
    of the combined 70. `evaluate.tune` now takes several maps. It changed `name` 0.5 → 1.0,
    `qname` 0.5 → 2.0, `narration` 2.0 → 3.0 and the intent scale ×1.5. The tuning objective went
    from 2.336 to 2.460.
  - Held-out questions were scored after tuning.
  - Caveat: during the structural work the eval script printed held-out rows too, so held-out
    numbers were visible, though never used for tuning.
- Results, with tools, MRR (P6 code → P7):
  - P6's 25: 0.888 → 1.000;
  - fixture 40: 0.813 → 0.912 (held-out 0.729 → 0.878);
  - presets 10: 0.642 → 0.850;
  - template 20: 0.529 → 0.762.
  Details are in REPORT.md §5.
