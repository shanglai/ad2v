// Semantic level of detail from the projected footprint in pixels, with hysteresis (P5 §5):
//   < 8 px hidden · 8–40 silhouette · 40–160 detail (modifiers + label) · > 160 open interior.
// A node moves up a level at the threshold and back down only below threshold × HYSTERESIS,
// so a glyph hovering at a boundary does not flicker.

export const enum Lod {
  Hidden = 0,
  Silhouette = 1,
  Detail = 2,
  Open = 3,
}

export const THRESHOLDS = [8, 40, 160] as const; // px entering Silhouette, Detail, Open
export const HYSTERESIS = 0.8;

export function lodFor(px: number, prev: Lod | undefined): Lod {
  let up: Lod = Lod.Hidden;
  for (let i = 0; i < THRESHOLDS.length; i++) if (px >= THRESHOLDS[i]!) up = (i + 1) as Lod;
  if (prev === undefined || up >= prev) return up;
  // going down: stay at prev while px is still above prev's entry threshold × hysteresis
  let lod = prev;
  while (lod > up && px < THRESHOLDS[lod - 1]! * HYSTERESIS) lod = (lod - 1) as Lod;
  return lod;
}
