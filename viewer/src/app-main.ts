// The ad2v map as an MCP App (P6 §5; MCP Apps 2026-01-26 via @modelcontextprotocol/ext-apps, MIT).
// The host renders this page in a sandboxed iframe when `ad2v_show` is called. It never loads the
// file or sql.js: every query is an app-only tool call (`viewer_*`) through the host bridge, and the
// page declares no network origins at all.
import { App as McpApp, applyHostStyleVariables } from "@modelcontextprotocol/ext-apps/app-with-deps";
import { RemoteSliceSource, type ToolResult } from "./data/RemoteSliceSource";
import { App } from "./ui/app";
import { toIntent, type ShowResult } from "./ui/intent";
import { h } from "./ui/dom";
import "./style.css";

const root = document.getElementById("app")!;

function message(title: string, text: string): void {
  root.replaceChildren(h("section", { class: "card info app-msg" }, h("h3", {}, title), h("p", {}, text)));
}

async function main(): Promise<void> {
  if (window.parent === window) {
    message("ad2v map (MCP App)", "This page runs inside an MCP host (Claude, ChatGPT, VS Code…) when the ad2v_show tool is called. For the standalone map, run: ad2v view <file>.");
    return;
  }
  let app: App | null = null;
  let resolveResult: (r: ShowResult | Error) => void = () => undefined;
  const result = new Promise<ShowResult | Error>((r) => (resolveResult = r));

  const mcp = new McpApp({ name: "ad2v-map", version: "0.6.0" }, { availableDisplayModes: ["inline", "fullscreen"] }, { autoResize: true });
  mcp.ontoolresult = (r) => {
    const sc = (r as ToolResult).structuredContent as ShowResult | undefined;
    if ((r as ToolResult).isError || !sc) resolveResult(new Error((r as ToolResult).content?.[0]?.text ?? "ad2v_show failed"));
    else resolveResult(sc);
  };
  mcp.ontoolcancelled = () => resolveResult(new Error("The tool call was cancelled."));
  mcp.onhostcontextchanged = (c) => {
    if (c.styles?.variables) applyHostStyleVariables(c.styles.variables);
    if (c.theme) app?.setHostTheme(c.theme);
    sizeTo(c.containerDimensions);
  };
  mcp.onteardown = async () => ({});
  await mcp.connect();

  const ctx = mcp.getHostContext();
  if (ctx?.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  sizeTo(ctx?.containerDimensions);
  message("ad2v map", "Waiting for the tool result…");

  const r = await result;
  if (r instanceof Error) {
    message("ad2v map", r.message);
    return;
  }
  const intent = toIntent(r);
  if (intent.theme === "auto" && ctx?.theme) intent.theme = ctx.theme;
  const ds = new RemoteSliceSource((name, args) => mcp.callServerTool({ name, arguments: args }) as Promise<ToolResult>, r.file);
  root.replaceChildren();
  app = new App(root, ds, {
    mode: "app",
    file: r.file,
    intent,
    onSelect: (text) => void mcp.updateModelContext({ content: [{ type: "text", text }] }).catch(() => undefined),
  });
  try {
    await app.start();
  } catch (e) {
    message("ad2v map", `Could not load the map: ${(e as Error).message}`);
  }
}

/** Fixed host height: fill it; flexible: use a map-friendly height up to the host's maximum. */
function sizeTo(dim: { height?: number; maxHeight?: number } | undefined): void {
  const el = document.documentElement;
  if (dim && "height" in dim && dim.height) el.style.setProperty("--app-h", "100vh");
  else el.style.setProperty("--app-h", `${Math.min(560, dim?.maxHeight ?? 560)}px`);
}

void main();
