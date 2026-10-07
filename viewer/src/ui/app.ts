// The viewer application: toolbar, map, panel timeline, replay, epoch scrubber and diff overlay.
// Read-only by design (P5 decision 9): no button runs the LLM or edits ad2v.yaml; where that is the
// next step, the equivalent CLI command is shown with a copy button.
import type { DataSource } from "../data/DataSource";
import type {
  Box,
  EdgeRow,
  EpochInfo,
  GlyphRow,
  JudgmentRow,
  LineageRow,
  LinkRow,
  Meta,
  NarrationRow,
  NodeRow,
  SceneSlice,
  StatusInfo,
  SuggestionRow,
  SummaryRow,
  WorkflowRow,
} from "../data/types";
import { Lod } from "../model/lod";
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
import { EDGE_MODES, type EdgeMode } from "../model/declutter";
import { ChatPanel } from "./chat";
import { legendPanel, notEvaluableNote } from "./legend";
import { Replay } from "./replay";

const RESOURCE_KINDS = new Set(["datastore", "queue", "external_service", "llm_endpoint", "ui"]);
const ALL = -1; // scene depth: the whole epoch
const APP_DEPTH = 1; // app mode: each slice brings a node's children; deeper levels load on demand
const MAX_INTENT_ROOTS = 24;

/** What `ad2v_show` asks the map to do (its structuredContent), P6 §5. */
export interface ShowIntent {
  intent: "focus" | "fit" | "path" | "replay" | "diff";
  nodes: string[];
  epoch?: string | null;
  workflowId?: string | null;
  detailLevel?: number | null;
  epochFrom?: string | null;
  epochTo?: string | null;
  theme?: "auto" | "light" | "dark";
}

export interface AppOptions {
  /** "app": the compact MCP App inside a chat (slices, no chat box, no scrubber). Default "full". */
  mode?: "full" | "app";
  /** The file name used in copyable CLI commands. */
  file?: string;
  intent?: ShowIntent;
  /** App mode: tell the host which node the user picked (ui/update-model-context). */
  onSelect?: (text: string) => void;
}

interface EpochData {
  epoch: EpochInfo;
  nodes: NodeRow[];
  byId: Map<string, NodeRow>;
  tree: SceneTree;
  anc: Ancestry;
  layout: Map<string, Box>;
  glyphs: Map<string, GlyphRow>;
  /** Nodes whose children are all loaded (every node in full mode). */
  expanded: Set<string>;
  complete: boolean;
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
  private legendEl: HTMLElement | null = null; // P8.1: the status legend overlay
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

  private readonly app: boolean;
  chat: ChatPanel | null = null;
  private readonly fileName: string;
  private readonly expanding = new Set<string>();
  private viewTimer: number | null = null;

