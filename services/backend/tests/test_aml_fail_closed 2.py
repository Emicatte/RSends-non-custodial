"""
Test: AML fail-closed semantics (Fix 8.5).

Verifies:
  - is_blacklisted raises AMLBlockedError when DB is down
  - _get_daily_total_eur raises AMLDataUnavailableError on failure
  - _update_daily_total raises AMLDataUnavailableError on failure
  - _get_monthly_total_eur raises AMLDataUnavailableError on failure
  - _get_velocity_count raises AMLDataUnavailableError on failure
  - _check_structuring returns True (suspicious) on DB error
  - monitor_transaction forces review when counters are unavailable

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_aml_fail_closed.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.aml_exceptions import AMLBlockedError, AMLDataUnavailableError


@pytest.mark.asyncio
async def test_is_blacklisted_raises_on_db_error():
    """Legacy blacklist DB failure → AMLBlockedError (fail-closed)."""
    from app.services.aml_service import is_blacklisted

    clean_addr = "0x1111111111111111111111111111111111111111"

    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_ctx.execute = AsyncMock(side_effect=Exception("connection refused"))

    call_count = 0
    original_async_session = None

    async def mock_session_factory():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            ok_ctx = AsyncMock()
            ok_ctx.__aenter__ = AsyncMock(return_value=ok_ctx)
            ok_ctx.__aexit__ = AsyncMock(return_value=False)
            ok_result = MagicMock()
            ok_result.scalar_one_or_none.return_value = None
            ok_ctx.execute = AsyncMock(return_value=ok_result)
            return ok_ctx
        return mock_ctx

    with patch("app.services.aml_service.async_session", side_effect=mock_session_factory):
        with pytest.raises(AMLBlockedError):
            await is_blacklisted(clean_addr)


@pytest.mark.asyncio
async def test_get_daily_total_raises_on_failure():
    """Daily total DB+Redis both fail → AMLDataUnavailableError."""
    from app.services.aml_service import _get_daily_total_eur

    with patch("app.services.aml_service.async_session") as mock_sess:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock(side_effect=Exception("db down"))
        mock_sess.return_value = mock_ctx

        with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=None):
            with pytest.raises(AMLDataUnavailableError):
                await _get_daily_total_eur("0xabc")


@pytest.mark.asyncio
async def test_update_daily_total_raises_on_failure():
    """Daily total update with Redis down → AMLDataUnavailableError."""
    from app.services.aml_service import _update_daily_total

    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=None):
        with pytest.raises(AMLDataUnavailableError):
            await _update_daily_total("0xabc", 100.0)


@pytest.mark.asyncio
async def test_get_monthly_total_raises_on_failure():
    """Monthly total DB failure → AMLDataUnavailableError."""
    from app.services.aml_service import _get_monthly_total_eur

    with patch("app.services.aml_service.async_session") as mock_sess:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock(side_effect=Exception("db down"))
        mock_sess.return_value = mock_ctx

        with pytest.raises(AMLDataUnavailableError):
            await _get_monthly_total_eur("0xabc")


@pytest.mark.asyncio
async def test_get_velocity_count_raises_on_failure():
    """Velocity counter Redis fail → AMLDataUnavailableError."""
    from app.services.aml_service import _get_velocity_count

    with patch("app.services.cache_service.get_redis", new_callable=AsyncMock, return_value=None):
        with pytest.raises(AMLDataUnavailableError):
            await _get_velocity_count("0xabc")


@pytest.mark.asyncio
async def test_check_structuring_returns_true_on_error():
    """Structuring check DB error → returns True (suspicious, fail-closed)."""
    from app.services.aml_service import _check_structuring

    cfg = {
        "structuring_window_hours": 24,
        "structuring_min_count": 5,
        "structuring_threshold_pct": 0.9,
    }

    with patch("app.services.aml_service.async_session") as mock_sess:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock(side_effect=Exception("db down"))
        mock_sess.return_value = mock_ctx

        result = await _check_structuring("0xabc", 950.0, 1000.0, cfg)
        assert result is True


@pytest.mark.asyncio
async def test_monitor_transaction_forces_review_on_counter_failure():
    """When AML counters are unavailable, monitor_transaction forces review."""
    from app.services.aml_service import monitor_transaction

    with patch("app.services.aml_service._get_thresholds", new_callable=AsyncMock) as mock_thresh, \
         patch("app.services.aml_service._update_daily_total", new_callable=AsyncMock) as mock_daily, \
         patch("app.services.aml_service._get_monthly_total_eur", new_callable=AsyncMock) as mock_monthly, \
         patch("app.services.aml_service._get_velocity_count", new_callable=AsyncMock) as mock_velocity, \
         patch("app.services.aml_service._check_structuring", new_callable=AsyncMock) as mock_struct:

        mock_thresh.return_value = {
            "single": 1000.0,
            "daily": 5000.0,
            "monthly": 15000.0,
            "velocity": 10,
            "structuring_window_hours": 24,
            "structuring_min_count": 5,
            "structuring_threshold_pct": 0.9,
        }
        mock_daily.side_effect = AMLDataUnavailableError("redis down")
        mock_monthly.side_effect = AMLDataUnavailableError("db down")
        mock_velocity.side_effect = AMLDataUnavailableError("redis down")
        mock_struct.return_value = False

        result = await monitor_transaction(
            sender="0xabc",
            recipient="0xdef",
            amount_eur=50.0,
        )

        assert result.requires_manual_review is True
        assert result.risk_level == "high"
        assert result.approved is True


@pytest.mark.asyncio
async def test_aml_data_unavailable_error_exists():
    """AMLDataUnavailableError is importable and is an Exception subclass."""
    assert issubclass(AMLDataUnavailableError, Exception)
    err = AMLDataUnavailableError("test")
    assert str(err) == "test"
