// The containment tree of one epoch, visibility by LOD, and representatives (the deepest
// visible ancestor-or-self of a node) used to draw edges and replay steps at any zoom.
import type { Box, GlyphRow, NodeRow } from "../data/types";
import { Lod, lodFor } from "./lod";

export const PORT_KINDS = new Set(["http_route", "mcp_tool", "cli_command", "event_consumer"]);

export interface TreeNode {
  row: NodeRow;
  box: Box;
  glyph: GlyphRow | undefined;
  children: string[];
  depth: number;
}

export class SceneTree {
  readonly nodes = new Map<string, TreeNode>();
  readonly roots: string[] = [];

  constructor(rows: NodeRow[], layout: Map<string, Box>, glyphs: Map<string, GlyphRow>) {
    for (const r of rows) {
      const box = layout.get(r.id);
      if (!box) continue; // no layout row: not drawable
      this.nodes.set(r.id, { row: r, box, glyph: glyphs.get(r.id), children: [], depth: 0 });
    }
    for (const [id, n] of this.nodes) {
      const p = n.row.parentId;
      if (p !== null && this.nodes.has(p)) this.nodes.get(p)!.children.push(id);
      else this.roots.push(id);
    }
    const setDepth = (id: string, d: number): void => {
      const n = this.nodes.get(id)!;
      n.depth = d;
      n.children.sort();
      for (const c of n.children) setDepth(c, d + 1);
    };
    this.roots.sort();
    for (const r of this.roots) setDepth(r, 0);
  }

  parent(id: string): string | null {
    const p = this.nodes.get(id)?.row.parentId ?? null;
    return p !== null && this.nodes.has(p) ? p : null;
  }

  ancestors(id: string): string[] {
    const out: string[] = [];
    let p = this.parent(id);
    while (p !== null) {
      out.push(p);
      p = this.parent(p);
    }
    return out;
  }

  /**
   * Visible nodes and their LOD. A root is always visible. A child is visible when its parent is
   * Open (or, for a port, when its parent shows Detail or more) and its own footprint is ≥ 8 px.
   */
  visible(pxOf: (b: Box) => number, prev: Map<string, Lod>): Map<string, Lod> {
    const out = new Map<string, Lod>();
    const visit = (id: string, forced: boolean): void => {
      const n = this.nodes.get(id)!;
      let lod = lodFor(pxOf(n.box), prev.get(id));
      if (forced && lod < Lod.Silhouette) lod = Lod.Silhouette;
      if (lod === Lod.Hidden) return;
      out.set(id, lod);
      for (const c of n.children) {
        const isPort = PORT_KINDS.has(this.nodes.get(c)!.row.kind);
        if (isPort ? lod >= Lod.Detail : lod === Lod.Open) visit(c, isPort);
      }
    };
    for (const r of this.roots) visit(r, true);
    return out;
  }

  /** Deepest visible ancestor-or-self. */
  representative(id: string, visible: Map<string, Lod>): string | null {
    let cur: string | null = this.nodes.has(id) ? id : null;
    while (cur !== null && !visible.has(cur)) cur = this.parent(cur);
    return cur;
  }
}
