// The viewer application: toolbar, map, panel timeline, replay, epoch scrubber and diff overlay.
// Read-only by design (P5 decision 9): no button runs the LLM or edits ad2v.yaml; where that is the
// next step, the equivalent CLI command is shown with a copy button.
import type { DataSource } from "../data/DataSource";
import type {
  EdgeRow,
  EpochInfo,
  JudgmentRow,
  LineageRow,
  LinkRow,
  Meta,
  NarrationRow,
  NodeRow,
  StatusInfo,
  SuggestionRow,
  SummaryRow,
  WorkflowRow,
} from "../data/types";
import { ancestry, type Ancestry } from "../model/projection";
import {
  classifyDiff,
  composeLineage,
  dedupSuggestions,
  fallbackCard,
  renderMentions,
  type DiffEntry,
  type Digest,
} from "../model/text";
import { PORT_KINDS, SceneTree } from "../model/tree";
import { MapScene, type MapModel } from "../render/scene";
import {
  loadThemeChoice,
  resolveTheme,
  saveThemeChoice,
  statusColors,
  statusStyle,
  THEMES,
  type ThemeChoice,
} from "../theme";
import { copyText, h } from "./dom";
import { Replay } from "./replay";

const RESOURCE_KINDS = new Set(["datastore", "queue", "external_service", "llm_endpoint", "ui"]);

interface EpochData {
  epoch: EpochInfo;
  nodes: NodeRow[];
  byId: Map<string, NodeRow>;
  tree: SceneTree;
  anc: Ancestry;
  edges: EdgeRow[];
  statusN: Map<string, StatusInfo>;
  statusE: Map<string, StatusInfo>;
  rollups: Map<string, Record<string, number>>;
  summaries: Map<string, SummaryRow>;
  links: LinkRow[];
  judgments: Map<string, JudgmentRow>;
  suggestions: SuggestionRow[];
  workflows: WorkflowRow[];
  lineage: LineageRow[];
}

export interface PerfProbe {
  firstRenderMs: number;
  fps: number;
  drawCalls: number;
  visibleNodes: number;
  triangles: number;
  heapMB: number | null;
  ready: boolean;
}

declare global {
  interface Window {
    __ad2vPerf?: PerfProbe;
    __ad2v?: App;
  }
}

export class App {
  private meta!: Meta;
  private epochs: EpochInfo[] = [];
  private cache = new Map<string, EpochData>();
  private cur!: EpochData;
  private effective = false;
  private showSuggestions = false;
  private compareFrom: string | null = null;
  private diffMap: Map<string, DiffEntry> | null = null;
  private ghosts: MapModel["ghosts"] = [];
  private selection: string | null = null;
  private replay: Replay | null = null;
  private timer: number | null = null;
  private speed = 1;
  private themeChoice: ThemeChoice = loadThemeChoice();
  private scene!: MapScene;
  private readonly t0 = performance.now();

  // DOM
  private readonly root: HTMLElement;
  private readonly mapEl = h("div", { class: "map", id: "map" });
  private readonly tooltip = h("div", { class: "tooltip", role: "tooltip" });
  private readonly timeline = h("div", { class: "timeline", id: "timeline", "aria-live": "polite" });
  private readonly panel = h("aside", { class: "panel", id: "panel" });
  private readonly toolbar = h("header", { class: "toolbar" });
  private readonly scrubber = h("footer", { class: "scrubber", id: "scrubber" });
  private readonly replayBar = h("div", { class: "replaybar hidden", id: "replaybar" });
  private readonly searchBox = h("input", { type: "search", id: "search", placeholder: "Search  ( / )", "aria-label": "search nodes" });
  private readonly searchResults = h("div", { class: "search-results hidden" });
  private readonly hud = h("div", { class: "hud hidden", id: "hud" });

  constructor(root: HTMLElement, private readonly ds: DataSource) {
    this.root = root;
  }

  async start(): Promise<void> {
    this.meta = await this.ds.meta();
    this.epochs = await this.ds.epochs();
    if (!this.epochs.length) throw new Error("this file has no materialized epoch (run: ad2v materialize --epochs last:10)");
    this.buildDom();
    const themeName = resolveTheme(this.themeChoice);
    document.documentElement.dataset.theme = themeName;
    this.scene = new MapScene(this.mapEl, THEMES[themeName], {
      hover: (id, x, y) => this.onHover(id, x, y),
      click: (id) => id && this.select(id, true),
      dblclick: (id) => id && this.enter(id),
      portal: (id) => this.select(id, true, true),
      view: () => undefined,
    });
    this.scene.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const head = this.epochs.find((e) => e.isHead) ?? this.epochs[this.epochs.length - 1]!;
    await this.showEpoch(head.epochId, false);
    this.startPerfProbe();
    window.__ad2v = this;
    this.card(this.welcomeCard());
  }

