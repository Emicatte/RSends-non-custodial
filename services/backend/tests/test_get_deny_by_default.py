"""M8 — deny-by-default for unauthenticated GET requests.

Drives the APIKeyMiddleware GET branch with a minimal app. `verify_api_key`
and `get_settings` are patched so no DB/Redis/API-key store is touched. Real
`is_exempt` / `is_get_public` (pure path functions) are used.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.api_auth import APIKeyMiddleware


class _Settings:
    def __init__(self, deny):
        self.api_get_deny_by_default = deny


def _client(monkeypatch, *, deny=True, api_client=None):
    async def _verify(_request):
        return api_client

    monkeypatch.setattr("app.middleware.api_auth.verify_api_key", _verify)
    monkeypatch.setattr("app.middleware.api_auth.get_settings", lambda: _Settings(deny))
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/v1/anomalies")          # non-exempt, not public → bucket D
    async def _anomalies():
        return {"ok": "anomalies"}

    @app.get("/api/v1/public/payment-intent/{intent_id}")   # public allowlist
    async def _public_intent(intent_id: str):
        return {"ok": "public_intent"}

    @app.get("/api/v1/tx/recent")          # public allowlist (account header)
    async def _tx_recent():
        return {"ok": "tx_recent"}

    @app.get("/api/v1/ledger/accounts")    # self-auth allowlist (dep would run in handler)
    async def _ledger():
        return {"ok": "ledger"}

    @app.get("/health")                    # exempt
    async def _health():
        return {"ok": "health"}

    @app.post("/api/v1/anomalies")         # non-GET: mandatory key (unchanged)
    async def _anomalies_post():
        return {"ok": "post"}

    return TestClient(app, raise_server_exceptions=False)


# ── deny-by-default ON ───────────────────────────────────────────────────
def test_unauth_get_non_allowlisted_denied(monkeypatch):
    c = _client(monkeypatch, deny=True, api_client=None)
    assert c.get("/api/v1/anomalies").status_code == 401


def test_unauth_get_public_allowed(monkeypatch):
    c = _client(monkeypatch, deny=True, api_client=None)
    assert c.get("/api/v1/public/payment-intent/pi_x").status_code == 200
    assert c.get("/api/v1/tx/recent").status_code == 200


def test_unauth_get_self_auth_passes_middleware(monkeypatch):
    # Middleware lets the GET reach the handler so the route's own auth dep can
    # run; here the stand-in handler returns 200.
    c = _client(monkeypatch, deny=True, api_client=None)
    assert c.get("/api/v1/ledger/accounts").status_code == 200


def test_exempt_get_allowed(monkeypatch):
    c = _client(monkeypatch, deny=True, api_client=None)
    assert c.get("/health").status_code == 200


def test_valid_key_get_passes(monkeypatch):
    c = _client(monkeypatch, deny=True, api_client={"scope": "read", "environment": "live"})
    assert c.get("/api/v1/anomalies").status_code == 200


# ── kill-switch OFF → legacy behaviour ───────────────────────────────────
def test_flag_off_restores_legacy_public_read(monkeypatch):
    c = _client(monkeypatch, deny=False, api_client=None)
    assert c.get("/api/v1/anomalies").status_code == 200


# ── non-GET unchanged ────────────────────────────────────────────────────
def test_non_get_still_mandatory(monkeypatch):
    c = _client(monkeypatch, deny=True, api_client=None)
    assert c.post("/api/v1/anomalies").status_code == 401
    c2 = _client(monkeypatch, deny=True, api_client={"scope": "write", "environment": "live"})
    assert c2.post("/api/v1/anomalies").status_code == 200
