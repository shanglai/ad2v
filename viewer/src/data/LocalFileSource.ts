// The whole .ad2v file in memory through sql.js (MIT). Used for a file picker / drop, for the URL
// served by `ad2v view`, and for the self-contained demo. Read-only: nothing is ever written.
import initSqlJs, { type Database, type SqlValue } from "sql.js";
import type { DataSource } from "./DataSource";
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
  NodeDetail,
  NodeRow,
  SceneSlice,
  Side,
  StatusInfo,
  StatusMode,
  StepRow,
  SuggestionRow,
  SummaryRow,
  WorkflowRow,
} from "./types";

export const LAYOUT_ALGORITHM = "nestgrid-v1";

/** P7: `?layout=nestgrid-v2` shows the experimental shelf layout when the file has it (ADR-0062). */
export function layoutAlgorithm(search: string = typeof location !== "undefined" ? location.search : ""): string {
  const v = new URLSearchParams(search).get("layout");
  return v === "nestgrid-v2" ? v : LAYOUT_ALGORITHM;
}
export const ALL = -1; // scene depth: the whole epoch
const MENTIONS_RE = /\n\nmentions: ([^\n]*)\s*$/;

type Row = Record<string, SqlValue>;

export class LocalFileSource implements DataSource {
  private constructor(private readonly db: Database) {}

  /** `wasmUrl`: where sql-wasm.wasm is (the browser build passes the bundled asset URL). */
  static async fromBytes(bytes: Uint8Array, wasmUrl?: string): Promise<LocalFileSource> {
    const SQL = await initSqlJs(wasmUrl ? { locateFile: () => wasmUrl } : undefined);
    return new LocalFileSource(new SQL.Database(bytes));
  }

  private all(sql: string, params: SqlValue[] = []): Row[] {
    const st = this.db.prepare(sql);
    try {
      st.bind(params);
      const out: Row[] = [];
      while (st.step()) out.push(st.getAsObject() as Row);
      return out;
    } finally {
      st.free();
    }
  }

  private hasTable(name: string): boolean {
    return this.all("SELECT 1 FROM sqlite_master WHERE name = ?", [name]).length > 0;
  }

  async meta(): Promise<Meta> {
    const m = Object.fromEntries(this.all("SELECT key, value FROM meta").map((r) => [String(r.key), String(r.value)]));
    const providers = this.hasTable("llm_runs")
      ? this.all("SELECT DISTINCT provider FROM llm_runs ORDER BY provider").map((r) => String(r.provider))
      : [];
    return {
      formatVersion: m.format_version ?? "?",
      systemName: m.system_name ?? "system",
      specCoverage: m.spec_coverage ?? "present",
      llmProviders: providers,
    };
  }

  async epochs(): Promise<EpochInfo[]> {
    const head = this.all("SELECT value FROM meta WHERE key = 'head_epoch'")[0]?.value ?? null;
    return this.all(
      "SELECT epoch_id, seq, parent_epoch_id, repo_commit, change_kind, pinned, label, materialized" +
        " FROM epochs WHERE materialized = 1 ORDER BY seq",
    ).map((r) => ({
      epochId: String(r.epoch_id),
      seq: Number(r.seq),
      parentEpochId: r.parent_epoch_id === null ? null : String(r.parent_epoch_id),
      commit: r.repo_commit === null ? null : String(r.repo_commit),
      changeKind: String(r.change_kind),
      pinned: Boolean(r.pinned),
      label: r.label === null ? null : String(r.label),
      materialized: Boolean(r.materialized),
      isHead: r.epoch_id === head,
    }));
  }

  async nodes(epoch: string): Promise<NodeRow[]> {
    return this.all(
      "SELECT id, side, kind, name, qualified_name, parent_id, path, span_start_line, span_end_line," +
        " attrs_json, spec_ref_json FROM nodes WHERE epoch_id = ? ORDER BY id",
      [epoch],
    ).map(toNode);
  }

  async layout(epoch: string): Promise<Map<string, Box>> {
    const out = new Map<string, Box>();
    for (const r of this.all(
      "SELECT node_id, x, y, z, w, h, d FROM layout WHERE epoch_id = ? AND algorithm = ? ORDER BY node_id",
      [epoch, layoutAlgorithm()],
    )) {
      out.set(String(r.node_id), { x: +r.x!, y: +r.y!, z: +r.z!, w: +r.w!, h: +r.h!, d: +r.d! });
    }
    return out;
  }

