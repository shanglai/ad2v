"""Streamable HTTP transport on `http.server`, bound to 127.0.0.1 only (P6 decision 1, ADR-0039).

One endpoint, `/mcp`, POST only. Every response is a single `application/json` body (allowed by
the spec; this server never streams). Modern (2026-07-28) requests must carry
`MCP-Protocol-Version`, `Mcp-Method` and, for `tools/call` / `resources/read`, `Mcp-Name`, and
they must match the body. A legacy `initialize` gets an `Mcp-Session-Id` (legacy clients need
the session to keep their negotiated capabilities). `Origin` and `Host` are checked against
DNS rebinding. GET and DELETE answer 405: there is no standalone SSE stream.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from ad2v.mcp.protocol import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LEGACY,
    META,
    METHOD_NOT_FOUND,
    MISSING_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_VERSION,
    Conn,
    RpcError,
    Server,
    _error,
    log,
)

PATH = "/mcp"
MAX_BODY = 4 * 1024 * 1024
_STATUS = {
    PARSE_ERROR: 400,
    INVALID_REQUEST: 400,
    INVALID_PARAMS: 400,
    HEADER_MISMATCH: 400,
    MISSING_CLIENT_CAPABILITY: 400,
    UNSUPPORTED_VERSION: 400,
    METHOD_NOT_FOUND: 404,
    INTERNAL_ERROR: 500,
}


def decode_header_value(v: str) -> str:
    """The Base64 sentinel format for non-ASCII header values (`=?base64?…?=`)."""
    if v.startswith("=?base64?") and v.endswith("?="):
        return base64.b64decode(v[len("=?base64?") : -2]).decode("utf-8")
    return v


class _Http(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], server: Server) -> None:
        super().__init__(addr, Handler)
        self.mcp = server
        self.sessions: dict[str, Conn] = {}
        self.lock = threading.Lock()

    @property
    def allowed_hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}


class Handler(BaseHTTPRequestHandler):
    server: _Http
    server_version = "ad2v-mcp"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # stderr, terse
        log("http " + (fmt % args))

    # -- helpers ---------------------------------------------------------------------------------
    def _send(self, status: int, body: dict[str, Any] | None, headers: dict[str, str] | None = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _reject(self, e: RpcError, rid: Any = None, status: int | None = None) -> None:
        self._send(status or _STATUS.get(e.code, 400), _error(rid, e))

    def _origin_ok(self) -> bool:
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        o = urlsplit(origin)
        return o.scheme in ("http", "https") and o.netloc in self.server.allowed_hosts

    # -- methods ---------------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, None, {"Allow": "POST"})

    do_DELETE = do_PUT = do_PATCH = do_GET  # noqa: N815

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != PATH:
            self._send(HTTPStatus.NOT_FOUND, None)
            return
        if not self._origin_ok():
            self._reject(RpcError(INVALID_REQUEST, "Forbidden origin or host"), status=403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._reject(
                RpcError(INVALID_REQUEST, "Missing or oversized body"), status=413 if length > 0 else 400
            )
            return
        try:
            msg = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reject(RpcError(PARSE_ERROR, "Parse error"))
            return
        if not isinstance(msg, dict):
            self._reject(RpcError(INVALID_REQUEST, "The body must be one JSON-RPC message"))
            return
        rid = msg.get("id")
        is_request = "id" in msg and "method" in msg
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        body_version = meta.get(META + "protocolVersion")
        hdr_version = self.headers.get("MCP-Protocol-Version")
        extra: dict[str, str] = {}

        if body_version is not None:  # modern: headers must mirror the body
            problem = self._header_problem(msg, params, body_version, hdr_version)
            if problem:
                self._reject(RpcError(HEADER_MISMATCH, problem), rid)
                return
            conn = Conn()
        elif msg.get("method") == "initialize":
            conn = Conn()
            sid = secrets.token_urlsafe(24)  # a session secret, not an output: no seeded RNG here
            with self.server.lock:
                self.server.sessions[sid] = conn
            extra["Mcp-Session-Id"] = sid
        else:
            sid = self.headers.get("Mcp-Session-Id")
            with self.server.lock:
                conn = self.server.sessions.get(sid or "") or Conn()
            if sid and conn.legacy_version is None:
                self._send(HTTPStatus.NOT_FOUND, None)  # unknown / expired legacy session
                return
            if conn.legacy_version is None and hdr_version in LEGACY:
                conn = Conn(legacy_version=hdr_version)  # sessionless legacy client

        if not is_request:
            self.server.mcp.handle(msg, conn)
            self._send(HTTPStatus.ACCEPTED, None)
            return
        ev = self.server.mcp.register(rid)
        try:
            resp = self.server.mcp.handle(msg, conn, ev)
        finally:
            self.server.mcp.done(rid)
        if resp is None:  # cancelled
            self._send(HTTPStatus.NO_CONTENT, None)
            return
        status = 200
        if "error" in resp:
            status = _STATUS.get(resp["error"]["code"], 200)
        self._send(status, resp, extra)

    def _header_problem(
        self, msg: dict[str, Any], params: dict[str, Any], body_version: str, hdr: str | None
    ) -> str | None:
        if hdr is None:
            return "Missing MCP-Protocol-Version header"
        if hdr != body_version:
            return f"Header mismatch: MCP-Protocol-Version '{hdr}' does not match body '{body_version}'"
        method = self.headers.get("Mcp-Method")
        if method is None:
            return "Missing Mcp-Method header"
        if method != msg.get("method"):
            return f"Header mismatch: Mcp-Method '{method}' does not match body '{msg.get('method')}'"
        if msg.get("method") in ("tools/call", "resources/read", "prompts/get"):
            want = params.get("name") if msg.get("method") != "resources/read" else params.get("uri")
            got = self.headers.get("Mcp-Name")
            if got is None:
                return "Missing Mcp-Name header"
            try:
                got = decode_header_value(got)
            except (ValueError, UnicodeDecodeError):
                return "Malformed Mcp-Name header"
            if got != want:
                return f"Header mismatch: Mcp-Name header value '{got}' does not match body value '{want}'"
        return None


def serve(server: Server, port: int = 0) -> tuple[_Http, str]:
    """Bind 127.0.0.1 (never another interface) and return (server, url); caller runs it."""
    httpd = _Http(("127.0.0.1", port), server)
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}{PATH}"
