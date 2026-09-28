// A minimal MCP client over stdio for tests and the e2e relay: spawns `python -m ad2v mcp`, speaks
// protocol 2026-07-28 (per-request _meta) and declares the MCP Apps extension.
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

export const PROTOCOL = "2026-07-28";
export const REPO = path.resolve(process.cwd(), "..");
export const APPS_CAPS = { extensions: { "io.modelcontextprotocol/ui": { mimeTypes: ["text/html;profile=mcp-app"] } } };

export function python(): string {
  const cands = [
    path.join(REPO, ".venv", "Scripts", "python.exe"),
    path.join(REPO, ".venv", "bin", "python"),
    process.env.AD2V_PYTHON ?? "",
  ].filter((p) => p && fs.existsSync(p));
  return cands[0] ?? "python";
}

interface Pending {
  resolve: (v: Record<string, unknown>) => void;
  reject: (e: Error) => void;
}

export class McpStdioClient {
  private proc: ChildProcessWithoutNullStreams;
  private next = 1;
  private pending = new Map<number, Pending>();
  readonly stderr: string[] = [];

  constructor(args: string[], private caps: Record<string, unknown> = APPS_CAPS) {
    this.proc = spawn(python(), ["-m", "ad2v", "mcp", ...args], { cwd: REPO, env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
    readline.createInterface({ input: this.proc.stdout }).on("line", (line) => {
      if (!line.trim()) return;
      const msg = JSON.parse(line) as { id?: number; result?: Record<string, unknown>; error?: { message: string } };
      const p = msg.id !== undefined ? this.pending.get(msg.id) : undefined;
      if (!p) return;
      this.pending.delete(msg.id!);
      if (msg.error) p.reject(new Error(msg.error.message));
      else p.resolve(msg.result!);
    });
    this.proc.stderr.on("data", (d: Buffer) => this.stderr.push(d.toString()));
  }

  request(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    const id = this.next++;
    const body = {
      jsonrpc: "2.0",
      id,
      method,
      params: {
        ...params,
        _meta: {
          "io.modelcontextprotocol/protocolVersion": PROTOCOL,
          "io.modelcontextprotocol/clientCapabilities": this.caps,
          "io.modelcontextprotocol/clientInfo": { name: "ad2v-tests", version: "0" },
        },
      },
    };
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify(body) + "\n");
    });
  }

  /** A raw message (used by the relay, which forwards the iframe's JSON-RPC as-is). */
  callTool(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("tools/call", { name, arguments: args });
  }

  close(): Promise<void> {
    return new Promise((resolve) => {
      this.proc.once("exit", () => resolve());
      this.proc.stdin.end();
      setTimeout(() => this.proc.kill(), 5000).unref();
    });
  }
}
