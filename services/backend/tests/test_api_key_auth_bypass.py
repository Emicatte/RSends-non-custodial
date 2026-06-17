"""
Test: API key debug auth bypass is gated by RSEND_DEV_AUTH_BYPASS + non-prod ENVIRONMENT.

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_api_key_auth_bypass.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.security.api_keys import verify_api_key


def _mock_request(path: str = "/api/v1/something", auth_header: str = ""):
    req = MagicMock()
    req.url.path = path
    headers = MagicMock()
    headers.get = lambda k, default="": auth_header if k == "Authorization" else default
    req.headers = headers
    return req


@pytest.mark.asyncio
async def test_no_bypass_when_debug_true_but_no_env_var(monkeypatch):
    """settings.debug=True alone must NOT bypass auth anymore."""
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    req = _mock_request()
    result = await verify_api_key(req)
    assert result is None


@pytest.mark.asyncio
async def test_no_bypass_in_production(monkeypatch):
    """RSEND_DEV_AUTH_BYPASS=1 must NOT bypass auth when ENVIRONMENT=production."""
    monkeypatch.setenv("RSEND_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")

    req = _mock_request()
    result = await verify_api_key(req)
    assert result is None


@pytest.mark.asyncio
async def test_no_bypass_in_prod_short(monkeypatch):
    """ENVIRONMENT=prod (short form) must also block bypass."""
    monkeypatch.setenv("RSEND_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "prod")

    req = _mock_request()
    result = await verify_api_key(req)
    assert result is None


@pytest.mark.asyncio
async def test_bypass_works_in_development(monkeypatch):
    """RSEND_DEV_AUTH_BYPASS=1 + ENVIRONMENT=development → bypass allowed."""
    monkeypatch.setenv("RSEND_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")

    req = _mock_request()
    result = await verify_api_key(req)
    assert result is not None
    assert result["client_id"] == "debug"


@pytest.mark.asyncio
async def test_bypass_works_with_no_environment(monkeypatch):
    """RSEND_DEV_AUTH_BYPASS=1 + no ENVIRONMENT → bypass allowed (local dev)."""
    monkeypatch.setenv("RSEND_DEV_AUTH_BYPASS", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    req = _mock_request()
    result = await verify_api_key(req)
    assert result is not None
    assert result["client_id"] == "debug"


@pytest.mark.asyncio
async def test_exempt_path_still_works(monkeypatch):
    """Exempt paths (/health) return exempt dict regardless of bypass flag."""
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)

    req = _mock_request(path="/health")
    result = await verify_api_key(req)
    assert result is not None
    assert result["client_id"] == "exempt"
