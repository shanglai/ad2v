# ADR-0014: Deterministic risk severity

- Status: accepted (P2). The formula is fixed by the P2 prompt. This ADR records the choices around
  it.
- Decisions:
  1. The weights live in the rules (`severity:`), so they are covered by `rules_hash` and overridable
     per project through the overlay (ADR-0012).
  2. `base` is the **max** over the node's flags, not the sum: a loop that is both `io_in_loop` and
     `llm_in_loop` scores as LLM-in-loop. Nesting bonuses **add**. Then everything is multiplied by
     `reach_factor`. (The prompt's `base + nesting_bonus × reach_factor` is read as
     `(base + bonus) × reach`, because the reach factor is meant to scale the whole risk.)
  3. **Reach** = the number of distinct *code-side* static workflows whose steps include the
     node, using the derived `workflow_step_nodes`. Spec workflows never contain code nodes.
  4. Severity is rounded to 4 decimals, so the stored float is identical across platforms. The rank
     orders by `(-severity, node id)`. Non-risky behavior nodes (only with `emit_all`) get severity
     0 and are ranked last.
  5. `attrs.severity_reach` is stored next to the score, so a reader can explain it.
- Consequences: the ranking is a triage heuristic, not a measurement. It rewards reachability from
  entry ports, so risky code that only runs from untraced entry points (scheduled jobs without a
  recognized decorator, library code) ranks low. The P2 performance re-check shows this (REPORT §4).
