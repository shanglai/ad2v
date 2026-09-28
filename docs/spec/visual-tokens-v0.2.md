# ad2v visual tokens, v0.2

Status: **draft**. §2 is **normative**, and §3–§4 are **informative**. Reference implementation:
`src/ad2v/tokens.py`. Palettes: `schema/themes/dark.json` and `schema/themes/light.json`. Preview:
`ad2v preview-tokens --out tokens.html`.

The glyph grammar ([`glyph-grammar-v0.2.md`](glyph-grammar-v0.2.md)) fixes **shape = kind** and
**modifiers = attributes**. This document fixes the third channel, **line / emphasis = status**
(the effective node status, format spec §6.4). The fourth channel, size = weight, is unchanged.

## 1. Principle: status survives without color

Every status has a unique **non-color signature** `(line, fill, decoration, weight)`. Color only
reinforces it. The map must stay readable in grayscale, for color-blind readers, when printed, and
when a theme is swapped. A test (`tests/test_tokens.py::test_no_two_statuses_differ_by_color_alone`)
fails if two statuses share a signature.

## 2. Status → style mapping (normative)

| status | token | line | fill | decoration | weight |
|---|---|---|---|---|---|
| `specified` | `status.specified` | dotted | tinted | none | regular |
| `implemented` | `status.implemented` | solid | tinted | none | regular |
| `verified` | `status.verified` | solid | tinted | **emphasis**: glow (dark) / halo (light) | regular |
| `drift` | `status.drift` | solid | tinted | **warning badge** (triangle with "!") | regular |
| `orphan` | `status.orphan` | dashed | tinted | none | regular |
| `missing` | `status.missing` | dotted | **hollow** (no fill) | none | regular |
| `needs_review` | `status.needs_review` | dash-dot | tinted | none | regular |
| `stale` (reserved, P3) | `status.stale` | solid | tinted | clock badge | regular |
| `none` (no coverage applies) | `status.none` | solid | tinted | none | **thin** |

Reference dash patterns at 2.2 px stroke: dotted `1.5 4.5` (round caps), dashed `7 5`,
dash-dot `9 4 1.5 4`. A viewer MAY scale them with zoom, but MUST keep the four patterns
distinguishable. "Tinted" fills use the status's `fill` color from the theme. "Hollow" means no fill.

A theme is a JSON object with at least: `background`, `surface`, `grid`, `text`, `text_muted`,
`edge`, `status.<status>.{stroke, fill}` for every status, `emphasis` (`kind`: `glow` or `halo`, plus
its parameters), `badge.{warning, warning_text, clock}`, and `severity_ramp` (5 colors, low → high,
for `attrs.severity` buckets).

**Contrast requirements (normative, tested for every shipped theme):** every status stroke, edge
color, badge color and severity-ramp color against `background` (and `surface` for strokes) ≥ 3:1
(WCAG 2.x non-text contrast). `text`, `text_muted` and the badge glyph ≥ 4.5:1.

## 3. Dark theme (informative)

Near-black background (`#0A0E16`). The spec/implemented/verified family is blue: `specified` is a
muted blue, `implemented` a clear blue, and `verified` the brightest blue plus a **bloom glow** (a
Gaussian blur of the outline, flooded with `#6FC3FF`, drawn under the stroke). `drift` is amber,
`orphan` red, `needs_review` violet, `missing` blue-gray, and `stale` and `none` are neutral grays.

## 4. Light theme (informative): verified without glow

Off-white background (`#F7F8FA`). **Glow disappears on white**: a light blur on a light background
adds almost no luminance contrast. So `verified` is drawn as a **saturated dark-blue outline
(`#0B47B8`, 7.6:1) that is slightly thicker than `implemented`, over a soft halo** (a 7 px, 60%-opacity
`#8FBCFF` stroke under the outline). The halo gives the same "lit" reading as the dark theme's
bloom, and the outline alone still carries the status, because solid + emphasis differs from solid.
The other colors are the dark theme's hues shifted darker until they reach ≥ 3:1 on off-white. The
warning badge uses a darker amber (`#9A5800`) so that its white "!" reaches 5.6:1.

## 5. Measured contrast (shipped palettes)

| status | dark stroke on bg | light stroke on bg |
|---|---|---|
| specified | 6.29 | 4.36 |
| implemented | 6.99 | 5.47 |
| verified | 11.75 | 7.58 |
| drift | 9.46 | 4.67 |
| orphan | 6.58 | 5.29 |
| missing | 6.89 | 4.89 |
| needs_review | 7.72 | 5.92 |
| stale | 7.50 | 4.49 |
| none | 4.21 | 3.41 |
| text / text_muted | 16.26 / 8.71 | 16.18 / 6.76 |
