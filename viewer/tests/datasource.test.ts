import { describe, expect, it } from "vitest";
import { LAYOUT_ALGORITHM } from "../src/data/LocalFileSource";
import { source } from "./fixture";

describe("LocalFileSource against the demo file", async () => {
  const ds = await source();
  const epochs = await ds.epochs();
  const head = epochs.find((e) => e.isHead)!;

  it("lists materialized epochs oldest first, with the head", async () => {
    expect(epochs.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(head.seq).toBe(8);
    expect(epochs[0]!.parentEpochId).toBeNull();
    expect(epochs[2]!.changeKind).toBe("spec");
    const meta = await ds.meta();
    expect(meta.formatVersion).toBe("0.6");
    expect(meta.llmProviders).toEqual(["fake"]);
  });

  it("has a layout row and a glyph for every node", async () => {
    const nodes = await ds.nodes(head.epochId);
    const layout = await ds.layout(head.epochId);
    const glyphs = await ds.glyphs(head.epochId);
    expect(LAYOUT_ALGORITHM).toBe("nestgrid-v1");
    expect(nodes.length).toBeGreaterThan(100);
    for (const n of nodes) {
      expect(layout.has(n.id)).toBe(true);
      expect(glyphs.has(n.id)).toBe(true);
    }
  });

  it("returns non-hierarchy edges only", async () => {
    const edges = await ds.edges(head.epochId);
    expect(edges.length).toBeGreaterThan(20);
    expect(edges.some((e) => e.kind === "contains" || e.kind === "declares")).toBe(false);
  });

  it("distinguishes normative and effective status", async () => {
    const nodes = await ds.nodes(head.epochId);
    const req3 = nodes.find((n) => n.qname === "REQ-003")!;
    const norm = await ds.status(head.epochId, "normative");
    const eff = await ds.status(head.epochId, "effective");
    expect(norm.get(req3.id)!.status).toBe("verified");
    expect(eff.get(req3.id)).toMatchObject({ status: "drift", normative: "verified", provenance: "llm" });
    expect([...eff.values()].filter((s) => s.status !== s.normative)).toHaveLength(2);
  });

  it("reads cards, links, judgments, suggestions and roll-ups", async () => {
    const e = head.epochId;
    const nodes = await ds.nodes(e);
    const byQ = (q: string) => nodes.find((n) => n.qname === q)!.id;
    const sum = (await ds.summaries(e)).get(byQ("container:api"))!;
    expect(sum.card).toMatch(/reconciliation API/);
    expect(sum.provider).toBe("fake");
    expect((await ds.rollups(e)).get(byQ("container:api"))).toBeTruthy();
    const links = await ds.links(e);
    const j = await ds.judgments(e);
    const drift = [...j.values()].find((x) => x.overlay === "drift")!;
    expect(links.find((l) => l.linkId === drift.linkId)).toBeTruthy();
    expect(drift.evidence.length).toBe(2);
    const sug = await ds.suggestions(e);
    expect(sug.map((s) => nodes.find((n) => n.id === s.codeId)!.qname).sort()).toEqual(["api/recon_api", "container:api"]);
    const detail = (await ds.nodeDetail(e, byQ("api/recon_api/matching.py::match_batch")))!;
    expect(detail.node.kind).toBe("function");
    expect(await ds.nodeDetail(e, "n_nope")).toBeNull();
  });

  it("reads workflows, steps, narrations and history", async () => {
    const e = head.epochId;
    const wfs = await ds.workflows(e);
    const post = wfs.find((w) => w.name === "POST /v1/reconciliations")!;
    const steps = await ds.steps(e, post.workflowId);
    expect(steps[0]!.seq).toBe(0);
    const nar = await ds.narrations(e, post.workflowId);
    expect(nar.length).toBeGreaterThan(5);
    expect(new Set(nar.map((n) => n.mode))).toEqual(new Set(["containment"]));
    const through = await ds.workflowsThrough(e, steps[1]!.nodeIds[0]!);
    expect(through).toContain(post.workflowId);
    const lin = await ds.lineage(epochs[1]!.epochId);
    expect(lin.map((l) => l.method)).toContain("same_content");
    const nodes = await ds.nodes(e);
    const hist = await ds.statusHistory(nodes.find((n) => n.qname === "REQ-003")!.id);
    expect(hist.map((h) => h.status)).toEqual(["verified", "verified", "stale", "stale", "stale", "stale", "stale", "verified"]);
  });
});
