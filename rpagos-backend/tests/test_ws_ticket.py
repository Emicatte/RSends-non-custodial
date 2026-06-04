"""M4 — sweep-feed WebSocket ownership auth via single-use tickets.

Covers the ticket service (mint/consume/single-use/fail-closed), the wallet-
authed mint route, and the WS gate (no/wrong-owner ticket → rejected; valid
ticket → connected). `authenticate_request`, Redis and `consume_sweep_ticket`
are patched so nothing touches real infra.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.security.auth import AuthError

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, k, v, ex=None):
        self.store[k] = v
        return True

    async def getdel(self, k):
        return self.store.pop(k, None)


def _patch_redis(monkeypatch, redis):
    async def _get():
        return redis

    monkeypatch.setattr("app.services.cache_service.get_redis", _get)


# ── Ticket service ───────────────────────────────────────────────────────
async def test_mint_then_consume_single_use(monkeypatch):
    _patch_redis(monkeypatch, _FakeRedis())
    from app.services.ws_ticket import consume_sweep_ticket, mint_sweep_ticket

    ticket = await mint_sweep_ticket("0x" + "A" * 40)  # mixed case
    assert ticket
    # consume returns the bound owner, lowercased
    assert await consume_sweep_ticket(ticket) == "0x" + "a" * 40
    # single-use: a replay finds nothing
    assert await consume_sweep_ticket(ticket) is None


async def test_consume_empty_or_unknown(monkeypatch):
    _patch_redis(monkeypatch, _FakeRedis())
    from app.services.ws_ticket import consume_sweep_ticket

    assert await consume_sweep_ticket(None) is None
    assert await consume_sweep_ticket("") is None
    assert await consume_sweep_ticket("does-not-exist") is None


async def test_ticket_redis_down_fail_closed(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr("app.services.cache_service.get_redis", _none)
    from app.services.ws_ticket import consume_sweep_ticket, mint_sweep_ticket

    assert await mint_sweep_ticket(ADDR_A) is None
    assert await consume_sweep_ticket("anything") is None


# ── Mint route (wallet-authed) ───────────────────────────────────────────
def test_mint_route_requires_auth(monkeypatch):
    from app.api.sweeper_routes import sweeper_router

    async def _reject(_request):
        raise AuthError("missing auth", 401)

    monkeypatch.setattr("app.security.auth.authenticate_request", _reject)
    app = FastAPI()
    app.include_router(sweeper_router)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/v1/forwarding/sweep-ticket").status_code == 401


def test_mint_route_authed_returns_ticket(monkeypatch):
    from app.api.sweeper_routes import sweeper_router

    async def _ok(_request):
        return ADDR_A

    monkeypatch.setattr("app.security.auth.authenticate_request", _ok)
    _patch_redis(monkeypatch, _FakeRedis())
    app = FastAPI()
    app.include_router(sweeper_router)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/v1/forwarding/sweep-ticket")
    assert r.status_code == 200
    body = r.json()
    assert body["ticket"]
    assert body["expires_in"] == 30


# ── WS gate ──────────────────────────────────────────────────────────────
def _ws_client():
    from app.api import websocket_routes

    app = FastAPI()
    app.include_router(websocket_routes.ws_router)
    return TestClient(app), websocket_routes


def test_ws_rejects_without_ticket():
    # No ticket → consume_sweep_ticket(None) short-circuits to None → rejected.
    c, _ = _ws_client()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/ws/sweep-feed/{ADDR_A}") as ws:
            ws.receive_json()


def test_ws_rejects_wrong_owner_ticket(monkeypatch):
    c, ws_mod = _ws_client()

    async def _consume(_ticket):
        return ADDR_B  # ticket bound to B...

    monkeypatch.setattr(ws_mod, "consume_sweep_ticket", _consume)
    with pytest.raises(WebSocketDisconnect):
        # ...but connecting to A's feed → owner mismatch → rejected
        with c.websocket_connect(f"/ws/sweep-feed/{ADDR_A}?ticket=x") as ws:
            ws.receive_json()


def test_ws_accepts_valid_ticket(monkeypatch):
    c, ws_mod = _ws_client()

    async def _consume(_ticket):
        return ADDR_A

    async def _noop_initial(_owner, _ws):
        return None

    monkeypatch.setattr(ws_mod, "consume_sweep_ticket", _consume)
    # Skip Redis/DB-backed initial state — not under test here.
    monkeypatch.setattr(ws_mod.feed_manager, "send_initial_state", _noop_initial)

    with c.websocket_connect(f"/ws/sweep-feed/{ADDR_A}?ticket=valid") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert msg["data"]["owner"] == ADDR_A
