"""Email-verification deny-by-default gate (email_verified_gate middleware).

Mirrors test_get_deny_by_default.py: a minimal app with only the gate
middleware, with verify_access_token and the DB session monkeypatched so no
Redis/DB is touched. The middleware imports both locally inside dispatch(), so
patching the source-module attributes is sufficient.
"""

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.email_verified_gate import (
    EmailVerifiedGateMiddleware,
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
    def __init__(self, user):
        self._user = user

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._user)


class _FakeSessionCM:
    def __init__(self, user):
        self._user = user

    async def __aenter__(self):
        return _FakeDB(self._user)

    async def __aexit__(self, *args):
        return False


BEARER = {"Authorization": "Bearer tok"}
UNVERIFIED = types.SimpleNamespace(email_verified=False)
VERIFIED = types.SimpleNamespace(email_verified=True)


def _client(monkeypatch, *, user, verify="ok"):
    async def _verify_ok(_token):
        return {"sub": "u1"}

    async def _verify_fail(_token):
        raise AuthError("invalid_token", "bad token")

    monkeypatch.setattr(
        "app.services.auth_service.verify_access_token",
        _verify_ok if verify == "ok" else _verify_fail,
    )
    monkeypatch.setattr(
        "app.db.session.async_session",
        lambda: _FakeSessionCM(user),
    )

    app = FastAPI()
    app.add_middleware(EmailVerifiedGateMiddleware)

    @app.get("/api/v1/user/api-keys")  # gated JWT-session route
    async def _keys():
        return {"ok": "keys"}

    @app.get("/api/v1/auth/me")  # allowlisted (exact)
    async def _me():
        return {"ok": "me"}

    @app.delete("/api/v1/user/account/sessions/{sid}")  # allowlisted (pattern)
    async def _revoke(sid: str):
        return {"ok": "revoked", "sid": sid}

    return TestClient(app, raise_server_exceptions=False)


def test_unverified_blocked_on_gated_route(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"


def test_verified_allowed_on_gated_route(monkeypatch):
    c = _client(monkeypatch, user=VERIFIED)
    r = c.get("/api/v1/user/api-keys", headers=BEARER)
    assert r.status_code == 200
    assert r.json() == {"ok": "keys"}


def test_unverified_allowed_on_allowlisted_me(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    assert c.get("/api/v1/auth/me", headers=BEARER).status_code == 200


def test_unverified_allowed_on_allowlisted_session_revoke(monkeypatch):
    c = _client(monkeypatch, user=UNVERIFIED)
    assert c.delete("/api/v1/user/account/sessions/abc", headers=BEARER).status_code == 200


def test_no_bearer_passes_through(monkeypatch):
    # No Authorization header → gate never engages; route responds normally.
    c = _client(monkeypatch, user=UNVERIFIED)
    assert c.get("/api/v1/user/api-keys").status_code == 200


def test_invalid_token_passes_through(monkeypatch):
    # Token fails verification → gate defers to the route's own auth (200 stub).
    c = _client(monkeypatch, user=UNVERIFIED, verify="fail")
    assert c.get("/api/v1/user/api-keys", headers=BEARER).status_code == 200


def test_allowlist_membership():
    assert _is_allowlisted("GET", "/api/v1/auth/me")
    assert _is_allowlisted("POST", "/api/v1/auth/logout")
    assert _is_allowlisted("POST", "/api/v1/auth/resend-verification")
    assert _is_allowlisted("DELETE", "/api/v1/user/account/sessions/sess-1")
    assert _is_allowlisted("POST", "/api/v1/user/account/delete")
    assert _is_allowlisted("POST", "/api/v1/user/account/delete/cancel")
    # Gated:
    assert not _is_allowlisted("GET", "/api/v1/user/api-keys")
    assert not _is_allowlisted("POST", "/api/v1/organizations")
    # Method-sensitive: POST to the sessions/{id} pattern is NOT allowlisted.
    assert not _is_allowlisted("POST", "/api/v1/user/account/sessions/sess-1")
