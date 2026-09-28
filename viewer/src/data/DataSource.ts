// Every query the viewer makes goes through this interface (P5 decision 6). P5 implements
// LocalFileSource (sql.js over the whole file); P6 will add a RemoteSliceSource for MCP Apps.
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
  statusHistory(nodeId: string): Promise<Array<{ epochId: string; seq: number; status: string }>>;
}