  // -- data --------------------------------------------------------------------------------------
  private async load(epochId: string): Promise<EpochData> {
    const hit = this.cache.get(epochId);
    if (hit) return hit;
    const ds = this.ds;
    const [nodes, layout, glyphs, edges, statusN, statusE, rollups, summaries, links, judgments, suggestions, workflows, lineage] =
      await Promise.all([
        ds.nodes(epochId), ds.layout(epochId), ds.glyphs(epochId), ds.edges(epochId),
        ds.status(epochId, "normative"), ds.status(epochId, "effective"), ds.rollups(epochId),
        ds.summaries(epochId), ds.links(epochId), ds.judgments(epochId), ds.suggestions(epochId),
        ds.workflows(epochId), ds.lineage(epochId),
      ]);
    const tree = new SceneTree(nodes, layout, glyphs);
    const anc = ancestry(new Map(nodes.map((n) => [n.id, n.parentId])));
    const d: EpochData = {
      epoch: this.epochs.find((e) => e.epochId === epochId)!,
      nodes, byId: new Map(nodes.map((n) => [n.id, n])), tree, anc, edges, statusN, statusE, rollups,
      summaries, links, judgments, suggestions, workflows, lineage,
    };
    this.cache.set(epochId, d);
    return d;
  }

  private label = (id: string): string => this.cur.byId.get(id)?.name ?? id;

  private async showEpoch(epochId: string, keepView: boolean): Promise<void> {
    this.cur = await this.load(epochId);
    await this.refreshDiff();
    this.pushModel(keepView);
    this.renderToolbarState();
    this.renderScrubber();
  }

  private pushModel(keepView = true): void {
    const d = this.cur;
    const groups = dedupSuggestions(d.suggestions, (id) => d.tree.nodes.get(id)?.depth ?? 99);
    const sugNodes = new Set<string>();
    for (const g of groups) {
      sugNodes.add(g.primary.specId);
      sugNodes.add(g.primary.codeId);
    }
    const links: MapModel["links"] = [];
    if (this.selection !== null) {
      for (const l of d.links)
        if (l.specId && l.codeId && (l.specId === this.selection || l.codeId === this.selection))
          links.push({ spec: l.specId, code: l.codeId, kind: "normative" });
      for (const g of groups)
        if (g.primary.specId === this.selection || g.primary.codeId === this.selection)
          links.push({ spec: g.primary.specId, code: g.primary.codeId, kind: "suggestion" });
    }
    this.scene.setModel(
      {
        tree: d.tree,
        status: this.effective ? d.statusE : d.statusN,
        rollups: d.rollups,
        edges: d.edges,
        label: this.label,
        effective: this.effective,
        suggestionNodes: sugNodes,
        suggestionPairs: groups.map((g) => [g.primary.specId, g.primary.codeId] as [string, string]),
        showSuggestions: this.showSuggestions,
        links,
        diff: this.diffMap,
        ghosts: this.ghosts,
      },
      keepView,
    );
  }

  private async refreshDiff(): Promise<void> {
    this.diffMap = null;
    this.ghosts = [];
    if (this.compareFrom === null || this.compareFrom === this.cur.epoch.epochId) return;
    const a = await this.load(this.compareFrom);
    const b = this.cur;
    const chain = this.epochs.filter((e) => e.seq > a.epoch.seq && e.seq <= b.epoch.seq);
    const rows = new Map<string, LineageRow[]>();
    for (const e of chain) rows.set(e.epochId, (await this.load(e.epochId)).lineage);
    const fwd = composeLineage(chain, rows);
    const entries = classifyDiff(
      { nodes: a.nodes, status: this.effective ? a.statusE : a.statusN },
      { nodes: b.nodes, status: this.effective ? b.statusE : b.statusN },
      fwd,
    );
    this.diffMap = new Map(entries.filter((e) => e.cls !== "removed").map((e) => [e.id, e]));
    this.ghosts = entries
      .filter((e) => e.cls === "removed")
      .map((e) => ({ id: e.id, box: a.tree.nodes.get(e.id)?.box, label: a.byId.get(e.id)?.name ?? e.id }))
      .filter((g): g is MapModel["ghosts"][number] => g.box !== undefined);
    this.card(this.changesCard(entries, a));
  }

