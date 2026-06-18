import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from app.services.sweep_service import (
    start_sweep_heartbeat,
    stop_sweep_heartbeat,
    HEARTBEAT_EXTEND_TTL_S,
)


@pytest.mark.asyncio
async def test_heartbeat_extends_ttl_periodically():
    """Heartbeat calls EXPIRE at least once per interval."""
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(return_value=True)

    with patch("app.services.sweep_service.get_redis", AsyncMock(return_value=mock_redis)):
        with patch("app.services.sweep_service.HEARTBEAT_INTERVAL_S", 0.1):
            task = start_sweep_heartbeat("test_key")
            await asyncio.sleep(0.35)
            await stop_sweep_heartbeat(task)

    assert mock_redis.expire.call_count >= 2
    mock_redis.expire.assert_called_with("sweep_lock:test_key", HEARTBEAT_EXTEND_TTL_S)


@pytest.mark.asyncio
async def test_heartbeat_survives_redis_error():
    """A transient Redis error must NOT kill the heartbeat."""
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(side_effect=[Exception("boom"), True, True])

    with patch("app.services.sweep_service.get_redis", AsyncMock(return_value=mock_redis)):
        with patch("app.services.sweep_service.HEARTBEAT_INTERVAL_S", 0.1):
            task = start_sweep_heartbeat("test_key")
            await asyncio.sleep(0.35)
            await stop_sweep_heartbeat(task)

    assert mock_redis.expire.call_count >= 2


@pytest.mark.asyncio
async def test_heartbeat_cancels_cleanly():
    """stop_sweep_heartbeat returns quickly and doesn't raise."""
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(return_value=True)

    with patch("app.services.sweep_service.get_redis", AsyncMock(return_value=mock_redis)):
        task = start_sweep_heartbeat("test_key")
        await asyncio.sleep(0.05)
        await stop_sweep_heartbeat(task)

    assert task.done()
    assert task.cancelled() or task.exception() is None
