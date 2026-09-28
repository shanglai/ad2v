// A minimal MCP Apps *host* for the e2e tests (P6 §6), built on the official AppBridge
// (@modelcontextprotocol/ext-apps, MIT). It behaves like a desktop host: it reads ui://ad2v/map with
// resources/read, renders it in a sandboxed srcdoc iframe under the spec's CSP, sends tool-input and
// tool-result, and forwards the app's tools/call to the real stdio server through the test relay
// (POST /rpc), rejecting tools whose visibility does not include "app".
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";

interface Rpc {
  (method: string, params: Record<string, unknown>): Promise<Record<string, unknown>>;
}

const rpc: Rpc = async (method, params) => {
  const r = await fetch("/rpc", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ method, params }) });
  const j = (await r.json()) as { result?: Record<string, unknown>; error?: { message: string } };
  if (j.error) throw new Error(j.error.message);
  return j.result!;
};

/** The CSP a host builds from the resource's `_meta.ui.csp` ({} here: the spec's restrictive default). */
function cspFor(csp: { connectDomains?: string[]; resourceDomains?: string[] } | undefined): string {
  const res = (csp?.resourceDomains ?? []).join(" ");
  const con = (csp?.connectDomains ?? []).join(" ") || "'none'";
  return [
    "default-src 'none'",
    `script-src 'self' 'unsafe-inline' ${res}`.trim(),
    `style-src 'self' 'unsafe-inline' ${res}`.trim(),
    `img-src 'self' data: ${res}`.trim(),
    "media-src 'self' data:",
    `connect-src ${con}`,
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
  ].join("; ");
}

declare global {
  interface Window {
    hostShow: (args: Record<string, unknown>, theme: "light" | "dark") => Promise<void>;
    hostLog: { modelContext: unknown[]; toolCalls: string[]; rejected: string[]; sizes: Array<{ width?: number; height?: number }>; ready: boolean; error: string | null };
  }
}

window.hostLog = { modelContext: [], toolCalls: [], rejected: [], sizes: [], ready: false, error: null };

window.hostShow = async (args, theme) => {
  const log = window.hostLog;
  const tools = ((await rpc("tools/list", {})) as { tools: Array<{ name: string; _meta?: { ui?: { visibility?: string[]; resourceUri?: string } } }> }).tools;
  const show = tools.find((t) => t.name === "ad2v_show")!;
  const uri = show._meta!.ui!.resourceUri!;
  const res = (await rpc("resources/read", { uri })) as { contents: Array<{ text: string; mimeType: string; _meta?: { ui?: { csp?: Record<string, string[]> } } }> };
  const c = res.contents[0]!;
  if (c.mimeType !== "text/html;profile=mcp-app") throw new Error(`unexpected MIME ${c.mimeType}`);
  const csp = cspFor(c._meta?.ui?.csp);
  const html = c.text.replace(/<head>/i, `<head><meta http-equiv="Content-Security-Policy" content="${csp}">`);

  document.body.dataset.theme = theme;
  const frame = document.createElement("iframe");
  frame.id = "app-frame";
  frame.setAttribute("sandbox", "allow-scripts"); // opaque origin; no same-origin, no forms, no popups
  frame.style.cssText = "width:100%;height:560px;border:1px solid #8886;border-radius:8px;display:block";
  document.getElementById("chat")!.append(frame);

  const bridge = new AppBridge(null, { name: "ad2v-test-host", version: "1.0.0" }, { serverTools: {}, serverResources: {}, logging: {}, updateModelContext: {} } as never, {
    hostContext: {
      theme,
      displayMode: "inline",
      availableDisplayModes: ["inline"],
      containerDimensions: { maxHeight: 560 },
      platform: "desktop",
      locale: "en-US",
    },
  } as never);
  const visible = new Map(tools.map((t) => [t.name, t._meta?.ui?.visibility ?? ["model", "app"]]));
  bridge.oncalltool = async (params) => {
    log.toolCalls.push(params.name);
    if (!(visible.get(params.name) ?? []).includes("app")) {
      log.rejected.push(params.name);
      throw new Error(`tool ${params.name} is not callable by apps`);
    }
    return (await rpc("tools/call", { name: params.name, arguments: params.arguments ?? {} })) as never;
  };
  bridge.onreadresource = async (params) => (await rpc("resources/read", { uri: params.uri })) as never;
  bridge.onupdatemodelcontext = async (params) => {
    log.modelContext.push(params);
    return {} as never;
  };
  bridge.onsizechange = (s) => log.sizes.push(s);
  bridge.onloggingmessage = () => undefined;

  const initialized = new Promise<void>((resolve) => (bridge.oninitialized = () => resolve()));
  frame.srcdoc = html;
  await new Promise((r) => frame.addEventListener("load", r, { once: true }));
  await bridge.connect(new PostMessageTransport(frame.contentWindow!, frame.contentWindow!));
  await initialized;
  await bridge.sendToolInput({ arguments: args });
  try {
    const result = await rpc("tools/call", { name: "ad2v_show", arguments: args });
    await bridge.sendToolResult(result as never);
  } catch (e) {
    log.error = (e as Error).message;
  }
  log.ready = true;
};
