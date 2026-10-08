// Every query the viewer makes goes through this interface (P5 decision 6). P5 implements
// LocalFileSource (sql.js over the whole file); P6 adds RemoteSliceSource (app tools of the MCP
// server, called through the MCP Apps host bridge). Both implement exactly the same results.
import type {
  Box,
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

export interface DataSource {
  meta(): Promise<Meta>;
  /** Materialized epochs only (the viewer never derives), oldest first. */
  epochs(): Promise<EpochInfo[]>;
  nodes(epoch: string): Promise<NodeRow[]>;
  layout(epoch: string): Promise<Map<string, Box>>;
  glyphs(epoch: string): Promise<Map<string, GlyphRow>>;
  /** Non-hierarchy edges (no contains / declares). */
  edges(epoch: string): Promise<EdgeRow[]>;
  status(epoch: string, mode: StatusMode): Promise<Map<string, StatusInfo>>;
  rollups(epoch: string): Promise<Map<string, Record<string, number>>>;
  nodeDetail(epoch: string, nodeId: string): Promise<NodeDetail | null>;
  links(epoch: string): Promise<LinkRow[]>;
  judgments(epoch: string): Promise<Map<string, JudgmentRow>>;
  suggestions(epoch: string): Promise<SuggestionRow[]>;
  summaries(epoch: string): Promise<Map<string, SummaryRow>>;
  workflows(epoch: string): Promise<WorkflowRow[]>;
  steps(epoch: string, workflowId: string): Promise<StepRow[]>;
  narrations(epoch: string, workflowId: string, mode?: string): Promise<NarrationRow[]>;
  workflowsThrough(epoch: string, nodeId: string): Promise<string[]>;
  lineage(epoch: string): Promise<LineageRow[]>;
  /** The slice of an epoch around `rootId` (see ad2v/mcp/slices.py `scene_ids`); rootId null or depth -1
   *  returns the whole epoch. Both viewers load maps through this one method. */
  scene(epoch: string, rootId: string | null, depth: number): Promise<SceneSlice>;
  statusHistory(nodeId: string): Promise<Array<{ epochId: string; seq: number; status: string }>>;
  /** P10: the Architecture view, one entry per infra environment (sorted by env). */
  c4(epoch: string): Promise<C4View[]>;
  /** P10: node id -> infra environment -> infra status (deployed, unwired, infra_orphan, ...). */
  infraStatus(epoch: string): Promise<Map<string, Record<string, string>>>;
}
