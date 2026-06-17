"""
Test: AML integration in signing endpoint (Fix 8.2).

Verifies:
  - Sanctioned recipient → signing denied
  - Sanctioned sender → signing denied
  - AML service failure → signing denied (fail-closed)
  - Clean addresses → signing allowed (passes through to rate limit)
  - AML high risk → signing denied

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 RSEND_DEV_AUTH_BYPASS=1 ENVIRONMENT=development \
    pytest tests/test_signing_aml.py -v
"""

import os
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("RSEND_DEV_AUTH_BYPASS", "1")
os.environ.setdefault("ENVIRONMENT", "development")

from app.main import app
from app.db.session import engine
from app.models.db_models import Base
from app.services.aml_service import AMLCheckResult


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _signing_body(**overrides) -> dict:
    base = {
        "wallet": "0x" + "aa" * 20,
        "recipient": "0x" + "bb" * 20,
        "token_in": "0x0000000000000000000000000000000000000000",
        "amount_in_wei": "1000000000000000000",
        "nonce": "0x" + "cc" * 32,
        "deadline": int(time.time()) + 300,
        "chain_id": 8453,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_signing_denied_for_sanctioned_recipient(client: AsyncClient):
    """Oracle signing must reject sanctioned recipient."""
    with patch("app.services.aml_service.is_blacklisted", new_callable=AsyncMock) as mock_bl:
        mock_bl.return_value = (True, "OFAC sanctioned: Tornado Cash")
        with patch("app.api.signing_routes._record_signing_denied", new_callable=AsyncMock):
            r = await client.post("/api/internal/signing/check", json=_signing_body())

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is False
    assert data["reason"] == "aml_recipient_blocked"
    assert "Tornado Cash" in data["details"]


@pytest.mark.asyncio
async def test_signing_denied_for_sanctioned_sender(client: AsyncClient):
    """Oracle signing must reject sanctioned sender."""
    call_count = 0

    async def mock_is_blacklisted(addr):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (False, None)
        return (True, "OFAC sanctioned: Lazarus Group")

    with patch("app.services.aml_service.is_blacklisted", side_effect=mock_is_blacklisted):
        with patch("app.api.signing_routes._record_signing_denied", new_callable=AsyncMock):
            r = await client.post("/api/internal/signing/check", json=_signing_body())

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is False
    assert data["reason"] == "aml_sender_blocked"


@pytest.mark.asyncio
async def test_signing_fails_closed_on_aml_error(client: AsyncClient):
    """If AML service raises, signing must be DENIED (fail-closed)."""
    with patch("app.services.aml_service.is_blacklisted", new_callable=AsyncMock) as mock_bl:
        mock_bl.side_effect = Exception("DB connection refused")
        with patch("app.api.signing_routes._record_signing_denied", new_callable=AsyncMock):
            r = await client.post("/api/internal/signing/check", json=_signing_body())

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is False
    assert data["reason"] == "aml_screening_error"


@pytest.mark.asyncio
async def test_signing_denied_for_high_risk(client: AsyncClient):
    """AML high risk → signing denied."""
    with patch("app.services.aml_service.is_blacklisted", new_callable=AsyncMock, return_value=(False, None)):
        with patch("app.services.aml_service.full_aml_check", new_callable=AsyncMock) as mock_aml:
            mock_aml.return_value = AMLCheckResult(
                approved=True,
                risk_level="high",
                alerts=["threshold_daily", "velocity"],
            )
            with patch("app.api.signing_routes._record_signing_denied", new_callable=AsyncMock):
                r = await client.post("/api/internal/signing/check", json=_signing_body())

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is False
    assert data["reason"] == "aml_high_risk"
    assert "threshold_daily" in data["details"]


@pytest.mark.asyncio
async def test_signing_allowed_when_aml_clean(client: AsyncClient):
    """Clean addresses pass AML and proceed to rate limit check."""
    with patch("app.services.aml_service.is_blacklisted", new_callable=AsyncMock, return_value=(False, None)):
        with patch("app.services.aml_service.full_aml_check", new_callable=AsyncMock) as mock_aml:
            mock_aml.return_value = AMLCheckResult(
                approved=True,
                risk_level="low",
                alerts=[],
            )
            with patch("app.services.signing_rate_limit.check_signing_rate_limit", new_callable=AsyncMock, return_value=(True, None)):
                with patch("app.services.signing_rate_limit.check_nonce_uniqueness", new_callable=AsyncMock, return_value=(True, None)):
                    r = await client.post("/api/internal/signing/check", json=_signing_body())

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is True
