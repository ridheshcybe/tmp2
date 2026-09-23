"""
AeroTwin Backend — API Key Gate
=================================

Opt-in protection for public demo deployments.  Enabled by setting:

    AEROTWIN_API_KEY=<secret>          # enables the gate
    AEROTWIN_KEY_OPEN_READ=1           # (default) leave GET/HEAD open

Behavior:
  - READ methods (GET/HEAD/OPTIONS) stay open when AEROTWIN_KEY_OPEN_READ=1
    (default) so demo dashboards are browsable without a key.
  - MUTATING requests (POST/PUT/PATCH/DELETE) and WebSocket handshakes must
    present the key via `X-API-Key: <key>` header or `?key=<key>` query param.
  - Health endpoints are always open (uptime monitors, Render health checks).
  - When AEROTWIN_KEY_OPEN_READ=0, reads are locked too (full private mode).

Key comparison is constant-time.  The frontend reads `?key=` from its URL and
attaches it to mutating calls and the WebSocket URL automatically (see
aerotwin-api.js).
"""

from __future__ import annotations

import hmac
import os
from typing import Awaitable, Callable
from urllib.parse import parse_qs

ASGIApp = Callable
Receive = Callable[..., Awaitable]
Send = Callable[..., Awaitable]

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# Static docs/health assets stay open even in private mode; everything else
# under /api follows the read/mutation rules.
_OPEN_PATHS = {"/", "/health", "/healthz", "/health/", "/docs", "/redoc",
               "/openapi.json", "/favicon.ico"}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class ApiKeyMiddleware:
    """Pure-ASGI API key gate (HTTP + WebSocket handshake)."""

    def __init__(self, app: ASGIApp, api_key: str, open_read: bool = True) -> None:
        self.app = app
        self.api_key = api_key
        self.open_read = open_read

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # ── key extraction / comparison ───────────────────────────────────────

    @staticmethod
    def _extract_provided(scope) -> str | None:
        """Return the caller-provided key from X-API-Key header or ?key=."""
        for k, v in scope.get("headers", []):
            if k.lower() == b"x-api-key":
                val = v.decode("latin-1").strip()
                if val:
                    return val
        try:
            qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            vals = qs.get("key", [])
            if vals and vals[0].strip():
                return vals[0].strip()
        except Exception:
            pass
        return None

    def _authorized(self, scope) -> bool:
        provided = self._extract_provided(scope)
        if provided is None:
            return False
        return hmac.compare_digest(provided.encode(), self.api_key.encode())

    # ── ASGI entry ────────────────────────────────────────────────────────

    async def __call__(self, scope, receive, send) -> None:
        if not self.enabled or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if path in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # WS handshake always requires the key (telemetry pushes sensor
            # data and accepts commands).  The dashboard appends ?key=.
            if self._authorized(scope):
                await self.app(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 4401,
                            "reason": "missing or invalid API key"})
            return

        method = scope.get("method", "GET").upper()
        if method in _READ_METHODS and self.open_read:
            await self.app(scope, receive, send)
            return

        if self._authorized(scope):
            await self.app(scope, receive, send)
        else:
            await self._reject_http(send)

    @staticmethod
    async def _reject_http(send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"ApiKey"),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": (b'{"error":"unauthorized","detail":"missing or invalid '
                     b'API key","status_code":401}'),
        })


def install(app, api_key: str = "", open_read: bool = True) -> None:
    """Wire the API-key gate as the outermost layer (call after rate limit)."""
    key = api_key or _env("AEROTWIN_API_KEY")
    if not key:
        return  # gate disabled — zero overhead when unset
    open_read = open_read and _env("AEROTWIN_KEY_OPEN_READ", "1") != "0"
    app.add_middleware(ApiKeyMiddleware, api_key=key, open_read=open_read)