  // -- DOM ---------------------------------------------------------------------------------------
  private buildDom(): void {
    const chat = h("div", { class: "chat" },
      h("input", { type: "text", disabled: true, placeholder: "Conversational agent arrives with MCP (P6)", "aria-label": "chat (not available yet)" }));
    const collapse = h("button", { class: "icon", title: "collapse panel", "aria-label": "collapse panel", onclick: () => this.root.classList.toggle("panel-collapsed") }, "❯");
    this.panel.append(h("div", { class: "panel-head" }, h("strong", {}, "Timeline"), collapse), this.timeline, chat);
    this.root.append(this.toolbar, h("main", { class: "body" }, this.mapEl, this.panel), this.replayBar, this.scrubber, this.tooltip, this.hud);
    this.mapEl.append(this.searchResults);
    this.searchBox.addEventListener("input", () => this.search(this.searchBox.value));
    this.searchBox.addEventListener("keydown", (e) => {
      if (e.key === "Enter") (this.searchResults.querySelector("button") as HTMLButtonElement | null)?.click();
      if (e.key === "Escape") { this.searchBox.blur(); this.searchResults.classList.add("hidden"); }
    });
    document.addEventListener("keydown", (e) => this.onKey(e));
    if (new URLSearchParams(location.search).get("perf") === "1") this.hud.classList.remove("hidden");
  }

  private renderToolbarState(): void {
    const diffCount = [...this.cur.statusE].filter(([, s]) => s.status !== s.normative).length;
    const llm = this.meta.llmProviders.length ? ` · LLM: ${this.meta.llmProviders.join(", ")}` : "";
    const wfSel = h("select", { id: "workflows", "aria-label": "replay a workflow", onchange: (e) => {
      const v = (e.target as HTMLSelectElement).value;
      if (v) void this.startReplay(v);
    } }, h("option", { value: "" }, "Replay a workflow…"),
      ...this.cur.workflows.filter((w) => w.side === "code").map((w) => h("option", { value: w.workflowId }, w.name)));
    this.toolbar.replaceChildren(
      h("span", { class: "brand" }, "ad2v"),
      h("span", { class: "sys" }, `${this.meta.systemName}${llm}`),
      this.searchBox,
      h("button", { id: "home", title: "system view (Home)", onclick: () => this.scene.home() }, "⌂"),
      h("button", { id: "toggle-effective", class: this.effective ? "on" : "", "aria-pressed": String(this.effective), title: "normative status (deterministic) or effective status (with LLM judgments)",
        onclick: () => this.toggleEffective() }, `${this.effective ? "Effective" : "Normative"} status · ${diffCount} differ`),
      h("button", { id: "toggle-suggestions", class: this.showSuggestions ? "on" : "", "aria-pressed": String(this.showSuggestions),
        onclick: () => { this.showSuggestions = !this.showSuggestions; this.pushModel(); this.renderToolbarState(); } }, `Suggestions ${this.showSuggestions ? "on" : "off"}`),
      wfSel,
      h("button", { id: "toggle-theme", title: "theme: system / dark / light", onclick: () => this.cycleTheme() }, `Theme: ${this.themeChoice}`),
    );
  }

  private toggleEffective(): void {
    this.effective = !this.effective;
    void this.refreshDiff().then(() => {
      this.pushModel();
      this.renderToolbarState();
    });
  }

  private cycleTheme(): void {
    const order: ThemeChoice[] = ["system", "dark", "light"];
    this.themeChoice = order[(order.indexOf(this.themeChoice) + 1) % 3]!;
    saveThemeChoice(this.themeChoice);
    this.applyTheme();
  }

  applyTheme(choice?: ThemeChoice): void {
    if (choice) this.themeChoice = choice;
    const name = resolveTheme(this.themeChoice);
    document.documentElement.dataset.theme = name;
    this.scene.setTheme(THEMES[name], name);
    this.renderToolbarState();
  }

  private renderScrubber(): void {
    const items = this.epochs.map((e) => {
      const sel = e.epochId === this.cur.epoch.epochId;
      const cmp = e.epochId === this.compareFrom;
      return h("button", {
        class: `epoch${sel ? " sel" : ""}${cmp ? " cmp" : ""}`,
        "data-seq": e.seq,
        title: `#${e.seq} ${e.changeKind}${e.commit ? " " + e.commit.slice(0, 10) : ""}${e.label ? " [" + e.label + "]" : ""}\nClick: show this epoch. Shift+click: compare from it.`,
        onclick: (ev) => void this.onEpochClick(e, (ev as MouseEvent).shiftKey),
      },
      h("span", { class: "seq" }, `#${e.seq}`),
      h("span", { class: "sha" }, e.commit ? e.commit.slice(0, 7) : "—"),
      h("span", { class: "kind" }, e.changeKind),
      e.pinned ? h("span", { class: "pin", title: "pinned" }, "\u{1F4CC}") : null,
      e.label ? h("span", { class: "label" }, e.label) : null);
    });
    const diffBtn = h("button", { id: "toggle-diff", class: this.compareFrom ? "on" : "", onclick: () => void this.toggleDiff() },
      this.compareFrom ? `Diff #${this.epochs.find((x) => x.epochId === this.compareFrom)?.seq} → #${this.cur.epoch.seq}` : "Compare with parent");
    this.scrubber.replaceChildren(h("span", { class: "scrub-title" }, "Epochs"), ...items, diffBtn);
  }

