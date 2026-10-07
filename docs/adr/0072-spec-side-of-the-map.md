# ADR-0072: The spec side of the map: steps off the map, scenario roll-up, readable labels

- Status: accepted (P9)
- Context: on the spec side, every Gherkin step was a glyph. A feature with ten scenarios drew
  forty small boxes whose only content was "Given …", each with its own status, and those
  statuses were almost always `none` or misleading. Scenarios themselves showed only their own
  link status, even when a tag (`@REQ-001`) tied them to a requirement that was verified or
  stale. Labels were bare ids (`RF-007`) or names cut at character 48, often mid-word.

## Decisions

1. **`layout.OFF_MAP_KINDS = {scenario_step}`.** Steps stay in the graph: ids, glyph rows, edges,
   workflows and validation are unchanged. They get no layout row, though, so they are not drawn
   and they do not count in density or child grids. The viewer's `SceneTree` already skips nodes
   without a box. A spec workflow (a scenario's replay) shows each step as its scenario on the map,
   with the step text in the replay card, and starts at the finest level.
2. **Step status is `none`** (reason kind `step`). A step is text, not a claim.
3. **A scenario rolls up the requirements it references.** For each tag that names a requirement,
   the statuses of that requirement's links are added as `via_spec_ref` reasons, one per
   (ref, status). Usual precedence then applies. So a scenario tagged `@REQ-001` goes `stale` when
   REQ-001 does. That is one more transition in the P3 history golden (4→5: 2 → 3 `verified →
   stale`).
4. **Labels** (`text.ts displayLabel`, used on the map, in cards, lists and the replay picker):
   - requirement: `<id> · <title>`;
   - spec component with an id: `CMP-001 · name`;
   - scenario: its name, then the ids it references (`Approve a run [REQ-007]`);
   - anything else: its name.
   NodeRow carries `title`, `refs`, `nfr` and `keyword` in both data sources, and the parity test
   covers them.
5. **Truncation at a word boundary with "…"** everywhere text is cut: map billboards (48),
   contents lists (80) and the replay picker (60).
6. **Cards.** A scenario card lists its steps in order, with the keyword marked
   (Given/Dado, When/Cuando, …). A non-functional requirement gets an NFR badge and a note. A
   requirement that is `not_evaluable` through its component names the component and its language.
7. **Stability.** On the P3 history scenario, 786/786 unchanged nodes keep their position across
   epochs, with both layout algorithms (1.0000, target ≥ 0.95).
