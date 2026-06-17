"""M9 — auth/ownership on /forwarding/spending-limits + /forwarding/estimate-gas.

spending-limits returns per-address data → must require wallet auth AND only
expose the caller's OWN address. estimate-gas is generic (recipient count) →
requires wallet auth to gate the RPC-backed estimator against anonymous abuse.

`authenticate_request` is patched for determinism (no Redis/DB); the service
calls are mocked so the happy paths don't need infra.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.auth import AuthError

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def _client():
    from app.api.sweeper_routes import sweeper_router

    app = FastAPI()
    app.include_router(sweeper_router)
    return TestClient(app, raise_server_exceptions=False)


def _patch_auth(monkeypatch, *, addr=None, reject=False):
    async def _fake(_request):
        if reject:
            raise AuthError("missing auth", 401)
        return addr

    monkeypatch.setattr("app.security.auth.authenticate_request", _fake)


# ── spending-limits ──────────────────────────────────────────────────────
def test_spending_limits_requires_auth(monkeypatch):
    _patch_auth(monkeypatch, reject=True)
    r = _client().get(f"/api/v1/forwarding/spending-limits?source_address={ADDR_A}&chain_id=8453")
    assert r.status_code == 401


def test_spending_limits_ownership_enforced(monkeypatch):
    # Authenticated as A, but asking for B's limits → 403 (no cross-address read).
    _patch_auth(monkeypatch, addr=ADDR_A)
    r = _client().get(f"/api/v1/forwarding/spending-limits?source_address={ADDR_B}&chain_id=8453")
    assert r.status_code == 403


def test_spending_limits_own_address_ok(monkeypatch):
    _patch_auth(monkeypatch, addr=ADDR_A)

    class _Status:
        source = ADDR_A
        chain_id = 8453
        per_hour_spent_wei = 0
        per_hour_limit_wei = 1
        per_day_spent_wei = 0
        per_day_limit_wei = 1
        global_daily_spent_wei = 0
        global_daily_limit_wei = 1
        sweeps_this_hour = 0
        max_sweeps_per_hour = 1

    async def _fake_status(self, source, chain_id):
        return _Status()

    monkeypatch.setattr("app.services.spending_policy.SpendingPolicy.get_status", _fake_status)
    r = _client().get(f"/api/v1/forwarding/spending-limits?source_address={ADDR_A}&chain_id=8453")
    assert r.status_code == 200
    assert r.json()["source_address"] == ADDR_A


# ── estimate-gas ─────────────────────────────────────────────────────────
def test_estimate_gas_requires_auth(monkeypatch):
    _patch_auth(monkeypatch, reject=True)
    r = _client().get("/api/v1/forwarding/estimate-gas?recipients=10&chain_id=8453")
    assert r.status_code == 401


def test_estimate_gas_authed_ok(monkeypatch):
    _patch_auth(monkeypatch, addr=ADDR_A)

    async def _fake_estimate(recipients, chain_id):
        return {"total_wei": 123, "l1_wei": 1, "l2_wei": 122}

    monkeypatch.setattr("app.services.gas_estimator.estimate_distribution_cost", _fake_estimate)
    r = _client().get("/api/v1/forwarding/estimate-gas?recipients=10&chain_id=8453")
    assert r.status_code == 200
    assert r.json()["recipients"] == 10
