# ADR-0041: Two tool surfaces; app tools mirror `DataSource`; scene slices

- Status: accepted (P6)
- Decisions:
  1. **Agent tools** (13, model-visible) are semantic and compact (ADR-0042). **App tools** (20,
     app-only) are the viewer's `DataSource`, one tool per method (`viewer_nodes`,
     `viewer_layout`, …, `viewer_scene`).
  2. **Same results.** `ad2v.mcp.slices` runs, statement for statement, the SQL of
     `LocalFileSource`, including JavaScript coercions (`String(null)` → "null", `Number(null)`
     → 0). Maps travel as JSON objects keyed by id; `RemoteSliceSource` rebuilds them.
     - **Parity test:** every method, every epoch of the demo file (plus every node for the
       per-node methods, every workflow for steps and narrations, 38 roots × 3 depths for
       scenes) deep-equals across the two sources, over the real stdio server.
  3. **`scene(epoch, rootId, depth)`** is a new `DataSource` method. For a focus node it returns:
     - every root;
     - the root's ancestor chain and each ancestor's children;
     - the root's subtree to `depth`;
     - the subtree's direct neighbors along non-hierarchy edges, each with its own ancestor
       chain;
     - the layout, glyphs, both statuses, roll-ups and the edges inside that set.

     `rootId = null` (or `depth = -1`) is the whole epoch. **The standalone viewer loads through
     `scene(epoch, null, -1)`**, so both viewers share one code path.
  4. **App mode never loads the file.** It asks for one slice per intent node (depth 1) and
     merges slices as the user enters or zooms into a container whose children are not loaded
     yet (`expanded` set).
     - Exception: the `diff` intent loads the two whole epochs, because classifying a diff
       needs every node of both.
  5. **Pagination.** Lists and maps over 2,000 items are paginated with `nextCursor`, and
     `RemoteSliceSource` follows the pages. `viewer_scene` is not paginated but refuses results
     over 8 MB. On dispatch, a module slice is 376 KB, a large component 528 KB, and the whole
     epoch 4.9 MB.
