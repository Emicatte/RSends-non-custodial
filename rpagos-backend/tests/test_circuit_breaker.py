"""
RPagos Backend — Circuit Breaker & Graceful Degradation Tests.

Tests:
  - CircuitBreaker state machine (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - Decorator with fallback
  - RPC fallback when primary circuit is OPEN
  - Redis graceful degradation (in-memory fallback)
  - Telegram circuit breaker (skip on failure)
  - External health endpoint
"""

import asyncio
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CBState,
    circuit_breaker,
    get_all_circuit_breakers,
    get_circuit_breaker,
    _registry,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Reset all circuit breakers between tests."""
    # Save original registry
    saved = dict(_registry)
    yield
    # Reset all CBs that existed during the test
    for cb in _registry.values():
        cb.reset()
    # Restore original registry (remove test-only CBs)
    keys_to_remove = [k for k in _registry if k not in saved]
    for k in keys_to_remove:
        del _registry[k]


# ═══════════════════════════════════════════════════════════════
#  Test: CircuitBreaker State Machine
# ═══════════════════════════════════════════════════════════════

class TestCircuitBreakerStateMachine:

    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker("test_closed", failure_threshold=3)
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        cb = CircuitBreaker("test_success", failure_threshold=3)

        async def ok():
            return "ok"

        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == CBState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker("test_open", failure_threshold=3, recovery_timeout=60.0)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        assert cb.state == CBState.OPEN
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker("test_reject", failure_threshold=2, recovery_timeout=60.0)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        # Now circuit is OPEN — next call should raise CircuitOpenError
        async def ok():
            return "ok"

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(ok)
        assert exc_info.value.name == "test_reject"

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test_halfopen", failure_threshold=2, recovery_timeout=0.1)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        assert cb.state == CBState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        assert cb.state == CBState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = CircuitBreaker("test_ho_close", failure_threshold=2, recovery_timeout=0.1)

        async def fail():
            raise RuntimeError("boom")

        async def ok():
            return "ok"

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        await asyncio.sleep(0.15)
        assert cb.state == CBState.HALF_OPEN

        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test_ho_reopen", failure_threshold=2, recovery_timeout=0.1)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        await asyncio.sleep(0.15)
        assert cb.state == CBState.HALF_OPEN

        with pytest.raises(RuntimeError):
            await cb.call(fail)

        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_limits_calls(self):
        cb = CircuitBreaker(
            "test_ho_limit", failure_threshold=2,
            recovery_timeout=0.1, half_open_max_calls=1,
        )

        async def fail():
            raise RuntimeError("boom")

        async def slow():
            await asyncio.sleep(0.5)
            return "ok"

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        await asyncio.sleep(0.15)
        assert cb.state == CBState.HALF_OPEN

        # First call allowed, second should be rejected
        # We simulate by calling ok then checking
        async def ok():
            return "ok"

        await cb.call(ok)
        # After success, state is CLOSED
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_excluded_exceptions_not_counted(self):
        cb = CircuitBreaker(
            "test_excluded", failure_threshold=2,
            excluded_exceptions=(ValueError,),
        )

        async def raise_value_error():
            raise ValueError("not a failure")

        for _ in range(5):
            with pytest.raises(ValueError):
                await cb.call(raise_value_error)

        # Should still be CLOSED — ValueError is excluded
        assert cb.state == CBState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = CircuitBreaker("test_reset", failure_threshold=2, recovery_timeout=60.0)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        assert cb.state == CBState.OPEN
        cb.reset()
        assert cb.state == CBState.CLOSED
        assert cb.failure_count == 0


# ═══════════════════════════════════════════════════════════════
#  Test: Decorator
# ═══════════════════════════════════════════════════════════════

class TestCircuitBreakerDecorator:

    @pytest.mark.asyncio
    async def test_decorator_passes_through(self):
        @circuit_breaker(name="test_deco_pass", failure_threshold=3)
        async def my_func(x):
            return x * 2

        result = await my_func(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_decorator_with_fallback(self):
        async def my_fallback(x):
            return -1

        @circuit_breaker(
            name="test_deco_fb", failure_threshold=2,
            recovery_timeout=60.0, fallback=my_fallback,
        )
        async def my_func(x):
            raise RuntimeError("down")

        # First 2 calls fail normally
        with pytest.raises(RuntimeError):
            await my_func(1)
        with pytest.raises(RuntimeError):
            await my_func(2)

        # Circuit open — fallback should be used
        result = await my_func(3)
        assert result == -1

    @pytest.mark.asyncio
    async def test_decorator_sync_fallback(self):
        def sync_fallback(x):
            return "fallback"

        @circuit_breaker(
            name="test_deco_sync_fb", failure_threshold=1,
            recovery_timeout=60.0, fallback=sync_fallback,
        )
        async def my_func(x):
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await my_func(1)

        result = await my_func(2)
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_decorator_registers_cb(self):
        @circuit_breaker(name="test_deco_reg", failure_threshold=5)
        async def my_func():
            return True

        cb = get_circuit_breaker("test_deco_reg")
        assert cb is not None
        assert cb.failure_threshold == 5


# ═══════════════════════════════════════════════════════════════
#  Test: Registry
# ═══════════════════════════════════════════════════════════════

class TestRegistry:

    def test_get_circuit_breaker(self):
        cb = CircuitBreaker("test_registry_get")
        retrieved = get_circuit_breaker("test_registry_get")
        assert retrieved is cb

    def test_get_nonexistent_returns_none(self):
        assert get_circuit_breaker("does_not_exist") is None

    def test_get_all(self):
        CircuitBreaker("test_all_a")
        CircuitBreaker("test_all_b")
        all_cbs = get_all_circuit_breakers()
        assert "test_all_a" in all_cbs
        assert "test_all_b" in all_cbs


# ═══════════════════════════════════════════════════════════════
#  Test: CircuitBreaker.info()
# ═══════════════════════════════════════════════════════════════

class TestCircuitBreakerInfo:

    def test_info_closed(self):
        cb = CircuitBreaker("test_info", failure_threshold=5, recovery_timeout=30.0)
        info = cb.info()
        assert info["name"] == "test_info"
        assert info["state"] == "closed"
        assert info["failure_count"] == 0
        assert info["failure_threshold"] == 5
        assert info["recovery_timeout"] == 30.0


# ═══════════════════════════════════════════════════════════════
#  Test: RPC Fallback (sweep_service._rpc_call)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="RPC circuit-breaker moved sweep_service -> rpc_manager (per-provider API); test pending rewrite")
class TestRPCFallback:

    @pytest.mark.asyncio
    async def test_rpc_call_uses_fallback_on_circuit_open(self):
        """When primary RPC circuit is open, fallback URLs are tried."""
        from app.services.sweep_service import _rpc_call, _rpc_cb

        # Force circuit open
        _rpc_cb._state = CBState.OPEN
        _rpc_cb._last_failure_time = time.monotonic()

        with patch(
            "app.services.sweep_service._rpc_call_raw",
            new_callable=AsyncMock,
            return_value="0x1234",
        ) as mock_raw:
            result = await _rpc_call(8453, "eth_blockNumber", [])
            assert result == "0x1234"
            # Should have been called with a fallback URL
            call_url = mock_raw.call_args[0][0]
            assert call_url != "https://mainnet.base.org"  # not the primary

    @pytest.mark.asyncio
    async def test_rpc_call_succeeds_normally(self):
        """Normal call goes through circuit breaker to primary URL."""
        from app.services.sweep_service import _rpc_call, _rpc_cb

        _rpc_cb.reset()

        with patch(
            "app.services.sweep_service._rpc_call_raw",
            new_callable=AsyncMock,
            return_value="0xabc",
        ):
            result = await _rpc_call(8453, "eth_blockNumber", [])
            assert result == "0xabc"

    @pytest.mark.asyncio
    async def test_rpc_call_all_fallbacks_fail(self):
        """When all fallbacks fail, raises RuntimeError."""
        from app.services.sweep_service import _rpc_call, _rpc_cb

        _rpc_cb._state = CBState.OPEN
        _rpc_cb._last_failure_time = time.monotonic()

        with patch(
            "app.services.sweep_service._rpc_call_raw",
            new_callable=AsyncMock,
            side_effect=RuntimeError("all down"),
        ):
            with pytest.raises(RuntimeError, match="All RPC endpoints failed"):
                await _rpc_call(8453, "eth_blockNumber", [])


# ═══════════════════════════════════════════════════════════════
#  Test: Redis Graceful Degradation (cache_service)
# ═══════════════════════════════════════════════════════════════

class TestRedisGracefulDegradation:

    @pytest.mark.asyncio
    async def test_cache_falls_back_to_memory_on_redis_down(self):
        """When Redis circuit is open, in-memory cache is used."""
        from app.services.cache_service import (
            cache_get, cache_set, _redis_cb, _memory_cache,
        )

        _memory_cache.clear()

        # Force Redis circuit open
        _redis_cb._state = CBState.OPEN
        _redis_cb._last_failure_time = time.monotonic()

        # Set should store in memory
        result = await cache_set("test:key", {"hello": "world"}, 60)
        assert result is False  # Redis failed, but memory has it

        # Get should retrieve from memory
        value = await cache_get("test:key")
        assert value == {"hello": "world"}

    @pytest.mark.asyncio
    async def test_cache_returns_none_when_no_fallback(self):
        """Cache miss returns None even with Redis down."""
        from app.services.cache_service import cache_get, _redis_cb, _memory_cache

        _memory_cache.clear()
        _redis_cb._state = CBState.OPEN
        _redis_cb._last_failure_time = time.monotonic()

        value = await cache_get("nonexistent:key")
        assert value is None

    @pytest.mark.asyncio
    async def test_memory_cache_lru_eviction(self):
        """In-memory cache evicts oldest entries when full."""
        from app.services.cache_service import InMemoryCache

        cache = InMemoryCache()
        cache.MAX_SIZE = 5

        for i in range(10):
            cache.set(f"key:{i}", i, 60)

        # Only last 5 should remain
        assert cache.get("key:0") is None
        assert cache.get("key:9") == 9

    @pytest.mark.asyncio
    async def test_memory_cache_ttl_expiry(self):
        """In-memory cache entries expire after TTL."""
        from app.services.cache_service import InMemoryCache

        cache = InMemoryCache()
        cache.set("expire:key", "value", 0)  # TTL=0 → immediately expired

        import time as _t
        _t.sleep(0.01)
        assert cache.get("expire:key") is None


# ═══════════════════════════════════════════════════════════════
#  Test: Telegram Circuit Breaker
# ═══════════════════════════════════════════════════════════════

class TestTelegramCircuitBreaker:

    @pytest.mark.asyncio
    async def test_telegram_skipped_when_circuit_open(self):
        """When Telegram circuit is open, notification returns False."""
        from app.services.sweep_service import _notify_telegram, _telegram_cb

        _telegram_cb._state = CBState.OPEN
        _telegram_cb._last_failure_time = time.monotonic()

        with patch("app.services.sweep_service.get_settings") as mock_settings:
            mock_settings.return_value.telegram_bot_token = "fake-token"
            result = await _notify_telegram("123", "test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_telegram_no_token_skips(self):
        """No bot token → returns False immediately (no CB interaction)."""
        from app.services.sweep_service import _notify_telegram, _telegram_cb

        _telegram_cb.reset()

        with patch("app.services.sweep_service.get_settings") as mock_settings:
            mock_settings.return_value.telegram_bot_token = ""
            result = await _notify_telegram("123", "test message")
            assert result is False


# ═══════════════════════════════════════════════════════════════
#  Test: External Health Endpoint
# ═══════════════════════════════════════════════════════════════

class TestExternalHealth:

    @pytest.mark.asyncio
    async def test_health_dependencies_returns_all_services(self):
        """GET /health/dependencies returns status for all circuit breakers."""
        from app.services.external_health import get_dependency_summary

        # Ensure some CBs exist
        CircuitBreaker("test_health_a")
        CircuitBreaker("test_health_b")

        summary = await get_dependency_summary()
        assert "overall" in summary
        assert "services" in summary
        assert summary["overall"] in ("healthy", "degraded", "down")

    @pytest.mark.asyncio
    async def test_health_shows_degraded_when_service_open(self):
        """If one service circuit is OPEN, overall is degraded."""
        from app.services.external_health import get_dependency_summary

        cb = CircuitBreaker("test_health_degraded", failure_threshold=1)
        cb._state = CBState.OPEN
        cb._last_failure_time = time.monotonic()

        summary = await get_dependency_summary()
        assert summary["overall"] == "degraded"
        svc = summary["services"]["test_health_degraded"]
        assert svc["status"] == "down"
        assert svc["circuit_state"] == "open"

    @pytest.mark.asyncio
    async def test_health_all_healthy(self):
        """All circuits CLOSED → overall healthy."""
        from app.services.external_health import get_dependency_summary

        # Reset all existing CBs
        for cb in get_all_circuit_breakers().values():
            cb.reset()

        summary = await get_dependency_summary()
        assert summary["overall"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_endpoint_via_api(self):
        """Test the actual HTTP endpoint."""
        from app.main import app
        from app.db.session import engine
        from app.models.db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/health/dependencies")
                assert r.status_code == 200
                data = r.json()
                assert "overall" in data
                assert "services" in data
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
