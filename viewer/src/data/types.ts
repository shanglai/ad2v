// Row types the viewer reads from an .ad2v file (format v0.6; reads v0.4 and v0.5 too). Everything here is read-only.

export type Side = "code" | "spec";
export type StatusMode = "normative" | "effective";

export interface EpochInfo {
  epochId: string;
  seq: number;
  parentEpochId: string | null;
  commit: string | null;
  changeKind: string;
  pinned: boolean;
  label: string | null;
  materialized: boolean;
  isHead: boolean;
}

export interface NodeRow {
  id: string;
  side: Side;
  kind: string;
  name: string;
  qname: string;
  parentId: string | null;
  path: string | null;
  spanStart: number | null;
  spanEnd: number | null;
}

export interface Box {
  x: number;
  y: number;
  z: number;
  w: number;
  h: number;
  d: number;
}

export interface GlyphRow {
  nodeId: string;
  baseShape: string;
  variant: string;
  modifiers: { ports: number; replicas: number; has_loop_risk: boolean; has_llm: boolean; external: boolean };
  sizeWeight: number;
  hasInterior: boolean;
}

export interface EdgeRow {
  src: string;
  dst: string;
  kind: string;
  weight: number;
}

export interface StatusInfo {
  status: string;
  normative: string;
  provenance: "deterministic" | "llm";
  suggested: boolean;
}

export interface LinkRow {
  linkId: string;
  specId: string | null;
  codeId: string | null;
  method: string;
  status: string;
  evidence: Array<Record<string, unknown>>;
  provenance: string;
  confidence: number;
}

export interface JudgmentRow {
  linkId: string;
  verdict: string;
  confidence: number;
  rationale: string;
  evidence: Array<{ side: string; start_line: number; end_line: number; claim: string }>;
  valid: boolean;
  overlay: "drift" | "evidence";
  provider: string | null;
  model: string | null;
}

export interface SuggestionRow {
  suggestionId: string;
  specId: string;
  codeId: string;
  rank: number;
  lexicalScore: number;
  verdict: string;
  confidence: number;
  rationale: string;
  state: string;
  provider: string | null;
}

export interface SummaryRow {
  nodeId: string;
  label: string | null;
  card: string | null;
  deep: string | null;
  mentions: string[];
  model: string | null;
  provider: string | null;
}

export interface WorkflowRow {
  workflowId: string;
  name: string;
  side: Side;
  entryNodeId: string;
  source: string;
}

export interface StepRow {
  seq: number;
  nodeIds: string[];
  depth: number;
}

export interface NarrationRow {
  detailLevel: number;
  spanStart: number;
  spanEnd: number;
  text: string;
  model: string;
  mode: string;
}

export interface NodeDetail {
  node: NodeRow;
  attrs: Record<string, unknown>;
  specRef: string[];
  reasons: Array<Record<string, unknown>>;
  contentHash: string;
}

export interface LineageRow {
  oldId: string;
  newId: string;
  method: string;
  score: number;
}

export interface Meta {
  formatVersion: string;
  systemName: string;
  specCoverage: string;
  llmProviders: string[];
}

/** A slice of one epoch around a focus node (P6): what the map renders, fetched in one call.
 *  `rootId: null` (or depth -1) is the whole epoch; `complete` says which one it is. */
export interface SceneSlice {
  epoch: string;
  rootId: string | null;
  depth: number;
  complete: boolean;
  nodes: NodeRow[];
  layout: Map<string, Box>;
  glyphs: Map<string, GlyphRow>;
  edges: EdgeRow[];
  normative: Map<string, StatusInfo>;
  effective: Map<string, StatusInfo>;
  rollups: Map<string, Record<string, number>>;
}
