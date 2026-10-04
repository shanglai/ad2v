// P7 M5 (ADR-0061): label placement, edge declutter and portal merging are pure functions.
import { describe, expect, it } from "vitest";
import {
  declutterEdges,
  labelPriority,
  liftEdges,
  mergePortals,
  placeLabels,
  type LabelCand,
} from "../src/model/declutter";
import type { AggEdge } from "../src/model/edges";

const cand = (id: string, x: number, priority = 0, area = 100, name = id): LabelCand => ({
  id,
  rect: [x, 0, x + 50, 16],
  priority,
  area,
  name,
});

describe("labels", () => {
  it("prefers problems, then ports, then footprint, then name", () => {
    expect(labelPriority("drift", false)).toBeGreaterThan(labelPriority("none", true));
    expect(labelPriority("none", true)).toBeGreaterThan(labelPriority("implemented", false));
    // three overlapping candidates: only the highest-priority one is placed
    const got = placeLabels([cand("big", 0, 0, 900), cand("port", 10, 1, 10), cand("bad", 20, 2, 1)], new Set());
    expect(got).toEqual(["bad"]);
    // no overlap: all placed, in priority order
    expect(placeLabels([cand("a", 0), cand("b", 100, 1), cand("c", 200, 2)], new Set())).toEqual(["c", "b", "a"]);
    // equal priority: larger footprint wins, then name
    expect(placeLabels([cand("x", 0, 0, 10), cand("y", 10, 0, 20)], new Set())).toEqual(["y"]);
    expect(placeLabels([cand("b", 0, 0, 10, "beta"), cand("a", 10, 0, 10, "alpha")], new Set())).toEqual(["a"]);
  });

  it("keeps last frame's labels when a newcomer only grazes them (hysteresis)", () => {
    // y overlaps x by 4 px: without history the larger y wins; with x shown before, x stays
    const x = cand("x", 0, 0, 10), y: LabelCand = { ...cand("y", 46, 0, 20) };
    expect(placeLabels([x, y], new Set())).toEqual(["y"]);
    expect(placeLabels([x, y], new Set(["x"]))).toEqual(["x"]);
    expect(placeLabels([cand("a", 0), cand("b", 100)], new Set(), 1)).toHaveLength(1);
  });
});

const e = (src: string, dst: string, weight = 1, group: AggEdge["group"] = "calls"): AggEdge => ({ src, dst, group, weight, count: 1 });

describe("edges", () => {
  it("selection mode keeps only edges touching the selection or hover", () => {
    const agg = [e("a", "b"), e("b", "c"), e("c", "d")];
    const r = declutterEdges(agg, "selection", new Set(["b"]));
    expect(r.edges.map((x) => x.src + x.dst)).toEqual(["ab", "bc"]);
    expect(r.hidden).toBe(1);
  });

  it("all mode is untouched under the limit and keeps touching + heaviest above it", () => {
    const agg = Array.from({ length: 10 }, (_, i) => e(`s${i}`, `d${i}`, i));
    expect(declutterEdges(agg, "all", new Set(), 20).limited).toBe(false);
    const r = declutterEdges(agg, "all", new Set(["s0"]), 5, 2);
    expect(r.limited).toBe(true);
    expect(r.edges.map((x) => x.src).sort()).toEqual(["s0", "s8", "s9"]);
    expect(r.hidden).toBe(7);
  });

  it("aggregates by parent pair, summing weights and dropping self-loops", () => {
    const parent: Record<string, string> = { a1: "A", a2: "A", b1: "B" };
    const lifted = liftEdges([e("a1", "b1", 2), e("a2", "b1", 3), e("a1", "a2", 9)], (id) => parent[id] ?? id);
    expect(lifted).toEqual([{ src: "A", dst: "B", group: "calls", weight: 5, count: 2 }]);
  });
});

describe("portals", () => {
  it("merges chips by destination and stacks them per wall side", () => {
    const out = mergePortals([
      { dest: "n1", label: "api", side: "e", at: [0, 0, 0] },
      { dest: "n1", label: "api", side: "e", at: [2, 0, 2] },
      { dest: "n2", label: "db", side: "e", at: [0, 0, 0] },
      { dest: "n3", label: "worker", side: "n", at: [0, 0, 0] },
    ]);
    expect(out.map((p) => [p.text, p.side, p.stack])).toEqual([
      ["→ api ×2", "e", 0],
      ["→ db", "e", 1],
      ["→ worker", "n", 0],
    ]);
    expect(out[0]!.at).toEqual([1, 0, 1]);
  });
});
