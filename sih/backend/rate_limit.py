"""
AeroTwin Backend — Rate Limit Middleware
==========================================

Dependency-free per-IP sliding-window rate limiter as pure ASGI middleware
(it runs *outside* Starlette's BaseHTTPMiddleware so it can also cover
WebSocket upgrades and won't deadlock on streaming responses).

Two tiers:
  - /api/*          : API_LIMIT requests per API_WINDOW_S  (default 120/min)
  - everything else : GENERAL_LIMIT per GENERAL_WINDOW_S (default 600/min)

Trusted-proxy note: client IP comes from the LEFTMOST X-Forwarded-For entry
only when the peer is in TRUSTED_PROXY_CIDRS (Render's outbound edge).
Anyone else can spoof XFF — direct clients are keyed by socket address.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Deque, Dict, Optional, Tuple

import ipaddress

ASGIApp = Callable
Receive = Callable[..., Awaitable]
Send = Callable[..., Awaitable]

# ── Configuration (env-overridable; 0 disables a tier) ────────────────────


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


API_LIMIT = _env_int("RATE_LIMIT_API_PER_MIN", 120)
API_WINDOW_S = 60.0
GENERAL_LIMIT = _env_int("RATE_LIMIT_GENERAL_PER_MIN", 600)
GENERAL_WINDOW_S = 60.0

# 429 responses also get rate-limited headers; keep body tiny.
_HEALTH_PATHS = {"/health", "/healthz", "/health/"}


def _parse_cidrs(raw: str) -> Tuple:
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(ipaddress.ip_network(part))
            except ValueError:
                continue
    return tuple(out)


TRUSTED_PROXY_CIDRS = _parse_cidrs(
    os.environ.get("TRUSTED_PROXY_CIDRS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
)


def client_ip_for(scope, trusted_cidrs: Iterable) -> str:
    """Best-effort client IP. XFF leftmost only from trusted proxies."""
    peer = scope.get("client")
    peer_ip = peer[0] if peer else "unknown"
    try:
        peer_addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return peer_ip
    trusted = any(peer_addr in net for net in trusted_cidrs)
    if trusted:
        for name in (b"x-forwarded-for",):
            for k, v in scope.get("headers", []):
                if k.lower() == name:
                    leftmost = v.decode("latin-1").split(",")[0].strip()
                    if leftmost:
                        return leftmost
    return peer_ip


class SlidingWindow:
    __slots__ = ("events",)

    def __init__(self) -> None:
        self.events: Deque[float] = deque()

    def hit(self, now: float, window: float, limit: int) -> Tuple[bool, float, int]:
        """Returns (allowed, retry_after_s, remaining)."""
        dq = self.events
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            retry = window - (now - dq[0]) + 0.05
            return False, max(retry, 0.05), 0
        dq.append(now)
        return True, 0.0, limit - len(dq)


class RateLimitMiddleware:
    """Pure-ASGI per-IP sliding-window rate limiter (HTTP + WebSocket)."""

    def __init__(
        self,
        app: ASGIApp,
        api_limit: int = API_LIMIT,
        api_window: float = API_WINDOW_S,
        general_limit: int = GENERAL_LIMIT,
        general_window: float = GENERAL_WINDOW_S,
        trusted_cidrs: Tuple = TRUSTED_PROXY_CIDRS,
    ) -> None:
        self.app = app
        self.api_limit = api_limit
        self.api_window = api_window
        self.general_limit = general_limit
        self.general_window = general_window
        self.trusted_cidrs = trusted_cidrs
        self._buckets: Dict[Tuple[str, str], SlidingWindow] = defaultdict(SlidingWindow)
        self._last_sweep = time.monotonic()

    def _tier(self, path: str) -> Tuple[str, int, float]:
        if path.startswith("/api/") or path == "/api":
            return ("api", self.api_limit, self.api_window)
        return ("general", self.general_limit, self.general_window)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        # Periodic sweep so idle IPs don't pin memory forever.
        if now - self._last_sweep > 300:
            self._last_sweep = now
            for key in list(self._buckets.keys()):
                dq = self._buckets[key].events
                while dq and now - dq[0] > self.general_window:
                    dq.popleft()
                if not dq:
                    del self._buckets[key]

        path = scope.get("path", "")
        if path in _HEALTH_PATHS:
            await self.app(scope, receive, send)
            return

        tier, limit, window = self._tier(path)
        ip = client_ip_for(scope, self.trusted_cidrs)
        key = (tier, ip)
        allowed, retry_after, remaining = self._buckets[key].hit(now, window, limit)

        if scope["type"] == "websocket":
            if not allowed:
                await send({
                    "type": "websocket.close",
                    "code": 1013,
                    "reason": "rate limited",
                })
            else:
                await self.app(scope, receive, send)
            return

        if not allowed:
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(int(retry_after) + 1).encode()),
                    (b"x-ratelimit-limit", str(limit).encode()),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": (
                    b'{"error":"rate limited","detail":"too many requests, '
                    b'slow down","status_code":429}'
                ),
            })
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", str(limit).encode()))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install(app) -> None:
    """Wrap the FastAPI app with the rate limiter as the OUTERMOST layer.

    Must run after all other middleware is registered so it executes first.
    """
    app.add_middleware(RateLimitMiddleware)
