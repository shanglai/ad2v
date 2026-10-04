// What the renderer draws for a status: the single place where tokens become render parameters,
// so a test can assert every status in both themes (visual tokens §2, P5 §6).
import * as THREE from "three";
import { statusColors, statusStyle, type LineStyle, type Theme, type ThemeName } from "../theme";

export interface OutlineRender {
  color: string; // the status stroke token
  line: LineStyle; // the normative line style
  widthPx: number;
  hollow: boolean;
  emphasis: { color: string; widthPx: number; alpha: number; additive: boolean } | null;
  badge: { glyph: string; bg: string; fg: string; shape: "round" | "triangle" } | null;
}

export const STROKE_PX = { detail: 2.2, far: 1.6 };

export function outlineFor(theme: Theme, name: ThemeName, status: string, detail: boolean): OutlineRender {
  const style = statusStyle(status);
  const colors = statusColors(theme, status);
  const regular = detail ? STROKE_PX.detail : STROKE_PX.far;
  let widthPx = regular;
  if (style.weight === "thin") widthPx = regular * 0.55;
  // light theme: verified is a slightly thicker saturated outline over a halo (visual tokens §4)
  if (style.decoration === "emphasis" && name === "light") widthPx = regular * 1.3;
  const emphasis =
    style.decoration === "emphasis"
      ? {
          color: theme.emphasis.color,
          widthPx: name === "dark" ? 12 : 8,
          alpha: theme.emphasis.opacity,
          additive: theme.emphasis.kind === "glow",
        }
      : null;
  const badge =
    style.decoration === "warning_badge"
      ? { glyph: "!", bg: theme.badge.warning, fg: theme.badge.warning_text, shape: "triangle" as const }
      : style.decoration === "clock_badge"
        ? { glyph: "◷", bg: theme.badge.clock, fg: theme.background, shape: "round" as const }
        : null;
  return { color: colors.stroke, line: style.line, widthPx, hollow: style.fill === "hollow", emphasis, badge };
}

/** A glyph body (P6.1, ADR-0051): a neutral slab lightly tinted toward its status; an open slab
 *  recedes toward the background so its children read first. Hollow (missing) is the background.
 *  Tokens `body.*`; mixing is in three.js's linear working space, exactly as the scene draws it. */
export function bodyColor(theme: Theme, status: string, open: boolean): THREE.Color {
  const bg = new THREE.Color(theme.background);
  const col = statusStyle(status).fill === "hollow"
    ? bg.clone()
    : new THREE.Color(theme.body.neutral).lerp(new THREE.Color(statusColors(theme, status).stroke), theme.body.tint);
  if (open) col.lerp(bg, theme.body.open_recede);
  return col;
}

/** "Dim the rest" (P6.1, ADR-0051): opaque, a blend toward the background by `dim.factor`; no alpha. */
export function dimmed(theme: Theme, color: THREE.Color | string): THREE.Color {
  return new THREE.Color(color).lerp(new THREE.Color(theme.background), theme.dim.factor);
}
