// P6.1 M6: "dim the rest" (ADR-0051). During a replay everything but the step blends toward the
// background (opaque, no alpha); the Dim toggle in the replay bar turns it off. Screenshots of the
// replay at detail levels 1 and 2 in both themes, plus the light-theme open-floor before/after pair
// (before = the P6 demo committed at HEAD: `git show HEAD:docs/reports/P5-demo.html` saved to the
// file named by AD2V_BEFORE_DEMO; the pair is skipped without it).
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const DEMO = pathToFileURL(path.resolve(process.cwd(), "demo-dist", "index.html")).href;
const BEFORE = process.env.AD2V_BEFORE_DEMO ?? "";
const SHOTS = path.resolve(process.cwd(), "..", "docs", "reports", "P6.1-screens");

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

async function open(page: Page, url: string, theme: "dark" | "light"): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.goto(url);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
}

const settle = (page: Page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r)))));

for (const theme of ["dark", "light"] as const) {
  test(`replay dims the rest and the toggle restores it (${theme})`, async ({ page }) => {
    fs.mkdirSync(SHOTS, { recursive: true });
    await open(page, DEMO, theme);
    await page.evaluate(async () => {
      const app = (window as unknown as Win).__ad2v;
      const wid = app.cur.workflows.find((w: { name: string }) => w.name === "POST /v1/reconciliations").workflowId;
      await app.startReplay(wid);
    });
    for (const level of [1, 2]) {
      const r = await page.evaluate((want) => {
        const app = (window as unknown as Win).__ad2v;
        const idx = app.replay.levels.findIndex((l: { level: number }) => l.level === want);
        app.replayTo(idx, 1);
        return { idx };
      }, level);
      expect(r.idx).toBeGreaterThanOrEqual(0);
      await settle(page);
      const s = await page.evaluate(() => {
        const app = (window as unknown as Win).__ad2v;
        const vis = [...app.scene.visibleLods().keys()] as string[];
        const step = app.replay.current.nodeIds as string[];
        return {
          dimmed: vis.filter((id) => app.scene.isDimmed(id)).length,
          visible: vis.length,
          stepDimmed: step.some((id) => app.scene.isDimmed(id)),
          pressed: document.querySelector("#dim")?.getAttribute("aria-pressed"),
        };
      });
      expect(s.pressed).toBe("true");
      expect(s.stepDimmed).toBe(false);
      expect(s.dimmed).toBeGreaterThan(0);
      expect(s.dimmed).toBeLessThan(s.visible);
      await page.screenshot({ path: path.join(SHOTS, `${theme}-replay-level${level}-dim.png`) });
    }
    await page.click("#dim");
    await settle(page);
    const off = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const vis = [...app.scene.visibleLods().keys()] as string[];
      return { dimmed: vis.filter((id) => app.scene.isDimmed(id)).length, pressed: document.querySelector("#dim")?.getAttribute("aria-pressed") };
    });
    expect(off).toEqual({ dimmed: 0, pressed: "false" });
    await page.click("#dim"); // back on, then stopping the replay clears it
    await page.evaluate(() => (window as unknown as Win).__ad2v.stopReplay());
    await settle(page);
    const after = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      return [...app.scene.visibleLods().keys()].filter((id) => app.scene.isDimmed(id)).length;
    });
    expect(after).toBe(0);
  });
}

test("light-theme open floor: before (P6) and after (P6.1)", async ({ page }) => {
  test.skip(!BEFORE || !fs.existsSync(BEFORE), "AD2V_BEFORE_DEMO not set");
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const [name, url] of [["before", pathToFileURL(BEFORE).href], ["after", DEMO]] as const) {
    await open(page, url, "light");
    await page.evaluate(() => (window as unknown as Win).__ad2v.focusByName("container:api"));
    await settle(page);
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SHOTS, `light-open-floor-${name}.png`) });
  }
});
