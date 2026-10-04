// Viewer UX v2 (P7, ADR-0061): pure, testable placement rules for labels, edges and portals.
import type { AggEdge } from "./edges";

// -- labels ------------------------------------------------------------------------------------------
export type Rect = [number, number, number, number]; // x0, y0, x1, y1 (px)

export interface LabelCand {
  id: string;
  rect: Rect;
  priority: number; // labelPriority()
  area: number; // footprint, px²
  name: string;
}

const PROBLEM = new Set(["drift", "missing", "orphan", "needs_review", "stale"]);

/** Problem statuses first, then ports, then everything else (footprint and name break ties). */
export function labelPriority(status: string, isPort: boolean): number {
  return PROBLEM.has(status) ? 2 : isPort ? 1 : 0;
}

export const HYSTERESIS_PX = 6;

function overlaps(a: Rect, b: Rect): boolean {
  return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}

function shrink(r: Rect, m: number): Rect {
  return [r[0] + m, r[1] + m, r[2] - m, r[3] - m];
}

/**
 * Greedy placement: candidates in priority order (problem > port > other), labels shown last
 * time before new ones of the same priority (hysteresis), then larger footprint, then name. A
 * label is placed when its rectangle overlaps no placed one; a label shown last time is tested
 * with a rectangle shrunk by HYSTERESIS_PX, so small camera moves do not make labels flicker.
 */
export function placeLabels(cands: LabelCand[], prev: ReadonlySet<string>, max = 400): string[] {
  const order = [...cands].sort(
    (a, b) =>
      b.priority - a.priority ||
      Number(prev.has(b.id)) - Number(prev.has(a.id)) ||
      b.area - a.area ||
      (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) ||
      (a.id < b.id ? -1 : 1),
  );
  const taken: Rect[] = [];
  const out: string[] = [];
  for (const c of order) {
    if (out.length >= max) break;
    const r = prev.has(c.id) ? shrink(c.rect, HYSTERESIS_PX) : c.rect;
    if (taken.some((t) => overlaps(r, t))) continue;
    taken.push(c.rect);
    out.push(c.id);
  }
  return out;
}

// -- edges -------------------------------------------------------------------------------------------
export type EdgeMode = "all" | "selection" | "aggregated";
export const EDGE_MODES: EdgeMode[] = ["all", "selection", "aggregated"];
export const EDGE_LIMIT = 150; // above this many visible edges, "all" shows the selection + the heaviest

/** Re-aggregate edges after mapping their ends (e.g. to the parent of a small representative). */
export function liftEdges(agg: AggEdge[], lift: (id: string) => string): AggEdge[] {
  const acc = new Map<string, AggEdge>();
  for (const e of agg) {
    const s = lift(e.src), d = lift(e.dst);
    if (s === d) continue;
    const key = `${s}|${d}|${e.group}`;
    const a = acc.get(key);
    if (a) {
      a.weight += e.weight;
      a.count += e.count;
    } else acc.set(key, { src: s, dst: d, group: e.group, weight: e.weight, count: e.count });
  }
  return [...acc.values()].sort((a, b) => (a.src + a.dst + a.group < b.src + b.dst + b.group ? -1 : 1));
}

export interface Decluttered {
  edges: AggEdge[];
  hidden: number;
  limited: boolean; // true when the limit kicked in
}

/**
 * `selection`: only edges touching the selection or hover. `all` / `aggregated`: everything up to
 * `limit`; above it, the touching edges plus the `topN` heaviest (deterministic order).
 */
export function declutterEdges(
  agg: AggEdge[],
  mode: EdgeMode,
  touching: ReadonlySet<string>,
  limit = EDGE_LIMIT,
  topN = Math.round(EDGE_LIMIT / 3),
): Decluttered {
  const touches = (e: AggEdge): boolean => touching.has(e.src) || touching.has(e.dst);
  if (mode === "selection") {
    const edges = agg.filter(touches);
    return { edges, hidden: agg.length - edges.length, limited: false };
  }
  if (agg.length <= limit) return { edges: agg, hidden: 0, limited: false };
  const heavy = [...agg]
    .sort((a, b) => b.weight - a.weight || (a.src + a.dst + a.group < b.src + b.dst + b.group ? -1 : 1))
    .slice(0, topN);
  const keep = new Set<AggEdge>([...heavy, ...agg.filter(touches)]);
  const edges = agg.filter((e) => keep.has(e));
  return { edges, hidden: agg.length - edges.length, limited: true };
}

// -- portals -----------------------------------------------------------------------------------------
export type WallSide = "n" | "e" | "s" | "w";

export interface PortalIn {
  dest: string;
  label: string;
  side: WallSide;
  at: [number, number, number]; // world point on the wall
}

export interface PortalOut {
  dest: string;
  text: string; // "→ api" or "→ api ×3"
  side: WallSide;
  at: [number, number, number];
  stack: number; // index within its wall side, for a pixel offset
  count: number;
}

/** One chip per destination ("→ api ×3"), stacked per wall side in label order. */
export function mergePortals(items: PortalIn[], max = 40): PortalOut[] {
  const by = new Map<string, PortalIn[]>();
  for (const p of items) by.set(p.dest, [...(by.get(p.dest) ?? []), p]);
  const merged = [...by.entries()].map(([dest, ps]) => {
    const n = ps.length;
    const at: [number, number, number] = [0, 0, 0];
    for (const p of ps) for (let i = 0; i < 3; i++) at[i]! += p.at[i]! / n;
    const sides = ps.map((p) => p.side).sort();
    return { dest, label: ps[0]!.label, side: sides[0]!, at, count: n };
  });
  merged.sort((a, b) => (a.side < b.side ? -1 : a.side > b.side ? 1 : a.label < b.label ? -1 : a.label > b.label ? 1 : a.dest < b.dest ? -1 : 1));
  const perSide = new Map<WallSide, number>();
  return merged.slice(0, max).map((m) => {
    const stack = perSide.get(m.side) ?? 0;
    perSide.set(m.side, stack + 1);
    return { dest: m.dest, text: `→ ${m.label}${m.count > 1 ? ` ×${m.count}` : ""}`, side: m.side, at: m.at, stack, count: m.count };
  });
}