  private async onEpochClick(e: EpochInfo, shift: boolean): Promise<void> {
    if (shift) {
      this.compareFrom = e.epochId;
      await this.showEpoch(this.cur.epoch.epochId, true);
      return;
    }
    if (this.compareFrom !== null) {
      // keep diffing parent -> selected
      const prev = this.epochs.filter((x) => x.seq < e.seq).pop();
      this.compareFrom = prev ? prev.epochId : null;
    }
    this.stopReplay();
    await this.showEpoch(e.epochId, true);
  }

  async toggleDiff(): Promise<void> {
    if (this.compareFrom !== null) this.compareFrom = null;
    else {
      const prev = this.epochs.filter((x) => x.seq < this.cur.epoch.seq).pop();
      if (!prev) return;
      this.compareFrom = prev.epochId;
    }
    await this.showEpoch(this.cur.epoch.epochId, true);
  }

  /** For tests and deep links: compare epoch `fromSeq` → `toSeq`. */
  async compare(fromSeq: number, toSeq: number): Promise<void> {
    const a = this.epochs.find((e) => e.seq === fromSeq), b = this.epochs.find((e) => e.seq === toSeq);
    if (!a || !b) return;
    this.compareFrom = a.epochId;
    await this.showEpoch(b.epochId, true);
  }

  // -- selection, navigation ------------------------------------------------------------------------
  select(id: string, addCard: boolean, fly = false): void {
    this.selection = id;
    this.scene.setSelection(id);
    this.pushModel();
    if (fly) this.scene.flyTo(id);
    if (addCard) void this.nodeCard(id).then((c) => this.card(c));
  }

  enter(id: string): void {
    const n = this.cur.tree.nodes.get(id);
    if (!n) return;
    const target = n.children.length ? id : (this.cur.tree.parent(id) ?? id);
    this.scene.setFocus(target);
    this.select(id, true);
    this.scene.flyTo(target);
  }

  /** For tests: select and frame a node by qualified name. */
  focusByName(qname: string, enter = true): string | null {
    const n = this.cur.nodes.find((x) => x.qname === qname);
    if (!n) return null;
    if (enter) this.enter(n.id);
    else this.select(n.id, true, true);
    return n.id;
  }