  async glyphs(epoch: string): Promise<Map<string, GlyphRow>> {
    const out = new Map<string, GlyphRow>();
    for (const r of this.all("SELECT * FROM glyphs WHERE epoch_id = ?", [epoch])) {
      out.set(String(r.node_id), {
        nodeId: String(r.node_id),
        baseShape: String(r.base_shape),
        variant: String(r.variant),
        modifiers: JSON.parse(String(r.modifiers_json)),
        sizeWeight: Number(r.size_weight),
        hasInterior: Boolean(r.has_interior),
      });
    }
    return out;
  }

  async edges(epoch: string): Promise<EdgeRow[]> {
    return this.all(
      "SELECT src, dst, kind, weight FROM edges WHERE epoch_id = ? AND kind NOT IN ('contains', 'declares')" +
        " ORDER BY src, kind, dst",
      [epoch],
    ).map((r) => ({ src: String(r.src), dst: String(r.dst), kind: String(r.kind), weight: Number(r.weight) }));
  }

  async status(epoch: string, mode: StatusMode): Promise<Map<string, StatusInfo>> {
    const out = new Map<string, StatusInfo>();
    if (mode === "effective" && this.hasTable("node_status_effective")) {
      for (const r of this.all(
        "SELECT node_id, status, normative_status, provenance, suggested FROM node_status_effective WHERE epoch_id = ?",
        [epoch],
      )) {
        out.set(String(r.node_id), {
          status: String(r.status),
          normative: String(r.normative_status),
          provenance: r.provenance === "llm" ? "llm" : "deterministic",
          suggested: Boolean(r.suggested),
        });
      }
      return out;
    }
    for (const r of this.all("SELECT node_id, status FROM node_status WHERE epoch_id = ?", [epoch])) {
      const s = String(r.status);
      out.set(String(r.node_id), { status: s, normative: s, provenance: "deterministic", suggested: false });
    }
    return out;
  }

  async rollups(epoch: string): Promise<Map<string, Record<string, number>>> {
    return new Map(
      this.all("SELECT node_id, counts_json FROM status_rollup WHERE epoch_id = ?", [epoch]).map((r) => [
        String(r.node_id),
        JSON.parse(String(r.counts_json)) as Record<string, number>,
      ]),
    );
  }

  async nodeDetail(epoch: string, nodeId: string): Promise<NodeDetail | null> {
    const r = this.all("SELECT * FROM nodes WHERE epoch_id = ? AND id = ?", [epoch, nodeId])[0];
    if (!r) return null;
    const s = this.all("SELECT reasons_json FROM node_status WHERE epoch_id = ? AND node_id = ?", [epoch, nodeId])[0];
    const reasons = s ? (JSON.parse(String(s.reasons_json)).reasons ?? []) : [];
    return {
      node: toNode(r),
      attrs: JSON.parse(String(r.attrs_json)),
      specRef: JSON.parse(String(r.spec_ref_json)),
      reasons,
      contentHash: String(r.content_hash),
    };
  }

  async links(epoch: string): Promise<LinkRow[]> {
    return this.all("SELECT * FROM links WHERE epoch_id = ? ORDER BY link_id", [epoch]).map((r) => ({
      linkId: String(r.link_id),
      specId: r.spec_node_id === null ? null : String(r.spec_node_id),
      codeId: r.code_node_id === null ? null : String(r.code_node_id),
      method: String(r.method),
      status: String(r.status),
      evidence: JSON.parse(String(r.evidence_json)),
      provenance: String(r.provenance),
      confidence: Number(r.confidence),
    }));
  }

  async judgments(epoch: string): Promise<Map<string, JudgmentRow>> {
    const out = new Map<string, JudgmentRow>();
    if (!this.hasTable("link_judgments")) return out;
    for (const r of this.all(
      "SELECT j.*, x.provider, x.model FROM link_judgments j LEFT JOIN llm_results x ON x.result_id = j.result_id" +
        " WHERE j.epoch_id = ?",
      [epoch],
    )) {
      out.set(String(r.link_id), {
        linkId: String(r.link_id),
        verdict: String(r.verdict),
        confidence: Number(r.confidence),
        rationale: String(r.rationale),
        evidence: JSON.parse(String(r.evidence_json)),
        valid: Boolean(r.valid),
        overlay: r.overlay === "drift" ? "drift" : "evidence",
        provider: r.provider === null ? null : String(r.provider),
        model: r.model === null ? null : String(r.model),
      });
    }
    return out;
  }

