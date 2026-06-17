"""
RSends Backend — Standalone Rate Limiter Service.

Reusable sliding-window rate limiter backed by Redis sorted sets.
Falls back to in-memory when Redis is unavailable.

Usage::

    from app.services.rate_limiter import RateLimiter

    limiter = RateLimiter()

    allowed = await limiter.check(
        key=f"merchant:{merchant_id}:payment_intent",
        max_requests=100,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(429, "Rate limit exceeded.")
"""

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding window rate limiter with Redis + in-memory fallback.

    Each instance maintains its own in-memory fallback state.
    Redis is shared across instances/processes.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._ops = 0

    async def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Check if the request is allowed under the rate limit.

        Args:
            key: Unique key for the rate limit bucket (e.g. "merchant:abc:payment_intent")
            max_requests: Maximum allowed requests in the window
            window_seconds: Sliding window size in seconds

        Returns:
            True if allowed, False if rate limit exceeded.
        """
        try:
            return await self._check_redis(key, max_requests, window_seconds)
        except Exception:
            return self._check_memory(key, max_requests, window_seconds)

    async def remaining(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> int:
        """Get the number of remaining requests in the current window.

        Does NOT consume a request slot.
        """
        try:
            count = await self._redis_count(key, window_seconds)
        except Exception:
            count = self._memory_count(key, window_seconds)
        return max(0, max_requests - count)

    async def reset(self, key: str) -> None:
        """Reset a rate limit bucket (e.g. after successful auth)."""
        try:
            from app.services.cache_service import get_redis
            r = await get_redis()
            await r.delete(key)
        except Exception:
            pass
        with self._lock:
            self._buckets.pop(key, None)

    # ── Redis implementation ─────────────────────────────────

    async def _check_redis(
        self, key: str, max_requests: int, window_seconds: int,
    ) -> bool:
        from app.services.cache_service import get_redis

        r = await get_redis()
        now = time.time()
        window_start = now - window_seconds

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        count = results[2]
        return count <= max_requests

    async def _redis_count(self, key: str, window_seconds: int) -> int:
        from app.services.cache_service import get_redis

        r = await get_redis()
        now = time.time()
        window_start = now - window_seconds

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = await pipe.execute()
        return results[1]

    # ── In-memory fallback ───────────────────────────────────

    def _check_memory(
        self, key: str, max_requests: int, window_seconds: int,
    ) -> bool:
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            self._ops += 1
            if self._ops % 1000 == 0:
                self._cleanup(now)

            bucket = self._buckets[key]
            self._buckets[key] = [t for t in bucket if t > window_start]
            self._buckets[key].append(now)
            count = len(self._buckets[key])

        return count <= max_requests

    def _memory_count(self, key: str, window_seconds: int) -> int:
        now = time.time()
        window_start = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key, [])
            return sum(1 for t in bucket if t > window_start)

    def _cleanup(self, now: float) -> None:
        stale_keys = [
            k for k, v in self._buckets.items()
            if not v or v[-1] < now - 3600
        ]
        for k in stale_keys:
            del self._buckets[k]


# ── Module-level singleton ────────────────────────────────────
_default_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the default RateLimiter singleton."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter()
    return _default_limiter
