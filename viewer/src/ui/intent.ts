// `ad2v_show`'s structuredContent -> the map's intent (shared by the MCP App and the chat, P7).
import type { ShowIntent } from "./app";

export interface ShowResult {
  file?: string;
  epoch?: string;
  intent?: ShowIntent["intent"];
  nodes?: Array<{ id: string }>;
  workflow_id?: string | null;
  detail_level?: number | null;
  epoch_from?: string | null;
  epoch_to?: string | null;
  theme?: "auto" | "light" | "dark";
}

export function toIntent(s: ShowResult): ShowIntent {
  return {
    intent: s.intent ?? "focus",
    nodes: (s.nodes ?? []).map((n) => n.id),
    epoch: s.epoch ?? null,
    workflowId: s.workflow_id ?? null,
    detailLevel: s.detail_level ?? null,
    epochFrom: s.epoch_from ?? null,
    epochTo: s.epoch_to ?? null,
    theme: s.theme ?? "auto",
  };
}
