// Mirror of Python's workflows.project(mode="containment") and narrate.levels(), so replay can
// re-project without a server. Parity with Python is tested on every fixture workflow and depth.
import type { StepRow } from "../data/types";

export interface CoarseStep {
  seq: number;
  nodeIds: string[]; // what the coarse step highlights: the depth-k ancestors of its nodes
  touched: string[]; // every node in the span, first-seen order
  span: [number, number]; // inclusive fine seq range
}

export type Ancestry = Map<string, string[]>; // node -> [root, ..., node]

export function ancestry(parentOf: Map<string, string | null>): Ancestry {
  const memo: Ancestry = new Map();
  const chain = (id: string): string[] => {
    const hit = memo.get(id);
    if (hit) return hit;
    const p = parentOf.get(id);
    const c = (p !== undefined && p !== null && parentOf.has(p) ? chain(p) : []).concat([id]);
    memo.set(id, c);
    return c;
  };
  for (const id of [...parentOf.keys()].sort()) chain(id);
  return memo;
}

export function project(steps: StepRow[], depth: number, anc: Ancestry): CoarseStep[] {
  if (depth < 0) throw new Error("depth must be >= 0");
  const key = (s: StepRow): string[] => {
    const out: string[] = [];
    for (const n of s.nodeIds) {
      const chain = anc.get(n) ?? [n];
      const a = chain[Math.min(depth, chain.length - 1)]!;
      if (!out.includes(a)) out.push(a);
    }
    return out;
  };
  const keys = steps.map(key);
  const groups: number[][] = [];
  let prev: string | null = null;
  keys.forEach((k, i) => {
    const kk = JSON.stringify(k);
    if (groups.length && kk === prev) groups[groups.length - 1]!.push(i);
    else groups.push([i]);
    prev = kk;
  });
  return groups.map((members, gi) => {
    const touched: string[] = [];
    for (const m of members) for (const n of steps[m]!.nodeIds) if (!touched.includes(n)) touched.push(n);
    return {
      seq: gi,
      nodeIds: [...keys[members[0]!]!],
      touched,
      span: [steps[members[0]!]!.seq, steps[members[members.length - 1]!]!.seq],
    };
  });
}

/** Detail levels with a distinct projection, coarse first (Python: narrate.levels). */
export function levels(steps: StepRow[], anc: Ancestry): Array<{ level: number; coarse: CoarseStep[] }> {
  const maxDepth = Math.max(1, ...steps.flatMap((s) => s.nodeIds.map((n) => (anc.get(n) ?? []).length)));
  const out: Array<{ level: number; coarse: CoarseStep[] }> = [];
  let prev = "";
  for (let k = 1; k <= maxDepth; k++) {
    const coarse = project(steps, k, anc);
    const spans = JSON.stringify(coarse.map((c) => c.span));
    if (spans !== prev) {
      out.push({ level: k, coarse });
      prev = spans;
    }
    if (coarse.length === steps.length) break;
  }
  return out;
}

/** The coarse step containing a fine playhead: re-projection never moves the playhead. */
export function coarseIndexOf(coarse: CoarseStep[], fineSeq: number): number {
  const i = coarse.findIndex((c) => c.span[0] <= fineSeq && fineSeq <= c.span[1]);
  return i < 0 ? 0 : i;
}
