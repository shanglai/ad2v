# ADR-0039: MCP server on the standard library, protocol 2026-07-28, dual-era

- Status: accepted (P6)
- Context:
  - The official Python MCP SDK depends on `httpx`, which brings in `certifi` (MPL-2.0, banned).
  - The P6 plan listed `initialize`/`initialized`, `ping` and logging. The current MCP
    specification (read on 2026-09-28) is **2026-07-28**, which made the protocol stateless: it
    removed the `initialize` handshake, `ping`, `logging/setLevel` and protocol sessions, and
    added `server/discover`.
- Decisions:
  1. **Pin 2026-07-28** (`LATEST_PROTOCOL_VERSION` of the schema). Every modern request must
     carry `io.modelcontextprotocol/protocolVersion` and `…/clientCapabilities` in
     `params._meta`. A missing field gives `-32602`; an unsupported version gives `-32022` with
     the `supported` list.
     - Results carry `resultType: "complete"` and `_meta["io.modelcontextprotocol/serverInfo"]`.
     - List and read results carry `ttlMs` and `cacheScope`. `tools/list` is `private`, because
       app-only tools depend on the declared capabilities.
  2. **Dual-era** (spec §Versioning, "Backward compatibility").
     - An `initialize` request selects legacy semantics (2025-11-25, 2025-06-18 or 2025-03-26)
       for that stdio process or HTTP session. `initialize` and `ping` are served in that mode.
     - Hosts in the field still open with `initialize`, and refusing them would make the
       server unusable today.
  3. **Implemented:**
     - `server/discover`, `tools/list`, `tools/call`, `resources/list`, `resources/read` and
       `resources/templates/list` (empty);
     - `notifications/cancelled` on stdio;
     - `ping` and `initialize` in legacy mode.

     **Not implemented:** prompts, completions, `subscriptions/listen` (nothing changes while
     the server runs), MRTR / sampling / elicitation / roots, and tasks.
  4. **Logging:** the logging feature is **deprecated** in 2026-07-28 ("log to stderr"). The
     server does not advertise `logging`. All diagnostics go to stderr with an `[ad2v-mcp]`
     prefix, and stdout carries protocol messages only. This departs from the P6 plan
     ("implement logging") in favor of the current spec.
  5. **stdio:** a reader thread and one worker thread.
     - A cancel for a queued request drops it; a cancel for a running one stops it at its next
       checkpoint. Neither sends a response.
     - JSON-RPC batches are refused (not part of MCP since 2025-06-18).
     - The server exits on stdin EOF.
  6. **Streamable HTTP:** `/mcp`, POST only, bound to **127.0.0.1**. Responses are always
     `application/json` (allowed), with no SSE.
     - `Origin` and `Host` must be the loopback origin; otherwise the answer is 403.
     - Modern requests must mirror `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` (with
       the Base64 sentinel decoding) or get `-32020`.
     - HTTP status follows the spec: 400 for protocol and header errors, 404 for an unknown
       method, 202 for notifications.
     - GET and DELETE answer 405. A legacy `initialize` mints an `Mcp-Session-Id` with
       `secrets` (a session secret, not an output, so the seed-987654 rule does not apply).
  7. Epoch arguments accept integers (`3`) as well as strings (`"3"`, `"#3"`, ids, labels):
     the MCP Inspector and models send numbers.
