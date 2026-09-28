// P5 §6: every rendered status in both themes uses the token values and the correct line style;
// the TypeScript mapping is the Python one (tests/fixtures/styles.json from tokens.py).
import { describe, expect, it } from "vitest";
import { outlineFor } from "../src/render/style";
import { DASH_PX, OVERLAY_BADGES, STATUS_STYLES, THEMES, token, type ThemeName } from "../src/theme";
import { json } from "./fixture";

const py = json<{
  statuses: Record<string, { token: string; line: string; fill: string; decoration: string; weight: string }>;
  overlays: Record<string, { glyph: string; color: string; text: string }>;
  dasharray: Record<string, string | null>;
  statusOrder: string[];
}>("styles.json");

describe("tokens", () => {
  it("mirrors the normative Python mapping exactly", () => {
    expect(STATUS_STYLES).toEqual(py.statuses);
    expect(OVERLAY_BADGES).toEqual(py.overlays);
    for (const [line, dash] of Object.entries(py.dasharray))
      expect(DASH_PX[line as keyof typeof DASH_PX].join(" ")).toBe(dash ? dash.split(" ").map(Number).join(" ") : "");
  });

  for (const name of ["dark", "light"] as ThemeName[]) {
    it(`renders every status from the ${name} tokens`, () => {
      const th = THEMES[name];
      for (const status of py.statusOrder) {
        const want = py.statuses[status]!;
        const r = outlineFor(th, name, status, true);
        expect(r.color).toBe((th.status as Record<string, { stroke: string }>)[status]!.stroke);
        expect(r.line).toBe(want.line);
        expect(r.hollow).toBe(want.fill === "hollow");
        expect(r.widthPx).toBeLessThan(want.weight === "thin" ? 2 : 4);
        expect(r.emphasis !== null).toBe(want.decoration === "emphasis");
        if (r.emphasis) {
          expect(r.emphasis.color).toBe(th.emphasis.color);
          expect(r.emphasis.additive).toBe(name === "dark"); // glow in dark, halo in light
        }
        if (want.decoration === "warning_badge") expect(r.badge).toEqual({ glyph: "!", bg: th.badge.warning, fg: th.badge.warning_text, shape: "triangle" });
        if (want.decoration === "clock_badge") expect(r.badge?.bg).toBe(th.badge.clock);
        if (want.decoration === "none" || want.decoration === "emphasis") expect(r.badge).toBeNull();
      }
      for (const ov of Object.values(OVERLAY_BADGES)) {
        expect(token(th, ov.color)).toMatch(/^#[0-9A-F]{6}$/i);
        expect(token(th, ov.text)).toMatch(/^#[0-9A-F]{6}$/i);
      }
    });
  }

  it("keeps the four line styles distinguishable", () => {
    const pats = Object.values(DASH_PX).map((p) => p.join(","));
    expect(new Set(pats).size).toBe(4);
  });
});
