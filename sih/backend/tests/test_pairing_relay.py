"""
Tests for the phone-pairing relay (backend.pairing_relay).

The relay is the serve.py /__* endpoint set, hosted by the FastAPI app so
cloud deploys (Render) can run the "Pair phone" flow without serve.py.
These tests pin the contract the two frontend pages depend on:

    POST /__pair                  -> {"token": ...}
    GET  /__pair/{token}          -> {"offer": ...}      (phone)
    POST /__pair/{token}/answer   -> {"ok": true}       (phone)
    GET  /__pair/{token}/answer   -> {"state": waiting|answered}
    GET  /__lanip                 -> {"public" | "ip"/"scheme"/"port"}
    GET  /__ice                   -> {"iceServers": [...], "turn": bool}
    POST /__ctl + GET /__ctl      -> the REST command fallback queue

Runs without the heavy backend imports: the router is mounted on a bare
FastAPI app here, exactly the surface the pages talk to.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # sih/backend

from backend.pairing_relay import PAIR_TTL_S, router  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("AEROTWIN_KEY", raising=False)
    monkeypatch.delenv("AEROTWIN_TURN_URL", raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _park_offer(client, offer="INVITE-ENVELOPE"):
    r = client.post("/__pair", json={"offer": offer})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ── offer parking + handshake ────────────────────────────────────────────────

def test_pair_create_returns_token(client):
    r = client.post("/__pair", json={"offer": "abc"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token and len(token) == 16


def test_pair_create_requires_offer(client):
    assert client.post("/__pair", json={}).status_code == 400
    assert client.post("/__pair", json={"offer": ""}).status_code == 400


def test_full_handshake_waiting_then_answered(client):
    token = _park_offer(client)

    poll = client.get(f"/__pair/{token}/answer").json()
    assert poll == {"state": "waiting"}

    assert client.get(f"/__pair/{token}").json() == {"offer": "INVITE-ENVELOPE"}

    r = client.post(f"/__pair/{token}/answer", json={"answer": "REPLY"})
    assert r.status_code == 200 and r.json() == {"ok": True}

    poll = client.get(f"/__pair/{token}/answer").json()
    assert poll["state"] == "answered"
    assert poll["answer"] == "REPLY"


def test_answer_requires_body_and_known_token(client):
    assert client.post("/__pair/deadbeef/answer",
                       json={"answer": "x"}).status_code == 404
    token = _park_offer(client)
    assert client.post(f"/__pair/{token}/answer",
                       json={}).status_code == 400


def test_unknown_token_404_and_expired_token_gone(client, monkeypatch):
    token = _park_offer(client)

    assert client.get("/__pair/ffffffffffffffff").status_code == 404

    # Age the session past the TTL, then any relay touch evicts it.
    import backend.pairing_relay as relay
    relay._sessions[token]["created"] -= PAIR_TTL_S + 1
    assert client.get(f"/__pair/{token}").status_code == 404
    assert client.get(f"/__pair/{token}/answer").json() == {"state": "gone"}


# ── access key gating (AEROTWIN_KEY) ─────────────────────────────────────────

@pytest.fixture()
def keyed_client(client, monkeypatch):
    monkeypatch.setenv("AEROTWIN_KEY", "sekrit")
    return client


def test_key_gates_phone_side_calls(keyed_client):
    c = keyed_client
    for method, url, kwargs in [
        ("post", "/__pair", {"json": {"offer": "x"}}),
        ("get", "/__pair/deadbeef", {}),
        ("post", "/__pair/deadbeef/answer", {"json": {"answer": "x"}}),
        ("post", "/__ctl", {"json": {"cmd": "throttle"}}),
        ("get", "/__ice", {}),
    ]:
        assert getattr(c, method)(url, **kwargs).status_code == 403, url

    # The desktop parking an offer must present the key too: on a public
    # deploy there is no trusted local caller to skip the check for.
    assert c.post("/__pair", json={"offer": "x"}).status_code == 403


def test_key_accepted_via_header_and_query(keyed_client):
    c = keyed_client
    header = {"x-aerotwin-key": "sekrit"}
    assert c.post("/__pair", json={"offer": "x"},
                  headers=header).status_code == 200
    assert c.get("/__ice", headers=header).status_code == 200
    assert c.get("/__ice?key=sekrit").status_code == 200
    assert c.get("/__ice?key=wrong").status_code == 403


def test_lanip_never_hands_out_the_key(keyed_client):
    info = keyed_client.get("/__lanip").json()
    assert info["key_required"] is True
    assert "key" not in info


# ── /__lanip origin logic ────────────────────────────────────────────────────

def test_lanip_reports_forwarded_public_origin(client):
    r = client.get("/__lanip", headers={
        "x-forwarded-proto": "https",
        "x-forwarded-host": "aerotwin-up6k.onrender.com",
    })
    assert r.json()["public"] == "https://aerotwin-up6k.onrender.com"
    assert "ip" not in r.json()


def test_lanip_falls_back_to_host_header(client):
    info = client.get("/__lanip", headers={
        "x-forwarded-proto": "https",
        "host": "example.com",
    }).json()
    assert info["public"] == "https://example.com"


def test_lanip_local_fallback_reports_lan_address(client):
    info = client.get("/__lanip").json()
    assert info["scheme"] == "http"
    assert info["ip"]
    assert info["port"]


# ── /__ice ───────────────────────────────────────────────────────────────────

def test_ice_default_stun_no_turn(client):
    body = client.get("/__ice").json()
    assert body["turn"] is False
    assert body["iceServers"][0]["urls"].startswith("stun:")


def test_ice_turn_from_env(client, monkeypatch):
    monkeypatch.setenv("AEROTWIN_TURN_URL", "turn:turn.example.com:3478")
    monkeypatch.setenv("AEROTWIN_TURN_USER", "bob")
    monkeypatch.setenv("AEROTWIN_TURN_CRED", "hunter2")
    body = client.get("/__ice").json()
    assert body["turn"] is True
    turn = body["iceServers"][-1]
    assert turn["urls"] == "turn:turn.example.com:3478"
    assert turn["username"] == "bob"
    assert turn["credential"] == "hunter2"


# ── /__ctl REST fallback ─────────────────────────────────────────────────────

def test_ctl_queue_and_cursor(client):
    for i in range(3):
        assert client.post("/__ctl", json={"cmd": "throttle",
                                           "value": i / 10}).status_code == 200

    drained = client.get("/__ctl?since=0").json()
    assert [c["value"] for c in drained["commands"]] == [0.0, 0.1, 0.2]
    assert drained["cursor"] == 3

    # Dashboard-style incremental drain: only newer commands come back.
    client.post("/__ctl", json={"cmd": "preset", "value": "cruise"})
    again = client.get("/__ctl?since=3").json()
    assert [c["cmd"] for c in again["commands"]] == ["preset"]
    assert again["cursor"] == 4


def test_ctl_requires_cmd_and_valid_json(client):
    assert client.post("/__ctl", json={}).status_code == 400
    assert client.post("/__ctl",
                       content=b"not json",
                       headers={"Content-Type": "application/json"}
                       ).status_code == 400
