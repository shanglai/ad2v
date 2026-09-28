// Edges at LOD: drawn between the visible representatives of their endpoints, weights summed.
import type { EdgeRow } from "../data/types";

export type EdgeGroup = "calls" | "data" | "messages" | "exposes" | "external" | "imports";

const GROUP: Record<string, EdgeGroup> = {
  calls: "calls",
  reads: "data",
  writes: "data",
  publishes: "messages",
  consumes: "messages",
  exposes: "exposes",
  invokes_external: "external",
  invokes_llm: "external",
  imports: "imports",
};

export const DEFAULT_GROUPS: ReadonlySet<EdgeGroup> = new Set(["calls", "data", "messages", "exposes", "external"]);

export interface AggEdge {
  src: string;
  dst: string;
  group: EdgeGroup;
  weight: number;
  count: number; // underlying edges
}

export function groupOf(kind: string): EdgeGroup | null {
  return GROUP[kind] ?? null; // annotated_as and hierarchy edges are not drawn as edges
}

export function aggregateEdges(
  edges: EdgeRow[],
  rep: (id: string) => string | null,
  groups: ReadonlySet<EdgeGroup> = DEFAULT_GROUPS,
): AggEdge[] {
  const acc = new Map<string, AggEdge>();
  for (const e of edges) {
    const g = groupOf(e.kind);
    if (g === null || !groups.has(g)) continue;
    const s = rep(e.src);
    const d = rep(e.dst);
    if (s === null || d === null || s === d) continue;
    const key = `${s}|${d}|${g}`;
    const a = acc.get(key);
    if (a) {
      a.weight += e.weight;
      a.count += 1;
    } else acc.set(key, { src: s, dst: d, group: g, weight: e.weight, count: 1 });
  }
  return [...acc.values()].sort((a, b) => (a.src + a.dst + a.group < b.src + b.dst + b.group ? -1 : 1));
}