  private onKey(e: KeyboardEvent): void {
    const typing = (e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "SELECT";
    if (typing && e.key !== "Escape") return;
    const sel = this.selection;
    const pan = 60;
    switch (e.key) {
      case "/": e.preventDefault(); this.searchBox.focus(); break;
      case "Home": this.scene.setFocus(null); this.scene.home(); break;
      case "Escape": case "Backspace": {
        const f = this.scene.getFocus() ?? sel;
        const p = f ? this.cur.tree.parent(f) : null;
        this.scene.setFocus(p);
        if (p) this.scene.flyTo(p); else this.scene.home();
        break;
      }
      case "Tab": {
        if (!sel) return;
        e.preventDefault();
        const p = this.cur.tree.parent(sel);
        const sib = p ? this.cur.tree.nodes.get(p)!.children : this.cur.tree.roots;
        const i = sib.indexOf(sel);
        const next = sib[(i + (e.shiftKey ? -1 : 1) + sib.length) % sib.length]!;
        this.select(next, true);
        this.scene.follow(next);
        break;
      }
      case "Enter": if (sel) this.enter(sel); break;
      case "ArrowLeft": case "a": this.scene.panBy(-pan, 0); break;
      case "ArrowRight": case "d": this.scene.panBy(pan, 0); break;
      case "ArrowUp": case "w": this.scene.panBy(0, -pan); break;
      case "ArrowDown": case "s": this.scene.panBy(0, pan); break;
      case "+": case "=": this.zoomCenter(1.25); break;
      case "-": this.zoomCenter(0.8); break;
      case " ": if (this.replay) { e.preventDefault(); this.togglePlay(); } break;
    }
  }

  private zoomCenter(f: number): void {
    const r = this.mapEl.getBoundingClientRect();
    this.scene.zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  }

  private search(q: string): void {
    const s = q.trim().toLowerCase();
    if (!s) { this.searchResults.classList.add("hidden"); return; }
    const scored = this.cur.nodes
      .map((n) => {
        const name = n.name.toLowerCase(), qn = n.qname.toLowerCase();
        const score = name.startsWith(s) ? 0 : qn.startsWith(s) ? 1 : name.includes(s) ? 2 : qn.includes(s) ? 3 : 9;
        return { n, score };
      })
      .filter((x) => x.score < 9)
      .sort((a, b) => a.score - b.score || a.n.qname.length - b.n.qname.length || (a.n.qname < b.n.qname ? -1 : 1))
      .slice(0, 20);
    this.searchResults.replaceChildren(...scored.map(({ n }) =>
      h("button", { onclick: () => { this.searchResults.classList.add("hidden"); this.select(n.id, true, true); } },
        h("span", { class: "kind" }, n.kind), " ", n.name, h("span", { class: "muted" }, ` ${n.qname}`))));
    this.searchResults.classList.toggle("hidden", scored.length === 0);
  }

  private onHover(id: string | null, x: number, y: number): void {
    if (!id) { this.tooltip.classList.remove("show"); return; }
    const n = this.cur.byId.get(id)!;
    const st = (this.effective ? this.cur.statusE : this.cur.statusN).get(id);
    const card = this.cur.summaries.get(id)?.card ?? this.fallback(id);
    const colors = statusColors(THEMES[resolveTheme(this.themeChoice)], st?.status ?? "none");
    this.tooltip.replaceChildren(
      h("div", { class: "tt-title" }, n.name, h("span", { class: "kind" }, ` ${n.kind.replace(/_/g, " ")}`)),
      h("div", { class: "tt-status" }, h("span", { class: "swatch", style: `border-color:${colors.stroke};border-style:${cssLine(st?.status ?? "none")}` }),
        ` ${st?.status ?? "none"}${st?.provenance === "llm" ? " (AI)" : ""}`),
      h("div", { class: "tt-card" }, oneLine(stripIds(card))),
    );
    this.tooltip.style.left = `${x + 14}px`;
    this.tooltip.style.top = `${y + 14}px`;
    this.tooltip.classList.add("show");
  }

  // -- panel cards ----------------------------------------------------------------------------------
  private card(el: HTMLElement): void {
    this.timeline.append(el);
    el.scrollIntoView({ block: "end", behavior: this.scene?.reducedMotion ? "auto" : "smooth" });
  }

  private welcomeCard(): HTMLElement {
    const fake = this.meta.llmProviders.includes("fake");
    return h("section", { class: "card info" },
      h("h3", {}, `${this.meta.systemName}`),
      h("p", {}, "Zoom with the wheel, drag to pan, double-click to enter a box, Esc to go up, / to search, Home for the system view. Click a glyph to pin it here."),
      fake ? h("p", { class: "warn" }, "LLM content in this file comes from the deterministic “fake” provider (demo data, not a real model).") : null,
      h("p", { class: "muted" }, `format ${this.meta.formatVersion} · ${this.epochs.length} materialized epoch(s) · spec coverage ${this.meta.specCoverage}`));
  }

  private digest(id: string): Digest {
    const d = this.cur;
    const n = d.tree.nodes.get(id);
    const counts: Record<string, number> = {};
    const ports: string[] = [];
    const risks = new Set<string>();
    const stack = [...(n?.children ?? [])];
    const subtree = new Set<string>([id]);
    while (stack.length) {
      const c = stack.pop()!;
      subtree.add(c);
      const cn = d.tree.nodes.get(c)!;
      counts[cn.row.kind] = (counts[cn.row.kind] ?? 0) + 1;
      if (PORT_KINDS.has(cn.row.kind)) ports.push(cn.row.name);
      stack.push(...cn.children);
    }
    for (const c of subtree) if (d.tree.nodes.get(c)?.glyph?.modifiers.has_loop_risk) risks.add("IO or LLM inside a loop");
    const resources = new Set<string>();
    for (const e of d.edges) if (subtree.has(e.src) && RESOURCE_KINDS.has(d.byId.get(e.dst)?.kind ?? "")) resources.add(d.byId.get(e.dst)!.name);
    return {
      kind: d.byId.get(id)?.kind ?? "node",
      counts, ports: ports.sort(), resources: [...resources].sort(), risks: [...risks],
      rollup: d.rollups.get(id) ?? {}, status: (this.effective ? d.statusE : d.statusN).get(id)?.status ?? "none",
    };
  }

  private fallback(id: string): string {
    return fallbackCard(this.label(id), this.digest(id));
  }

  private mentionsEl(text: string, mentions: string[]): HTMLElement {
    const p = h("p", {});
    for (const seg of renderMentions(text, mentions, (x) => this.cur.byId.get(x)?.name ?? null)) {
      if ("nodeId" in seg) p.append(h("a", { href: "#", class: "mention", onclick: (e) => { e.preventDefault(); this.select(seg.nodeId, true, true); } }, seg.label));
      else p.append(seg.text);
    }
    return p;
  }

  private async nodeCard(id: string): Promise<HTMLElement> {
    const d = this.cur;
    const n = d.byId.get(id)!;
    const detail = await this.ds.nodeDetail(d.epoch.epochId, id);
    const sn = d.statusN.get(id), se = d.statusE.get(id);
    const sum = d.summaries.get(id);
    const sec = (title: string, open: boolean, ...kids: Array<Node | string | null>): HTMLElement =>
      h("details", { open }, h("summary", {}, title), ...kids);
    const fly = h("button", { class: "linkish", onclick: () => this.select(id, false, true) }, "fly here");
    const reasons = (detail?.reasons ?? []).slice(0, 6).map((r) => h("li", {}, `${String(r.status)}: ${String(r.kind)}`));
    const header = h("div", { class: "card-head" },
      h("h3", {}, n.name, " ", h("span", { class: "kind" }, n.kind.replace(/_/g, " "))),
      h("div", { class: "qname" }, n.qname), fly,
      h("div", { class: "statuses" },
        statusChip("normative", sn?.status ?? "none"),
        se && se.status !== se.normative ? statusChip(`effective${se.provenance === "llm" ? " (AI)" : ""}`, se.status) : null),
      reasons.length ? h("ul", { class: "reasons" }, ...reasons) : null);
    // summary
    const summaryEl = sum?.card || sum?.deep
      ? h("div", {}, sum.card ? this.mentionsEl(sum.card, sum.mentions) : null, sum.deep ? this.mentionsEl(sum.deep, sum.mentions) : null,
          h("p", { class: "muted" }, `summary by ${sum.model ?? "?"}${sum.provider === "fake" ? " (fake provider, demo)" : ""}`))
      : h("div", {}, h("p", {}, this.fallback(id)), h("p", { class: "muted" }, "deterministic card (no LLM summary in this file)"));
    // links + judgments
    const myLinks = d.links.filter((l) => (l.specId === id || l.codeId === id) && l.method !== "none");
    const linkEls = myLinks.map((l) => {
      const other = l.specId === id ? l.codeId : l.specId;
      const j = d.judgments.get(l.linkId);
      return h("div", { class: "link" },
        h("div", {}, h("a", { href: "#", onclick: (e) => { e.preventDefault(); if (other) this.select(other, true, true); } }, other ? this.label(other) : "—"),
          ` · ${l.method} · `, statusChip("", l.status)),
        l.evidence.length ? h("div", { class: "muted" }, "evidence: " + l.evidence.map((ev) => String(ev.kind)).join(", ")) : null,
        j ? h("div", { class: "judgment" },
          h("strong", {}, `judge: ${j.verdict}`), ` (${j.confidence.toFixed(2)}${j.valid ? "" : ", invalid"})${j.provider === "fake" ? " · fake provider" : j.model ? ` · ${j.model}` : ""}`,
          h("p", {}, j.rationale),
          j.evidence.length ? h("ul", {}, ...j.evidence.map((ev) => h("li", {}, `${ev.side} lines ${ev.start_line}–${ev.end_line}: ${ev.claim}`))) : null)
          : null);
    });
    // suggestions (deduplicated across containment levels)
    const groups = dedupSuggestions(d.suggestions, (x) => d.tree.nodes.get(x)?.depth ?? 99)
      .filter((g) => g.primary.specId === id || g.primary.codeId === id || g.collapsed.some((c) => c.codeId === id));
    const sugEls = groups.map((g) => {
      const s = g.primary;
      const cmd = `ad2v suggestions accept ${s.suggestionId.slice(0, 12)} --manifest ad2v.yaml`;
      return h("div", { class: "suggestion" },
        h("div", {}, `${this.label(s.specId)} ↔ ${this.label(s.codeId)} · confidence ${s.confidence.toFixed(2)} · BM25 rank ${s.rank}${s.provider === "fake" ? " · fake provider" : ""}`),
        h("p", {}, s.rationale),
        g.collapsed.length ? h("p", { class: "muted" }, "also at other levels: " + g.collapsed.map((c) => this.label(c.codeId)).join(", ")) : null,
        h("div", { class: "cmd" }, h("code", {}, cmd), h("button", { class: "copy", onclick: (e) => void copyText(cmd).then((ok) => { (e.target as HTMLElement).textContent = ok ? "copied" : "copy failed"; }) }, "copy")),
        h("p", { class: "muted" }, "Accepting edits ad2v.yaml, so it stays a CLI step (human confirmation)."));
    });
    // risk
    const attrs = detail?.attrs ?? {};
    const risk = Array.isArray(attrs.risk) && attrs.risk.length
      ? h("p", {}, `${(attrs.risk as string[]).join(", ")} · severity ${String(attrs.severity ?? "?")} · rank ${String(attrs.severity_rank ?? "?")}`)
      : null;
    // workflows through
    const wids = await this.ds.workflowsThrough(d.epoch.epochId, id);
    const wfEls = wids.map((w) => {
      const wf = d.workflows.find((x) => x.workflowId === w);
      return h("div", { class: "wf" }, h("button", { class: "play", title: "replay", onclick: () => void this.startReplay(w) }, "▶"), ` ${wf?.name ?? w}`);
    });
    // history
    const hist = await this.ds.statusHistory(id);
    const renamed = d.lineage.filter((l) => l.newId === id);
    const histEl = h("div", {},
      hist.length ? h("p", {}, hist.map((x) => `#${x.seq} ${x.status}`).join(" → ")) : h("p", { class: "muted" }, "no other materialized epoch has this node"),
      ...renamed.map((r) => h("p", {}, `renamed from ${r.oldId} (${r.method}, score ${r.score})`)));
    return h("section", { class: "card node", "data-node": id },
      header,
      sec("Summary", true, summaryEl),
      myLinks.length ? sec(`Spec ↔ code links (${myLinks.length})`, true, ...linkEls) : null,
      sugEls.length ? sec(`Suggestions (${sugEls.length})`, true, ...sugEls) : null,
      risk ? sec("Risk", true, risk) : null,
      wfEls.length ? sec(`Workflows through here (${wfEls.length})`, false, ...wfEls) : null,
      sec("History", false, histEl));
  }

  private changesCard(entries: DiffEntry[], a: EpochData): HTMLElement {
    const b = this.cur;
    const name = (e: DiffEntry): string => (e.cls === "removed" ? a.byId.get(e.id)?.name : b.byId.get(e.id)?.name) ?? e.id;
    const item = (e: DiffEntry, text: string): HTMLElement =>
      h("li", {}, h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); if (e.cls !== "removed") this.select(e.id, true, true); } }, name(e)), ` ${text}`);
    const tr = entries.filter((e) => e.cls === "transition" || (e.cls === "renamed" && e.from !== e.to));
    const sections: Array<[string, HTMLElement[]]> = [
      ["Status transitions", tr.map((e) => item(e, `${e.from} → ${e.to}`))],
      ["Added", entries.filter((e) => e.cls === "added").map((e) => item(e, ""))],
      ["Removed", entries.filter((e) => e.cls === "removed").map((e) => item(e, ""))],
      ["Renamed", entries.filter((e) => e.cls === "renamed").map((e) => item(e, `(was ${e.oldName})`))],
    ];
    return h("section", { class: "card changes" },
      h("h3", {}, `Changes #${a.epoch.seq} → #${b.epoch.seq}`),
      ...sections.map(([t, els]) => h("details", { open: els.length > 0 && els.length < 30 }, h("summary", {}, `${t} (${els.length})`), h("ul", {}, ...els.slice(0, 200)))));
  }

  // -- replay -------------------------------------------------------------------------------------------
  async startReplay(workflowId: string): Promise<void> {
    const d = this.cur;
    const wf = d.workflows.find((w) => w.workflowId === workflowId);
    if (!wf) return;
    const [steps, narrations] = await Promise.all([this.ds.steps(d.epoch.epochId, workflowId), this.ds.narrations(d.epoch.epochId, workflowId)]);
    this.stopReplay();
    this.replay = new Replay(workflowId, wf.name, steps, d.anc, narrations as NarrationRow[]);
    this.replayBar.classList.remove("hidden");
    this.card(h("section", { class: "card info" }, h("h3", {}, `Replay: ${wf.name}`), h("p", { class: "muted" }, `${steps.length} fine steps · ${this.replay.levels.length} detail levels`)));
    this.renderReplay(true);
  }

  stopReplay(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.replay = null;
    this.replayBar.classList.add("hidden");
    this.scene?.setReplay(null);
  }

  private togglePlay(): void {
    if (!this.replay) return;
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null; }
    else this.timer = window.setInterval(() => {
      if (!this.replay || this.replay.atEnd) { if (this.timer !== null) clearInterval(this.timer); this.timer = null; this.renderReplay(false); return; }
      this.replay.step(1);
      this.renderReplay(true);
    }, 1400 / this.speed);
    this.renderReplay(false);
  }

  /** For tests: set the replay detail level (index into the distinct levels) and step. */
  replayTo(levelIdx: number, stepIdx: number): { playhead: number; level: number; index: number } | null {
    const r = this.replay;
    if (!r) return null;
    r.setLevel(levelIdx);
    r.playhead = r.coarse[Math.min(stepIdx, r.coarse.length - 1)]!.span[0];
    this.renderReplay(true);
    return { playhead: r.playhead, level: r.level, index: r.index };
  }

  setReplayLevel(levelIdx: number): { playhead: number; level: number; index: number } | null {
    const r = this.replay;
    if (!r) return null;
    r.setLevel(levelIdx);
    this.renderReplay(true);
    return { playhead: r.playhead, level: r.level, index: r.index };
  }

  private renderReplay(announce: boolean): void {
    const r = this.replay;
    if (!r) return;
    const cur = r.current, prev = r.previous;
    this.scene.setReplay({ nodes: cur.nodeIds, prev: prev?.nodeIds ?? [] });
    this.scene.follow(this.cur.tree.representative(cur.nodeIds[0] ?? "", this.scene.visibleLods()) ?? cur.nodeIds[0] ?? "");
    const slider = h("input", { type: "range", id: "detail", min: 0, max: r.levels.length - 1, value: r.levelIdx, "aria-label": "detail level",
      oninput: (e) => { r.setLevel(Number((e.target as HTMLInputElement).value)); this.renderReplay(true); } });
    const speed = h("select", { "aria-label": "speed", onchange: (e) => { this.speed = Number((e.target as HTMLSelectElement).value); if (this.timer !== null) { this.togglePlay(); this.togglePlay(); } } },
      ...[0.5, 1, 2, 4].map((s) => h("option", { value: s, selected: s === this.speed }, `${s}×`)));
    this.replayBar.replaceChildren(
      h("strong", {}, r.name),
      h("button", { title: "previous step", onclick: () => { r.step(-1); this.renderReplay(true); } }, "⏮"),
      h("button", { id: "play", title: "play / pause (space)", onclick: () => this.togglePlay() }, this.timer !== null ? "⏸" : "▶"),
      h("button", { title: "next step", onclick: () => { r.step(1); this.renderReplay(true); } }, "⏭"),
      h("span", { id: "replay-pos" }, `step ${r.index + 1}/${r.coarse.length} · fine ${r.playhead}`),
      h("label", {}, "detail ", slider, ` level ${r.level}`),
      speed,
      h("button", { title: "stop replay", onclick: () => this.stopReplay() }, "✕"));
    if (announce) {
      const nar = r.narration();
      const text = nar.text ?? this.fallbackStep(cur.nodeIds, prev?.nodeIds ?? [], r.index);
      this.card(h("section", { class: "card step", "data-level": r.level, "data-index": r.index },
        nar.parent ? h("p", { class: "subtitle" }, nar.parent) : null,
        h("p", {}, stripIds(text)),
        h("p", { class: "muted" }, `level ${r.level} · step ${r.index + 1}/${r.coarse.length} · fine span ${cur.span[0]}–${cur.span[1]}${nar.text ? "" : " · deterministic narration"}`)));
    }
  }

  private fallbackStep(cur: string[], prev: string[], i: number): string {
    const kinds = new Set<string>();
    const ps = new Set(prev), cs = new Set(cur);
    for (const e of this.cur.edges) if (ps.has(e.src) && cs.has(e.dst)) kinds.add(e.kind);
    return `Step ${i + 1}: ${cur.map(this.label).join(", ")}${kinds.size ? ` via ${[...kinds].join(", ")}` : ""}.`;
  }

  // -- perf probe ------------------------------------------------------------------------------------------
  private startPerfProbe(): void {
    let first = -1;
    const tick = (): void => {
      const s = this.scene.stats();
      if (first < 0 && s.drawCalls > 0) first = performance.now() - this.t0;
      const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
      window.__ad2vPerf = {
        firstRenderMs: first, fps: s.fps, drawCalls: s.drawCalls, visibleNodes: s.visibleNodes, triangles: s.triangles,
        heapMB: mem ? mem.usedJSHeapSize / 1048576 : null, ready: first >= 0,
      };
      if (!this.hud.classList.contains("hidden"))
        this.hud.textContent = `${s.fps.toFixed(0)} fps · ${s.drawCalls} draw calls · ${s.visibleNodes} visible · ${(s.triangles / 1000).toFixed(0)}k tris${mem ? ` · ${(mem.usedJSHeapSize / 1048576).toFixed(0)} MB` : ""}`;
    };
    setInterval(tick, 250);
    requestAnimationFrame(() => requestAnimationFrame(tick));
  }
}

function statusChip(label: string, status: string): HTMLElement {
  const style = statusStyle(status);
  return h("span", { class: `chip st-${status}`, "data-line": style.line, title: `${status}: ${style.line} line${style.decoration !== "none" ? ", " + style.decoration.replace("_", " ") : ""}` },
    label ? `${label}: ` : "", status);
}

function cssLine(status: string): string {
  const l = statusStyle(status).line;
  return l === "dash_dot" ? "dashed" : l;
}

function stripIds(s: string): string {
  return s.replace(/\s?\(n_[0-9a-f]{20}\)/g, "").replace(/\bn_[0-9a-f]{20}\b/g, "").replace(/\s+\[mentions:[^\]]*\]/, "");
}

function oneLine(s: string): string {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > 200 ? t.slice(0, 197) + "…" : t;
}
