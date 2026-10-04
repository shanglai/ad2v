// P7 M5 (ADR-0061): viewer UX v2 on the demo: a replay step hidden at the current LOD says
// "inside <ancestor>" and "zoom to step" makes it visible (issue 71); the suggestions toggle shows
// its count; the edge mode switch declutters; portal chips are one per destination; an open
// container lists its contents in the panel.
import { expect, test } from "@playwright/test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const DEMO = pathToFileURL(path.resolve(process.cwd(), "demo-dist", "index.html")).href;
type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(DEMO);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
});

test("a replay step hidden at this LOD offers 'zoom to step' (issue 71)", async ({ page }) => {
  const found = await page.evaluate(async () => {
    const app = (window as unknown as Win).__ad2v;
    const wid = app.cur.workflows.find((w: { name: string }) => w.name === "POST /v1/reconciliations").workflowId;
    await app.startReplay(wid);
    const r = app.replay;
    for (let lv = r.levels.length - 1; lv >= 0; lv--) {
      r.setLevel(lv);
      for (let s = 0; s < r.coarse.length; s++) {
        app.scene.home(true);
        app.replayTo(lv, s);
        await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
        app.replayTo(lv, s); // the step card is written for what is visible now
        if (document.querySelector("#timeline .card.step:last-of-type #zoom-to-step")) return { lv, s, ids: r.current.nodeIds };
      }
    }
    return null;
  });
  test.skip(found === null, "no replay step of the demo is hidden at its framed LOD");
  const hidden = await page.evaluate((ids: string[]) => ids.filter((i) => !(window as unknown as Win).__ad2v.scene.visibleLods().has(i)), found!.ids);
  expect(hidden.length).toBeGreaterThan(0);
  await expect(page.locator("#timeline .card.step").last().locator("#step-inside")).toContainText("inside ");
  await page.locator("#timeline .card.step").last().locator("#zoom-to-step").click();
  await page.waitForFunction((ids: string[]) => ids.some((i) => (window as unknown as Win).__ad2v.scene.visibleLods().has(i)), hidden, { timeout: 10_000 });
});

test("suggestions count, edge modes, merged portals and contents list", async ({ page }) => {
  await expect(page.locator("#sug-count")).toHaveText(/^[1-9]\d*$/);
  const all = await page.evaluate(() => (window as unknown as Win).__ad2v.scene.edgeStats.visible);
  await page.selectOption("#edge-mode", "selection");
  await page.waitForFunction(() => (window as unknown as Win).__ad2v.scene.edgeStats.visible === 0);
  await page.selectOption("#edge-mode", "aggregated");
  await page.waitForFunction((n: number) => {
    const s = (window as unknown as Win).__ad2v.scene.edgeStats;
    return s.visible > 0 && s.visible <= n;
  }, all);
  await page.selectOption("#edge-mode", "all");
  await page.evaluate(() => (window as unknown as Win).__ad2v.focusByName("container:api"));
  await page.waitForTimeout(300);
  const chips = await page.locator(".portal").allTextContents();
  expect(new Set(chips).size).toBe(chips.length); // one chip per destination
  expect(chips.length).toBeGreaterThan(0);
  const card = page.locator("#timeline section.card.node").last();
  await expect(card.locator("summary", { hasText: /^Contents \(\d+\)$/ })).toBeVisible();
  const first = card.locator("ul.children li button").first();
  const name = (await first.textContent())!;
  await first.click();
  await expect(page.locator("#timeline section.card.node").last().locator("h3")).toContainText(name);
});
