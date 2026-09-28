"""stdio transport: newline-delimited JSON-RPC on stdin/stdout; diagnostics on stderr only.

A reader thread parses lines and hands requests to one worker thread in order, so a
`notifications/cancelled` for a queued or running request is seen immediately: a queued
request is dropped, a running one stops at its next checkpoint, and neither gets a response.
The server exits when stdin reaches end-of-file.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
from typing import IO, Any

from ad2v.mcp.protocol import PARSE_ERROR, Conn, RpcError, Server, _error, log

_STOP = object()


def serve(server: Server, stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> None:
    inp = stdin if stdin is not None else sys.stdin.buffer
    out = stdout if stdout is not None else sys.stdout.buffer
    conn = Conn()
    work: queue.Queue[Any] = queue.Queue()
    write_lock = threading.Lock()

    def write(msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with write_lock:
            out.write(line)
            out.flush()

    def worker() -> None:
        while True:
            item = work.get()
            if item is _STOP:
                return
            msg, ev = item
            rid = msg.get("id")
            try:
                if ev.is_set():
                    continue  # cancelled while queued
                resp = server.handle(msg, conn, ev)
                if resp is not None and not ev.is_set():
                    write(resp)
            finally:
                server.done(rid)

    t = threading.Thread(target=worker, name="ad2v-mcp-worker", daemon=True)
    t.start()
    try:
        for raw in inp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                write(_error(None, RpcError(PARSE_ERROR, "Parse error")))
                continue
            if isinstance(msg, list):  # JSON-RPC batches are not part of MCP since 2025-06-18
                write(_error(None, RpcError(-32600, "Batches are not supported")))
                continue
            if isinstance(msg, dict) and "id" in msg and "method" in msg:
                work.put((msg, server.register(msg["id"])))
            else:
                resp = server.handle(msg, conn)  # notifications (cancel) act immediately
                if resp is not None:
                    write(resp)
    except KeyboardInterrupt:
        pass
    finally:
        work.put(_STOP)
        t.join(timeout=5)
        log("stdin closed; exiting")
