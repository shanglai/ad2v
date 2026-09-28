"""`ad2v view`: serve the built viewer and one .ad2v file on 127.0.0.1 (P5, format spec §12).

A stdlib `ThreadingHTTPServer` bound to the loopback interface only. It serves the static viewer
(package data `ad2v/_viewer`, or `viewer/dist` in a source checkout) and the file at
`/project.ad2v`. GET and HEAD only, no directory listing, no path outside the viewer directory,
nothing written. The browser loads the file with sql.js; the server never interprets it.
"""

from __future__ import annotations

import mimetypes
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ad2v import store

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

    def _serve(self, head: bool) -> None:
        path = unquote(urlsplit(self.path).path)
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

    def _refuse(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse  # noqa: N815


def serve(ad2v_file: Path, port: int = 0, root: Path | None = None) -> tuple[ThreadingHTTPServer, str]:
    """Start serving in a daemon thread. Returns (server, viewer URL)."""
    ad2v_file = Path(ad2v_file).resolve()
    store.open_readonly(ad2v_file).close()  # fail early on a missing or foreign file
    root = (root or viewer_dir()).resolve()
    server = ThreadingHTTPServer((HOST, port), partial(Handler, root=root, ad2v_file=ad2v_file))
    threading.Thread(target=server.serve_forever, daemon=True, name="ad2v-view").start()
    url = f"http://{HOST}:{server.server_address[1]}/index.html?file={FILE_PATH.lstrip('/')}"
    return server, url


def run(ad2v_file: Path, port: int = 0, open_browser: bool = True) -> None:  # pragma: no cover - interactive
    server, url = serve(ad2v_file, port)
    print(f"ad2v view: {url}  (127.0.0.1 only; Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
