// Display-only text helpers: mentions inside summaries, suggestion dedup, the deterministic
// fallback card, and diff classification. No LLM is ever asked for anything (P5 decisions 3, 4).
import type { EpochInfo, LineageRow, NodeRow, StatusInfo, SuggestionRow } from "../data/types";

export type Segment = { text: string } | { nodeId: string; label: string };

/** `(n_xxx)` tokens become links when in `mentions`, and are stripped otherwise. */
export function renderMentions(text: string, mentions: string[], labelOf: (id: string) => string | null): Segment[] {
  const out: Segment[] = [];
  const re = /\s?\((n_[0-9a-f]{20})\)|\bn_[0-9a-f]{20}\b/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    const id = m[1] ?? m[0];
    const at = m.index ?? 0;
    if (at > last) out.push({ text: text.slice(last, at) });
    const label = mentions.includes(id) ? labelOf(id) : null;
    if (label !== null) out.push({ text: " " }, { nodeId: id, label });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  // merge adjacent text segments
  const merged: Segment[] = [];
  for (const s of out) {
    const prev = merged[merged.length - 1];
    if ("text" in s && prev && "text" in prev) prev.text += s.text;
    else merged.push({ ...s });
  }
  return merged;
}

/**
 * Suggestions for one spec item at several containment levels merge (P5 decision 2): keep the
 * one whose code node is highest in containment; the others are collapsed into its card.
 */
export function dedupSuggestions(
  sugg: SuggestionRow[],
  depthOf: (id: string) => number,
): Array<{ primary: SuggestionRow; collapsed: SuggestionRow[] }> {
  const bySpec = new Map<string, SuggestionRow[]>();
  for (const s of sugg) {
    if (s.state !== "open") continue;
    const list = bySpec.get(s.specId) ?? [];
    list.push(s);
    bySpec.set(s.specId, list);
  }
  const out: Array<{ primary: SuggestionRow; collapsed: SuggestionRow[] }> = [];
  for (const spec of [...bySpec.keys()].sort()) {
    const list = bySpec.get(spec)!.sort(
      (a, b) => depthOf(a.codeId) - depthOf(b.codeId) || b.confidence - a.confidence || (a.codeId < b.codeId ? -1 : 1),
    );
    out.push({ primary: list[0]!, collapsed: list.slice(1) });
  }
  return out;
}

export interface Digest {
  kind: string;
  counts: Record<string, number>;
  ports: string[];
  resources: string[];
  risks: string[];
  rollup: Record<string, number>;
  status: string;
}

/** The deterministic card shown when a node has no LLM summary. */
export function fallbackCard(label: string, d: Digest): string {
  const parts: string[] = [`${label} is a ${d.kind.replace(/_/g, " ")}`];
  const kids = Object.entries(d.counts)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} ${plural(k.replace(/_/g, " "), n)}`);
  if (kids.length) parts.push(`containing ${kids.join(", ")}`);
  let s = parts.join(" ") + ".";
  if (d.ports.length) s += ` Ports: ${d.ports.slice(0, 4).join(", ")}${d.ports.length > 4 ? ", …" : ""}.`;
  if (d.resources.length) s += ` Touches ${d.resources.slice(0, 4).join(", ")}${d.resources.length > 4 ? ", …" : ""}.`;
  if (d.risks.length) s += ` Risks: ${d.risks.join(", ")}.`;
  const roll = Object.entries(d.rollup).filter(([k]) => k !== "none");
  if (roll.length) s += ` Inside: ${roll.map(([k, n]) => `${n} ${k}`).join(", ")}.`;
  s += ` Status: ${d.status}.`;
  return s;
}

export type DiffClass = "added" | "removed" | "renamed" | "transition" | "unchanged";

export interface DiffEntry {
  id: string; // id in B (or in A for removed)
  cls: DiffClass;
  oldId?: string;
  oldName?: string;
  from?: string;
  to?: string;
}

/** Classify every node of A → B, with ids mapped through the lineage composed along the chain. */
export function classifyDiff(
  a: { nodes: NodeRow[]; status: Map<string, StatusInfo> },
  b: { nodes: NodeRow[]; status: Map<string, StatusInfo> },
  lineage: Map<string, string>, // old id (in A) -> id in B
): DiffEntry[] {
  const inB = new Map(b.nodes.map((n) => [n.id, n]));
  const inA = new Map(a.nodes.map((n) => [n.id, n]));
  const image = new Set<string>();
  const out: DiffEntry[] = [];
  for (const n of a.nodes) {
    const target = lineage.get(n.id) ?? n.id;
    if (!inB.has(target)) {
      out.push({ id: n.id, cls: "removed" });
      continue;
    }
    image.add(target);
    const from = a.status.get(n.id)?.status;
    const to = b.status.get(target)?.status;
    if (target !== n.id) out.push({ id: target, cls: "renamed", oldId: n.id, oldName: n.qname, from, to });
    else if (from !== undefined && to !== undefined && from !== to) out.push({ id: target, cls: "transition", from, to });
    else out.push({ id: target, cls: "unchanged" });
  }
  for (const n of b.nodes) if (!image.has(n.id) && !inA.has(n.id)) out.push({ id: n.id, cls: "added" });
  return out.sort((x, y) => (x.id < y.id ? -1 : x.id > y.id ? 1 : x.cls < y.cls ? -1 : 1));
}

/** Compose lineage from A to B along the parent chain (epochs oldest → newest). */
export function composeLineage(chain: EpochInfo[], rows: Map<string, LineageRow[]>): Map<string, string> {
  const fwd = new Map<string, string>();
  for (const e of chain) {
    const step = new Map((rows.get(e.epochId) ?? []).filter((r) => r.method !== "ambiguous").map((r) => [r.oldId, r.newId]));
    for (const [src, cur] of fwd) if (step.has(cur)) fwd.set(src, step.get(cur)!);
    for (const [o, n] of step) if (!fwd.has(o) && ![...fwd.values()].includes(o)) fwd.set(o, n);
  }
  return fwd;
}

function plural(word: string, n: number): string {
  if (n === 1) return word;
  return /(s|x|ch|sh)$/.test(word) ? `${word}es` : `${word}s`;
}
