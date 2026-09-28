# ad2v over MCP: set up a host

`ad2v mcp` is a read-only MCP server over your `.ad2v` files. The model gets tools to find
components (`ad2v_locate`, `ad2v_search`), explain them (`ad2v_get_node`, `ad2v_links`,
`ad2v_workflow`, `ad2v_diff`, …), and point at them on the map (`ad2v_show`). Hosts that support
**MCP Apps** (Claude, ChatGPT, VS Code, …) render the map inline in the conversation.

- Protocol: MCP **2026-07-28**; older hosts that open with `initialize` (2025-11-25, 2025-06-18,
  2025-03-26) work too. MCP Apps extension **2026-01-26** (ADR-0039, ADR-0040).
- Read-only: files are opened with SQLite `mode=ro`. There are no write tools. Accepting
  suggestions, running the LLM layer, and materializing or pruning epochs stay CLI steps; tools
  return the exact command instead.
- No LLM calls and no network: the server only reads local files. The map app declares no
  network origins.

Prepare a file first (see the README). The map needs a materialized epoch; for history, run
`ad2v materialize project.ad2v --epochs last:5`.

## Serving files

```text
python -m ad2v mcp --root <dir>      # every *.ad2v under <dir> (listed by ad2v_files)
python -m ad2v mcp --file <x.ad2v>   # exactly one file
python -m ad2v mcp --root <dir> --http [--port 8765]   # Streamable HTTP on 127.0.0.1 only
```

With `--root`, a `file` argument is resolved strictly inside the root. Absolute paths, `..`,
symlinks leaving the root and non-`.ad2v` files are refused.

## Claude Desktop

Edit `claude_desktop_config.json`:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Use the Python **inside the virtualenv where ad2v is installed**, with absolute paths.

Windows:

```json
{
  "mcpServers": {
    "ad2v": {
      "command": "C:\\Users\\you\\projects\\ad2v\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ad2v", "mcp", "--root", "C:\\Users\\you\\projects\\maps"]
    }
  }
}
```

macOS / Linux:

```json
{
  "mcpServers": {
    "ad2v": {
      "command": "/Users/you/projects/ad2v/.venv/bin/python",
      "args": ["-m", "ad2v", "mcp", "--root", "/Users/you/projects/maps"]
    }
  }
}
```

Restart Claude Desktop, then ask for example: "Using ad2v, where are bank statements fetched?
Show me on the map."

## Claude Code

```bash
claude mcp add ad2v -- /path/to/ad2v/.venv/bin/python -m ad2v mcp --root /path/to/maps
```

Add `--scope project` to share it through `.mcp.json` in the repository. Check it with
`claude mcp list`.

## VS Code

`.vscode/mcp.json` in the workspace (or the user-level MCP configuration):

```json
{
  "servers": {
    "ad2v": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "ad2v", "mcp", "--root", "${workspaceFolder}"]
    }
  }
}
```

On Windows use `${workspaceFolder}\\.venv\\Scripts\\python.exe`.

## ChatGPT and other hosts that need a remote HTTPS server

`ad2v mcp --http` binds **127.0.0.1 only**. It validates `Origin` and `Host` against DNS
rebinding and has no authentication. It is meant for local testing and for local hosts that
speak HTTP. A host that only connects to remote HTTPS servers (ChatGPT connectors, for example)
cannot reach it.

Exposing it would need a tunnel or a deployment. **That is out of scope, and this project does
not set one up.** Before doing it yourself, weigh the risk: the server gives read access to
your code map, which includes names, paths, spec text, risks and LLM summaries of your
repository.

Checklist for later:

- [ ] Put an authenticating reverse proxy in front (the MCP authorization spec, OAuth 2.1),
  never the bare server.
- [ ] Serve only a dedicated `--root` holding the maps you mean to share.
- [ ] Keep `Origin` validation; add the public origin to the allowed list in code, not `*`.
- [ ] TLS end to end; rate limits; access logs.
- [ ] Remember that a host may cache tool results (`cacheScope`) and send them to its model
  provider.

## Troubleshooting

- **stdout is for the protocol only.** On stdio every byte on stdout must be a JSON-RPC message.
  ad2v writes all diagnostics to **stderr**. If you wrap the command in a script, don't `echo`
  anything to stdout.
- **Windows paths.** In JSON, backslashes are doubled (`C:\\Users\\…`), or use forward slashes.
  Use absolute paths: hosts start servers from their own working directory.
- **The wrong Python.** `ModuleNotFoundError: ad2v` means the host started a Python without ad2v.
  Point `command` at the virtualenv's interpreter (`.venv\Scripts\python.exe` or
  `.venv/bin/python`), or at the `ad2v` executable next to it (`args: ["mcp", …]`).
- **"not materialized".** The tool result carries the command. Run it, for example
  `ad2v materialize project.ad2v --epochs last:5`.
- **The map shows "not built".** In a source checkout, run `npm ci && npm run build:app` in
  `viewer/`. Wheels include the app.
- **Nothing inline.** The host may not support MCP Apps. `ad2v_show` still lists the components,
  and `ad2v view <file>` opens the full map locally.
- **Logs.** Claude Desktop keeps server stderr in its MCP log folder (`%APPDATA%\Claude\logs` or
  `~/Library/Logs/Claude`). Look for `[ad2v-mcp]` lines.
- **Inspect it yourself.** Put the same `mcpServers` block in a file and run
  `npx -y @modelcontextprotocol/inspector@2.8.0 --cli --config servers.json --server ad2v --method tools/list`,
  or run it without `--cli` for the web UI. `viewer/scripts/conformance.mjs` does this for every
  tool.
