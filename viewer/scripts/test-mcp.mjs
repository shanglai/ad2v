// `npm run test:mcp`: every P6 check that needs the Python MCP server, in order.
//   1. build the MCP App (budget + license gate) and the e2e test host
//   2. Vitest parity: RemoteSliceSource over stdio == LocalFileSource
//   3. protocol conformance with the MCP Inspector (npx, not a dependency)
//   4. Playwright: the App in the test host, both themes (10 screenshots)
// The Python side runs separately: `pytest -m mcp` (repository root).
import { spawnSync } from "node:child_process";

const win = process.platform === "win32";
const steps = [
  ["build:app", "npm", ["run", "build:app"], {}],
  ["build test host", "npx", ["vite", "build", "--mode", "host"], {}],
  ["parity (vitest)", "npx", ["vitest", "run"], { AD2V_TEST_MCP: "1" }],
  ["conformance (MCP Inspector)", "node", ["scripts/conformance.mjs"], {}],
  ["App e2e (playwright)", "npx", ["playwright", "test", "e2e/app.spec.ts"], {}],
];
for (const [label, cmd, args, env] of steps) {
  console.log(`\n=== ${label}`);
  const r = spawnSync(cmd, args, { stdio: "inherit", shell: win, env: { ...process.env, ...env } });
  if (r.status !== 0) {
    console.error(`test:mcp: "${label}" failed (exit ${r.status})`);
    process.exit(r.status ?? 1);
  }
}
console.log("\ntest:mcp: all MCP checks passed");
