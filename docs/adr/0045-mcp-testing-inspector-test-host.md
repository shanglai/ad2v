# ADR-0045: How the MCP layer is tested

- Status: accepted (P6)
- Decisions:
  1. **Conformance.** The official MCP Inspector (`@modelcontextprotocol/inspector@2.8.0`, CLI
     mode) runs **through `npx` from its own cache and is not a project dependency**. Its tree
     includes Vite 8, and so `lightningcss` (MPL-2.0), which our gate forbids (ADR-0035).
     - `scripts/conformance.mjs` checks, over stdio and Streamable HTTP, in the modern and the
       legacy era:
       - `tools/list --strict` (schema portability);
       - `resources/list` and `read` of the map (MIME type);
       - `--app-info` for `ad2v_show`;
       - `tools/call` of the agent tools.
  2. **Test host.** `viewer/e2e/host/` is a desktop-like host built on the official `AppBridge`.
     - It reads the resource, injects the CSP built from `_meta.ui.csp` (the spec's
       restrictive default), and loads the HTML as `srcdoc` in an `iframe sandbox="allow-scripts"`
       (an opaque origin).
     - It forwards the app's `tools/call` to the real stdio server through a Node relay, and
       rejects tools whose visibility lacks `app`.
     - Web hosts must add a second, sandbox-proxy iframe on another origin. The test host does
       not, like desktop hosts.
  3. **No network from the iframe.** Every request whose frame is not the host page is recorded,
     and the App e2e asserts there are none. The app also calls only `viewer_*` tools.
  4. **Parity** (ADR-0041) runs in Vitest by spawning `python -m ad2v mcp`. `npm run test:mcp`
     chains the App build, the parity test, conformance and the App e2e; `pytest -m mcp` covers
     the Python side.
  5. Playwright's Chromium was installed for this session and deleted at the end, as in P5.
