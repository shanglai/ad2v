// P5 §10: the demo in both themes: system view, entered container, risky loop, replay at two
// detail levels (same playhead), effective status with the AI badge, and the diff overlay.
// Saves 12 screenshots to docs/reports/P5-screens/.
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const DEMO = pathToFileURL(path.resolve(process.cwd(), "demo-dist", "index.html")).href;
const SHOTS = path.resolve(process.cwd(), "..", "docs", "reports", "P5-screens");

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

async function open(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" }); // cuts instead of flights
  await page.goto(DEMO);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function settle(page: Page): Promise<void> {
  await page.waitForTimeout(700); // the label pass runs once the camera has settled
}

async function shot(page: Page, theme: string, n: number, name: string): Promise<void> {
  await settle(page);
  await page.screenshot({ path: path.join(SHOTS, `${theme}-${n}-${name}.png`) });
}

for (const theme of ["dark", "light"] as const) {
  test(`viewer tour (${theme})`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await open(page, theme);

    // 1. system view
    await shot(page, theme, 1, "system");
    const roots = await page.evaluate(() => (window as unknown as Win).__ad2v.scene.visibleLods().size);
    expect(roots).toBeGreaterThan(5);

    // 2. entered container:api at interior LOD
    await page.evaluate(() => (window as unknown as Win).__ad2v.focusByName("container:api"));
    await shot(page, theme, 2, "container-api");
    const apiLod = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const id = app.cur.nodes.find((n: { qname: string }) => n.qname === "container:api").id;
      return app.scene.visibleLods().get(id);
    });
    expect(apiLod).toBe(3); // Lod.Open

    // 3. matching.py with the risky loop visible
    await page.evaluate(() => (window as unknown as Win).__ad2v.focusByName("api/recon_api/matching.py"));
    await shot(page, theme, 3, "matching-risky-loop");
    const loopVisible = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const loop = app.cur.nodes.find((n: { kind: string; qname: string }) => n.kind === "loop" && n.qname.includes("match_batch"));
      return app.scene.visibleLods().has(loop.id);
    });
    expect(loopVisible).toBe(true);
    await expect(page.locator(".card.node").last()).toContainText("matching.py");

    // 4. replay of POST /v1/reconciliations at two detail levels, same playhead
    await page.evaluate(() => (window as unknown as Win).__ad2v.scene.home(true));
    const wid = await page.evaluate(() => (window as unknown as Win).__ad2v.cur.workflows.find((w: { name: string }) => w.name === "POST /v1/reconciliations").workflowId);
    await page.evaluate((w) => (window as unknown as Win).__ad2v.startReplay(w), wid);
    await page.waitForSelector("#replaybar:not(.hidden)");
    const a = await page.evaluate(() => (window as unknown as Win).__ad2v.replayTo(0, 2));
    await settle(page);
    const b = await page.evaluate(() => (window as unknown as Win).__ad2v.setReplayLevel(1));
    expect(b.playhead).toBe(a.playhead); // re-projection never moves the playhead
    expect(b.level).toBeGreaterThan(a.level);
    await expect(page.locator(".card.step").last()).toContainText(/level/);
    await shot(page, theme, 4, "replay-two-levels");
    await page.evaluate(() => (window as unknown as Win).__ad2v.stopReplay());

    // 5. effective status: REQ-003 drift from the (fake) judge, with the AI badge
    await page.click("#toggle-effective");
    await expect(page.locator("#toggle-effective")).toContainText("Effective status");
    await page.evaluate(() => (window as unknown as Win).__ad2v.focusByName("REQ-003", false));
    await expect(page.locator(".card.node").last()).toContainText("effective (AI): drift");
    await shot(page, theme, 5, "effective-req003-ai-drift");
    await page.click("#toggle-effective");

    // 6. diff overlay between history epochs 2 and 3
    await page.evaluate(() => (window as unknown as Win).__ad2v.compare(2, 3));
    await page.evaluate(() => (window as unknown as Win).__ad2v.scene.home(true));
    await expect(page.locator(".card.changes").last()).toContainText("verified → stale");
    await shot(page, theme, 6, "diff-epoch-2-3");

    expect(errors).toEqual([]);
  });
}
