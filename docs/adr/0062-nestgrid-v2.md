# ADR-0062: `nestgrid-v2` (shelf packing), behind a flag

- Status: accepted (P7). v1 stays the default.
- Context: nestgrid-v1 sizes a whole grid column by its widest child and a row by its tallest,
  so parents with mixed child sizes are mostly empty (issue 54). On dispatch, the code root is
  8,475 × 4,341 units.
- Decisions:
  1. **v2** packs children on **shelves** (rows of their own height). Each child has a persisted
     slot: a shelf, an x offset, and a reserved width (`quantize(w × 1.2)`). It keeps v1's
     persistence rule:
     - a child keeps its slot while it fits its reserved width;
     - removed children free their interval;
     - new children, in (kind, qualified name) order, take the first free interval that fits,
       then the end of a shelf within the target width, then a new shelf;
     - a child that outgrows its interval moves alone. Shelf heights are quantized and never
       shrink.
     - The target width is set at a parent's first layout:
       `max(widest child, 1.15 × √(sum of reserved areas))`.
  2. Ports, heights, the spec/code regions and `layout_grids` storage are shared with v1. The v2
     grid JSON adds `xoff`, `widths` and `target`.
  3. **Opt-in.** `ad2v layout FILE --algorithm nestgrid-v2` writes rows under that algorithm
     name. The viewer shows them with `?layout=nestgrid-v2`. The MCP App and the default viewer
     use v1.
- Results:
  - Density = children's footprints over parents' inner areas, area-weighted.

    | | v1 | v2 |
    |---|---|---|
    | dispatch, all parents | 0.498 | **0.552** |
    | dispatch, top level | 0.531 | **0.604** |
    | dispatch, code-root area | 8,475 × 4,341 (36.8 M) | **2,792 × 2,775 (7.7 M, 4.8× smaller)** |
    | payments-recon fixture, all | **0.456** | 0.428 |

  - Stability on the P3 history scenario: **835/835 (100%) for both**.
- **Decision.** The rule was to keep v1 unless v2 wins on both density and stability. v2 ties on
  stability (it does not beat v1), and it loses density on the small fixture. So v1 stays the
  default. v2 is clearly better on a large repository; switching the default is a P8 question,
  after people have looked at the screenshots.
