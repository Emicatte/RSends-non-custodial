"""M5 — internal shared rate-limit endpoint (Redis-backed, fail-closed).

Covers the limiter logic (allow ≤ max, block > max, per-key isolation,
Redis-down fail-closed) and the X-Internal-Secret gate (H3 dependency).

No DB is touched (minimal FastAPI app + fake Redis), so this suite does not
need the model-registration / engine.dispose() dance the DB tests require.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ratelimit_routes import (
    RateLimitCheckRequest,
    ratelimit_check,
    ratelimit_router,
)


# ── Fake Redis (honors incr/expire pipeline + ttl) ───────────────────────
class _FakePipe:
    def __init__(self, store):
        self.store = store
        self._ops = []

    def incr(self, k):
        self._ops.append(("incr", k))
        return self

    def expire(self, k, s):
        self._ops.append(("expire", k, s))
        return self

    async def execute(self):
        res = []
        for op in self._ops:
            if op[0] == "incr":
                self.store[op[1]] = self.store.get(op[1], 0) + 1
                res.append(self.store[op[1]])
            else:
                res.append(True)
        self._ops = []
        return res


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return _FakePipe(self.store)

    async def ttl(self, _k):
        return 60


async def _call(monkeypatch, *, key="1.2.3.4", mx=3, win=60, redis=None):
    if redis is not None:
        async def _get():
            return redis
        monkeypatch.setattr("app.services.cache_service.get_redis", _get)
    return await ratelimit_check(
        RateLimitCheckRequest(bucket="oracle-sign", key=key, max=mx, window_seconds=win),
        _internal=None,
    )


# ── Limiter logic ────────────────────────────────────────────────────────
async def test_allows_up_to_max_then_blocks(monkeypatch):
    fake = _FakeRedis()
    for i in range(3):
        r = await _call(monkeypatch, mx=3, redis=fake)
        assert r.allowed is True, f"call {i + 1} should be allowed"
    r = await _call(monkeypatch, mx=3, redis=fake)
    assert r.allowed is False
    assert r.retry_after and r.retry_after > 0


async def test_separate_keys_are_independent(monkeypatch):
    fake = _FakeRedis()
    for _ in range(3):
        assert (await _call(monkeypatch, key="a", mx=3, redis=fake)).allowed is True
    # A different key (= different IP) has its own counter.
    assert (await _call(monkeypatch, key="b", mx=3, redis=fake)).allowed is True


async def test_redis_down_fail_closed(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr("app.services.cache_service.get_redis", _none)
    r = await ratelimit_check(
        RateLimitCheckRequest(bucket="oracle-sign", key="1.2.3.4", max=10, window_seconds=60),
        _internal=None,
    )
    assert r.allowed is False
    assert r.retry_after == 60


# ── X-Internal-Secret gate (reused H3 dependency) ────────────────────────
class _Settings:
    internal_proxy_secret = "topsecret"
    debug = False


def _client(monkeypatch, *, redis=None):
    monkeypatch.setattr("app.api.signing_routes.get_settings", lambda: _Settings())
    if redis is not None:
        async def _get():
            return redis
        monkeypatch.setattr("app.services.cache_service.get_redis", _get)
    app = FastAPI()
    app.include_router(ratelimit_router)
    return TestClient(app)


def test_missing_or_wrong_secret_forbidden(monkeypatch):
    client = _client(monkeypatch)
    payload = {"bucket": "oracle-sign", "key": "1.2.3.4", "max": 10, "window_seconds": 60}

    # No secret → 403 (dependency rejects before the handler/Redis).
    assert client.post("/api/internal/ratelimit/check", json=payload).status_code == 403
    # Wrong secret → 403.
    assert client.post(
        "/api/internal/ratelimit/check",
        headers={"X-Internal-Secret": "wrong"},
        json=payload,
    ).status_code == 403


def test_correct_secret_allows(monkeypatch):
    client = _client(monkeypatch, redis=_FakeRedis())
    resp = client.post(
        "/api/internal/ratelimit/check",
        headers={"X-Internal-Secret": "topsecret"},
        json={"bucket": "oracle-sign", "key": "9.9.9.9", "max": 10, "window_seconds": 60},
    )
    assert resp.status_code == 200
    assert resp.json()["allowed"] is True
