# ADR-0034: Deterministic layout `nestgrid-v1`, computed in Python and persisted

- Status: accepted (P5)
- Context: the viewer needs positions that are identical for everyone who opens the file and
  that move as little as possible between epochs (mental map). A force-directed or browser-side
  layout gives neither.
- Decisions:
  1. **Python computes the layout** at extract and materialize time and writes `layout` rows. The
     viewer never lays anything out, so every consumer (the viewer now, MCP later) sees the same
     boxes.
  2. **Nested grids** (format spec §12.1): children in a grid inside their parent, ports on the
     east and south edges, a spec region to the west. Stable order is kind, then qualified name.
     No randomness.
  3. **Stability through persisted grids.** `layout_grids` stores each parent's tracks, child slots
     and port slots. A new epoch starts from the parent epoch's grids through `id_lineage`.
     - The first version (no persisted port slots, exact track sizes) moved 6.5% of boxes on the
       P3 history. Two causes: ports reshuffled when the ⌈n/2⌉ edge split changed, and track
       growth cascaded.
     - Four changes bring it to 765/765 boxes unmoved: persisting port slots (new ports go to the
       shorter edge), quantizing tracks (1…16, then ×1.25), 20% headroom on growth, and never
       shrinking.
  4. **History dependence is accepted** as a named exception to principle 8, like `id_lineage`.
  5. Layout rows are kept for every epoch that has them and are removed only by `prune`.
- Consequences:
  - Large repositories get sparse layouts (headroom, quantized tracks). On dispatch the system box
    is about 8,500 × 4,300 units, with the dense content in one region (see `pending.md`).
  - A later `nestgrid-v2` can tighten packing; `algorithm` is part of the key.
