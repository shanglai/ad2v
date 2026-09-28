// P6 §4 parity: every DataSource method, called with the same arguments, returns deep-equal results
// from LocalFileSource (sql.js over the file) and RemoteSliceSource (app tools of the real stdio MCP
// server, spawned here). Run with `npm run test:mcp`.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import path from "node:path";
import type { DataSource } from "../../src/data/DataSource";
import type { EpochInfo } from "../../src/data/types";
import { RemoteSliceSource } from "../../src/data/RemoteSliceSource";
import { FIXTURES, source } from "../fixture";
import { McpStdioClient } from "./client";

let client: McpStdioClient;
let local: DataSource;
let remote: RemoteSliceSource;
let epochs: EpochInfo[];

beforeAll(async () => {
  client = new McpStdioClient(["--file", path.join(FIXTURES, "demo.ad2v")]);
  remote = new RemoteSliceSource((name, args) => client.callTool(name, args));
  local = await source();
  epochs = await local.epochs();
}, 60_000);

afterAll(async () => {
  await client.close();
});

describe("RemoteSliceSource over stdio == LocalFileSource", () => {
  it("lists the app tools only for an MCP Apps client, all app-only and linked to the map", async () => {
    const r = (await client.request("tools/list")) as { tools: Array<{ name: string; _meta?: { ui?: { visibility?: string[]; resourceUri?: string } } }> };
    const app = r.tools.filter((t) => t.name.startsWith("viewer_"));
    expect(app.length).toBe(20);
    for (const t of app) {
      expect(t._meta?.ui?.visibility).toEqual(["app"]);
      expect(t._meta?.ui?.resourceUri).toBe("ui://ad2v/map");
    }
    const plain = new McpStdioClient(["--file", path.join(FIXTURES, "demo.ad2v")], {});
    const r2 = (await plain.request("tools/list")) as { tools: Array<{ name: string }> };
    await plain.close();
    expect(r2.tools.some((t) => t.name.startsWith("viewer_"))).toBe(false);
  });

  it("meta and epochs", async () => {
    expect(await remote.meta()).toEqual(await local.meta());
    expect(await remote.epochs()).toEqual(epochs);
  });

  it("every per-epoch method, for every epoch", async () => {
    for (const e of epochs) {
      const id = e.epochId;
      for (const m of ["nodes", "layout", "glyphs", "edges", "rollups", "links", "judgments", "suggestions", "summaries", "workflows", "lineage"] as const) {
        expect(await remote[m](id), `${m} @ #${e.seq}`).toEqual(await local[m](id));
      }
      for (const mode of ["normative", "effective"] as const) {
        expect(await remote.status(id, mode), `status ${mode} @ #${e.seq}`).toEqual(await local.status(id, mode));
      }
    }
  });

  it("node details, workflows through, status history (head, every node)", async () => {
    const head = epochs.find((e) => e.isHead)!.epochId;
    const nodes = await local.nodes(head);
    for (const n of nodes) {
      expect(await remote.nodeDetail(head, n.id), n.qname).toEqual(await local.nodeDetail(head, n.id));
      expect(await remote.workflowsThrough(head, n.id)).toEqual(await local.workflowsThrough(head, n.id));
      expect(await remote.statusHistory(n.id)).toEqual(await local.statusHistory(n.id));
    }
    expect(await remote.nodeDetail(head, "n_nope")).toBeNull();
  });

  it("steps and narrations of every workflow (head), both modes", async () => {
    const head = epochs.find((e) => e.isHead)!.epochId;
    for (const w of await local.workflows(head)) {
      expect(await remote.steps(head, w.workflowId)).toEqual(await local.steps(head, w.workflowId));
      for (const mode of ["containment", "call_depth"]) {
        expect(await remote.narrations(head, w.workflowId, mode)).toEqual(await local.narrations(head, w.workflowId, mode));
      }
    }
  });

  it("scene slices: whole epoch, and every container / component / module at depths 0-2", async () => {
    for (const e of [epochs[1]!, epochs.find((x) => x.isHead)!]) {
      expect(await remote.scene(e.epochId, null, -1)).toEqual(await local.scene(e.epochId, null, -1));
      const roots = (await local.nodes(e.epochId)).filter((n) => ["container", "component", "module", "spec_doc"].includes(n.kind));
      for (const r of roots) {
        for (const depth of [0, 1, 2]) {
          const a = await remote.scene(e.epochId, r.id, depth);
          const b = await local.scene(e.epochId, r.id, depth);
          expect(a, `${r.qname} depth ${depth}`).toEqual(b);
          expect(a.complete).toBe(false);
          expect(a.nodes.length).toBeLessThan((await local.nodes(e.epochId)).length + 1);
        }
      }
    }
  });
});
