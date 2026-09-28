# ADR-0043: `ad2v_locate`: deterministic BM25F with kind priors; weights in the rules

- Status: accepted (P6)
- Decisions:
  1. **Scoring.** One BM25 index per field (P4's stdlib BM25 and tokenizer, with the stemmer
     memoized):
     - `name`;
     - `qname`;
     - `code` (ports' method, path, command and handler, risk flags, touched resources, and the
       first 12 lines of the node or of its handler, i.e. the def line and docstring);
     - `spec` (EARS text, steps, …);
     - `summary` (LLM, informative);
     - `narration` (attached to each workflow's entry port).

     The score is the weighted sum over fields.
  2. **Intents.** Trigger words in the question select kind multipliers (`where`, `risk`,
     `requirement`, `flow`, `endpoint`). A question that names a status ("drifting", "stale",
     "orphan"; matched on stems) multiplies nodes whose normative or effective status matches
     it.
  3. **Prefix expansion.** A query token of ≥ `prefix_min` (4) characters also matches words
     that start with it: "night" matches "nightly", and "classifi" (from "classified") matches
     "classify".
  4. **The weights live in the rules file** (`retrieval:` in `rules/python.yaml`) and are covered
     by `rules_hash`: they decide which components a question points at. The server reads the
     rules stored with the epoch, and older files fall back to the bundled rules. Adding them
     changed `rules_hash` (new epoch ids for new extractions); no golden pins it.
  5. **Eval protocol.**
     - 25 questions in `fixtures/payments-recon/expected-questions.yaml`, 8 held out.
     - Metrics: recall@5, MRR, nDCG@5.
     - Questions that name a status or a diff are scored through the tool a model would call
       (`ad2v_status`, `ad2v_diff`).
     - Tuning is coordinate descent over fixed value lists, in a fixed order, and ties keep the
       current value. It runs on the 17 non-held-out questions only.
  6. **Result (reported in P6):** the structural fixes (prefix expansion, stemmed status words,
     the `endpoint` intent), found on tuning questions, gave most of the gain.
     - Weight tuning raised the tuning-set objective but lowered held-out MRR by about one
       question's rank. That is noise at this size, and it is reported, not hidden.
     - The tuned weights were kept because the procedure fixed that rule before the held-out
       numbers were seen. Choosing weights by held-out results would leak.
