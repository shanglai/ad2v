# ADR-0035: Viewer stack, and what we left out for licenses and weight

- Status: accepted (P5)
- Decisions:
  1. **Vite 7, not Vite 8.** Vite 8 depends on `lightningcss` (MPL-2.0), which the no-copyleft rule
     forbids anywhere in the npm tree. Vite 7 with Vitest 4 has no copyleft dependency.
  2. **License gate in the build.** `scripts/check-licenses.mjs`:
     - walks every installed package and evaluates SPDX expressions (OR/AND);
     - fails on GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA and OFL;
     - fails if any font file is in the build output.

     Both `npm run build` and `npm run build:demo` run it. Result: 158 packages (MIT 123,
     Apache-2.0 18, ISC 7, BSD-2-Clause 6, BSD-3-Clause 3, BlueOak-1.0.0 1).
  3. **Labels are Canvas 2D atlas billboards** drawn with the system UI font.
     - There is no SDF text library (troika) and no font asset in the build, so there is no font
       license question and the bundle is smaller.
     - three's example fonts sit in `node_modules` but are not imported; the gate reports them as
       info only.
  4. **Glow is additive ribbon shells** around verified glyphs in the dark theme, and a halo in
     the light theme. There is no bloom post-processing pass, which would cost extra render targets
     on integrated GPUs.
  5. **Screen-space ribbons** for outlines, edges and overlays.
     - Widths and dash patterns are in pixels, so the four line styles (solid, dashed, dotted,
       dash-dot) stay distinguishable at every zoom.
     - The material is double-sided; with back-face culling the ribbons were invisible.
  6. **sql.js** (MIT) runs SQL on the file in the browser. It needs `'wasm-unsafe-eval'` in the
     CSP, and nothing broader.
