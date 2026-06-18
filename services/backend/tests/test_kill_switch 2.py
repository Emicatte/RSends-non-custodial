"""
Test: Kill switch implementation (Fix 8.4).

Verifies:
  - Global kill switch stops execution
  - Per-client kill switch stops specific client
  - Auto-stop stops execution
  - Fail-closed on Redis down
  - Clean state allows execution

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_kill_switch.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.kill_switch import (
    KillSwitch,
    kill_switch,
    set_global_stop,
    set_client_stop,
    auto_stop,
    clear_auto_stop,
    get_status,
    _invalidate_cache,
)


def _mock_redis(**key_values):
    """Create a mock Redis that returns values from a dict."""
    r = AsyncMock()

    async def mock_get(key):
        return key_values.get(key)

    r.get = mock_get
    r.set = AsyncMock()
    r.delete = AsyncMock()
    return r


@pytest.fixture(autouse=True)
def clear_cache():
    _invalidate_cache()
    yield
    _invalidate_cache()


@pytest.mark.asyncio
async def test_allows_execution_when_clean():
    """No flags set → execution allowed."""
    r = _mock_redis()
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute()
    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_global_stop_blocks_execution():
    """Global kill switch active → execution denied."""
    r = _mock_redis(**{"kill_switch:global": b"1"})
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute()
    assert allowed is False
    assert reason == "global_kill_switch_active"


@pytest.mark.asyncio
async def test_auto_stop_blocks_execution():
    """Auto-stop active → execution denied with reason."""
    r = _mock_redis(**{"kill_switch:auto_stop": b"anomaly_detected"})
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute()
    assert allowed is False
    assert "auto_stop_active" in reason
    assert "anomaly_detected" in reason


@pytest.mark.asyncio
async def test_client_stop_blocks_specific_client():
    """Per-client kill switch → blocks that client only."""
    r = _mock_redis(**{"kill_switch:client:merchant_123": b"1"})
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute(client_id="merchant_123")
    assert allowed is False
    assert "client_kill_switch_active" in reason


@pytest.mark.asyncio
async def test_client_stop_allows_other_clients():
    """Per-client kill switch for merchant_123 → merchant_456 is not affected."""
    r = _mock_redis(**{"kill_switch:client:merchant_123": b"1"})
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute(client_id="merchant_456")
    assert allowed is True


@pytest.mark.asyncio
async def test_fails_closed_on_redis_down():
    """Redis unavailable → execution denied (fail-closed)."""
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=None):
        allowed, reason = await kill_switch.can_execute()
    assert allowed is False
    assert reason == "kill_switch_unverifiable"


@pytest.mark.asyncio
async def test_fails_closed_on_redis_error():
    """Redis raises exception → execution denied (fail-closed)."""
    r = AsyncMock()
    r.get = AsyncMock(side_effect=Exception("connection reset"))
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        allowed, reason = await kill_switch.can_execute()
    assert allowed is False
    assert reason == "kill_switch_unverifiable"


@pytest.mark.asyncio
async def test_set_global_stop():
    """set_global_stop writes to Redis."""
    r = AsyncMock()
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        await set_global_stop(True)
        r.set.assert_called_once_with("kill_switch:global", "1")

        r.reset_mock()
        await set_global_stop(False)
        r.delete.assert_called_once_with("kill_switch:global")


@pytest.mark.asyncio
async def test_auto_stop_sets_with_ttl():
    """auto_stop writes to Redis with TTL."""
    r = AsyncMock()
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        await auto_stop("test_reason", ttl_seconds=600)
        r.set.assert_called_once_with("kill_switch:auto_stop", "test_reason", ex=600)


@pytest.mark.asyncio
async def test_get_status_returns_dict():
    """get_status returns structured status."""
    r = _mock_redis()
    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=r):
        status = await get_status()
    assert status["executing_allowed"] is True
    assert status["redis_available"] is True
    assert status["global_stopped"] is False
