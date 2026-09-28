"""A standard-library MCP server core: JSON-RPC 2.0 dispatch, independent of the transport (ADR-0039).

Pinned protocol: **2026-07-28** (stateless: every request carries its protocol version and client
capabilities in `params._meta`; `server/discover` advertises versions). The server is
**dual-era**: an `initialize` request selects legacy semantics (2025-11-25, 2025-06-18,
2025-03-26) for the rest of that stdio process or HTTP session, because hosts in the field still
open with the handshake.

Transports (stdio, Streamable HTTP) call `Server.handle(message, conn)` and write whatever it
returns. A `Conn` holds only what a legacy handshake established; modern requests never read it.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ad2v import __version__

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED = [MODERN, *LEGACY]
APPS_EXT = "io.modelcontextprotocol/ui"  # MCP Apps extension, pinned 2026-01-26 (ADR-0040)
APP_MIME = "text/html;profile=mcp-app"
META = "io.modelcontextprotocol/"
SERVER_INFO = {"name": "ad2v", "title": "ad2v code map", "version": __version__}

# JSON-RPC and MCP error codes (2026-07-28 §Error Codes)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
MISSING_CLIENT_CAPABILITY = -32021
UNSUPPORTED_VERSION = -32022

LIST_TTL_MS = 60_000
EPOCH_ARGS = frozenset(
    {"epoch", "from", "to", "epoch_from", "epoch_to"}
)  # "3" and 3 both name epoch #3  # tools/resources lists only change with a new server version


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None, http_status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.data, self.http_status = code, message, data, http_status

    def to_json(self) -> dict[str, Any]:
        e: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            e["data"] = self.data
        return e


class Cancelled(Exception):
    """Raised inside a handler at a checkpoint after `notifications/cancelled`."""


@dataclass
class Conn:
    """Per stdio process / HTTP session state: set only by a legacy `initialize`."""

    legacy_version: str | None = None
    client_caps: dict[str, Any] = field(default_factory=dict)
    client_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class Request:
    """What a handler sees: arguments plus the capabilities that apply to this one request."""

    id: Any
    method: str
    params: dict[str, Any]
    version: str
    client_caps: dict[str, Any]
    modern: bool
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def apps(self) -> bool:
        """The client declared the MCP Apps extension with the HTML profile."""
        ext = (self.client_caps.get("extensions") or {}).get(APPS_EXT) or {}
        return APP_MIME in (ext.get("mimeTypes") or [])

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


@dataclass
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Request, dict[str, Any]], dict[str, Any]]
    visibility: tuple[str, ...] = ("model",)  # MCP Apps `_meta.ui.visibility`
    resource_uri: str | None = None  # MCP Apps `_meta.ui.resourceUri`
    output_schema: dict[str, Any] | None = None

    @property
    def app_only(self) -> bool:
        return "model" not in self.visibility

    def describe(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }
        if self.output_schema is not None:
            d["outputSchema"] = self.output_schema
        ui: dict[str, Any] = {}
        if self.resource_uri:
            ui["resourceUri"] = self.resource_uri
        if self.visibility != ("model", "app") and (self.resource_uri or self.app_only):
            ui["visibility"] = list(self.visibility)
        if ui:
            d["_meta"] = {"ui": ui}
        return d


@dataclass
class Resource:
    uri: str
    name: str
    title: str
    description: str
    mime_type: str
    read: Callable[[], dict[str, Any]]  # -> one `contents` entry (without uri / mimeType)

    def describe(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "mimeType": self.mime_type,
        }


def log(msg: str) -> None:
    """All diagnostics go to stderr; stdout carries protocol messages only (stdio)."""
    print(f"[ad2v-mcp] {msg}", file=sys.stderr, flush=True)


class Server:
    def __init__(self, tools: list[Tool], resources: list[Resource], instructions: str) -> None:
        # deterministic order (2026-07-28: tools/list SHOULD be stable)
        self.tools = {t.name: t for t in sorted(tools, key=lambda t: (t.app_only, t.name))}
        self.resources = {r.uri: r for r in resources}
        self.instructions = instructions
        self._inflight: dict[Any, threading.Event] = {}
        self._lock = threading.Lock()
        self.stats: dict[str, list[float]] = {}

    # -- capabilities ---------------------------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        return {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "extensions": {APPS_EXT: {"mimeTypes": [APP_MIME]}},
        }

    # -- cancellation ---------------------------------------------------------------------------
    def cancel(self, request_id: Any) -> None:
        with self._lock:
            ev = self._inflight.get(_key(request_id))
        if ev is not None:
            ev.set()

    def is_cancelled(self, request_id: Any) -> bool:
        with self._lock:
            ev = self._inflight.get(_key(request_id))
        return ev is not None and ev.is_set()

    def register(self, request_id: Any) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._inflight[_key(request_id)] = ev
        return ev

    def done(self, request_id: Any) -> None:
        with self._lock:
            self._inflight.pop(_key(request_id), None)

    # -- dispatch -------------------------------------------------------------------------------
    def handle(self, msg: Any, conn: Conn, cancel: threading.Event | None = None) -> dict[str, Any] | None:
        """One JSON-RPC message in, one response (or None for a notification / cancelled request)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return None  # a response from the client: this server never sends requests
            return _error(
                msg.get("id") if isinstance(msg, dict) else None, RpcError(INVALID_REQUEST, "Invalid Request")
            )
        method: str = msg["method"]
        is_request = "id" in msg
        rid = msg.get("id")
        if is_request and (rid is None or isinstance(rid, bool) or not isinstance(rid, (str, int))):
            return _error(None, RpcError(INVALID_REQUEST, "Request id must be a string or an integer"))
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _error(rid, RpcError(INVALID_PARAMS, "params must be an object")) if is_request else None
        if not is_request:
            self._notification(method, params, conn)
            return None
        t0 = time.perf_counter()
        try:
            req = self._request(rid, method, params, conn, cancel or threading.Event())
            result = self._dispatch(req, conn)
            if req.cancel.is_set():
                return None
            if req.modern:
                result.setdefault("resultType", "complete")
                result.setdefault("_meta", {})[META + "serverInfo"] = SERVER_INFO
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Cancelled:
            return None
        except RpcError as e:
            return _error(rid, e)
        except Exception as e:  # noqa: BLE001 - a bug must not kill the server
            log(f"internal error in {method}: {type(e).__name__}: {e}")
            return _error(rid, RpcError(INTERNAL_ERROR, "Internal error", http_status=500))
        finally:
            key = method if method != "tools/call" else f"tools/call:{params.get('name')}"
            self.stats.setdefault(key, []).append((time.perf_counter() - t0) * 1000)

    def _notification(self, method: str, params: dict[str, Any], conn: Conn) -> None:
        if method == "notifications/cancelled":
            self.cancel(params.get("requestId"))
        # notifications/initialized (legacy) and anything else: nothing to do

    def _request(
        self, rid: Any, method: str, params: dict[str, Any], conn: Conn, cancel: threading.Event
    ) -> Request:
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        version = meta.get(META + "protocolVersion")
        if method == "initialize":
            return Request(rid, method, params, "", {}, modern=False, cancel=cancel)
        if version is not None:
            if version not in SUPPORTED or version in LEGACY:
                raise RpcError(
                    UNSUPPORTED_VERSION,
                    "Unsupported protocol version",
                    {"supported": SUPPORTED, "requested": version},
                )
            caps = meta.get(META + "clientCapabilities")
            if not isinstance(caps, dict):
                raise RpcError(INVALID_PARAMS, f"missing _meta['{META}clientCapabilities']")
            return Request(rid, method, params, version, caps, modern=True, cancel=cancel)
        if conn.legacy_version is not None:
            return Request(
                rid, method, params, conn.legacy_version, conn.client_caps, modern=False, cancel=cancel
            )
        raise RpcError(
            INVALID_PARAMS,
            f"missing _meta['{META}protocolVersion'] (this server speaks {MODERN}; legacy clients send "
            f"initialize)",
            {"supported": SUPPORTED},
        )

    def _dispatch(self, req: Request, conn: Conn) -> dict[str, Any]:
        m = req.method
        if m == "initialize":
            return self._initialize(req.params, conn)
        if m == "server/discover":
            if not req.modern:
                raise RpcError(METHOD_NOT_FOUND, "Method not found: server/discover", http_status=404)
            return {
                "supportedVersions": SUPPORTED,
                "capabilities": self.capabilities(),
                "serverInfo": SERVER_INFO,
                "instructions": self.instructions,
                **_cache(req),
            }
        if m == "ping":
            return {}
        if m == "tools/list":
            tools = [t.describe() for t in self.tools.values() if req.apps or not t.app_only]
            return {"tools": tools, **_cache(req, private=True)}
        if m == "tools/call":
            return self._call(req)
        if m == "resources/list":
            return {"resources": [r.describe() for r in self.resources.values()], **_cache(req)}
        if m == "resources/templates/list":
            return {"resourceTemplates": [], **_cache(req)}
        if m == "resources/read":
            uri = req.params.get("uri")
            r = self.resources.get(uri) if isinstance(uri, str) else None
            if r is None:
                raise RpcError(INVALID_PARAMS, "Resource not found", {"uri": uri})
            content = {"uri": r.uri, "mimeType": r.mime_type, **r.read()}
            return {"contents": [content], **_cache(req)}
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {m}", http_status=404)

    def _initialize(self, params: dict[str, Any], conn: Conn) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        chosen = asked if asked in LEGACY else LEGACY[0]
        conn.legacy_version = chosen
        conn.client_caps = params.get("capabilities") if isinstance(params.get("capabilities"), dict) else {}
        conn.client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        log(
            f"legacy session: protocol {chosen} (client asked {asked!r}), client "
            f"{conn.client_info.get('name')!r}"
        )
        return {
            "protocolVersion": chosen,
            "capabilities": self.capabilities(),
            "serverInfo": SERVER_INFO,
            "instructions": self.instructions,
        }

    def _call(self, req: Request) -> dict[str, Any]:
        name = req.params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        args = req.params.get("arguments") or {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        args = {
            k: (str(v) if k in EPOCH_ARGS and isinstance(v, int) and not isinstance(v, bool) else v)
            for k, v in args.items()
        }
        problem = validate_args(tool.input_schema, args)
        if problem:
            return tool_error(f"Invalid arguments for {tool.name}: {problem}")
        return tool.handler(req, args)


def _cache(req: Request, private: bool = False) -> dict[str, Any]:
    if not req.modern:
        return {}
    return {"ttlMs": LIST_TTL_MS, "cacheScope": "private" if private else "public"}


def _key(rid: Any) -> str:
    return json.dumps(rid)


def _error(rid: Any, e: RpcError) -> dict[str, Any]:
    out: dict[str, Any] = {"jsonrpc": "2.0", "error": e.to_json()}
    if rid is not None:
        out["id"] = rid
    return out


def tool_error(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """A tool-level failure the model can read and act on (not a protocol error)."""
    out: dict[str, Any] = {"content": [{"type": "text", "text": message}], "isError": True}
    if data is not None:
        out["structuredContent"] = {"error": message, **data}
    return out


# -- a small JSON Schema subset validator for tool arguments (type, enum, required, bounds) -----
def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    props: dict[str, Any] = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in args:
            return f"missing required argument '{k}'"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(args) - set(props))
        if extra:
            return f"unknown argument(s): {', '.join(extra)}"
    for k, v in args.items():
        if k in props:
            p = _check(props[k], v, k)
            if p:
                return p
    return None


_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _check(s: dict[str, Any], v: Any, path: str) -> str | None:
    t = s.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    if types and not any(_TYPES[x](v) for x in types):
        return f"'{path}' must be {' or '.join(types)}"
    if "enum" in s and v not in s["enum"]:
        return f"'{path}' must be one of {', '.join(map(str, s['enum']))}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            return f"'{path}' must be >= {s['minimum']}"
        if "maximum" in s and v > s["maximum"]:
            return f"'{path}' must be <= {s['maximum']}"
    if isinstance(v, str):
        if "maxLength" in s and len(v) > s["maxLength"]:
            return f"'{path}' is longer than {s['maxLength']} characters"
        if "minLength" in s and len(v) < s["minLength"]:
            return f"'{path}' is shorter than {s['minLength']} characters"
    if isinstance(v, list):
        if "maxItems" in s and len(v) > s["maxItems"]:
            return f"'{path}' has more than {s['maxItems']} items"
        if "minItems" in s and len(v) < s["minItems"]:
            return f"'{path}' needs at least {s['minItems']} items"
        if "items" in s:
            for i, x in enumerate(v):
                p = _check(s["items"], x, f"{path}[{i}]")
                if p:
                    return p
    return None
