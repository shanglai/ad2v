# ADR-0040: MCP Apps 2026-01-26: the map as `ui://ad2v/map`

- Status: accepted (P6)
- Context: the MCP Apps extension (`io.modelcontextprotocol/ui`, SEP-1865) is stable at
  **2026-01-26** (github.com/modelcontextprotocol/ext-apps, `specification/2026-01-26/apps.mdx`).
- Decisions:
  1. **Resource.** `ui://ad2v/map`, MIME type `text/html;profile=mcp-app`, one self-contained
     HTML document (inline JS and CSS, 988 KB, budget 2 MB; no wasm, no sql.js, no data).
     - `_meta.ui.csp` is `{}`: no connect, resource, frame or base-URI domains. The host
       therefore applies the spec's restrictive default CSP.
     - `prefersBorder: true`.
     - The wheel ships it as `ad2v/_app/app.html`.
  2. **Linkage.** `ad2v_show` carries `_meta.ui.resourceUri = "ui://ad2v/map"` and is visible
     to the model and the app (the default). The 20 `viewer_*` tools carry
     `visibility: ["app"]`: hosts hide them from the model and let only the map call them.
     - Their descriptions also start with "internal: used by the ad2v map UI", for hosts that
       ignore visibility.
     - They are **listed only when the client declared** the extension with the HTML MIME
       type (spec: "servers SHOULD check client capabilities"). A host without MCP Apps never
       sees them.
  3. **Iframe side.** The official `@modelcontextprotocol/ext-apps` 2.0.3 `App` class
     (`app-with-deps` entry). Its npm tree is 15 packages (MIT, ISC), which passes the gate.
     - It sets zod to jitless mode, so it runs under the default CSP (no `unsafe-eval`).
     - Used: `ui/initialize` with `availableDisplayModes: [inline, fullscreen]`, the
       `tool-result` / `tool-cancelled` / `host-context-changed` / `resource-teardown`
       handlers, `tools/call` for app tools, `ui/update-model-context` when the user selects a
       node, `size-changed` (autoResize), and host theme and style variables.
  4. **Not used:** `ui/message` (the map never speaks for the user), `ui/open-link` (there is
     nothing to open), `ui/request-display-mode` (we declare fullscreen; the host decides),
     `ui/download-file`, sampling.
  5. The theme follows `hostContext.theme`, then `prefers-color-scheme`. `prefers-reduced-motion`
     turns camera flights into cuts.
