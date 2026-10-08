// P10 M6 (ADR-0079): the Architecture tab. The brownfield fixture is extracted with the manifest
// `ad2v init` proposes (infra_root: [infra]) and two plans (prod, dev), and served by a real
// `ad2v view`. Checks: the C4 view per environment, infra statuses as line styles, the element card,
// click-through to the map and back (selection sync), infra badges on the map.
// Screenshots: docs/reports/P10-screens/.
import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const SHOTS = path.join(ROOT, "docs", "reports", "P10-screens");
type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

let proc: ChildProcess | null = null;
let url = "";
let tmp = "";

function run(args: string[]): string {
  const r = spawnSync(PY, ["-m", "ad2v", ...args], { encoding: "utf-8" });
  expect(r.status, r.stderr).toBe(0);
  return r.stdout;
}

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ad2v-arch-"));
  const bf = path.join(ROOT, "fixtures", "brownfield-es");
  const manifest = path.join(tmp, "bf.yaml");
  run(["init", "--repo", bf, "--write", manifest]);
  fs.writeFileSync(manifest, fs.readFileSync(manifest, "utf-8").replace('"settings.API_PREFIX": ""', '"settings.API_PREFIX": "/api/v1"'));
  const plans = path.join(ROOT, "fixtures", "infra", "brownfield-es");
  const out = run(["extract", "--repo", bf, "--manifest", manifest, "--out", path.join(tmp, "bf.ad2v"),
    "--infra-plan", `prod=${path.join(plans, "prod.json")}`, "--infra-plan", `dev=${path.join(plans, "dev.json")}`]);
  expect(out).toContain("Infra (dev, prod)");
  proc = spawn(PY, ["-m", "ad2v", "view", path.join(tmp, "bf.ad2v"), "--no-browser", "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
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

test.afterAll(async () => {
  proc?.kill();
  await new Promise((r) => setTimeout(r, 300));
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

async function open(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.goto(url);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
}

async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(2, 2);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOTS, name) });
}

const el = (page: Page, name: string) => page.locator(`#architecture g.c4-el`, { has: page.locator("text", { hasText: name }) }).first();

for (const theme of ["dark", "light"] as const) {
  test(`architecture tab, environments, card and click-through (${theme})`, async ({ page }) => {
    await open(page, theme);
    await page.locator("#tab-arch").click();
    await expect(page.locator("#architecture svg.c4")).toBeVisible();
    // environments: dev first (no `default`), then prod
    await expect(page.locator("#infra-env")).toHaveValue("dev");
    await expect(el(page, "conciliacion-backend-dev")).toHaveAttribute("data-infra", "in_use");
    await expect(el(page, "frontend")).toHaveAttribute("data-infra", "undeployed"); // count = 0 in dev
    await expect(el(page, "worker")).toHaveAttribute("data-infra", "undeployed");
    await shot(page, `${theme}-1-architecture-dev.png`);

    await page.locator("#infra-env").selectOption("prod");
    await expect(el(page, "conciliacion-frontend")).toHaveAttribute("data-kind", "static_site");
    await expect(el(page, "conciliacion-archivo")).toHaveAttribute("data-infra", "infra_orphan");
    const wires = page.locator("#architecture g.c4-rel[data-kind='wires']");
    expect(await wires.count()).toBe(2);
    await expect(wires.first().locator("title")).toContainText(/DATABASE_URL|EVENTS_TOPIC/);
    await shot(page, `${theme}-2-architecture-prod.png`);

    await el(page, "conciliacion-backend").click();
    const card = page.locator("#timeline .c4-card").last();
    await expect(card).toContainText("Runs: backend");
    await expect(card.locator("#c4-unwired")).toContainText("EXPORT_BUCKET");
    await expect(card.locator("#c4-infra-status")).toContainText("prod");
    await shot(page, `${theme}-3-architecture-card.png`);

    // click-through to the map, the selection follows; and back
    await card.locator("button[data-node]").first().click();
    await expect(page.locator("#architecture")).toBeHidden();
    const sel = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      return app.cur.byId.get(app.selection)?.qname as string;
    });
    expect(sel).toBe("container:backend");
    await page.locator("#toggle-infra").click();
    const badge = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const id = app.cur.nodes.find((n: { qname: string }) => n.qname === "container:worker").id;
      return app.mapLabel(id) as string;
    });
    expect(badge.startsWith("∅☁")).toBe(true);
    await shot(page, `${theme}-4-map-infra-badges.png`);
    await page.locator("#tab-arch").click();
    await expect(page.locator("#architecture g.c4-el.selected")).toHaveCount(1);
  });
}
