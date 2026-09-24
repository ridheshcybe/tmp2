"""
Phone-pairing relay — the serve.py /__* endpoints, cloud edition.
================================================================

On the LAN, serve.py (src/frontend) hosts the WebRTC signaling relay.
On cloud deploys (Render) the FastAPI backend serves the frontend pages
itself, so the same relay lives here — same routes, same payload shapes,
same one-time tokens and 15-minute TTL. That makes the dashboard's
"Pair phone" QR work on the deployed site from any phone, with no
serve.py and no tunnel.

Routes (all optional from the pages' point of view — they degrade
gracefully when absent, so nothing breaks where this router is not
mounted):

    GET  /__lanip                 where the QR should point
    POST /__pair                  desktop parks a WebRTC offer -> {token}
    GET  /__pair/{token}          phone fetches the offer
    POST /__pair/{token}/answer   phone posts its answer
    GET  /__pair/{token}/answer   desktop polls for the answer
    GET  /__ice                   STUN/TURN list for both peers
    POST /__ctl                   phone queues a control command (REST fallback)
    GET  /__ctl?since=N           dashboard drains the command queue

Access model: with AEROTWIN_KEY set, the phone-side calls (offer fetch,
answer POST, /__ctl POST, /__ice) must present the key (?key= or the
x-aerotwin-key header). Unlike serve.py there is no trusted local
machine here, so the key is never handed out by /__lanip — leave it
unset on a public demo deploy; one-time tokens + TTL + rate limiting
are the protection, and /api keeps its own AEROTWIN_API_KEY gate.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import socket
import time
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Request

router = APIRouter()

PAIR_TTL_S = 15 * 60          # same session lifetime serve.py uses
CTL_MAX_ITEMS = 200           # bound the REST fallback queue

_sessions: Dict[str, dict] = {}
_pair_lock = asyncio.Lock()

_ctl: List[dict] = []
_ctl_seq = 0
_ctl_lock = asyncio.Lock()


def _access_key() -> str:
    return os.environ.get("AEROTWIN_KEY", "").strip()


def _presented_key(request: Request) -> str:
    return (request.headers.get("x-aerotwin-key", "")
            or request.query_params.get("key", ""))


def _key_ok(request: Request) -> bool:
    want = _access_key()
    if not want:
        return True
    return hmac.compare_digest(_presented_key(request), want)


def _housekeep_locked() -> None:
    """Drop expired pairing sessions (caller holds _pair_lock)."""
    cutoff = time.time() - PAIR_TTL_S
    stale = [t for t, s in _sessions.items() if s["created"] < cutoff]
    for t in stale:
        del _sessions[t]


def _lan_ip() -> str:
    """Best-effort LAN address (a browser cannot see the host's own IP)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packets sent; picks an iface
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _public_origin(request: Request) -> Optional[str]:
    """The origin phones should open, when this instance is public.

    Render (and any TLS-terminating proxy) forwards the real scheme and
    host in X-Forwarded-* headers; uvicorn behind a remote proxy does not
    rewrite request.url, so build the origin from the headers instead of
    trusting the ASGI scheme. Returns None for plain local requests.
    """
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if not proto:
        return None
    host = (request.headers.get("x-forwarded-host", "").split(",")[0].strip()
            or request.headers.get("host", "").strip())
    return f"{proto}://{host}" if host else None


@router.get("/__lanip")
async def lanip(request: Request):
    info: dict = {}
    public = _public_origin(request)
    if public:
        # Public deploy: the QR simply points back at this origin.
        info["public"] = public
    else:
        # Plain local run of the backend: report the LAN address.
        info.update(ip=_lan_ip(), scheme="http",
                    port=request.url.port or 80)
    info["key_required"] = bool(_access_key())
    # Deliberately NOT returning the key (serve.py hands it to the local
    # desktop): on a public deploy every caller is remote, so handing the
    # key to anyone would defeat the gate.
    return info


@router.get("/__ice")
async def ice(request: Request):
    if not _key_ok(request):
        return _forbidden()
    url = os.environ.get("AEROTWIN_TURN_URL", "").strip()
    servers = [{"urls": "stun:stun.l.google.com:19302"}]
    if url:
        server = {"urls": url}
        user = os.environ.get("AEROTWIN_TURN_USER", "").strip()
        cred = os.environ.get("AEROTWIN_TURN_CRED", "").strip()
        if user:
            server["username"] = user
        if cred:
            server["credential"] = cred
        servers.append(server)
    return {"iceServers": servers, "turn": bool(url)}


@router.post("/__pair")
async def pair_create(request: Request):
    if not _key_ok(request):
        return _forbidden()
    try:
        body = await request.json()
        offer = str((body or {}).get("offer") or "")
    except Exception:
        offer = ""
    if not offer:
        return _json({"detail": "offer required"}, 400)
    token = uuid.uuid4().hex[:16]
    async with _pair_lock:
        _housekeep_locked()
        _sessions[token] = {"offer": offer, "answer": None,
                            "created": time.time()}
    return {"token": token}


@router.get("/__pair/{token}")
async def pair_offer(token: str, request: Request):
    if not _key_ok(request):
        return _forbidden()
    async with _pair_lock:
        _housekeep_locked()
        session = _sessions.get(token)
        if session is None:
            return _json({"detail": "unknown or expired token"}, 404)
        offer = session["offer"]
    return {"offer": offer}


@router.post("/__pair/{token}/answer")
async def pair_answer(token: str, request: Request):
    if not _key_ok(request):
        return _forbidden()
    try:
        body = await request.json()
        answer = str((body or {}).get("answer") or "")
    except Exception:
        answer = ""
    if not answer:
        return _json({"detail": "answer required"}, 400)
    async with _pair_lock:
        _housekeep_locked()
        session = _sessions.get(token)
        if session is None:
            return _json({"detail": "unknown or expired token"}, 404)
        session["answer"] = answer
    return {"ok": True}


@router.get("/__pair/{token}/answer")
async def pair_poll(token: str):
    async with _pair_lock:
        _housekeep_locked()
        session = _sessions.get(token)
        if session is None:
            return _json({"state": "gone"}, 404)
        answered = session["answer"] is not None
        payload: dict = {"state": "answered" if answered else "waiting"}
        if answered:
            payload["answer"] = session["answer"]
    return payload


@router.post("/__ctl")
async def ctl_post(request: Request):
    if not _key_ok(request):
        return _forbidden()
    try:
        body = await request.json()
    except Exception:
        return _json({"detail": "bad json"}, 400)
    cmd = (body or {}).get("cmd")
    if not cmd:
        return _json({"detail": "cmd required"}, 400)
    global _ctl_seq
    async with _ctl_lock:
        _ctl_seq += 1
        _ctl.append({"seq": _ctl_seq, "cmd": str(cmd),
                     "value": (body or {}).get("value"),
                     "at": time.time()})
        del _ctl[:-CTL_MAX_ITEMS]
    return {"ok": True}


@router.get("/__ctl")
async def ctl_get(since: int = 0):
    async with _ctl_lock:
        commands = [c for c in _ctl if c["seq"] > since]
        cursor = _ctl[-1]["seq"] if _ctl else since
    return {"commands": commands, "cursor": cursor}


# ── small helpers (avoid importing Response just for two error paths) ──────

def _json(payload: dict, code: int):
    from fastapi.responses import JSONResponse
    return JSONResponse(payload, status_code=code)


def _forbidden():
    return _json({"detail": "invalid pairing key"}, 403)
