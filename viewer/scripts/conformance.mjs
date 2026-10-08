// P6 §6 protocol conformance with the official MCP Inspector CLI, run through `npx` from its own
// cache: it is NOT a dependency of this project (its tree includes Vite 8 -> lightningcss, MPL-2.0,
// which the license gate forbids). Checks, over stdio and Streamable HTTP, in the modern
// (2026-07-28) and the legacy (initialize, 2025-11-25) eras:
//   tools/list with --strict schema checks, resources/list + resources/read of ui://ad2v/map (MIME),
//   the MCP App metadata of ad2v_show (--app-info), and one tools/call per agent tool.
// Writes test-results/conformance.json (gitignored). Exit code 1 on any failure.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export const INSPECTOR = "@modelcontextprotocol/inspector@2.8.0";
const viewer = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const repo = path.resolve(viewer, "..");
const py = [path.join(repo, ".venv", "Scripts", "python.exe"), path.join(repo, ".venv", "bin", "python"), process.env.AD2V_PYTHON ?? ""]
  .find((p) => p && fs.existsSync(p)) ?? "python";
const fixture = path.join(viewer, "tests", "fixtures", "demo.ad2v");
const out = path.join(viewer, "test-results");
fs.mkdirSync(out, { recursive: true });
const cfgPath = path.join(out, "inspector-stdio.json");
fs.writeFileSync(cfgPath, JSON.stringify({ mcpServers: { ad2v: { command: py, args: ["-m", "ad2v", "mcp", "--file", fixture] } } }));

const AGENT_CALLS = [
  ["ad2v_files", []],
  ["ad2v_overview", []],
  ["ad2v_search", ["query=match"]],
  ["ad2v_locate", ["question=where are bank statements fetched?"]],
  ["ad2v_get_node", ["node=REQ-003"]],
  ["ad2v_neighborhood", ["node=api/recon_api/matching.py::match_batch", "depth=2"]],
  ["ad2v_status", ["status=orphan"]],
  ["ad2v_links", ["node=REQ-003"]],
  ["ad2v_risks", []],
  ["ad2v_workflow", ["workflow=POST /v1/reconciliations", "detail_level=2"]],
  ["ad2v_diff", ["from=2", "to=3"]],
  ["ad2v_show", ["intent=focus", 'node_ids=["container:api"]']],
  ["ad2v_llm_plan", []],
];

function inspector(target, era, args) {
  const r = spawnSync("npx", ["-y", INSPECTOR, "--cli", ...target, "--protocol-era", era, ...args], {
    encoding: "utf8", shell: process.platform === "win32", timeout: 180_000, maxBuffer: 64 * 1024 * 1024,
  });
  let json = null;
  try { json = JSON.parse(r.stdout.slice(r.stdout.indexOf("{"))); } catch { /* not JSON */ }
  return { code: r.status, json, stderr: (r.stderr ?? "").split("\n").filter((l) => l && !l.includes("deprecated")).slice(0, 12).join("\n") };
}

async function httpServer() {
  const p = spawn(py, ["-m", "ad2v", "mcp", "--file", fixture, "--http", "--port", "0"], { cwd: repo });
  const url = await new Promise((resolve, reject) => {
    let buf = "";
    p.stderr.on("data", (d) => {
      buf += d.toString();
      const m = /Streamable HTTP on (http:\/\/127\.0\.0\.1:\d+\/mcp)/.exec(buf);
      if (m) resolve(m[1]);
    });
    setTimeout(() => reject(new Error("http server did not start")), 30_000);
  });
  return { p, url };
}

const quote = (s) => (process.platform === "win32" && /[\s"]/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s);
const results = [];
let failed = 0;
function record(transport, era, check, ok, detail = "") {
  results.push({ transport, era, check, ok, detail });
  if (!ok) failed++;
  console.log(`${ok ? "ok  " : "FAIL"} ${transport.padEnd(5)} ${era.padEnd(6)} ${check}${detail ? "  " + detail : ""}`);
}

const version = INSPECTOR.split("@").pop(); // pinned; the launcher has no --version flag (it would start the web UI)
const http = await httpServer();
try {
  const targets = {
    stdio: ["--config", quote(cfgPath), "--server", "ad2v"],
    http: ["--transport", "http", "--server-url", http.url],
  };
  for (const [transport, target] of Object.entries(targets)) {
    for (const era of ["modern", "legacy"]) {
      const tl = inspector(target, era, ["--method", "tools/list", "--strict"]);
      const tools = tl.json?.tools ?? [];
      const agent = tools.filter((t) => t.name.startsWith("ad2v_"));
      const schemasOk = tools.every((t) => t.inputSchema?.type === "object" && t.annotations?.readOnlyHint === true);
      record(transport, era, "tools/list --strict", tl.code === 0 && agent.length === 14 && schemasOk, // P10: + ad2v_architecture
        `${tools.length} tools (${agent.length} agent)${tl.stderr.includes("Warning") ? " WARN: " + tl.stderr : ""}`);
      const rl = inspector(target, era, ["--method", "resources/list"]);
      const res = (rl.json?.resources ?? []).find((r) => r.uri === "ui://ad2v/map");
      record(transport, era, "resources/list", rl.code === 0 && res?.mimeType === "text/html;profile=mcp-app");
      const rr = inspector(target, era, ["--method", "resources/read", "--uri", "ui://ad2v/map"]);
      const c = rr.json?.contents?.[0];
      record(transport, era, "resources/read ui://ad2v/map", rr.code === 0 && c?.mimeType === "text/html;profile=mcp-app" && /<html/i.test(c?.text ?? ""),
        `${(c?.text ?? "").length} chars`);
      const ai = inspector(target, era, ["--method", "tools/call", "--tool-name", "ad2v_show", "--app-info"]);
      record(transport, era, "ad2v_show --app-info", ai.code === 0 && ai.json?.resourceUri === "ui://ad2v/map", JSON.stringify(ai.json ?? ai.stderr).slice(0, 160));
      const calls = transport === "stdio" && era === "modern" ? AGENT_CALLS : AGENT_CALLS.filter(([n]) => ["ad2v_overview", "ad2v_locate", "ad2v_show"].includes(n));
      for (const [name, args] of calls) {
        const r = inspector(target, era, ["--method", "tools/call", "--tool-name", name, ...(args.length ? ["--tool-arg", ...args.map(quote)] : [])]);
        const ok = r.code === 0 && r.json && !r.json.isError && Array.isArray(r.json.content) && r.json.structuredContent !== undefined;
        record(transport, era, `tools/call ${name}`, ok, ok ? "" : (r.json?.content?.[0]?.text ?? r.stderr).slice(0, 200));
      }
    }
  }
} finally {
  http.p.kill();
}
fs.writeFileSync(path.join(out, "conformance.json"), JSON.stringify({ inspector: INSPECTOR, version, failed, results }, null, 1));
console.log(`\nMCP Inspector ${version}: ${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
