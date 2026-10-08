// P10 M8: first render of the Architecture tab (measured, not asserted beyond a loose ceiling).
// Runs only with AD2V_C4_PERF=<file.ad2v>[,<file.ad2v>...]; prints the timings for the report.
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const FILES = (process.env.AD2V_C4_PERF ?? "").split(",").filter(Boolean);
type Win = Window & { __ad2vPerf: { ready: boolean } };

for (const file of FILES) {
  test(`architecture first render: ${path.basename(file)}`, async ({ page }) => {
    const proc: ChildProcess = spawn(PY, ["-m", "ad2v", "view", file, "--no-browser", "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
    try {
      const url = await new Promise<string>((resolve, reject) => {
        let buf = "";
        proc.stdout!.on("data", (d) => { buf += String(d); const m = /(http:\/\/127\.0\.0\.1:\d+\/\S+)/.exec(buf); if (m) resolve(m[1]!); });
        setTimeout(() => reject(new Error("no URL")), 30_000);
      });
      await page.goto(url);
      await page.waitForFunction(() => (window as unknown as Win).__ad2vPerf?.ready, null, { timeout: 120_000 });
      const ms = await page.evaluate(async () => {
        const t0 = performance.now();
        (document.querySelector("#tab-arch") as HTMLButtonElement).click();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        return { ms: performance.now() - t0, elements: document.querySelectorAll("#architecture g.c4-el").length };
      });
      console.log(`C4 first render ${path.basename(file)}: ${ms.ms.toFixed(0)} ms, ${ms.elements} elements`);
      expect(ms.ms).toBeLessThan(20_000);
    } finally {
      proc.kill();
    }
  });
}
