"""`/api/chat/*` on the `ad2v view` server (P7, ADR-0057). The endpoint spends money, so:

- the server binds 127.0.0.1 only;
- a per-launch token (`secrets.token_urlsafe(32)`, never seeded) reaches the page in the URL
  *fragment* (never sent to a server, never in logs) and must come back in `X-Ad2v-Token`;
- `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding);
- `Origin`, when present, must be the same origin, and it is required on POST;
- POST bodies must be `application/json` and at most 16 KB; there are no CORS headers at all,
  so a cross-origin preflight fails.
"""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from typing import Any

MAX_BODY = 16 * 1024
TOKEN_HEADER = "X-Ad2v-Token"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def check(handler: Any, port: int, token: str, post: bool) -> tuple[HTTPStatus, str] | None:
    """None if the request may proceed, else (status, reason)."""
    host = handler.headers.get("Host", "")
    if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return HTTPStatus.FORBIDDEN, "bad Host"
    origin = handler.headers.get("Origin")
    allowed = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    if origin is not None and origin not in allowed:
        return HTTPStatus.FORBIDDEN, "bad Origin"
    if post and origin is None:
        return HTTPStatus.FORBIDDEN, "missing Origin"
    got = handler.headers.get(TOKEN_HEADER, "")
    if not got or not secrets.compare_digest(got, token):
        return HTTPStatus.UNAUTHORIZED, "missing or wrong token"
    if post:
        ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON only"
        n = int(handler.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large"
    return None


def read_json(handler: Any) -> dict[str, Any]:
    n = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def sse(event: str, data: dict[str, Any]) -> bytes:
    """One server-sent event; the JSON is on one line, so no `data:` continuation is needed."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def chunk(b: bytes) -> bytes:
    """HTTP/1.1 chunked transfer framing."""
    return f"{len(b):X}\r\n".encode() + b + b"\r\n"


LAST_CHUNK = b"0\r\n\r\n"
