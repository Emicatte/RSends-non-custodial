"""Email-verification gate (email_verified_gate middleware) — FAIL-CLOSED.

Mirrors test_get_deny_by_default.py: a minimal app with only the gate
middleware, with verify_access_token and the DB session monkeypatched so no
Redis/DB is touched. The middleware imports both locally inside dispatch(), so
patching the source-module attributes is sufficient.

The gate is scoped to the JWT-session namespace and fails CLOSED within it:
the only way through a non-allowlisted gated route is a positively-confirmed
verified user. Out-of-namespace routes (wallet/merchant/payment) are never
touched, even when they carry an `Authorization: Bearer` header.
"""

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.email_verified_gate import (
    EmailVerifiedGateMiddleware,
    _in_namespace,
    _is_allowlisted,
)
from app.services.auth_service import AuthError


# ── Fakes for the middleware's user lookup ──
class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeDB:
    def __init__(self, user, raises):
        self._user = user
        self._raises = raises

    async def execute(self, *args, **kwargs):
        if self._raises:
            raise RuntimeError("db down")
        return _FakeResult(self._user)


class _FakeSessionCM:
    def __init__(self, user, raises):
        self._user = user
        self._raises = raises

    async def __aenter__(self):
        return _FakeDB(self._user, self._raises)

    async def __aexit__(self, *args):
        return False


BEARER = {"Authorization": "Bearer tok"}
MERCHANT_BEARER = {"Authorization": "Bearer rsend_live_deadbeef"}
UNVERIFIED = types.SimpleNamespace(email_verified=False)
VERIFIED = types.SimpleNamespace(email_verified=True)


def _client(monkeypatch, *, user=VERIFIED, verify="ok", db_raises=False):
    async def _verify_ok(_token):
        return {"sub": "u1"}

    async def _verify_fail(_token):
        raise AuthError("invalid_token", "bad token")

    async def _verify_unavailable(_token):
        raise AuthError("auth_unavailable", "redis down")

    verifier = {
        "ok": _verify_ok,
        "fail": _verify_fail,
        "unavailable": _verify_unavailable,
    }[verify]

    monkeypatch.setattr("app.services.auth_service.verify_access_token", verifier)
    monkeypatch.setattr(
        "app.db.session.async_session",
        lambda: _FakeSessionCM(user, db_raises),
    )

    app = FastAPI()
    app.add_middleware(EmailVerifiedGateMiddleware)

    @app.get("/api/v1/user/api-keys")  # gated JWT-session route
    async def _keys():
        return {"ok": "keys"}

    @app.get("/api/v1/auth/me")  # allowlisted (and outside namespace)
    async def _me():
        return {"ok": "me"}

    @app.delete("/api/v1/user/account/sessions/{sid}")  # allowlisted pattern (in ns)
    async def _revoke(sid: str):
        return {"ok": "revoked", "sid": sid}

    @app.post("/api/v1/merchant/payment-intent")  # OUTSIDE namespace (merchant API)
    async def _merchant():
        return {"ok": "merchant"}

    return TestClient(app, raise_server_exceptions=False)


# ── Happy path: verified user passes (no false negatives) ──
def test_verified_user_allowed_on_gated_route(monkeypatch):
    c = _client(monkeypatch, user=VERIFIED)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 200
    assert r.json() == {"ok": "keys"}


def test_unverified_user_blocked_on_gated_route(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"


# ── FAIL-CLOSED: cannot confirm verification → deny ──
def test_invalid_token_on_gated_route_blocked_401(monkeypatch):
    c = _client(monkeypatch, verify="fail")
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_token"


def test_no_bearer_on_gated_route_blocked_401(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/v1/user/api-keys")  # no Authorization header
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "no_token"


def test_db_error_blocks_403(monkeypatch):
    # The key custodial case: cannot read the user → DENY, not pass-through.
    c = _client(monkeypatch, user=VERIFIED, db_raises=True)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"


def test_user_not_found_blocks_403(monkeypatch):
    c = _client(monkeypatch, user=None)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 403


def test_auth_unavailable_returns_503(monkeypatch):
    c = _client(monkeypatch, verify="unavailable")
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "auth_unavailable"


# ── Out-of-namespace routes are NEVER touched (merchant/wallet/payment) ──
def test_out_of_namespace_merchant_bearer_passes_through(monkeypatch):
    # Merchant API key on the SAME Bearer header; verify would FAIL. The gate
    # must NOT act outside its namespace — proves merchant/payment untouched.
    c = _client(monkeypatch, verify="fail")
    r = c.post("/api/v1/merchant/payment-intent", headers=MERCHANT_BEARER)
    assert r.status_code == 200
    assert r.json() == {"ok": "merchant"}


# ── Allowlist stays reachable by unverified users ──
def test_allowlisted_me_passes(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    assert c.get("/api/v1/auth/me", headers=BEARER).status_code == 200


def test_allowlisted_session_revoke_passes(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    assert (
        c.delete("/api/v1/user/account/sessions/abc", headers=BEARER).status_code == 200
    )


# ── Unit checks ──
def test_namespace_membership():
    assert _in_namespace("/api/v1/user/api-keys")
    assert _in_namespace("/api/v1/organizations")
    assert _in_namespace("/api/v1/organizations/switch")
    assert _in_namespace("/api/v1/invites/tok/preview")
    # Out of namespace → never gated:
    assert not _in_namespace("/api/v1/merchant/payment-intent")
    assert not _in_namespace("/api/v1/forwarding/rules")
    assert not _in_namespace("/api/v1/splits/contracts")
    assert not _in_namespace("/api/v1/dashboard/stats")
    assert not _in_namespace("/api/v1/auth/me")


def test_allowlist_membership():
    assert _is_allowlisted("GET", "/api/v1/auth/me")
    assert _is_allowlisted("DELETE", "/api/v1/user/account/sessions/sess-1")
    assert _is_allowlisted("POST", "/api/v1/user/account/delete")
    assert not _is_allowlisted("GET", "/api/v1/user/api-keys")
    # Method-sensitive: POST to the sessions/{id} pattern is NOT allowlisted.
    assert not _is_allowlisted("POST", "/api/v1/user/account/sessions/sess-1")
