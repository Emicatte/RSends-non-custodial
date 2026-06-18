import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from app.middleware.db_backpressure import (
    _db_semaphore,
    _is_db_heavy,
    get_db_semaphore_state,
    DB_HEAVY_SEMAPHORE_LIMIT,
)


def test_is_db_heavy_matches_known_paths():
    assert _is_db_heavy("/api/v1/merchant/payment-intent") is True
    assert _is_db_heavy("/api/v1/merchant/payment-intent/pi_abc123") is True
    assert _is_db_heavy("/api/v1/tx/callback") is True
    assert _is_db_heavy("/api/v1/sweep/execute") is True
    assert _is_db_heavy("/api/v1/split") is True
    assert _is_db_heavy("/api/v1/aml/check") is True


def test_is_db_heavy_rejects_non_heavy_paths():
    assert _is_db_heavy("/health") is False
    assert _is_db_heavy("/health/deep") is False
    assert _is_db_heavy("/metrics") is False
    assert _is_db_heavy("/api/v1/keys/generate") is False
    assert _is_db_heavy("/ws/sweep-feed") is False


def test_semaphore_state_initial():
    state = get_db_semaphore_state()
    assert state["limit"] == DB_HEAVY_SEMAPHORE_LIMIT
    assert state["available"] == DB_HEAVY_SEMAPHORE_LIMIT
    assert state["in_use"] == 0


@pytest.mark.asyncio
async def test_semaphore_state_tracks_usage():
    await _db_semaphore.acquire()
    try:
        state = get_db_semaphore_state()
        assert state["in_use"] == 1
        assert state["available"] == DB_HEAVY_SEMAPHORE_LIMIT - 1
    finally:
        _db_semaphore.release()


@pytest.mark.asyncio
async def test_semaphore_rejects_when_exhausted():
    """When all slots are taken, wait_for should timeout."""
    acquired = []
    for _ in range(DB_HEAVY_SEMAPHORE_LIMIT):
        await _db_semaphore.acquire()
        acquired.append(True)

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_db_semaphore.acquire(), timeout=0.1)
    finally:
        for _ in acquired:
            _db_semaphore.release()
