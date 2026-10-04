"""`ad2v view`: serve the built viewer and one .ad2v file on 127.0.0.1 (P5, format spec §12).

A stdlib `ThreadingHTTPServer` bound to the loopback interface only. It serves the static viewer
(package data `ad2v/_viewer`, or `viewer/dist` in a source checkout) and the file at
`/project.ad2v`. GET and HEAD only, no directory listing, no path outside the viewer directory,
nothing written. The browser loads the file with sql.js; the server never interprets it.

P7: with `--chat`, the same server also answers `/api/chat/*` (the viewer's own chat agent,
ADR-0056/0057): POST is accepted there only, behind a per-launch token, Host and Origin checks.
The agent writes informative `llm_*` rows into the file; nothing else changes.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ad2v import store
from ad2v.chat import http as chat_http

HOST = "127.0.0.1"
FILE_PATH = "/project.ad2v"
_HERE = Path(__file__).resolve().parent


class ViewerNotBuilt(FileNotFoundError):
    pass


def viewer_dir() -> Path:
    bundled = _HERE / "_viewer"
    if (bundled / "index.html").is_file():
        return bundled
    for parent in _HERE.parents:
        candidate = parent / "viewer" / "dist"
        if (candidate / "index.html").is_file():
            return candidate
    raise ViewerNotBuilt(
        "the viewer is not built: run `npm ci && npm run build` in viewer/ (or install a wheel)"
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "ad2v-view"
    sys_version = ""
    protocol_version = "HTTP/1.1"  # chunked server-sent events for the chat (P7)

    def __init__(self, *args, root: Path, ad2v_file: Path, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.root = root
        self.ad2v_file = ad2v_file
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:  # quiet: the CLI prints the URL
        pass

    def _send(self, body: bytes | None, ctype: str, head: bool) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body or b"")))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'",
        )
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def _json(self, status: HTTPStatus, obj: dict) -> None:  # type: ignore[type-arg]
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _chat(self, path: str, post: bool) -> None:
        chat = getattr(self.server, "chat", None)
        if chat is None:
            if not post and path == "/api/chat/session":
                self._json(
                    HTTPStatus.OK,
                    {
                        "enabled": False,
                        "command": f"ad2v view {self.ad2v_file.name} --chat --manifest ad2v.yaml",
                        "why": "the chat is off unless ad2v view is started with --chat and an llm: "
                        "section with pricing in ad2v.yaml",
                    },
                )
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        bad = chat_http.check(self, self.server.server_address[1], self.server.chat_token, post)  # type: ignore[attr-defined]
        if bad is not None:
            self.send_error(bad[0], bad[1])
            return
        if not post and path == "/api/chat/session":
            self._json(HTTPStatus.OK, chat.session())
        elif post and path == "/api/chat/reset":
            chat_http.read_json(self)
            chat.reset()
            self._json(HTTPStatus.OK, chat.session())
        elif post and path == "/api/chat/cancel":
            chat_http.read_json(self)
            chat.cancel()
            self._json(HTTPStatus.OK, {"cancelled": True})
        elif post and path == "/api/chat/turn":
            q = str(chat_http.read_json(self).get("question") or "").strip()
            if not q:
                self.send_error(HTTPStatus.BAD_REQUEST, "question required")
                return
            self._stream_turn(chat, q)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _stream_turn(self, chat, question: str) -> None:  # noqa: ANN001
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(event: str, data: dict) -> None:  # type: ignore[type-arg]
            self.wfile.write(chat_http.chunk(chat_http.sse(event, data)))
            self.wfile.flush()

        try:
            chat.turn(question, emit)
            self.wfile.write(chat_http.LAST_CHUNK)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            chat.cancel()  # the page went away: stop before the next model call

    def _serve(self, head: bool) -> None:
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/chat/"):
            self._chat(path, post=False)
            return
        if path == FILE_PATH:
            self._send(self.ad2v_file.read_bytes(), "application/octet-stream", head)
            return
        if path in ("", "/"):
            path = "/index.html"
        target = (self.root / path.lstrip("/")).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".wasm":
            ctype = "application/wasm"
        elif target.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        self._send(target.read_bytes(), ctype, head)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(head=True)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/chat/"):
            self._chat(path, post=True)
            return
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def _refuse(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse  # noqa: N815 (no CORS preflight ever succeeds)


def serve(
    ad2v_file: Path, port: int = 0, root: Path | None = None, chat: object | None = None
) -> tuple[ThreadingHTTPServer, str]:
    """Start serving in a daemon thread. Returns (server, viewer URL). With a chat service, the
    URL carries the per-launch token in its fragment (`#chat=<token>`)."""
    ad2v_file = Path(ad2v_file).resolve()
    store.open_readonly(ad2v_file).close()  # fail early on a missing or foreign file
    root = (root or viewer_dir()).resolve()
    server = ThreadingHTTPServer((HOST, port), partial(Handler, root=root, ad2v_file=ad2v_file))
    server.daemon_threads = True
    server.chat = chat  # type: ignore[attr-defined]
    server.chat_token = chat_http.new_token() if chat is not None else ""  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True, name="ad2v-view").start()
    url = f"http://{HOST}:{server.server_address[1]}/index.html?file={FILE_PATH.lstrip('/')}"
    if chat is not None:
        url += f"#chat={server.chat_token}"  # type: ignore[attr-defined]
    return server, url


def run(
    ad2v_file: Path, port: int = 0, open_browser: bool = True, chat: object | None = None
) -> None:  # pragma: no cover - interactive
    server, url = serve(ad2v_file, port, chat=chat)
    print(f"ad2v view: {url}  (127.0.0.1 only; Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
