// P10 M6 (ADR-0079): the Architecture tab. A C4 view (context + containers) derived by the Python
// side and stored with its own deterministic layout (c4_layout); this module only draws it. Same
// visual language as the map: theme tokens, line styles for the infra statuses, badges.
// No write actions; clicking an element shows its card and offers "open in map".
import type { C4Element, C4View } from "../data/types";
import { DASH_PX, type Theme } from "../theme";
import { h } from "./dom";

const SVG = "http://www.w3.org/2000/svg";

/** Infra status -> line style (visual tokens): problems are never color-only. */
export const INFRA_LINE: Record<string, keyof typeof DASH_PX> = {
  deployed: "solid",
  in_use: "solid",
  wired: "solid",
  undeployed: "dashed",
  ambiguous: "dashed",
  unwired: "dash_dot",
  infra_orphan: "dotted",
  unknown: "solid",
};

/** A short badge for an infra status (map labels and element corners). */
export function infraBadge(status: string | undefined): string {
  switch (status) {
    case "deployed":
    case "wired":
      return "☁";
    case "undeployed":
      return "∅☁";
    case "unwired":
      return "⚠";
    case "ambiguous":
      return "?☁";
    case "infra_orphan":
      return "∅";
    default:
      return "";
  }
}

export const KIND_LABEL: Record<string, string> = {
  person: "person",
  system: "system",
  external_system: "external system",
  deployment_unit: "deployment unit",
  static_site: "static site",
  code_container: "code container",
  managed_datastore: "datastore",
  managed_queue: "queue",
  bucket: "bucket",
  scheduler: "scheduler",
};

function s<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}, ...kids: Array<Node | string>): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const c of kids) el.append(c);
  return el;
}

function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.4 ? cut.slice(0, sp) : cut) + "…";
}

export interface ArchOptions {
  onSelect: (el: C4Element) => void;
}

export class ArchitectureView {
  readonly el = h("div", { class: "arch hidden", id: "architecture", role: "region", "aria-label": "architecture (C4)" });
  private readonly svgHost = h("div", { class: "arch-canvas" });
  private view: C4View | null = null;
  private selected: string | null = null;
  private highlight = new Set<string>();

  constructor(private readonly opts: ArchOptions) {
    this.el.append(this.svgHost);
  }

  set(view: C4View | null, theme: Theme, selected: string | null, highlight: Set<string>): void {
    this.view = view;
    this.selected = selected;
    this.highlight = highlight;
    this.render(theme);
  }

  elementFor(nodeIds: string[]): C4Element | null {
    if (!this.view) return null;
    for (const id of nodeIds) {
      const hit = this.view.elements.find((e) => e.level === "container" && e.nodeIds.includes(id));
      if (hit) return hit;
    }
    return null;
  }

  private render(theme: Theme): void {
    const v = this.view;
    if (!v || !v.elements.length) {
      this.svgHost.replaceChildren(h("p", { class: "muted arch-empty" }, "No architecture in this epoch."));
      return;
    }
    const boxes = v.layout;
    let maxX = 0, maxY = 0;
    for (const b of boxes.values()) { maxX = Math.max(maxX, b.x + b.w); maxY = Math.max(maxY, b.y + b.h); }
    const pad = 24;
    const svg = s("svg", { viewBox: `${-pad} ${-pad} ${maxX + 2 * pad} ${maxY + 2 * pad}`, class: "c4", role: "img", "aria-label": `C4 container view${v.env ? ` (${v.env})` : ""}` });
    const defs = s("defs");
    defs.append(s("marker", { id: "c4-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
      s("path", { d: "M0,0 L10,5 L0,10 z", fill: theme.edge })));
    svg.append(defs);
    const byId = new Map(v.elements.map((e) => [e.id, e]));
    // the system boundary first, then relations, then elements on top
    const sys = v.elements.find((e) => e.kind === "system");
    const sb = sys ? boxes.get(sys.id) : undefined;
    if (sys && sb) {
      svg.append(s("rect", { x: sb.x, y: sb.y, width: sb.w, height: sb.h, rx: 14, fill: theme.surface, stroke: theme.text_muted, "stroke-width": 1.5, "stroke-dasharray": "10 6", "data-element-id": sys.id, "data-kind": "system" }),
        s("text", { x: sb.x + 14, y: sb.y + 22, fill: theme.text_muted, "font-size": 14, "font-weight": 600 }, `${clip(sys.name, 60)} · system boundary`));
    }
    const center = (id: string): [number, number, number, number, number, number] | null => {
      const b = boxes.get(id);
      return b ? [b.x + b.w / 2, b.y + b.h / 2, b.x, b.y, b.w, b.h] : null;
    };
    const exitPoint = (from: [number, number, number, number, number, number], to: [number, number]): [number, number] => {
      const [cx, cy, , , w, h0] = from;
      const dx = to[0] - cx, dy = to[1] - cy;
      if (!dx && !dy) return [cx, cy];
      const t = Math.min(Math.abs((w / 2) / (dx || 1e-9)), Math.abs((h0 / 2) / (dy || 1e-9)));
      return [cx + dx * t, cy + dy * t];
    };
    for (const r of v.relations) {
      if (!byId.has(r.src) || !byId.has(r.dst)) continue;
      const a = center(r.src), b = center(r.dst);
      if (!a || !b) continue;
      const p1 = exitPoint(a, [b[0], b[1]]), p2 = exitPoint(b, [a[0], a[1]]);
      const envVars = Array.isArray(r.attrs.env_vars) ? (r.attrs.env_vars as string[]) : [];
      const hot = this.selected !== null && (r.src === this.selected || r.dst === this.selected);
      const g = s("g", { class: `c4-rel${hot ? " hot" : ""}`, "data-kind": r.kind, "data-src": r.src, "data-dst": r.dst });
      g.append(s("title", {}, `${r.kind}${envVars.length ? `: ${envVars.join(", ")}` : ""}`));
      g.append(s("line", { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1], stroke: hot ? theme.emphasis.color : theme.edge, "stroke-width": hot ? 2.4 : 1.4, "marker-end": "url(#c4-arrow)" }));
      g.append(s("text", { x: (p1[0] + p2[0]) / 2 + 4, y: (p1[1] + p2[1]) / 2 - 4, fill: theme.text_muted, "font-size": 11 }, r.kind));
      svg.append(g);
    }
    for (const e of v.elements) {
      if (e.kind === "system") continue;
      const b = boxes.get(e.id);
      if (!b) continue;
      svg.append(this.element(e, b, theme));
    }
    this.svgHost.replaceChildren(svg);
  }

