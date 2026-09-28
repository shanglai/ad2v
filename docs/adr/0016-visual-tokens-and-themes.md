# ADR-0016: Visual tokens and themes

- Status: accepted (P2)
- Decisions:
  1. The status channel is a **non-color signature** `(line, fill, decoration, weight)`. It is unique
     per status and tested. Color only reinforces it. That is what "readable with color removed"
     means operationally.
  2. Two statuses the prompt does not style get styles now, so every `node_status` value renders:
     `stale` (solid + clock badge, reserved for P3) and `none` (thin solid, neutral gray).
  3. The **themes are informative** JSON files under `schema/themes/` (shipped in the wheel). Only
     the status → style mapping and the contrast requirements are normative.
  4. The **light theme's verified** is a saturated outline plus a soft halo, not a glow. Glow on
     white adds no luminance contrast.
  5. `preview-tokens` writes one static HTML page with inline SVG, CSS and filter definitions, and
     no scripts or external assets. It includes a grayscale copy of the dark panel, as a visual
     proof of decision 1.
  6. Contrast is computed with the WCAG 2.x relative-luminance formula, implemented in stdlib
     Python (no dependency).
