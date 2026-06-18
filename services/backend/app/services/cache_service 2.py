"""
RSend Cache Service — Redis connection con health tracking.

Cache per:
  - Token metadata da Alchemy (TTL: 10 min)
  - Prezzi token (TTL: 2 min)
  - Portfolio data (TTL: 30 sec)
  - Rate limiting per IP (sliding window)

Graceful degradation (solo per cache, NON per idempotency):
  - Redis down → in-memory LRU cache fallback
  - Circuit breaker tracks Redis health for /health/dependencies
"""

import json
import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Optional, Any
from datetime import datetime, timezone

import redis.asyncio as redis
from app.config import get_settings
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("cache_service")

_pool: Optional[redis.Redis] = None

# ── Health tracking (cached 5s) ──────────────────────────
_redis_healthy: bool = False
_last_health_check: float = 0
_HEALTH_CHECK_INTERVAL = 5  # secondi

_redis_cb = CircuitBreaker(
    name="redis",
    failure_threshold=3,
    recovery_timeout=15.0,
    half_open_max_calls=1,
)


# ═══════════════════════════════════════════════════════════
#  Centralized Redis Circuit Breaker (gates get_redis)
# ═══════════════════════════════════════════════════════════

from enum import Enum as _Enum


class _RedisCBState(_Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_rcb_state: _RedisCBState = _RedisCBState.CLOSED
_rcb_failure_count: int = 0
_rcb_opened_at: float = 0.0
_rcb_last_probe_at: float = 0.0

RCB_FAILURE_THRESHOLD = 3
RCB_OPEN_DURATION_S = 15
RCB_HALF_OPEN_PROBE_INTERVAL_S = 5


def _rcb_record_success() -> None:
    global _rcb_state, _rcb_failure_count
    if _rcb_state != _RedisCBState.CLOSED:
        logger.info("Redis circuit breaker → CLOSED (recovered)")
    _rcb_state = _RedisCBState.CLOSED
    _rcb_failure_count = 0


def _rcb_record_failure() -> None:
    global _rcb_state, _rcb_failure_count, _rcb_opened_at
    _rcb_failure_count += 1
    if _rcb_failure_count >= RCB_FAILURE_THRESHOLD and _rcb_state != _RedisCBState.OPEN:
        _rcb_state = _RedisCBState.OPEN
        _rcb_opened_at = time.monotonic()
        logger.warning(
            "Redis circuit breaker OPEN after %d failures — "
            "connections gated for %ds",
            _rcb_failure_count, RCB_OPEN_DURATION_S,
        )


def _rcb_should_attempt() -> bool:
    global _rcb_state, _rcb_last_probe_at
    now = time.monotonic()

    if _rcb_state == _RedisCBState.CLOSED:
        return True

    if _rcb_state == _RedisCBState.OPEN:
        if now - _rcb_opened_at < RCB_OPEN_DURATION_S:
            return False
        _rcb_state = _RedisCBState.HALF_OPEN
        _rcb_last_probe_at = 0.0
        logger.info("Redis circuit breaker → HALF_OPEN (probing recovery)")

    if now - _rcb_last_probe_at < RCB_HALF_OPEN_PROBE_INTERVAL_S:
        return False
    _rcb_last_probe_at = now
    return True


def get_redis_cb_state() -> dict:
    """Return current CB state for health endpoints."""
    return {
        "state": _rcb_state.value,
        "failure_count": _rcb_failure_count,
        "opened_at": _rcb_opened_at if _rcb_state != _RedisCBState.CLOSED else None,
    }


# ═══════════════════════════════════════════════════════════
#  In-Memory Fallback Cache (LRU, TTL-aware)
# ═══════════════════════════════════════════════════════════

class InMemoryCache:
    """Simple in-memory LRU cache with TTL, used when Redis is down."""

    MAX_SIZE = 1000

    def __init__(self) -> None:
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl)
            self._data.move_to_end(key)
            while len(self._data) > self.MAX_SIZE:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_memory_cache = InMemoryCache()
_redis_down_warned = False


# ═══════════════════════════════════════════════════════════
#  Redis Connection
# ═══════════════════════════════════════════════════════════

