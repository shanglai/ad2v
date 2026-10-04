# ADR-0061: Viewer UX v2: labels, edges, portals, dashes, hidden replay steps

- Status: accepted (P7)
- Context: on big repositories the map was sparse and tangled. Labels collided, long dashed
  edges aliased into cross-hatching (issue 55), and portal chips overlapped. A replay step that
  is not visible at the current LOD silently highlighted an ancestor (issue 71), and open
  suggestions were easy to miss.
- Decisions. The placement rules are pure functions in `viewer/src/model/declutter.ts`, tested in
  Vitest.
  1. **Labels.**
     - Greedy placement in priority order: problem statuses (drift, missing, orphan,
       needs_review, stale), then ports, then larger footprint, then name.
     - A label is rejected if its screen rectangle overlaps a placed one.
     - **Hysteresis:** labels shown last time sort first within their priority and are tested
       with a rectangle shrunk by 6 px, so small camera moves don't make them flicker.
     - An open container's node card lists its contents with statuses (up to 60; click to fly),
       because culled labels must still be reachable.
  2. **Edges.** A toolbar select chooses `all`, `selection` or `aggregated`.
     - `selection` draws only edges touching the selection, the hover or the replay/intent
       emphasis.
     - `aggregated` lifts every representative below the label LOD to its visible parent: one
       weighted ribbon per parent pair, self-loops dropped.
     - In `all` and `aggregated`, above **150** visible edges (`scene.edgeLimit`), only the
       touching edges plus the 50 heaviest are drawn. Hovering then shows a node's edges, and
       the select's tooltip says how many are hidden.
  3. **Portal chips.** One chip per destination (`→ api ×3`) at the mean wall point. Chips are
     stacked per wall side (22 px apart) in label order, at most 40.
  4. **Dashes (issue 55).** The ribbon shader computes each segment's own screen pixels per
     world unit, so a dash has the same on-screen length on foreshortened and arcing segments.
     One global factor had made dashes on some segments shorter than a pixel, which aliased.
  5. **Hidden replay steps (issue 71).** When a step's nodes are not visible at the current LOD,
     the step card says "inside <ancestor>" and offers **zoom to step**. The button fits the
     step's own boxes, which opens their parents; `frameStep` frames the visible representative,
     which is already readable.
  6. **Suggestions.** The toggle shows the number of open suggestions. A one-time hint card
     (`localStorage` key `ad2v.hint.suggestions`, inside try/catch) names the toggle and the
     CLI command.
