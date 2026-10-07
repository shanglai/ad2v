import { describe, expect, it } from "vitest";
import type { Box, NodeRow, StatusInfo, SuggestionRow } from "../src/data/types";
import { aggregateEdges, groupOf } from "../src/model/edges";
import { Lod, lodFor } from "../src/model/lod";
import { ancestry, coarseIndexOf, levels, project } from "../src/model/projection";
import {
  classifyDiff,
  composeLineage,
  dedupSuggestions,
  displayLabel,
  fallbackCard,
  renderMentions,
  truncateWords,
} from "../src/model/text";
import { SceneTree } from "../src/model/tree";
import { json, source } from "./fixture";

describe("projection parity with Python", async () => {
  const ds = await source();
  const fx = json<{ epoch: string; workflows: Array<{ workflowId: string; byDepth: Record<string, Array<{ nodeIds: string[]; touched: string[]; span: [number, number] }>>; levels: number[] }> }>("projections.json");
  const nodes = await ds.nodes(fx.epoch);
  const anc = ancestry(new Map(nodes.map((n) => [n.id, n.parentId])));

  it("covers every code workflow", () => expect(fx.workflows.length).toBeGreaterThan(5));

  for (const w of fx.workflows) {
    it(`matches Python for ${w.workflowId} at every depth`, async () => {
      const steps = await ds.steps(fx.epoch, w.workflowId);
      for (const [k, want] of Object.entries(w.byDepth)) {
        const got = project(steps, Number(k), anc).map((c) => ({ nodeIds: c.nodeIds, touched: c.touched, span: c.span }));
        expect(got, `depth ${k}`).toEqual(want);
      }
      expect(levels(steps, anc).map((l) => l.level)).toEqual(w.levels);
    });
  }

  it("keeps the playhead inside the containing coarse step at every level", async () => {
    const w = fx.workflows[0]!;
    const steps = await ds.steps(fx.epoch, w.workflowId);
    for (const lv of levels(steps, anc)) {
      for (const s of steps) {
        const c = lv.coarse[coarseIndexOf(lv.coarse, s.seq)]!;
        expect(c.span[0] <= s.seq && s.seq <= c.span[1]).toBe(true);
      }
    }
    expect(() => project(steps, -1, anc)).toThrow();
  });
});

describe("LOD with hysteresis", () => {
  it("uses the P5 thresholds going up", () => {
    expect([4, 8, 39, 40, 159, 160, 900].map((px) => lodFor(px, undefined))).toEqual([
      Lod.Hidden, Lod.Silhouette, Lod.Silhouette, Lod.Detail, Lod.Detail, Lod.Open, Lod.Open,
    ]);
  });
  it("only drops below threshold × 0.8", () => {
    expect(lodFor(150, Lod.Open)).toBe(Lod.Open); // 150 ≥ 160 × 0.8 = 128
    expect(lodFor(127, Lod.Open)).toBe(Lod.Detail);
    expect(lodFor(33, Lod.Detail)).toBe(Lod.Detail);
    expect(lodFor(31, Lod.Detail)).toBe(Lod.Silhouette);
    expect(lodFor(6.5, Lod.Silhouette)).toBe(Lod.Silhouette);
    expect(lodFor(6, Lod.Silhouette)).toBe(Lod.Hidden);
    expect(lodFor(20, Lod.Open)).toBe(Lod.Silhouette); // several levels at once
  });
});

function row(id: string, parentId: string | null, kind = "module"): NodeRow {
  return { id, side: "code", kind, name: id, qname: id, parentId, path: null, spanStart: null, spanEnd: null, title: null, refs: [], nfr: false, keyword: null };
}
const box = (w: number): Box => ({ x: 0, y: 0, z: 0, w, h: w, d: 0.2 });

describe("tree visibility and representatives", () => {
  const rows = [row("sys", null, "system"), row("c", "sys", "container"), row("m", "c"), row("f", "m", "function"), row("p", "c", "http_route")];
  const layout = new Map([["sys", box(100)], ["c", box(40)], ["m", box(10)], ["f", box(1)], ["p", box(0.4)]]);
  const tree = new SceneTree(rows, layout, new Map());
  const px = (scale: number) => (b: Box) => b.w * scale;

  it("opens containers by size and hides small children", () => {
    const vis = tree.visible(px(5), new Map()); // sys 500 open, c 200 open, m 50 detail, f 5 hidden
    expect([...vis.keys()].sort()).toEqual(["c", "m", "p", "sys"]);
    expect(vis.get("m")).toBe(Lod.Detail);
    expect(tree.representative("f", vis)).toBe("m");
    expect(tree.representative("nope", vis)).toBeNull();
  });
  it("shows ports only when their container shows detail", () => {
    const vis = tree.visible(px(2), new Map()); // sys 200 open; c 80 → detail (not open)
    expect(vis.has("p")).toBe(true);
    expect(vis.has("m")).toBe(false);
    expect(tree.ancestors("f")).toEqual(["m", "c", "sys"]);
  });
  it("always shows the roots", () => {
    expect(tree.visible(() => 0, new Map()).get("sys")).toBe(Lod.Silhouette);
  });
});

