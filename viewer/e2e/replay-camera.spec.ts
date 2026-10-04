// P6.1 M5: the replay camera keeps every step on screen and readable (ADR-0050).
// Fixture replay of POST /v1/reconciliations at detail levels 1 and 2, both themes: each step's
// highlighted box is >= 90% inside the viewport and >= 40 px on its smaller side.
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const DEMO = pathToFileURL(path.resolve(process.cwd(), "demo-dist", "index.html")).href;
const OUT = path.resolve(process.cwd(), "test-results", "replay-camera.json");

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

for (const theme of ["dark", "light"] as const) {
  test(`replay camera frames every step (${theme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.goto(DEMO);
    await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
    const rows = await page.evaluate(async () => {
      const app = (window as unknown as Win).__ad2v;
      const wid = app.cur.workflows.find((w: { name: string }) => w.name === "POST /v1/reconciliations").workflowId;
      await app.startReplay(wid);
      const r = app.replay;
      const out: Array<{ level: number; step: number; inside: number; minSide: number; nodes: string[] }> = [];
      const raf = () => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
      for (const want of [1, 2]) {
        const idx = r.levels.findIndex((l: { level: number }) => l.level === want);
        if (idx < 0) continue;
        r.setLevel(idx);
        for (let s = 0; s < r.coarse.length; s++) {
          app.replayTo(idx, s);
          await raf(); // LODs follow the camera on the next frame
          const step = r.current.nodeIds as string[];
          const b = app.scene.screenBox(step, true); // what is drawn: the box, or its ring
          out.push({ level: want, step: s + 1, inside: b.inside, minSide: Math.min(b.x1 - b.x0, b.y1 - b.y0), nodes: step });
        }
      }
      return out;
    });
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    const prev = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, "utf8")) : {};
    fs.writeFileSync(OUT, JSON.stringify({ ...prev, [theme]: rows }, null, 1));
    expect(rows.length).toBeGreaterThan(4);
    expect(new Set(rows.map((r) => r.level))).toEqual(new Set([1, 2]));
    for (const r of rows) {
      expect(r.inside, `level ${r.level} step ${r.step}`).toBeGreaterThanOrEqual(0.9);
      expect(r.minSide, `level ${r.level} step ${r.step}`).toBeGreaterThanOrEqual(40);
    }
  });
}