  constructor(root: HTMLElement, private readonly ds: DataSource, private readonly opts: AppOptions = {}) {
    this.root = root;
    this.app = opts.mode === "app";
    this.fileName = opts.file ?? "project.ad2v";
    if (this.app && opts.intent?.theme && opts.intent.theme !== "auto") this.themeChoice = opts.intent.theme;
    else if (this.app) this.themeChoice = "system";
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
      view: () => this.onView(),
    });
    this.scene.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const it = this.opts.intent;
    const want = this.app ? (it?.intent === "diff" ? it.epochTo : it?.epoch) : null;
    const head = this.epochs.find((e) => e.epochId === want) ?? this.epochs.find((e) => e.isHead) ?? this.epochs[this.epochs.length - 1]!;
    await this.showEpoch(head.epochId, false);
    this.startPerfProbe();
    window.__ad2v = this;
    if (this.app && it) await this.applyIntent(it);
    else {
      this.card(this.welcomeCard());
      const hint = this.suggestionsHint();
      if (hint) this.card(hint);
    }
    if (this.chat) void this.chat.init();
  }

  // -- data --------------------------------------------------------------------------------------
  /** App mode: which slices to fetch first for an epoch (the intent's nodes); null = whole epoch. */
  private async initialRoots(epochId: string): Promise<Array<string | null>> {
    const it = this.opts.intent;
    if (!this.app || !it || it.intent === "diff") return [null];
    let ids = it.nodes;
    if (it.intent === "replay" && it.workflowId) {
      const steps = await this.ds.steps(epochId, it.workflowId);
      ids = [...ids, ...new Set(steps.flatMap((s) => s.nodeIds))];
    }
    ids = [...new Set(ids)].slice(0, MAX_INTENT_ROOTS);
    return ids.length ? ids : [null];
  }

  private async load(epochId: string): Promise<EpochData> {
    const hit = this.cache.get(epochId);
    if (hit) return hit;
    const ds = this.ds;
    const roots = epochId === (this.opts.intent?.epoch ?? null) || this.cache.size === 0 ? await this.initialRoots(epochId) : [null];
    const [slices, summaries, links, judgments, suggestions, workflows, lineage] = await Promise.all([
      Promise.all(roots.map((r) => ds.scene(epochId, r, r === null ? ALL : APP_DEPTH))),
      ds.summaries(epochId), ds.links(epochId), ds.judgments(epochId), ds.suggestions(epochId),
      ds.workflows(epochId), ds.lineage(epochId),
    ]);
    const d: EpochData = {
      epoch: this.epochs.find((e) => e.epochId === epochId)!,
      nodes: [], byId: new Map(), tree: new SceneTree([], new Map(), new Map()), anc: new Map(),
      layout: new Map(), glyphs: new Map(), expanded: new Set(), complete: false,
      edges: [], statusN: new Map(), statusE: new Map(), rollups: new Map(),
      summaries, links, judgments, suggestions, workflows, lineage,
    };
    this.absorb(d, slices);
    this.cache.set(epochId, d);
    return d;
  }

  /** Merge scene slices into an epoch's data and rebuild the tree (slices only ever add nodes). */
  private absorb(d: EpochData, slices: SceneSlice[]): void {
    const edgeKey = (e: EdgeRow): string => `${e.src}|${e.kind}|${e.dst}`;
    const seenEdges = new Set(d.edges.map(edgeKey));
    for (const s of slices) {
      for (const n of s.nodes) if (!d.byId.has(n.id)) { d.byId.set(n.id, n); d.nodes.push(n); }
      for (const [k, v] of s.layout) d.layout.set(k, v);
      for (const [k, v] of s.glyphs) d.glyphs.set(k, v);
      for (const [k, v] of s.normative) d.statusN.set(k, v);
      for (const [k, v] of s.effective) d.statusE.set(k, v);
      for (const [k, v] of s.rollups) d.rollups.set(k, v);
      for (const e of s.edges) if (!seenEdges.has(edgeKey(e))) { seenEdges.add(edgeKey(e)); d.edges.push(e); }
      if (s.complete) {
        d.complete = true;
        for (const n of s.nodes) d.expanded.add(n.id);
      } else if (s.rootId !== null) {
        const parent = new Map(s.nodes.map((n) => [n.id, n.parentId]));
        for (let p = parent.get(s.rootId) ?? null; p !== null; p = parent.get(p) ?? null) d.expanded.add(p);
        const kids = new Map<string, string[]>();
        for (const n of s.nodes) if (n.parentId !== null) (kids.get(n.parentId) ?? kids.set(n.parentId, []).get(n.parentId)!).push(n.id);
        let frontier = [s.rootId];
        for (let level = 0; level < s.depth; level++) {
          for (const f of frontier) d.expanded.add(f);
          frontier = frontier.flatMap((f) => kids.get(f) ?? []);
        }
      }
    }
    d.nodes.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    d.tree = new SceneTree(d.nodes, d.layout, d.glyphs);
    d.anc = ancestry(new Map(d.nodes.map((n) => [n.id, n.parentId])));
  }

  /** App mode: load a node's children when it is entered or zoomed open. */
  private async expand(id: string): Promise<void> {
    const d = this.cur;
    if (d.complete || d.expanded.has(id) || this.expanding.has(id)) return;
    this.expanding.add(id);
    try {
      this.absorb(d, [await this.ds.scene(d.epoch.epochId, id, APP_DEPTH)]);
      if (d === this.cur) this.pushModel(true);
    } finally {
      this.expanding.delete(id);
    }
  }

  private onView(): void {
    if (!this.app || this.cur?.complete) return;
    if (this.viewTimer !== null) clearTimeout(this.viewTimer);
    this.viewTimer = window.setTimeout(() => {
      this.viewTimer = null;
      const d = this.cur;
      const open = [...this.scene.visibleLods()]
        .filter(([id, l]) => l === Lod.Open && !d.expanded.has(id) && d.tree.nodes.get(id)?.glyph?.hasInterior)
        .map(([id]) => id)
        .slice(0, 6);
      for (const id of open) void this.expand(id);
    }, 200);
  }

  /** Names of nodes outside the loaded slices (app mode), fetched for cards. */
  private readonly extraNames = new Map<string, string>();
  private label = (id: string): string => this.cur.byId.get(id)?.name ?? this.extraNames.get(id) ?? id;

  private async ensureNames(ids: Array<string | null>): Promise<void> {
    const missing = [...new Set(ids)].filter((x): x is string => !!x && !this.cur.byId.has(x) && !this.extraNames.has(x)).slice(0, 20);
    const got = await Promise.all(missing.map((x) => this.ds.nodeDetail(this.cur.epoch.epochId, x)));
    got.forEach((g, i) => { if (g) this.extraNames.set(missing[i]!, g.node.name); });
  }

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
    const collapse = h("button", { class: "icon", title: "collapse panel", "aria-label": "collapse panel", onclick: () => this.root.classList.toggle("panel-collapsed") }, "❯");
    if (this.app) {
      // Inside a chat: the host is the conversation, so no chat box; no scrubber; one card at a time.
      this.root.classList.add("app-mode");
      this.panel.append(h("div", { class: "panel-head" }, h("strong", {}, "Details"), collapse), this.timeline);
      this.root.append(this.toolbar, h("main", { class: "body" }, this.mapEl, this.panel), this.replayBar, this.tooltip, this.hud);
    } else {
      // P7: the viewer's own chat (ad2v view --chat); disabled with the enabling command otherwise
      this.chat = new ChatPanel(
        {
          fileName: this.fileName,
          select: (id) => this.select(id, true, true),
          show: (it) => void this.applyIntent(it, false), // the chat turn is the card
          label: (id) => this.cur?.byId.get(id)?.name ?? null,
        },
        (el) => this.card(el),
      );
      this.panel.append(h("div", { class: "panel-head" }, h("strong", {}, "Timeline"), this.chat.meterEl, collapse), this.timeline, this.chat.el);
      this.root.append(this.toolbar, h("main", { class: "body" }, this.mapEl, this.panel), this.replayBar, this.scrubber, this.tooltip, this.hud);
    }
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
    if (this.app) return this.renderAppToolbar();
    const diffCount = [...this.cur.statusE].filter(([, s]) => s.status !== s.normative).length;
    const llm = this.meta.llmProviders.length ? ` · LLM: ${this.meta.llmProviders.join(", ")}` : "";
    const openSug = this.openSuggestions();
    const mode = this.scene.edgesMode;
    const stats = this.scene.edgeStats;
    const edgeSel = h("select", { id: "edge-mode", "aria-label": "which edges to draw",
      title: stats.limited || stats.hidden ? `${stats.hidden} edge(s) hidden; hover or select a node to see its edges` : "which edges to draw",
      onchange: (e) => { this.scene.setEdgeMode((e.target as HTMLSelectElement).value as EdgeMode); } },
      ...EDGE_MODES.map((m) => h("option", { value: m, selected: m === mode }, `Edges: ${m}`)));
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
        title: `${openSug} open link suggestion(s) from the LLM layer`,
        onclick: () => { this.showSuggestions = !this.showSuggestions; this.pushModel(); this.renderToolbarState(); } },
        `Suggestions ${this.showSuggestions ? "on" : "off"}`, openSug ? h("span", { class: "badge", id: "sug-count" }, String(openSug)) : null),
      edgeSel,
      wfSel,
      h("button", { id: "toggle-theme", title: "theme: system / dark / light", onclick: () => this.cycleTheme() }, `Theme: ${this.themeChoice}`),
      h("button", { id: "toggle-legend", class: this.legendEl ? "on" : "", "aria-pressed": String(!!this.legendEl),
        title: "what each status and line style means", onclick: () => this.toggleLegend() }, "Legend"),
    );
  }

  /** P8.1 (ADR-0066): the status legend, including `not_evaluable`. */
  toggleLegend(): void {
    if (this.legendEl) {
      this.legendEl.remove();
      this.legendEl = null;
    } else {
      this.legendEl = legendPanel(() => this.toggleLegend());
      this.root.append(this.legendEl);
    }
    this.renderToolbarState();
  }

  private openSuggestions(): number {
    return dedupSuggestions(this.cur.suggestions, (id) => this.cur.tree.nodes.get(id)?.depth ?? 99).length;
  }

  /** P7: once per browser, a hint when the file has open suggestions (localStorage may be unavailable). */
  private suggestionsHint(): HTMLElement | null {
    const n = this.openSuggestions();
    const key = "ad2v.hint.suggestions";
    try {
      if (!n || localStorage.getItem(key)) return null;
      localStorage.setItem(key, "1");
    } catch {
      if (!n) return null;
    }
    return h("section", { class: "card info hint", id: "sug-hint" },
      h("p", {}, `${n} open link suggestion(s) from the LLM layer. Turn on `, h("strong", {}, "Suggestions"), " in the toolbar to see them on the map; accept or reject them with ",
        h("code", {}, `ad2v suggestions list ${this.fileName} --open`), "."));
  }

  /** App mode: breadcrumbs of the selection, status toggle, theme, diff label and "Open full map". */
  private renderAppToolbar(): void {
    const d = this.cur;
    const at = this.selection ?? this.scene?.getFocus() ?? null;
    const path = at ? [...(d.anc.get(at) ?? [at])] : [];
    const crumbs = h("nav", { class: "crumbs", "aria-label": "breadcrumbs" },
      h("button", { class: "linkish", title: "system view", onclick: () => { this.scene.setFocus(null); this.scene.home(); } }, this.meta.systemName),
      ...path.filter((id) => d.tree.parent(id) !== null).flatMap((id) => [
        h("span", { class: "sep" }, "›"),
        h("button", { class: "linkish", onclick: () => this.enter(id) }, this.label(id)),
      ]));
    const diffCount = [...d.statusE].filter(([, s]) => s.status !== s.normative).length;
    const cmp = this.compareFrom ? this.epochs.find((x) => x.epochId === this.compareFrom) : undefined;
    const cmd = `ad2v view ${this.fileName}`;
    this.toolbar.replaceChildren(
      h("span", { class: "brand" }, "ad2v"),
      crumbs,
      ...(cmp ? [h("span", { class: "chip", id: "diff-label" }, `Diff #${cmp.seq} → #${d.epoch.seq}`)] : []),
      h("button", { id: "toggle-effective", class: this.effective ? "on" : "", "aria-pressed": String(this.effective), title: "normative status (deterministic) or effective status (with LLM judgments)",
        onclick: () => this.toggleEffective() }, `${this.effective ? "Effective" : "Normative"} · ${diffCount} differ`),
      h("button", { id: "toggle-theme", title: "theme: system / dark / light", onclick: () => this.cycleTheme() }, `Theme: ${this.themeChoice}`),
      h("button", { id: "open-full", title: "the full map runs locally: copy the command", onclick: () => this.card(
        h("section", { class: "card info" }, h("h3", {}, "Open the full map"),
          h("p", {}, "The app cannot start local programs. Run this in a terminal:"),
          h("div", { class: "cmd" }, h("code", {}, cmd), h("button", { class: "copy", onclick: (e) => void copyText(cmd).then((ok) => { (e.target as HTMLElement).textContent = ok ? "copied" : "copy failed"; }) }, "copy")))) }, "Open full map"),
    );
  }

  /** App mode: the host's theme (host context), or the system's. */
  setHostTheme(theme: "light" | "dark" | undefined): void {
    this.themeChoice = theme ?? "system";
    if (this.scene) this.applyTheme();
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
    if (this.app) {
      this.renderAppToolbar();
      const n = this.cur.byId.get(id);
      const st = (this.effective ? this.cur.statusE : this.cur.statusN).get(id);
      if (n) this.opts.onSelect?.(
        `On the ad2v map (${this.fileName}, epoch #${this.cur.epoch.seq}) the user selected ${n.name} ` +
        `[${n.kind}, ${st?.status ?? "none"}${st?.provenance === "llm" ? " (AI)" : ""}] ${n.qname} (${id}).`);
    }
  }

  enter(id: string, addCard = true): void {
    const go = (): void => {
      const n = this.cur.tree.nodes.get(id);
      if (!n) return;
      const target = n.children.length ? id : (this.cur.tree.parent(id) ?? id);
      this.scene.setFocus(target);
      this.select(id, addCard);
      this.scene.flyTo(target);
    };
    if (this.app && !this.cur.expanded.has(id)) void this.expand(id).then(go);
    else go();
  }

  /** App mode: carry out an `ad2v_show` intent (node ids + camera intent; never coordinates). */
  async applyIntent(it: ShowIntent, cards = true): Promise<void> {
    const ids = it.nodes.filter((x) => this.cur.byId.has(x));
    const instant = this.scene.reducedMotion;
    switch (it.intent) {
      case "focus":
        this.scene.setEmphasis(ids); // P6.1: dim the rest (ADR-0051)
        if (ids.length === 1) this.enter(ids[0]!, cards);
        else if (ids.length) { this.scene.fit(ids, instant); this.select(ids[0]!, cards); }
        break;
      case "fit":
        this.scene.fit(ids, instant);
        if (cards) this.card(this.listCard("Components", ids));
        break;
      case "path":
        this.scene.setReplay({ nodes: [], prev: [], path: ids });
        this.scene.setEmphasis(ids);
        this.scene.frameStep(ids, instant);
        if (cards) this.card(this.listCard("Path", ids, true));
        break;
      case "replay":
        if (it.workflowId) {
          await this.startReplay(it.workflowId);
          const r = this.replay;
          if (r && it.detailLevel) {
            const idx = r.levels.findIndex((l) => l.level >= it.detailLevel!);
            this.setReplayLevel(idx < 0 ? r.levels.length - 1 : idx);
          }
        }
        break;
      case "diff":
        if (it.epochFrom && it.epochTo) await this.compareIds(it.epochFrom, it.epochTo);
        if (ids.length) this.scene.fit(ids, instant);
        break;
    }
  }

  async compareIds(fromId: string, toId: string): Promise<void> {
    if (!this.epochs.some((e) => e.epochId === fromId) || !this.epochs.some((e) => e.epochId === toId)) return;
    this.compareFrom = fromId;
    await this.showEpoch(toId, true);
  }

  private listCard(title: string, ids: string[], ordered = false): HTMLElement {
    const items = ids.map((id) => h("li", {}, h("a", { href: "#", onclick: (e) => { e.preventDefault(); this.select(id, true, true); } }, this.label(id)),
      h("span", { class: "muted" }, ` ${this.cur.byId.get(id)?.kind.replace(/_/g, " ") ?? ""}`)));
    return h("section", { class: "card info list" }, h("h3", {}, `${title} (${ids.length})`), h(ordered ? "ol" : "ul", {}, ...items));
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
      case "Home": this.scene.setFocus(null); this.scene.setEmphasis(null); this.scene.home(); break;
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
    this.scene.setHover(id); // P7: a decluttered map shows the hovered node's edges
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
    if (this.app) {
      this.timeline.replaceChildren(el); // one card at a time inside a chat
      return;
    }
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
    if (!d.complete) await this.ensureNames([
      ...d.links.filter((l) => l.specId === id || l.codeId === id).flatMap((l) => [l.specId, l.codeId]),
      ...d.suggestions.filter((s) => s.specId === id || s.codeId === id).flatMap((s) => [s.specId, s.codeId]),
    ]);
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
      reasons.length ? h("ul", { class: "reasons" }, ...reasons) : null,
      (se?.status ?? sn?.status) === "not_evaluable"
        ? h("p", { class: "scope-note", id: "scope-note" },
            notEvaluableNote(typeof detail?.attrs?.language === "string" ? detail.attrs.language : undefined))
        : null);
    // P7 (ADR-0061): what is inside, with statuses; click to fly (labels on the map are culled)
    const kids = d.tree.nodes.get(id)?.children ?? [];
    const kidsEl = kids.length
      ? h("ul", { class: "children" }, ...[...kids]
        .sort((a, b) => (d.byId.get(a)?.name ?? a).localeCompare(d.byId.get(b)?.name ?? b))
        .slice(0, 60)
        .map((k) => h("li", {},
          h("button", { class: "linkish", onclick: () => this.select(k, true, true) }, d.byId.get(k)?.name ?? k),
          " ", statusChip("", (this.effective ? d.statusE : d.statusN).get(k)?.status ?? "none"))))
      : null;
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
      const cmd = `ad2v suggestions accept ${this.fileName} ${s.suggestionId.slice(0, 12)} --manifest ad2v.yaml`;
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
      kidsEl ? sec(`Contents (${kids.length})`, kids.length <= 30, kidsEl) : null,
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
    this.scene?.setEmphasis(null);
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
    this.scene.setEmphasis(cur.nodeIds); // the rest is dimmed, opaquely (ADR-0051)
    this.scene.frameStep(cur.nodeIds); // P6.1: on screen and readable at every step and level
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
      h("button", { id: "dim", title: "dim everything but the step (opaque blend toward the background)", "aria-pressed": String(this.scene.dimEnabled),
        onclick: () => { this.scene.setDim(!this.scene.dimEnabled); this.renderReplay(false); } }, "Dim"),
      h("button", { title: "stop replay", onclick: () => this.stopReplay() }, "✕"));
    if (announce) {
      const nar = r.narration();
      const text = nar.text ?? this.fallbackStep(cur.nodeIds, prev?.nodeIds ?? [], r.index);
      // P7 (issue 71): a step not visible at this LOD is drawn as its visible ancestor; say so
      const hidden = cur.nodeIds.filter((id) => !this.scene.visibleLods().has(id));
      const anc = hidden.length ? this.scene.representative(hidden[0]!) : null;
      this.card(h("section", { class: "card step", "data-level": r.level, "data-index": r.index },
        nar.parent ? h("p", { class: "subtitle" }, nar.parent) : null,
        h("p", {}, stripIds(text)),
        hidden.length && anc ? h("p", { class: "muted inside", id: "step-inside" },
          `inside ${this.label(anc)} `,
          h("button", { class: "linkish", id: "zoom-to-step", onclick: () => this.scene.fit(hidden, this.scene.reducedMotion) }, "zoom to step")) : null,
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
