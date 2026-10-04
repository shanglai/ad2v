// P7 M4: the viewer's own chat against a real `ad2v view --chat` server with the fake provider (no
// model is called). Per theme: the panel and meter come up; an unscripted question is answered with
// grounded citation chips; a scripted turn calls ad2v_show and the map follows (focus + dim); the
// answer's Markdown is rendered safely (no raw HTML, no outside links); a chip pins the node.
// The static demo (no server) keeps the input disabled with the enabling command.
import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const DEMO_FILE = path.resolve(process.cwd(), "tests", "fixtures", "demo.ad2v");
const DEMO_HTML = pathToFileURL(path.resolve(process.cwd(), "demo-dist", "index.html")).href;
const SHOTS = path.join(ROOT, "docs", "reports", "P7-screens");
const SCRIPTED = "Walk me through starting a reconciliation run.";

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean } }; // eslint-disable-line @typescript-eslint/no-explicit-any

let proc: ChildProcess | null = null;
let url = "";

test.beforeAll(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ad2v-chat-"));
  const file = path.join(tmp, "demo.ad2v");
  fs.copyFileSync(DEMO_FILE, file);
  const manifest = path.join(tmp, "ad2v.yaml");
  fs.writeFileSync(manifest, "llm:\n  provider: fake\n  output_language: auto\n  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}\n");
  expect(spawnSync(PY, ["-c", "import ad2v"]).status).toBe(0);
  proc = spawn(PY, ["-m", "ad2v", "view", file, "--no-browser", "--port", "0", "--chat", "--manifest", manifest,
    "--replay-dir", path.resolve(process.cwd(), "e2e", "chat-recordings")], { stdio: ["ignore", "pipe", "pipe"] });
  url = await new Promise<string>((resolve, reject) => {
    let buf = "";
    proc!.stdout!.on("data", (d) => {
      buf += String(d);
      const m = /(http:\/\/127\.0\.0\.1:\d+\/\S+#chat=\S+)/.exec(buf);
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
  await expect(page.locator("#chat-input")).toBeEnabled({ timeout: 15_000 });
}

async function ask(page: Page, q: string): Promise<void> {
  const before = await page.locator(".chat-turn").count();
  await page.fill("#chat-input", q);
  await page.press("#chat-input", "Control+Enter");
  await expect(page.locator(".chat-turn")).toHaveCount(before + 1);
  await expect(page.locator(".chat-turn").last().locator(".ai-label")).toBeVisible({ timeout: 30_000 });
}

for (const theme of ["dark", "light"] as const) {
  test(`chat turn, citations, follow and safe markdown (${theme})`, async ({ page }) => {
    fs.mkdirSync(SHOTS, { recursive: true });
    await open(page, theme);
    await expect(page.locator("#chat-meter")).toContainText("/ $0.25");
    await expect(page.locator("#chat-estimate")).toContainText("next turn ≈");

    await ask(page, "where are bank statements fetched?");
    const turn = page.locator(".chat-turn").last();
    const chips = turn.locator(".citations .chip.cite");
    expect(await chips.count()).toBeGreaterThan(0);
    await expect(turn.locator(".tool-steps summary")).toHaveText("1 tool step");
    const id = await chips.first().getAttribute("data-node");
    await chips.first().click();
    await expect(page.locator("#timeline section.card:not(.chat-turn)").last()).toContainText((await chips.first().textContent())!.trim());
    await expect(page.locator("#timeline > section").last()).not.toHaveClass(/chat-turn/); // the node card is pinned
    expect(await page.evaluate(() => (window as unknown as Win).__ad2v.selection)).toBe(id);

    await ask(page, SCRIPTED);
    const t2 = page.locator(".chat-turn").last();
    await expect(t2.locator(".tool-steps summary")).toHaveText("2 tool steps");
    // the map followed ad2v_show: a focus intent with the rest dimmed
    await page.waitForFunction(() => {
      const app = (window as unknown as Win).__ad2v;
      return [...app.scene.visibleLods().keys()].some((n: string) => app.scene.isDimmed(n));
    });
    // safe markdown: raw HTML is text, outside links are not links
    await expect(t2.locator(".answer strong")).toHaveText("POST /v1/reconciliations");
    await expect(t2.locator(".answer li")).toHaveCount(2);
    expect(await t2.locator(".answer img, .answer a, .answer script").count()).toBe(0);
    await expect(t2.locator(".answer")).toContainText("<img src=x onerror=alert(1)>");
    await expect(t2.locator(".answer")).toContainText("not a node");
    await t2.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOTS, `${theme}-chat-follow.png`) });
    const meter = await page.locator("#chat-meter").textContent();
    expect(meter).not.toContain("$0.0000 /");
  });
}

test("static demo: chat input disabled with the enabling command", async ({ page }) => {
  await page.goto(DEMO_HTML);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
  const input = page.locator("#chat-input");
  await expect(input).toBeDisabled();
  await expect(input).toHaveAttribute("placeholder", /--chat --manifest ad2v.yaml/);
});