describe("edge aggregation", () => {
  it("draws edges between representatives and sums weights", () => {
    const reps = new Map<string, string | null>([["a1", "A"], ["a2", "A"], ["b1", "B"], ["c", null]]);
    const rep = (id: string) => (reps.has(id) ? reps.get(id)! : id);
    const agg = aggregateEdges(
      [
        { src: "a1", dst: "b1", kind: "calls", weight: 2 },
        { src: "a2", dst: "b1", kind: "calls", weight: 3 },
        { src: "a1", dst: "b1", kind: "reads", weight: 1 },
        { src: "a1", dst: "a2", kind: "calls", weight: 9 }, // inside one representative
        { src: "a1", dst: "c", kind: "calls", weight: 1 }, // endpoint not visible
        { src: "a1", dst: "b1", kind: "annotated_as", weight: 1 },
      ],
      rep,
    );
    expect(agg).toEqual([
      { src: "A", dst: "B", group: "calls", weight: 5, count: 2 },
      { src: "A", dst: "B", group: "data", weight: 1, count: 1 },
    ]);
    expect(groupOf("contains")).toBeNull();
  });
});

describe("text helpers", () => {
  it("links mentioned ids and strips the others", () => {
    const a = "n_" + "a".repeat(20), b = "n_" + "b".repeat(20);
    const segs = renderMentions(`hosts X (${a}) and Y (${b}).`, [a], (id) => (id === a ? "Alpha" : null));
    expect(segs).toEqual([{ text: "hosts X " }, { nodeId: a, label: "Alpha" }, { text: " and Y." }]);
  });

  it("merges suggestions for one spec item at several containment levels", () => {
    const s = (id: string, code: string, conf: number, state = "open"): SuggestionRow => ({
      suggestionId: id, specId: "CMP", codeId: code, rank: 1, lexicalScore: 1, verdict: "match", confidence: conf, rationale: "", state, provider: "fake",
    });
    const depth = (x: string) => ({ container: 1, component: 2 }[x] ?? 3);
    const out = dedupSuggestions([s("s1", "component", 0.98), s("s2", "container", 0.86), s("s3", "x", 0.9, "rejected")], depth);
    expect(out).toHaveLength(1);
    expect(out[0]!.primary.codeId).toBe("container");
    expect(out[0]!.collapsed.map((c) => c.codeId)).toEqual(["component"]);
  });

  it("builds a deterministic fallback card", () => {
    const card = fallbackCard("api", { kind: "container", counts: { module: 3, function: 1, class: 2 }, ports: ["GET /a"], resources: ["db"], risks: ["IO or LLM inside a loop"], rollup: { orphan: 2, none: 5 }, status: "orphan" });
    expect(card).toBe("api is a container containing 3 modules, 1 function, 2 classes. Ports: GET /a. Touches db. Risks: IO or LLM inside a loop. Inside: 2 orphan. Status: orphan.");
  });

  it("classifies a diff through composed lineage", () => {
    const st = (s: string): StatusInfo => ({ status: s, normative: s, provenance: "deterministic", suggested: false });
    const a = { nodes: [row("keep", null), row("old", null), row("gone", null), row("flip", null)], status: new Map([["keep", st("implemented")], ["old", st("verified")], ["gone", st("none")], ["flip", st("verified")]]) };
    const b = { nodes: [row("keep", null), row("new", null), row("flip", null), row("born", null)], status: new Map([["keep", st("implemented")], ["new", st("verified")], ["flip", st("stale")], ["born", st("none")]]) };
    const lin = composeLineage(
      [{ epochId: "e2", seq: 2, parentEpochId: "e1", commit: null, changeKind: "code", pinned: false, label: null, materialized: true, isHead: false },
       { epochId: "e3", seq: 3, parentEpochId: "e2", commit: null, changeKind: "code", pinned: false, label: null, materialized: true, isHead: true }],
      new Map([["e2", [{ oldId: "old", newId: "mid", method: "same_content", score: 1 }]], ["e3", [{ oldId: "mid", newId: "new", method: "same_content", score: 1 }]]]),
    );
    expect(lin.get("old")).toBe("new");
    const got = Object.fromEntries(classifyDiff(a, b, lin).map((e) => [e.id, e.cls]));
    expect(got).toEqual({ keep: "unchanged", new: "renamed", gone: "removed", flip: "transition", born: "added" });
  });
});

describe("P9 labels (ADR-0072)", () => {
  it("truncates at a word boundary with an ellipsis", () => {
    expect(truncateWords("short", 48)).toBe("short");
    expect(truncateWords("El sistema deberá conciliar los movimientos del extracto bancario", 30)).toBe("El sistema deberá conciliar…");
    expect(truncateWords("a, b, c, d, e, f, g, h, i, j", 12)).toBe("a, b, c, d…");
    expect(truncateWords("Supercalifragilisticexpialidocious", 10)).toBe("Supercali…"); // one long word
    expect(truncateWords("x".repeat(60), 48)).toHaveLength(48);
  });
  it("labels requirements, components with ids and scenarios", () => {
    const n = { kind: "requirement", name: "REQ-001", qname: "REQ-001", title: "Start a run", refs: [] };
    expect(displayLabel(n)).toBe("REQ-001 · Start a run");
    expect(displayLabel({ ...n, title: null })).toBe("REQ-001");
    expect(displayLabel({ ...n, kind: "spec_component", name: "Reconciliation API", qname: "CMP-001" })).toBe("CMP-001 · Reconciliation API");
    expect(displayLabel({ ...n, kind: "spec_component", name: "Frontend", qname: "requerimientos.md::Frontend" })).toBe("Frontend");
    expect(displayLabel({ ...n, kind: "scenario", name: "Approve a run", qname: "f::Approve a run", refs: ["REQ-007"] })).toBe("Approve a run [REQ-007]");
    expect(displayLabel({ ...n, kind: "module", name: "app.py", qname: "app.py" })).toBe("app.py");
  });
});
