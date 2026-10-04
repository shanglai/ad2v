// P5 §6: every rendered status in both themes uses the token values and the correct line style;
// the TypeScript mapping is the Python one (tests/fixtures/styles.json from tokens.py).
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { bodyColor, dimmed, outlineFor } from "../src/render/style";
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

  // P6.1 (ADR-0051): edges and outlines read against the open-container floor, and a replay step
  // reads against its dimmed neighbors, in both themes (WCAG 1.4.11 non-text contrast >= 3:1).
  const lum = (c: THREE.Color): number => {
    const s = new THREE.Color(`#${c.getHexString()}`); // what is on screen, quantized to 8 bit sRGB
    return 0.2126 * s.r + 0.7152 * s.g + 0.0722 * s.b; // .r/.g/.b are linear in the working space
  };
  const ratio = (a: THREE.Color | string, b: THREE.Color | string): number => {
    const [x, y] = [lum(new THREE.Color(a)), lum(new THREE.Color(b))].sort((p, q) => q - p);
    return (x! + 0.05) / (y! + 0.05);
  };
  for (const name of ["dark", "light"] as ThemeName[]) {
    it(`keeps edges and outlines >= 3:1 on bodies and open floors (${name})`, () => {
      const th = THEMES[name];
      const strokes = py.statusOrder.map((s) => [s, (th.status as Record<string, { stroke: string }>)[s]!.stroke] as const);
      const floors = py.statusOrder.map((s) => bodyColor(th, s, true));
      for (const [s, stroke] of strokes) {
        expect(ratio(stroke, bodyColor(th, s, false)), `${s} on its body`).toBeGreaterThanOrEqual(3);
        for (const f of floors) expect(ratio(stroke, f), `${s} on a floor`).toBeGreaterThanOrEqual(3);
      }
      for (const f of floors) expect(ratio(th.edge, f), "edge on a floor").toBeGreaterThanOrEqual(3);
    });

    it(`dims opaquely and keeps the step >= 3:1 against dimmed neighbors (${name})`, () => {
      const th = THEMES[name];
      expect(th.dim.factor).toBe(0.7);
      const bg = new THREE.Color(th.background);
      const d = dimmed(th, th.edge);
      expect(d.equals(new THREE.Color(th.edge).lerp(bg, 0.7))).toBe(true); // a color, not an alpha
      const neighbors = py.statusOrder.flatMap((s) => [
        dimmed(th, bodyColor(th, s, false)),
        dimmed(th, bodyColor(th, s, true)),
        dimmed(th, (th.status as Record<string, { stroke: string }>)[s]!.stroke),
        dimmed(th, th.edge),
        bodyColor(th, s, false), // the step's own body and the container it sits in stay undimmed
        bodyColor(th, s, true),
      ]);
      for (const n of neighbors) expect(ratio(th.replay.highlight, n), "step highlight").toBeGreaterThanOrEqual(3);
      for (const s of py.statusOrder) {
        const stroke = (th.status as Record<string, { stroke: string }>)[s]!.stroke;
        for (const ns of py.statusOrder) expect(ratio(stroke, dimmed(th, bodyColor(th, ns, true))), `${s} on a dimmed floor`).toBeGreaterThanOrEqual(3);
      }
    });
  }
});
