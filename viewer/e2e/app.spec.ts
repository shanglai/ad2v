// P6 §6: the MCP App inside a test host (official AppBridge), talking to the real stdio server.
// Five scenarios in both themes -> 10 screenshots in docs/reports/P6-screens/. Every request made
// by the iframe is recorded: there must be none (the app gets all data through app-only tools).
import { expect, test, type Frame, type Page } from "@playwright/test";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { McpStdioClient } from "../tests/mcp/client";

const FIXTURE = path.resolve(process.cwd(), "tests", "fixtures", "demo.ad2v");
const HOST_HTML = path.resolve(process.cwd(), "e2e", "host", "dist", "e2e", "host", "host.html");
const SHOTS = path.resolve(process.cwd(), "..", "docs", "reports", "P6-screens");

let client: McpStdioClient;
let server: http.Server;
let base = "";

type Win = Window & { __ad2v: any; __ad2vPerf: { ready: boolean; firstRenderMs: number } }; // eslint-disable-line @typescript-eslint/no-explicit-any
type HostWin = Window & { hostShow: (a: Record<string, unknown>, t: string) => Promise<void>; hostLog: { modelContext: Array<{ content?: Array<{ text: string }> }>; toolCalls: string[]; rejected: string[]; ready: boolean; error: string | null } };

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  client = new McpStdioClient(["--file", FIXTURE]);
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
  server?.close();
  await client?.close();
});

async function call(name: string, args: Record<string, unknown>): Promise<any> { // eslint-disable-line @typescript-eslint/no-explicit-any
  return (await client.callTool(name, args)).structuredContent;
}

/** Opens the host, runs ad2v_show(args) and returns the app frame once the map has rendered. */
async function show(page: Page, args: Record<string, unknown>, theme: "light" | "dark", leaks: string[]): Promise<Frame> {
  page.on("request", (r) => {
    if (r.frame() !== page.mainFrame() && !/^(data|about|blob):/.test(r.url())) leaks.push(r.url());
  });
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.goto(base);
  await page.evaluate(([a, t]) => (window as unknown as HostWin).hostShow(a as Record<string, unknown>, t as string), [args, theme] as const);
  const frame = page.frames().find((f) => f !== page.mainFrame())!;
  await frame.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 60_000 });
  await expect(page.locator("html")).toBeVisible();
  const err = await page.evaluate(() => (window as unknown as HostWin).hostLog.error);
  expect(err).toBeNull();
  return frame;
}

async function shot(page: Page, theme: string, n: number, name: string): Promise<void> {
  await page.mouse.move(2, 2); // no hover tooltip in the shot
  await page.waitForTimeout(800); // labels are placed once the camera settles
  const chat = (await page.locator("#chat").boundingBox())!;
  await page.screenshot({ path: path.join(SHOTS, `${theme}-${n}-${name}.png`), clip: chat });
}

async function checkHost(page: Page, leaks: string[]): Promise<void> {
  const log = await page.evaluate(() => (window as unknown as HostWin).hostLog);
  expect(leaks, "requests from the iframe").toEqual([]);
  expect(log.rejected, "the app called a tool that is not app-visible").toEqual([]);
  expect(log.toolCalls.every((t) => t.startsWith("viewer_"))).toBe(true);
}

