// P8 M5 (docs/security.md §1): a hostile .ad2v file runs no script in either viewer mode.
// tests/hostile.py appends script payloads (<img onerror>, <script>, <svg onload>, javascript:
// links) to every free-text column and every JSON string leaf of the demo file, plus one
// 100,000-character node name. The standalone viewer is served by a real `ad2v view` (its CSP
// applies); the MCP App runs in the test host against a real stdio server. Every node gets a panel
// card, a workflow is replayed (narrations), and the payloads must show up as text only.
import { expect, test, type Frame, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { McpStdioClient } from "../tests/mcp/client";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const DEMO_FILE = path.resolve(process.cwd(), "tests", "fixtures", "demo.ad2v");
const HOST_HTML = path.resolve(process.cwd(), "e2e", "host", "dist", "e2e", "host", "host.html");
const MARK = "__ad2vXss";

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean }; __ad2vXss?: number }; // eslint-disable-line @typescript-eslint/no-explicit-any
type HostWin = Window & { hostShow: (a: Record<string, unknown>, t: string) => Promise<void>; hostLog: { error: string | null } };

let file = "";
let proc: ChildProcess | null = null;
let url = "";
let client: McpStdioClient;
let server: http.Server;
let base = "";

test.beforeAll(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ad2v-hostile-"));
  file = path.join(tmp, "hostile.ad2v");
  const made = spawnSync(PY, [path.join(ROOT, "tests", "hostile.py"), DEMO_FILE, file, "xss"], { encoding: "utf-8" });
  expect(made.status, made.stderr).toBe(0);
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
  client = new McpStdioClient(["--file", file]);
  server = http.createServer((req, res) => {
    if (req.method === "GET" && (req.url === "/" || req.url === "/index.html")) {
      res.writeHead(200, { "content-type": "text/html" }).end(fs.readFileSync(HOST_HTML));
      return;
    }
    if (req.method === "POST" && req.url === "/rpc") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const { method, params } = JSON.parse(body) as { method: string; params: Record<string, unknown> };
        client.request(method, params).then(
          (result) => res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ result })),
          (e: Error) => res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ error: { message: e.message } })),
        );
      });
      return;
    }
    res.writeHead(404).end();
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${(server.address() as { port: number }).port}/`;
});

test.afterAll(async () => {
  proc?.kill();
  server?.close();
  await client?.close();
});

function watch(page: Page): { dialogs: string[]; errors: string[] } {
  const seen = { dialogs: [] as string[], errors: [] as string[] };
  page.on("dialog", (d) => {
    seen.dialogs.push(d.message());
    void d.dismiss();
  });
  page.on("pageerror", (e) => seen.errors.push(String(e)));
  return seen;
}

/** Opens a card for every loaded node and replays the first workflow (narrations, step cards). */
async function exercise(target: Page | Frame): Promise<number> {
  return target.evaluate(async () => {
    const app = (window as unknown as Win).__ad2v;
    const all = new Set<string>((app.cur?.nodes ?? []).map((r: { id: string }) => r.id)); // EpochData.nodes: NodeRow[]
    let n = 0;
    for (const id of [...all].slice(0, 80)) {
      app.select(id, true, false);
      n++;
    }
    const wf = app.cur?.workflows?.[0];
    if (wf) {
      await app.startReplay(wf.workflowId);
      for (let s = 0; s < Math.min(6, app.replay?.coarse?.length ?? 0); s++) app.replayTo(0, s);
    }
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return n;
  });
}

test("standalone viewer (ad2v view): payloads render as text, no script runs", async ({ page }) => {
  const seen = watch(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(url);
  await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
  const n = await exercise(page);
  expect(n).toBeGreaterThan(10);
  await page.mouse.move(700, 430);
  await page.waitForTimeout(500);
  expect(await page.evaluate((m) => (window as unknown as Record<string, unknown>)[m], MARK)).toBeUndefined();
  expect(seen.dialogs).toEqual([]);
  expect(await page.locator("body").innerText()).toContain("<img src=x onerror="); // shown as text
  expect(await page.locator("img[src='x'], svg[onload], script:not([src]):not([type])").count()).toBe(0);
  expect(seen.errors).toEqual([]);
});

test("MCP App in the test host: payloads render as text, no script runs", async ({ page }) => {
  const seen = watch(page);
  const hit = (await client.callTool("ad2v_search", { query: "reconciliation", limit: 5 })).structuredContent as { nodes: Array<{ id: string }> };
  expect(hit.nodes.length).toBeGreaterThan(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(base);
  await page.evaluate((ids) => (window as unknown as HostWin).hostShow({ intent: "focus", node_ids: ids }, "dark"), [hit.nodes[0]!.id]);
  const frame = page.frames().find((f) => f !== page.mainFrame())!;
  await frame.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
  expect(await page.evaluate(() => (window as unknown as HostWin).hostLog.error)).toBeNull();
  const n = await exercise(frame);
  expect(n).toBeGreaterThan(0);
  expect(await frame.evaluate((m) => (window as unknown as Record<string, unknown>)[m], MARK)).toBeUndefined();
  expect(await page.evaluate((m) => (window as unknown as Record<string, unknown>)[m], MARK)).toBeUndefined();
  expect(seen.dialogs).toEqual([]);
  expect(await frame.locator("body").innerText()).toContain("<img src=x onerror=");
  expect(await frame.locator("img[src='x'], svg[onload], script:not([src]):not([type])").count()).toBe(0);
  expect(seen.errors).toEqual([]);
});
