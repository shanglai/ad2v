# ADR-0030: Task details not fixed by the P4 prompt

- Status: accepted (P4)
- Decisions:
  1. **Judge scope.** Judgeable links have both sides, a method other than `none`, a status of
     implemented/verified/stale, and a code side that is not a test function (tests are evidence,
     as in ADR-0020). A port's slice uses its handler's code. A container or component has no
     span, so its slice is an IR digest (children, ports, calls, touches); the live run shows this
     is often too little to judge (`cannot_tell`).
  2. **Callee signatures** are those of direct callees on a workflow that also passes through the
     node, or all direct callees when the node is on no workflow. A node on no workflow reaches
     the resources its direct callees touch.
  3. **Suggestions.**
     - The candidate pool is containers, components, ports, functions and classes (no tests) for
       spec items, and requirements, spec components and endpoints for code items.
     - Tokens are lowercase, split on camelCase, with a small stopword list and light suffix
       stemming. BM25 uses k1 = 1.2 and b = 0.75.
     - Only `match` verdicts at or above the threshold become rows; a pair found from both sides
       keeps the higher confidence. `no_match` verdicts stay in `llm_results` for audit.
     - `accept`/`reject` edit ad2v.yaml line by line, appending only. Before writing, the edit
       must parse back to the same data plus the one entry, or it is refused.
     - `manifest_link` resolves the code name by kind in a fixed order (function first) and gives
       `missing` when the target does not exist.
  4. **Summaries.** Summaries cover the code side only, in scope `structural`. `label` rows are
     deterministic (model `ad2v`). The `confidence` column (NOT NULL in the schema) holds 1.0 for a
     valid output; summaries have no model confidence. Valid mentions are appended to the `deep`
     text.
  5. **Narrations.** Only code workflows are narrated (spec scenarios already are prose).
     Detail levels start at 1 and stop at the first level whose projection is the fine trace.
     A level with more than 40 coarse steps is narrated in chunks of 40.
  6. **Prose extraction** runs on Markdown `spec_doc`s with at least 40 characters of prose. IDs
     are numbered across documents in path order, so two proposals never collide. The model
     returns structured JSON; ad2v renders the Markdown.
