"""/health/deep must not be permanently degraded when Celery is by design
absent (the lifespan runs webhook-delivery / intent-expiration as asyncio
fallbacks). A permanently-yellow health check is a health check nobody reads.

Real-Celery deployments keep the old semantics: workers configured but not
responding still degrades.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


def _ok():
    return {"status": "ok", "latency_ms": 1.0}


@pytest.fixture(autouse=True)
def _isolate_components(monkeypatch):
    """Pin every non-celery component green so the verdict isolates celery."""

    async def _pg():
        return _ok()

    async def _redis():
        return _ok()

    async def _rpc():
        return {"status": "ok", "block": 1, "latency_ms": 1.0}

    monkeypatch.setattr("app.api.health_routes._check_postgres", _pg)
    monkeypatch.setattr("app.api.health_routes._check_redis", _redis)
    monkeypatch.setattr("app.api.health_routes._check_rpc", _rpc)

    async def _celery_warn():
        return {"status": "warn", "workers": 0, "detail": "no workers responding"}

    monkeypatch.setattr("app.api.health_routes._check_celery", _celery_warn)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_fallback_active_reports_not_configured_and_healthy(client):
    app.state.celery_fallback_active = True
    try:
        r = await client.get("/health/deep")
        body = r.json()
        assert body["components"]["celery"]["status"] == "not_configured"
        assert body["status"] == "healthy"
        assert r.status_code == 200
    finally:
        app.state.celery_fallback_active = False


@pytest.mark.asyncio
async def test_no_fallback_keeps_degraded_semantics(client):
    app.state.celery_fallback_active = False
    r = await client.get("/health/deep")
    body = r.json()
    assert body["components"]["celery"]["status"] == "warn"
    assert body["status"] == "degraded"
