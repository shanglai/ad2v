# ADR-0036: Viewer data access, `ad2v view`, and what the viewer may do

- Status: accepted (P5)
- Decisions:
  1. **Every query goes through `DataSource`.** `LocalFileSource` implements it with sql.js over
     the file bytes. The P6 MCP source will implement the same interface, so the UI does not
     change.
  2. **Only materialized epochs are shown.** `ad2v materialize --epochs last:N` (plus pinned)
     prepares a file for browsing history. The viewer never materializes anything itself.
  3. **Read-only, no LLM.** The viewer has no button that calls an LLM or edits `ad2v.yaml`.
     - Accepting a suggestion shows the exact CLI command with a copy button.
     - Missing summaries fall back to a deterministic card built from counts, ports, resources,
       risks and roll-ups.
  4. **`ad2v view`** binds `127.0.0.1` only and serves GET and HEAD only (405 otherwise). Headers:
     - `Cache-Control: no-store`;
     - `X-Content-Type-Options: nosniff`;
     - a CSP of `default-src 'self'` plus `'wasm-unsafe-eval'`.

     The file is served at a fixed path (`/project.ad2v`), so there is no path parameter to
     traverse.
  5. **Packaging.** The built viewer (`viewer/dist`) ships in the wheel as the `ad2v._viewer`
     package data. A source checkout without a build gets a clear "build the viewer" error.
  6. **Single-file demo.** `npm run build:demo` inlines everything into
     `docs/reports/P5-demo.html` (4.26 MB), including the demo `.ad2v` as base64. It opens from
     `file://`.
