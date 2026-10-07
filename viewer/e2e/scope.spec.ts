// P8.1 (ADR-0066): code in a language no active extractor reads is shown as not_evaluable.
// The polyglot fixture (Python API + TypeScript web client) is extracted and served by a real
// `ad2v view`; the legend explains the status and a TypeScript module's card names its language.
// Screenshots: docs/reports/P8.1-screens/.
import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const SHOTS = path.join(ROOT, "docs", "reports", "P8.1-screens");
type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

let proc: ChildProcess | null = null;
let url = "";

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ad2v-scope-"));
  const file = path.join(tmp, "polyglot.ad2v");
  const made = spawnSync(PY, ["-m", "ad2v", "extract", "--repo", path.join(ROOT, "fixtures", "polyglot"), "--out", file], { encoding: "utf-8" });
  expect(made.status, made.stderr).toBe(0);
  expect(made.stdout).toContain("typescript 2 file(s); shown as not_evaluable");
  proc = spawn(PY, ["-m", "ad2v", "view", file, "--no-browser", "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
  url = await new Promise<string>((resolve, reject) => {
    let buf = "";
    proc!.stdout!.on("data", (d) => {
      buf += String(d);
      const m = /(http:\/\/127\.0\.0\.1:\d+\/\S+)/.exec(buf);
      if (m) resolve(m[1]!);
    });
    proc!.on("exit", (c) => reject(new Error(`ad2v view exited ${c}`)));
    setTimeout(() => reject(new Error(`no URL: ${buf}`)), 30_000);
  });
});

test.afterAll(() => {
  proc?.kill();
});

async function open(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.goto(url);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
}

for (const theme of ["dark", "light"] as const) {
  test(`not_evaluable: legend, card note and map (${theme})`, async ({ page }) => {
    await open(page, theme);
    await page.locator("#toggle-legend").click();
    const legend = page.locator("#legend");
    await expect(legend).toBeVisible();
    await expect(legend.locator('li[data-status="not_evaluable"]')).toContainText("no active extractor reads");
    await expect(legend.locator("li")).toHaveCount(10);
    await page.mouse.move(2, 2);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(SHOTS, `${theme}-1-legend.png`) });
    await page.locator("#legend-close").click();
    await expect(legend).toHaveCount(0);

    const id = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const row = app.cur.nodes.find((n: { qname: string }) => n.qname === "web/src/cart.ts");
      app.enter(row.parentId, false);
      app.select(row.id, true, true);
      return row.id as string;
    });
    expect(id).toMatch(/^n_/);
    const card = page.locator("#timeline .card.node").last();
    await expect(card.locator(".statuses")).toContainText("not_evaluable");
    await expect(card.locator("#scope-note")).toContainText("in typescript, which no active extractor reads");
    await page.mouse.move(2, 2);
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(SHOTS, `${theme}-2-typescript-module.png`) });

    const req = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const r = app.cur.nodes.find((n: { qname: string }) => n.qname === "REQ-002");
      return app.cur.statusN.get(r.id)?.status as string;
    });
    expect(req).toBe("not_evaluable");
  });
}