  async suggestions(epoch: string): Promise<SuggestionRow[]> {
    if (!this.hasTable("link_suggestions")) return [];
    return this.all(
      "SELECT s.*, x.provider FROM link_suggestions s LEFT JOIN llm_results x ON x.result_id = s.result_id" +
        " WHERE s.epoch_id = ? ORDER BY s.suggestion_id",
      [epoch],
    ).map((r) => ({
      suggestionId: String(r.suggestion_id),
      specId: String(r.spec_node_id),
      codeId: String(r.code_node_id),
      rank: Number(r.candidate_rank),
      lexicalScore: Number(r.lexical_score),
      verdict: String(r.verdict),
      confidence: Number(r.confidence),
      rationale: String(r.rationale),
      state: String(r.state),
      provider: r.provider === null ? null : String(r.provider),
    }));
  }

  async summaries(epoch: string): Promise<Map<string, SummaryRow>> {
    const out = new Map<string, SummaryRow>();
    const get = (id: string): SummaryRow => {
      let s = out.get(id);
      if (!s) {
        s = { nodeId: id, label: null, card: null, deep: null, mentions: [], model: null, provider: null };
        out.set(id, s);
      }
      return s;
    };
    for (const r of this.all(
      "SELECT s.node_id, s.length, s.text, s.model, x.provider FROM summaries s" +
        " LEFT JOIN llm_results x ON x.result_id = s.result_id WHERE s.epoch_id = ? ORDER BY s.node_id, s.length",
      [epoch],
    )) {
      const s = get(String(r.node_id));
      const text = String(r.text);
      if (r.length === "label") s.label = text;
      else if (r.length === "card") s.card = text;
      else {
        const m = MENTIONS_RE.exec(text); // P4 appends the validated mentions to the deep text
        s.mentions = m ? m[1]!.split(",").map((x) => x.trim()).filter(Boolean) : [];
        s.deep = m ? text.slice(0, m.index) : text;
      }
      if (r.length !== "label") {
        s.model = String(r.model);
        s.provider = r.provider === null ? null : String(r.provider);
      }
    }
    return out;
  }

  async workflows(epoch: string): Promise<WorkflowRow[]> {
    return this.all(
      "SELECT workflow_id, name, side, entry_node_id, source FROM workflows WHERE epoch_id = ? ORDER BY name, workflow_id",
      [epoch],
    ).map((r) => ({
      workflowId: String(r.workflow_id),
      name: String(r.name),
      side: String(r.side) as Side,
      entryNodeId: String(r.entry_node_id),
      source: String(r.source),
    }));
  }

  async steps(epoch: string, workflowId: string): Promise<StepRow[]> {
    return this.all(
      "SELECT seq, node_ids_json, depth FROM workflow_steps WHERE epoch_id = ? AND workflow_id = ? ORDER BY seq",
      [epoch, workflowId],
    ).map((r) => ({ seq: Number(r.seq), nodeIds: JSON.parse(String(r.node_ids_json)), depth: Number(r.depth) }));
  }

  async narrations(epoch: string, workflowId: string, mode = "containment"): Promise<NarrationRow[]> {
    return this.all(
      "SELECT detail_level, span_start, span_end, text, model, mode FROM narrations" +
        " WHERE epoch_id = ? AND workflow_id = ? AND mode = ? ORDER BY detail_level, span_start",
      [epoch, workflowId, mode],
    ).map((r) => ({
      detailLevel: Number(r.detail_level),
      spanStart: Number(r.span_start),
      spanEnd: Number(r.span_end),
      text: String(r.text),
      model: String(r.model),
      mode: String(r.mode),
    }));
  }

  async workflowsThrough(epoch: string, nodeId: string): Promise<string[]> {
    return this.all(
      "SELECT DISTINCT workflow_id FROM workflow_step_nodes WHERE epoch_id = ? AND node_id = ? ORDER BY workflow_id",
      [epoch, nodeId],
    ).map((r) => String(r.workflow_id));
  }

  async lineage(epoch: string): Promise<LineageRow[]> {
    return this.all("SELECT old_id, new_id, method, score FROM id_lineage WHERE epoch_id = ? ORDER BY old_id", [
      epoch,
    ]).map((r) => ({ oldId: String(r.old_id), newId: String(r.new_id), method: String(r.method), score: Number(r.score) }));
  }

