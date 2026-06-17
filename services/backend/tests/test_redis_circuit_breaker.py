import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import app.services.cache_service as cs


@pytest.fixture(autouse=True)
def reset_cb_state():
    """Reset CB state before each test."""
    cs._rcb_state = cs._RedisCBState.CLOSED
    cs._rcb_failure_count = 0
    cs._rcb_opened_at = 0.0
    cs._rcb_last_probe_at = 0.0
    cs._pool = None
    yield
    cs._rcb_state = cs._RedisCBState.CLOSED
    cs._rcb_failure_count = 0
    cs._rcb_opened_at = 0.0
    cs._rcb_last_probe_at = 0.0
    cs._pool = None


def test_cb_stays_closed_on_success():
    cs._rcb_record_success()
    assert cs.get_redis_cb_state()["state"] == "closed"
    assert cs.get_redis_cb_state()["failure_count"] == 0


def test_cb_opens_after_threshold():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    state = cs.get_redis_cb_state()
    assert state["state"] == "open"
    assert state["failure_count"] == cs.RCB_FAILURE_THRESHOLD


def test_cb_open_blocks_attempts():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    assert cs._rcb_should_attempt() is False


def test_cb_transitions_to_half_open_after_duration():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    cs._rcb_opened_at = time.monotonic() - cs.RCB_OPEN_DURATION_S - 1
    assert cs._rcb_should_attempt() is True
    assert cs.get_redis_cb_state()["state"] == "half_open"


def test_cb_half_open_rate_limits_probes():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    cs._rcb_opened_at = time.monotonic() - cs.RCB_OPEN_DURATION_S - 1
    assert cs._rcb_should_attempt() is True  # first probe allowed
    assert cs._rcb_should_attempt() is False  # second probe blocked (too soon)


def test_cb_recovers_on_success():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    assert cs.get_redis_cb_state()["state"] == "open"
    cs._rcb_record_success()
    assert cs.get_redis_cb_state()["state"] == "closed"
    assert cs.get_redis_cb_state()["failure_count"] == 0


@pytest.mark.asyncio
async def test_get_redis_returns_none_when_cb_open():
    for _ in range(cs.RCB_FAILURE_THRESHOLD):
        cs._rcb_record_failure()

    with patch("redis.asyncio.from_url") as mock_from_url:
        result = await cs.get_redis()
        assert result is None
        mock_from_url.assert_not_called()


@pytest.mark.asyncio
async def test_get_redis_records_failure_on_connection_error():
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379"

    with patch("app.services.cache_service.get_settings", return_value=mock_settings):
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(side_effect=ConnectionError("refused"))
            mock_from_url.return_value = mock_client

            result = await cs.get_redis()
            assert result is None
            assert cs._rcb_failure_count == 1


@pytest.mark.asyncio
async def test_get_redis_records_success_on_ping():
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379"
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    cs._pool = mock_client

    result = await cs.get_redis()
    assert result is mock_client
    assert cs._rcb_failure_count == 0
    assert cs.get_redis_cb_state()["state"] == "closed"


def test_health_state_dict_structure():
    state = cs.get_redis_cb_state()
    assert "state" in state
    assert "failure_count" in state
    assert "opened_at" in state
    assert state["state"] == "closed"
    assert state["opened_at"] is None
