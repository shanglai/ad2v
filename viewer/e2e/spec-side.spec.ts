// P9 M4 (ADR-0072): the spec side of the map. Scenario steps are not drawn (they are listed, in
// order, in their scenario's card), a scenario shows the statuses of the requirements it
// references, labels read `<id> · <title>`, and non-functional requirements carry an NFR badge.
// Two files, each extracted and served by a real `ad2v view`: payments-recon (English) and
// brownfield-es (Spanish, with the manifest `ad2v init` proposes). Screenshots: docs/reports/P9-screens/.
import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const SHOTS = path.join(ROOT, "docs", "reports", "P9-screens");
type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

const procs: ChildProcess[] = [];
const urls: Record<string, string> = {};
let tmp = "";

function run(args: string[]): string {
  const r = spawnSync(PY, ["-m", "ad2v", ...args], { encoding: "utf-8" });
  expect(r.status, r.stderr).toBe(0);
  return r.stdout;
}

async function serve(file: string): Promise<string> {
  const proc = spawn(PY, ["-m", "ad2v", "view", file, "--no-browser", "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
  procs.push(proc);
  return new Promise<string>((resolve, reject) => {
    let buf = "";
    proc.stdout!.on("data", (d) => {
      buf += String(d);
      const m = /(http:\/\/127\.0\.0\.1:\d+\/\S+)/.exec(buf);
      if (m) resolve(m[1]!);
    });
    proc.on("exit", (c) => reject(new Error(`ad2v view exited ${c}`)));
    setTimeout(() => reject(new Error(`no URL: ${buf}`)), 30_000);
  });
}

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ad2v-spec-side-"));
  const pr = path.join(ROOT, "fixtures", "payments-recon");
  run(["extract", "--repo", pr, "--out", path.join(tmp, "pr.ad2v"), "--test-results", path.join(pr, "test-results", "junit.xml")]);
  const bf = path.join(ROOT, "fixtures", "brownfield-es");
  const manifest = path.join(tmp, "bf.yaml");
  run(["init", "--repo", bf, "--write", manifest]);
  // the one value init cannot know, filled in as the human would
  fs.writeFileSync(manifest, fs.readFileSync(manifest, "utf-8").replace('"settings.API_PREFIX": ""', '"settings.API_PREFIX": "/api/v1"'));
  run(["extract", "--repo", bf, "--manifest", manifest, "--out", path.join(tmp, "bf.ad2v")]);
  urls.pr = await serve(path.join(tmp, "pr.ad2v"));
  urls.bf = await serve(path.join(tmp, "bf.ad2v"));
});

test.afterAll(async () => {
  for (const p of procs) p.kill();
  await new Promise((r) => setTimeout(r, 300)); // let the servers release the files (Windows)
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

async function open(page: Page, which: "pr" | "bf", theme: "dark" | "light"): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.goto(urls[which]!);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
}

/** Enter the node's parent and select it (card + fly); returns its id. */
async function show(page: Page, qname: string): Promise<string> {
  return page.evaluate((q) => {
    const app = (window as unknown as Win).__ad2v;
    const row = app.cur.nodes.find((n: { qname: string }) => n.qname === q);
    if (row.parentId) app.enter(row.parentId, false);
    app.select(row.id, true, true);
    return row.id as string;
  }, qname);
}

async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(2, 2);
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(SHOTS, name) });
}

const SCENARIO = "features/reconciliation.feature::Statement reconciliation::Start a reconciliation run";

for (const theme of ["dark", "light"] as const) {
  test(`spec side, payments-recon (${theme})`, async ({ page }) => {
    await open(page, "pr", theme);
    const counts = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const steps = app.cur.nodes.filter((n: { kind: string }) => n.kind === "scenario_step");
      const drawn = steps.filter((n: { id: string }) => app.cur.tree.nodes.has(n.id));
      const notNone = steps.filter((n: { id: string }) => (app.cur.statusN.get(n.id)?.status ?? "none") !== "none");
      return { steps: steps.length, drawn: drawn.length, notNone: notNone.length };
    });
    expect(counts.steps).toBeGreaterThan(0);
    expect(counts).toMatchObject({ drawn: 0, notNone: 0 }); // in the graph, off the map, no status

    await show(page, SCENARIO);
    let card = page.locator("#timeline .card.node").last();
    await expect(card.locator("h3")).toContainText("Start a reconciliation run [REQ-001, REQ-002]");
    const steps = card.locator("#scenario-steps li");
    expect(await steps.count()).toBeGreaterThanOrEqual(3);
    await expect(steps.first().locator(".kw")).toHaveText("Given");
    await expect(card.locator(".reasons")).toContainText("via_spec_ref");
    const [sc, reqs] = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      const st = (q: string): string => app.cur.statusN.get(app.cur.nodes.find((n: { qname: string }) => n.qname === q).id)?.status;
      return [st("features/reconciliation.feature::Statement reconciliation::Start a reconciliation run"), [st("REQ-001"), st("REQ-002")]];
    });
    expect(reqs).toContain(sc); // the scenario rolls up the requirements it references (worst first)
    await shot(page, `${theme}-1-payments-recon-scenario.png`);

    await show(page, "REQ-001");
    card = page.locator("#timeline .card.node").last();
    await expect(card.locator("h3")).toContainText("REQ-001 · Start a reconciliation run");
    await show(page, "CMP-001");
    card = page.locator("#timeline .card.node").last();
    await expect(card.locator("h3")).toContainText("CMP-001 · Reconciliation API");
    await shot(page, `${theme}-2-payments-recon-component.png`);

    // spec scenarios are offered for replay; a step's text is the step card
    const opt = page.locator('#workflows optgroup[label="Spec scenarios"] option', { hasText: "Start a reconciliation run" });
    await expect(opt).toHaveCount(1);
    await page.locator("#workflows").selectOption(await opt.getAttribute("value") as string);
    await expect(page.locator("#timeline .card.step").last()).toContainText("Given");
    await shot(page, `${theme}-3-payments-recon-replay.png`);
  });

  test(`spec side, brownfield-es (${theme})`, async ({ page }) => {
    await open(page, "bf", theme);
    await show(page, "RNF-001");
    let card = page.locator("#timeline .card.node").last();
    await expect(card.locator("#nfr-badge")).toHaveText("NFR");
    await expect(card.locator(".nfr-note")).toContainText("Non-functional requirement");
    await expect(card.locator("h3")).toContainText("RNF-001 · ");
    await shot(page, `${theme}-4-brownfield-nfr.png`);

    const sc = await page.evaluate(() => {
      const app = (window as unknown as Win).__ad2v;
      return app.cur.nodes.find((n: { kind: string; refs: string[] }) => n.kind === "scenario" && n.refs.length).qname as string;
    });
    await show(page, sc);
    card = page.locator("#timeline .card.node").last();
    await expect(card.locator("h3")).toContainText("[RF-");
    const kws = await card.locator("#scenario-steps .kw").allTextContents();
    expect(kws).toEqual(expect.arrayContaining(["Cuando", "Entonces"]));
    await shot(page, `${theme}-5-brownfield-scenario.png`);

    await show(page, "RF-007");
    card = page.locator("#timeline .card.node").last();
    await expect(card.locator(".statuses")).toContainText("not_evaluable");
    await expect(card.locator("#scope-note")).toContainText("component Frontend");
    await expect(card.locator("#scope-note")).toContainText("typescript");
    await shot(page, `${theme}-6-brownfield-component-out-of-scope.png`);
  });
}
