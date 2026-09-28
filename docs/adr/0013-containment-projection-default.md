# ADR-0013: Containment projection is the default; call-depth becomes a mode

- Status: accepted (P2). Amends ADR-0009 §4. Decided in the P2 prompt.
- Context: the viewer's zoom follows the `contains` hierarchy. A replay slider driven by call
  depth would highlight functions while the screen shows containers, so the lit glyphs would not
  exist at that zoom.
- Decision: `project(steps, depth, mode="containment", ancestry_map=...)` is the default. A step's
  key is the ordered, de-duplicated list of the depth-k ancestors of its nodes (root = depth 0; a
  node shallower than k is its own key). Maximal runs of equal keys merge, and the coarse step
  highlights those ancestors. `mode="call_depth"` keeps P1's semantics. `workflows.ancestry(graph)`
  builds the map.
- Invariants (tested with seeded random data, seed 987654, for both modes):
  - the coarse spans are contiguous and partition the trace;
  - increasing k never merges steps. For containment: equal keys at k+1 imply equal keys at k,
    because the depth-k ancestor is a function of the depth-(k+1) ancestor;
  - containment only: every member of a coarse step has the same key, the coarse step's `node_ids`
    equal that key, and neighbouring coarse steps have different keys (maximal runs).
- Consequences: the API changed: `detail_level` became `depth`, and `mode` and `ancestry_map` were
  added. There are no external callers yet. Narrations stay keyed by `(detail_level, span_start)`. A
  P4 narration must also record which mode it was written for, which is still an open question (see
  REPORT §7).