  private element(e: C4Element, b: { x: number; y: number; w: number; h: number }, theme: Theme): SVGGElement {
    const status = typeof e.attrs.infra_status === "string" ? e.attrs.infra_status : "unknown";
    const pal = (theme as unknown as { infra: Record<string, { stroke: string; fill: string }> }).infra;
    const col = e.kind === "person" || e.kind === "external_system" ? { stroke: theme.text_muted, fill: theme.surface } : (pal[status] ?? pal.unknown!);
    const dash = (DASH_PX[INFRA_LINE[status] ?? "solid"] ?? []).join(" ");
    const sel = e.id === this.selected, hl = this.highlight.has(e.id);
    const stroke = sel ? theme.emphasis.color : col.stroke;
    const width = sel ? 3.2 : hl ? 2.6 : 1.8;
    const g = s("g", { class: `c4-el${sel ? " selected" : ""}${hl ? " highlight" : ""}`, tabindex: 0, role: "button",
      "data-element-id": e.id, "data-kind": e.kind, "data-infra": status, "aria-label": `${KIND_LABEL[e.kind] ?? e.kind} ${e.name}: ${status}` });
    g.addEventListener("click", () => this.opts.onSelect(e));
    g.addEventListener("keydown", (ev) => { if ((ev as KeyboardEvent).key === "Enter") this.opts.onSelect(e); });
    const common = { fill: col.fill, stroke, "stroke-width": width, "stroke-dasharray": e.kind === "external_system" ? "6 4" : dash };
    if (e.kind === "person") {
      const r = Math.min(b.h * 0.22, 16);
      g.append(s("circle", { cx: b.x + b.w / 2, cy: b.y + r, r, ...common }),
        s("rect", { x: b.x, y: b.y + 2 * r + 4, width: b.w, height: b.h - 2 * r - 4, rx: 18, ...common }));
    } else if (e.kind === "managed_datastore" || e.kind === "bucket") {
      const ry = 10;
      g.append(s("path", { d: `M${b.x},${b.y + ry} a${b.w / 2},${ry} 0 0,1 ${b.w},0 v${b.h - 2 * ry} a${b.w / 2},${ry} 0 0,1 ${-b.w},0 z`, ...common }),
        s("path", { d: `M${b.x},${b.y + ry} a${b.w / 2},${ry} 0 0,0 ${b.w},0`, fill: "none", stroke, "stroke-width": width }));
    } else if (e.kind === "managed_queue") {
      g.append(s("rect", { x: b.x, y: b.y + 8, width: b.w, height: b.h - 16, rx: (b.h - 16) / 2, ...common }));
    } else {
      g.append(s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 10, ...common }));
    }
    const ty = e.kind === "person" ? b.y + b.h - 30 : b.y + b.h / 2 - 6;
    g.append(s("text", { x: b.x + b.w / 2, y: ty, "text-anchor": "middle", fill: theme.text, "font-size": 13, "font-weight": 600 }, clip(e.name, 28)));
    const sub = [KIND_LABEL[e.kind] ?? e.kind];
    if (Array.isArray(e.attrs.deploys) && e.attrs.deploys.length) sub.push(`runs ${(e.attrs.deploys as string[]).join(", ")}`);
    g.append(s("text", { x: b.x + b.w / 2, y: ty + 18, "text-anchor": "middle", fill: theme.text_muted, "font-size": 11 }, clip(sub.join(" · "), 34)));
    const badge = infraBadge(status) + (Array.isArray(e.attrs.unwired) && e.attrs.unwired.length ? " ⚠" : "");
    if (badge && e.kind !== "person" && e.kind !== "external_system") {
      g.append(s("text", { x: b.x + 8, y: b.y + 16, fill: col.stroke, "font-size": 12, class: "c4-badge" }, badge));
    }
    const worst = typeof e.attrs.coverage_worst === "string" ? e.attrs.coverage_worst : "";
    if (worst && worst !== "none") {
      const sc = (theme.status as Record<string, { stroke: string; fill: string }>)[worst] ?? theme.status.none;
      const label = clip(worst.replace(/_/g, " "), 16);
      const w = 8 + label.length * 6.2;
      g.append(s("rect", { x: b.x + b.w - w - 6, y: b.y + b.h - 22, width: w, height: 16, rx: 4, fill: sc.fill, stroke: sc.stroke, "stroke-width": 1.2, class: "c4-cov" }),
        s("text", { x: b.x + b.w - w / 2 - 6, y: b.y + b.h - 10, "text-anchor": "middle", fill: theme.text, "font-size": 10 }, label));
    }
    g.append(s("title", {}, `${e.name} (${KIND_LABEL[e.kind] ?? e.kind}) · infra: ${status}${worst ? ` · requirements: ${worst}` : ""}`));
    return g;
  }
}