async def get_redis() -> Optional[redis.Redis]:
    """Lazy-init Redis connection pool. Returns None if CB is open or connection fails.

    Centralized circuit breaker prevents thundering-herd on Redis recovery:
    when Redis is down, all callers get None immediately without retrying.
    """
    global _pool

    if not _rcb_should_attempt():
        return None

    if _pool is None:
        settings = get_settings()
        url = getattr(settings, 'redis_url', None)
        if not url:
            return None
        try:
            _pool = redis.from_url(
                url,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            await _pool.ping()
            logger.info("Redis connected: %s", url)
            _rcb_record_success()
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
            _pool = None
            _rcb_record_failure()
            return None
    else:
        try:
            await _pool.ping()
            _rcb_record_success()
        except Exception as e:
            logger.debug("Redis ping failed: %s", e)
            _rcb_record_failure()
            _pool = None
            return None

    return _pool


async def is_redis_healthy() -> bool:
    """Check Redis health con cache di 5 secondi."""
    global _redis_healthy, _last_health_check
    now = time.time()
    if now - _last_health_check < _HEALTH_CHECK_INTERVAL:
        return _redis_healthy
    try:
        r = await get_redis()
        if r:
            await r.ping()
            _redis_healthy = True
        else:
            _redis_healthy = False
    except Exception:
        _redis_healthy = False
    _last_health_check = now
    return _redis_healthy


async def _redis_ping() -> bool:
    """Check if Redis is reachable (used by health checks)."""
    return await is_redis_healthy()


# ═══════════════════════════════════════════════════════════
#  Generic Cache (with circuit breaker + fallback)
# ═══════════════════════════════════════════════════════════

async def _redis_get(key: str) -> Optional[str]:
    r = await get_redis()
    return await r.get(key)


async def _redis_setex(key: str, ttl: int, value: str) -> None:
    r = await get_redis()
    await r.setex(key, ttl, value)


async def _redis_delete(key: str) -> None:
    r = await get_redis()
    await r.delete(key)


async def cache_get(key: str) -> Optional[Any]:
    """Get a cached value. Falls back to in-memory if Redis is down."""
    global _redis_down_warned
    try:
        val = await _redis_cb.call(_redis_get, key)
        if val is None:
            return None
        parsed = json.loads(val)
        # Also store in memory cache as backup
        _memory_cache.set(key, parsed, 600)
        return parsed
    except (CircuitOpenError, Exception):
        if not _redis_down_warned:
            logger.warning("Redis unavailable — using in-memory cache fallback")
            _redis_down_warned = True
        return _memory_cache.get(key)


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Set a cached value with TTL. Falls back to in-memory."""
    serialized = json.dumps(value, default=str)
    # Always store in memory as backup
    _memory_cache.set(key, value, ttl_seconds)
    try:
        await _redis_cb.call(_redis_setex, key, ttl_seconds, serialized)
        return True
    except (CircuitOpenError, Exception):
        return False


async def cache_delete(key: str) -> bool:
    """Delete a cached key."""
    _memory_cache.delete(key)
    try:
        await _redis_cb.call(_redis_delete, key)
        return True
    except (CircuitOpenError, Exception):
        return False


# ═══════════════════════════════════════════════════════════
#  Alchemy-specific Cache
# ═══════════════════════════════════════════════════════════

async def get_token_metadata(contract_address: str, chain_id: int) -> Optional[dict]:
    """Cache token metadata per 10 minuti."""
    key = f"meta:{chain_id}:{contract_address.lower()}"
    return await cache_get(key)


async def set_token_metadata(
    contract_address: str,
    chain_id: int,
    metadata: dict,
) -> None:
    """Salva token metadata in cache."""
    key = f"meta:{chain_id}:{contract_address.lower()}"
    await cache_set(key, metadata, ttl_seconds=600)  # 10 min


async def get_portfolio(address: str, chain_id: int) -> Optional[dict]:
    """Cache portfolio completo per 30 secondi."""
    key = f"portfolio:{chain_id}:{address.lower()}"
    return await cache_get(key)


async def set_portfolio(address: str, chain_id: int, data: dict) -> None:
    """Salva portfolio in cache."""
    key = f"portfolio:{chain_id}:{address.lower()}"
    await cache_set(key, data, ttl_seconds=30)


async def get_prices() -> Optional[dict]:
    """Cache prezzi token per 2 minuti."""
    return await cache_get("prices:usd")


async def set_prices(prices: dict) -> None:
    """Salva prezzi in cache."""
    await cache_set("prices:usd", prices, ttl_seconds=120)


# ═══════════════════════════════════════════════════════════
#  Rate Limiting (Sliding Window)
# ═══════════════════════════════════════════════════════════

async def check_rate_limit(
    identifier: str,
    max_requests: int = 60,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """
    Sliding window rate limiter.

    Returns:
        (allowed: bool, remaining: int)
    """
    try:
        r = await get_redis()
        key = f"rl:{identifier}"
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds

        pipe = r.pipeline()
        # Rimuovi entries scadute
        pipe.zremrangebyscore(key, 0, window_start)
        # Aggiungi request corrente
        pipe.zadd(key, {str(now): now})
        # Conta requests nella finestra
        pipe.zcard(key)
        # Imposta TTL sulla chiave
        pipe.expire(key, window_seconds)

        results = await pipe.execute()
        count = results[2]
        remaining = max(0, max_requests - count)

        return (count <= max_requests, remaining)
    except Exception:
        # Se Redis è down, permetti la richiesta
        return (True, max_requests)


# ═══════════════════════════════════════════════════════════
#  Cleanup
# ═══════════════════════════════════════════════════════════

async def close_redis() -> None:
    """Chiudi il pool Redis."""
    global _pool, _redis_healthy
    if _pool:
        await _pool.close()
        _pool = None
        _redis_healthy = False
