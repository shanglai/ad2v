// Visual tokens: the normative status → style mapping (a mirror of tokens.py, compared in a test)
// and the informative palettes, read straight from schema/themes/*.json. All colors come from here.
import darkJson from "../../schema/themes/dark.json";
import lightJson from "../../schema/themes/light.json";

export type LineStyle = "solid" | "dotted" | "dashed" | "dash_dot";
export type ThemeName = "dark" | "light";
export type ThemeChoice = ThemeName | "system";

export interface StatusStyle {
  token: string;
  line: LineStyle;
  fill: "tinted" | "hollow";
  decoration: "none" | "emphasis" | "warning_badge" | "clock_badge";
  weight: "regular" | "thin";
}

export const STATUS_STYLES: Record<string, StatusStyle> = {
  specified: { token: "status.specified", line: "dotted", fill: "tinted", decoration: "none", weight: "regular" },
  implemented: { token: "status.implemented", line: "solid", fill: "tinted", decoration: "none", weight: "regular" },
  verified: { token: "status.verified", line: "solid", fill: "tinted", decoration: "emphasis", weight: "regular" },
  drift: { token: "status.drift", line: "solid", fill: "tinted", decoration: "warning_badge", weight: "regular" },
  orphan: { token: "status.orphan", line: "dashed", fill: "tinted", decoration: "none", weight: "regular" },
  missing: { token: "status.missing", line: "dotted", fill: "hollow", decoration: "none", weight: "regular" },
  needs_review: { token: "status.needs_review", line: "dash_dot", fill: "tinted", decoration: "none", weight: "regular" },
  stale: { token: "status.stale", line: "solid", fill: "tinted", decoration: "clock_badge", weight: "regular" },
  none: { token: "status.none", line: "solid", fill: "tinted", decoration: "none", weight: "thin" },
};

/** Overlay badges: the glyph is the non-color signature (visual tokens §6, tokens.OVERLAY_BADGES). */
export const OVERLAY_BADGES: Record<string, { glyph: string; color: string; text: string }> = {
  ai: { glyph: "AI", color: "badge.ai", text: "badge.ai_text" },
  suggestion: { glyph: "?", color: "badge.suggestion", text: "badge.suggestion_text" },
  diff_added: { glyph: "+", color: "diff.added", text: "diff.badge_text" },
  diff_removed: { glyph: "−", color: "diff.removed", text: "diff.badge_text" },
  diff_renamed: { glyph: "↺", color: "diff.renamed", text: "diff.badge_text" },
  diff_transition: { glyph: "→", color: "diff.transition", text: "diff.badge_text" },
};

/** Screen-space dash patterns in px at a 2.2 px stroke (visual tokens §2): [on, off, on, off]. */
export const DASH_PX: Record<LineStyle, number[]> = {
  solid: [],
  dotted: [1.5, 4.5],
  dashed: [7, 5],
  dash_dot: [9, 4, 1.5, 4],
};

export type Theme = Omit<typeof darkJson, "emphasis"> & {
  emphasis: { kind: string; color: string; opacity: number; radius?: number; width?: number };
};
export const THEMES: Record<ThemeName, Theme> = { dark: darkJson as Theme, light: lightJson as unknown as Theme };

export function token(theme: Theme, dotted: string): string {
  let cur: unknown = theme;
  for (const p of dotted.split(".")) cur = (cur as Record<string, unknown>)[p];
  return String(cur);
}

export function statusStyle(status: string): StatusStyle {
  return STATUS_STYLES[status] ?? STATUS_STYLES.none!;
}

export function statusColors(theme: Theme, status: string): { stroke: string; fill: string } {
  const s = (theme.status as Record<string, { stroke: string; fill: string }>)[status];
  return s ?? theme.status.none;
}

export function resolveTheme(choice: ThemeChoice): ThemeName {
  if (choice !== "system") return choice;
  const dark = typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
  return dark ? "dark" : "light";
}

const KEY = "ad2v.theme";
export function loadThemeChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}
export function saveThemeChoice(c: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, c);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}