  async scene(epoch: string, rootId: string | null, depth: number): Promise<SceneSlice> {
    const ids = this.sceneIds(epoch, rootId, depth);
    let [nodes, layout, glyphs, edges, normative, effective, rollups] = await Promise.all([
      this.nodes(epoch), this.layout(epoch), this.glyphs(epoch), this.edges(epoch),
      this.status(epoch, "normative"), this.status(epoch, "effective"), this.rollups(epoch),
    ]);
    if (ids !== null) {
      const keep = new Set(ids);
      const pick = <V>(m: Map<string, V>): Map<string, V> => new Map([...m].filter(([k]) => keep.has(k)));
      nodes = nodes.filter((n) => keep.has(n.id));
      layout = pick(layout);
      glyphs = pick(glyphs);
      normative = pick(normative);
      effective = pick(effective);
      rollups = pick(rollups);
      edges = edges.filter((e) => keep.has(e.src) && keep.has(e.dst));
    }
    return { epoch, rootId, depth: ids !== null ? depth : ALL, complete: ids === null, nodes, layout, glyphs, edges, normative, effective, rollups };
  }

  /** Mirrors ad2v/mcp/slices.py scene_ids: roots, the ancestor chain of the root with each ancestor's
   *  children, the root's subtree to `depth`, and the subtree's direct neighbors with their chains. */
  private sceneIds(epoch: string, rootId: string | null, depth: number): string[] | null {
    if (rootId === null || depth === ALL) return null;
    const parent = new Map<string, string | null>();
    const kids = new Map<string, string[]>();
    for (const r of this.all("SELECT id, parent_id FROM nodes WHERE epoch_id = ? ORDER BY id", [epoch])) {
      const id = String(r.id), p = r.parent_id === null ? null : String(r.parent_id);
      parent.set(id, p);
      if (p !== null) (kids.get(p) ?? kids.set(p, []).get(p)!).push(id);
    }
    if (!parent.has(rootId)) throw new Error(`not found: ${rootId}`);
    const keep = new Set<string>([...parent].filter(([, p]) => p === null).map(([k]) => k));
    const chain = (n: string | null | undefined): void => {
      while (n !== null && n !== undefined && !keep.has(n)) {
        keep.add(n);
        n = parent.get(n);
      }
    };
    const anc: string[] = [];
    for (let n: string | null | undefined = rootId; n !== null && n !== undefined; n = parent.get(n)) anc.push(n);
    for (const a of anc) keep.add(a);
    for (const a of anc) for (const c of kids.get(a) ?? []) keep.add(c);
    const sub = new Set<string>([rootId]);
    let frontier = [rootId];
    for (let i = 0; i < Math.max(depth, 0); i++) {
      const nxt = frontier.flatMap((f) => kids.get(f) ?? []);
      for (const c of nxt) sub.add(c);
      frontier = nxt;
    }
    for (const s of sub) keep.add(s);
    for (const r of this.all(
      "SELECT src, dst FROM edges WHERE epoch_id = ? AND kind NOT IN ('contains', 'declares')",
      [epoch],
    )) {
      const src = String(r.src), dst = String(r.dst);
      if (sub.has(src) || sub.has(dst)) {
        chain(src);
        chain(dst);
      }
    }
    return [...keep].sort();
  }

  async statusHistory(nodeId: string): Promise<Array<{ epochId: string; seq: number; status: string }>> {
    return this.all(
      "SELECT e.epoch_id, e.seq, s.status FROM node_status s JOIN epochs e ON e.epoch_id = s.epoch_id" +
        " WHERE s.node_id = ? ORDER BY e.seq",
      [nodeId],
    ).map((r) => ({ epochId: String(r.epoch_id), seq: Number(r.seq), status: String(r.status) }));
  }
}

function toNode(r: Row): NodeRow {
  return {
    id: String(r.id),
    side: String(r.side) as Side,
    kind: String(r.kind),
    name: String(r.name),
    qname: String(r.qualified_name),
    parentId: r.parent_id === null ? null : String(r.parent_id),
    path: r.path === null ? null : String(r.path),
    spanStart: r.span_start_line === null ? null : Number(r.span_start_line),
    spanEnd: r.span_end_line === null ? null : Number(r.span_end_line),
    ...displayFields(r),
  };
}

/** P9 (ADR-0072): title, referenced ids, non-functional flag and step keyword (slices.py `_display`). */
function displayFields(r: Row): Pick<NodeRow, "title" | "refs" | "nfr" | "keyword"> {
  const attrs = (r.attrs_json ? JSON.parse(String(r.attrs_json)) : {}) as Record<string, unknown>;
  const refs = (r.spec_ref_json ? JSON.parse(String(r.spec_ref_json)) : []) as unknown[];
  return {
    title: typeof attrs.title === "string" ? attrs.title : null,
    refs: [...new Set(refs.map(String))].sort(),
    nfr: attrs.requirement_type === "nonfunctional",
    keyword: typeof attrs.keyword === "string" ? attrs.keyword : null,
  };
}
