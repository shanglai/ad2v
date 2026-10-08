# ADR-0078: Infra findings are a separate dimension (`infra_status`), not map statuses

- Status: accepted (P10)
- Context: the ten link/node statuses answer one question: does the code do what the spec says?
  "Is this container deployed?" and "is this env var provided?" are a different axis. A verified
  requirement whose service is undeployed in dev is still verified. Folding infra into the
  precedence would let a missing env var in one environment hide a drift, or the reverse.

## Decisions

1. **A new derived table,** `infra_status(epoch, node, env, status, reasons)`, with one row per
   (node, infra environment):
   - code containers: `deployed` / `undeployed` / `ambiguous`;
   - code nodes that read env vars, in a deployed container: `wired` / `unwired`, with the
     missing names and units as reasons;
   - infra resources other than modules: `in_use` (touched by a `references`, `wires` or `deploys`
     edge) or `infra_orphan`.
   An epoch without infra input has no rows: nothing is claimed, and readers show `unknown`.
2. **Not in the 10-status precedence.** `node_status` is unchanged, and the map's line styles stay
   the spec↔code statuses.
3. **Presentation.**
   - the map shows a small infra badge on labels, behind a toggle: ☁ deployed, ∅☁ undeployed,
     ⚠ unwired, ?☁ ambiguous, ∅ orphan;
   - the Architecture view uses these statuses as its primary styling, with line styles (solid,
     dashed, dash-dot, dotted) and theme tokens `infra.*` in both themes, at ≥ 3:1 contrast;
   - node cards list the status per environment.
4. **Per environment.** Every finding is per infra environment. The viewer has an environment
   selector, and the MCP overview and `ad2v_architecture` report each environment.