for (const theme of ["dark", "light"] as const) {
  test.describe(`MCP App (${theme})`, () => {
    test("1. focus container:api", async ({ page }) => {
      const leaks: string[] = [];
      const f = await show(page, { intent: "focus", node_ids: ["container:api"], theme }, theme, leaks);
      const api = (await call("ad2v_search", { query: "container:api" })).nodes[0].id as string;
      await expect.poll(() => f.evaluate((id) => (window as unknown as Win).__ad2v.scene.visibleLods().get(id), api)).toBe(3);
      await expect(f.locator(".card.node")).toContainText("container:api");
      await expect(f.locator("html")).toHaveAttribute("data-theme", theme);
      const ctx = await page.evaluate(() => (window as unknown as HostWin).hostLog.modelContext);
      expect(JSON.stringify(ctx)).toContain(api); // the click / focus reached the host as model context
      await shot(page, theme, 1, "focus-container-api");
      await checkHost(page, leaks);
    });

    test("2. path along POST /v1/reconciliations", async ({ page }) => {
      const leaks: string[] = [];
      const wf = await call("ad2v_workflow", { workflow: "POST /v1/reconciliations", detail_level: 3 });
      const ids = [...new Set((wf.steps as Array<{ nodes: Array<{ id: string }> }>).flatMap((s) => s.nodes.map((n) => n.id)))];
      expect(ids.length).toBeGreaterThan(2);
      const f = await show(page, { intent: "path", node_ids: ids, theme }, theme, leaks);
      await expect(f.locator(".card.list")).toContainText(`Path (${ids.length})`);
      await shot(page, theme, 2, "path-post-reconciliations");
      await checkHost(page, leaks);
    });

    test("3. replay at two detail levels", async ({ page }) => {
      const leaks: string[] = [];
      const wid = (await call("ad2v_workflow", { workflow: "POST /v1/reconciliations" })).workflow.workflow_id as string;
      const f = await show(page, { intent: "replay", workflow_id: wid, detail_level: 1, theme }, theme, leaks);
      await f.waitForSelector("#replaybar:not(.hidden)");
      const a = await f.evaluate(() => (window as unknown as Win).__ad2v.replayTo(0, 2));
      const b = await f.evaluate(() => (window as unknown as Win).__ad2v.setReplayLevel(1));
      expect(b.playhead).toBe(a.playhead);
      expect(b.level).toBeGreaterThan(a.level);
      await shot(page, theme, 3, "replay-two-levels");
      await checkHost(page, leaks);
    });

    test("4. diff between epochs 2 and 3", async ({ page }) => {
      const leaks: string[] = [];
      const f = await show(page, { intent: "diff", epoch_from: "2", epoch_to: "3", theme }, theme, leaks);
      await expect(f.locator(".card.changes")).toContainText("verified → stale");
      await expect(f.locator("#diff-label")).toContainText("#2 → #3");
      await shot(page, theme, 4, "diff-epoch-2-3");
      await checkHost(page, leaks);
    });

    test("5. click into a module and back", async ({ page }) => {
      const leaks: string[] = [];
      const f = await show(page, { intent: "focus", node_ids: ["api/recon_api"], theme }, theme, leaks);
      const mod = (await call("ad2v_search", { query: "api/recon_api/matching.py", kind: "module" })).nodes[0].id as string;
      const before = (await page.evaluate(() => (window as unknown as HostWin).hostLog.toolCalls)).filter((t) => t === "viewer_scene").length;
      const at = await f.evaluate((id) => (window as unknown as Win).__ad2v.scene.screenOf(id), mod); // canvas coords
      const canvas = (await page.frameLocator("#app-frame").locator("canvas").boundingBox())!; // page coords
      await page.mouse.dblclick(canvas.x + at.x, canvas.y + at.y);
      await expect.poll(() => f.evaluate(() => (window as unknown as Win).__ad2v.scene.getFocus())).toBe(mod);
      await expect(f.locator(".card.node")).toContainText("matching.py");
      await shot(page, theme, 5, "enter-module");
      const after = (await page.evaluate(() => (window as unknown as HostWin).hostLog.toolCalls)).filter((t) => t === "viewer_scene").length;
      expect(after).toBeGreaterThan(before); // entering fetched the module's slice
      await f.locator("canvas").focus();
      await page.keyboard.press("Escape");
      const parent = await f.evaluate(() => (window as unknown as Win).__ad2v.scene.getFocus());
      expect(parent).not.toBe(mod);
      await checkHost(page, leaks);
    });
  });
}
