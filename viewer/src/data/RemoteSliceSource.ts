// The DataSource over the MCP server's app-only tools (P6 decision 3b). In the MCP App the calls go
// through the host bridge (`tools/call` from the iframe); in tests they go straight to the stdio
// server. Each method is one tool (`viewer_<method>`), paginated with `nextCursor`; maps arrive as
// JSON objects keyed by id and are rebuilt here, so results deep-equal LocalFileSource's.
import type { DataSource } from "./DataSource";
import type {
  Box,
  C4Box,
  C4View,
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
  StatusInfo,
  StatusMode,
  StepRow,
  SuggestionRow,
  SummaryRow,
  WorkflowRow,
} from "./types";

export interface ToolResult {
  content?: Array<{ type: string; text?: string }>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
}

/** Calls one MCP tool by name and resolves with its CallToolResult. */
export type ToolCaller = (name: string, args: Record<string, unknown>) => Promise<ToolResult>;

export class ToolCallError extends Error {}

type Obj<V> = Record<string, V>;
const toMap = <V>(o: Obj<V>): Map<string, V> => new Map(Object.entries(o));

export class RemoteSliceSource implements DataSource {
  constructor(
    private readonly call: ToolCaller,
    readonly file?: string,
  ) {}

  /** One tool call, following `nextCursor` until the last page. */
  private async get<T>(tool: string, args: Record<string, unknown> = {}): Promise<T> {
    let cursor: string | undefined;
    let acc: unknown = undefined;
    for (let guard = 0; guard < 10_000; guard++) {
      const a: Record<string, unknown> = { ...args };
      if (this.file !== undefined) a.file = this.file;
      if (cursor !== undefined) a.cursor = cursor;
      const r = await this.call(tool, a);
      if (r.isError) throw new ToolCallError(r.content?.[0]?.text ?? `${tool} failed`);
      const sc = r.structuredContent ?? {};
      const data = sc.data;
      if (acc === undefined) acc = data;
      else if (Array.isArray(acc) && Array.isArray(data)) (acc as unknown[]).push(...data);
      else if (acc && data && typeof acc === "object" && typeof data === "object") Object.assign(acc as object, data);
      cursor = typeof sc.nextCursor === "string" ? sc.nextCursor : undefined;
      if (cursor === undefined) return acc as T;
    }
    throw new ToolCallError(`${tool}: too many pages`);
  }

  meta(): Promise<Meta> {
    return this.get<Meta>("viewer_meta");
  }
  epochs(): Promise<EpochInfo[]> {
    return this.get<EpochInfo[]>("viewer_epochs");
  }
  nodes(epoch: string): Promise<NodeRow[]> {
    return this.get<NodeRow[]>("viewer_nodes", { epoch });
  }
  async layout(epoch: string): Promise<Map<string, Box>> {
    return toMap(await this.get<Obj<Box>>("viewer_layout", { epoch }));
  }
  async glyphs(epoch: string): Promise<Map<string, GlyphRow>> {
    return toMap(await this.get<Obj<GlyphRow>>("viewer_glyphs", { epoch }));
  }
  edges(epoch: string): Promise<EdgeRow[]> {
    return this.get<EdgeRow[]>("viewer_edges", { epoch });
  }
  async status(epoch: string, mode: StatusMode): Promise<Map<string, StatusInfo>> {
    return toMap(await this.get<Obj<StatusInfo>>("viewer_status", { epoch, mode }));
  }
  async rollups(epoch: string): Promise<Map<string, Record<string, number>>> {
    return toMap(await this.get<Obj<Record<string, number>>>("viewer_rollups", { epoch }));
  }
  nodeDetail(epoch: string, nodeId: string): Promise<NodeDetail | null> {
    return this.get<NodeDetail | null>("viewer_node_detail", { epoch, node_id: nodeId });
  }
  links(epoch: string): Promise<LinkRow[]> {
    return this.get<LinkRow[]>("viewer_links", { epoch });
  }
  async judgments(epoch: string): Promise<Map<string, JudgmentRow>> {
    return toMap(await this.get<Obj<JudgmentRow>>("viewer_judgments", { epoch }));
  }
  suggestions(epoch: string): Promise<SuggestionRow[]> {
    return this.get<SuggestionRow[]>("viewer_suggestions", { epoch });
  }
  async summaries(epoch: string): Promise<Map<string, SummaryRow>> {
    return toMap(await this.get<Obj<SummaryRow>>("viewer_summaries", { epoch }));
  }
  workflows(epoch: string): Promise<WorkflowRow[]> {
    return this.get<WorkflowRow[]>("viewer_workflows", { epoch });
  }
  steps(epoch: string, workflowId: string): Promise<StepRow[]> {
    return this.get<StepRow[]>("viewer_steps", { epoch, workflow_id: workflowId });
  }
  narrations(epoch: string, workflowId: string, mode = "containment"): Promise<NarrationRow[]> {
    return this.get<NarrationRow[]>("viewer_narrations", { epoch, workflow_id: workflowId, mode });
  }
  workflowsThrough(epoch: string, nodeId: string): Promise<string[]> {
    return this.get<string[]>("viewer_workflows_through", { epoch, node_id: nodeId });
  }
  lineage(epoch: string): Promise<LineageRow[]> {
    return this.get<LineageRow[]>("viewer_lineage", { epoch });
  }
  async c4(epoch: string): Promise<C4View[]> {
    const got = await this.get<Array<Omit<C4View, "layout"> & { layout: Obj<C4Box> }>>("viewer_c4", { epoch });
    return got.map((v) => ({ ...v, layout: toMap(v.layout) }));
  }
  async infraStatus(epoch: string): Promise<Map<string, Record<string, string>>> {
    return toMap(await this.get<Obj<Record<string, string>>>("viewer_infra_status", { epoch }));
  }
  async scene(epoch: string, rootId: string | null, depth: number): Promise<SceneSlice> {
    const s = await this.get<Record<string, unknown>>("viewer_scene", rootId === null ? { epoch, depth } : { epoch, root_id: rootId, depth });
    return {
      epoch: s.epoch as string,
      rootId: (s.rootId as string | null) ?? null,
      depth: s.depth as number,
      complete: Boolean(s.complete),
      nodes: s.nodes as NodeRow[],
      layout: toMap(s.layout as Obj<Box>),
      glyphs: toMap(s.glyphs as Obj<GlyphRow>),
      edges: s.edges as EdgeRow[],
      normative: toMap(s.normative as Obj<StatusInfo>),
      effective: toMap(s.effective as Obj<StatusInfo>),
      rollups: toMap(s.rollups as Obj<Record<string, number>>),
    };
  }
  statusHistory(nodeId: string): Promise<Array<{ epochId: string; seq: number; status: string }>> {
    return this.get("viewer_status_history", { node_id: nodeId });
  }
}
