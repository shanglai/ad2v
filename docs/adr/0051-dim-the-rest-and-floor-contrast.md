# ADR-0051: "Dim the rest" without transparency, and contrast on open floors

- Status: accepted (P6.1)
- Context: the user asked whether alpha would help a replayed step stand out, and noticed grey
  blocks matching grey lines. Real transparency needs sorted, blended draws and costs fill-rate
  on large maps. Separately, P5's body colors were hard-coded per theme and never contrast-tested.
- Decisions:
  1. **Opaque dimming.** During a replay and the App `path`/`focus` intents, every visible node
     that is not the step, inside the step, or a container of the step is drawn **blended toward
     the theme background** by `dim.factor` = 0.7. This applies to bodies, outlines, edges, badges
     and labels (a per-instance `dim` in the billboard shader mixes toward a `background`
     uniform). Glow is dropped on dimmed nodes. Nothing is transparent, the draw count is
     unchanged, and the dimmed set is computed once per rebuild.
  2. **Toggle.** A "Dim" button in the replay bar (`aria-pressed`), on by default. The same state
     applies to the App intents. Home and stopping the replay clear the emphasis.
  3. **Body tokens.** `body.neutral`, `body.tint` (0.08) and `body.open_recede` (0.55) replace
     the hard-coded colors. `bodyColor()` in `render/style.ts` is the single source, mirrored by
     `tokens.body_color()` in Python. Mixing is in linear light, as three.js does.
  4. **Contrast fixes** (WCAG 1.4.11, ≥ 3:1), tested in Vitest and pytest for both themes:
     - every status stroke against its own body and every open floor, and the edge color against
       every open floor;
     - the replay highlight (new token `replay.highlight`) against dimmed and undimmed neighbors.
     Token changes: dark `edge` #6E7D94 → #97A5BA, dark `status.none` #6B7689 → #8792A6, light
     `status.none` #7D8799 → #6E788A; `replay.highlight` dark #C9E8FF, light #1D4ED8 (the light
     emphasis halo #8FBCFF was 1.35:1 against light floors).
  5. Worst cases before → after:
     - light: `none` outline on its body 2.43 → 3.50; edge on the verified open floor 2.97 →
       3.98;
     - dark: edge on a closed body 1.45 → 3.70; edge on an open floor 2.11 → 4.1+.
- Performance: dispatch (5,374 nodes) on the GPU (ADR-0038 method). 59.9 fps median with dim
  on and off. First render 1.17–1.22 s (three runs), against 0.86 s in P5 on the same machine.
  The file was re-extracted with the P6.1 extractor and the cause was not isolated (issue 73).
  It is still under the 3 s target.
