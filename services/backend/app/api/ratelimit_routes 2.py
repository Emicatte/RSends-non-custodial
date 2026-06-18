"""
RSends Backend — Internal generic rate limiter (Redis-backed, fail-closed).

Called server-side by the Next.js oracle as a SHARED early gate before the
heavy AML + EIP-712 signing work. The previous oracle throttle lived in an
in-memory Map per Lambda (per-process, not shared); this endpoint makes the
gate atomic and shared across all instances via Redis (M5).

Internal-only:
  - Gated by X-Internal-Secret (reuses the H3 internal-secret dependency), so
    only the server-side oracle can reach it — not the public proxy/browser
    (the Next catch-all already denylists `api/internal/*`).
  - Exempt from API-key auth (added to EXEMPT_PATHS).

Fail-closed: if Redis is unreachable, the request is DENIED (consistent with
the signing rate limiter and the rest of the signing path).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.signing_routes import require_internal_secret

logger = logging.getLogger(__name__)

ratelimit_router = APIRouter(prefix="/api/internal/ratelimit", tags=["ratelimit"])


class RateLimitCheckRequest(BaseModel):
    bucket: str = Field(..., min_length=1, max_length=64)
    key: str = Field(..., min_length=1, max_length=200)
    max: int = Field(..., ge=1, le=100_000)
    window_seconds: int = Field(..., ge=1, le=86_400)


class RateLimitCheckResponse(BaseModel):
    allowed: bool
    retry_after: Optional[int] = None


def _safe_key(raw: str) -> str:
    """Sanitize the caller-supplied key for use in a Redis key."""
    return raw.strip().replace(" ", "_").replace("\n", "").replace("\r", "")[:200]


@ratelimit_router.post("/check", response_model=RateLimitCheckResponse)
async def ratelimit_check(
    body: RateLimitCheckRequest,
    _internal: None = Depends(require_internal_secret),
) -> RateLimitCheckResponse:
    """Atomic fixed-window rate-limit check.

    Increments a Redis counter `rl:{bucket}:{key}` with a `window_seconds` TTL.
    Returns allowed=False (with retry_after) once the count exceeds `max`.
    """
    from app.services.cache_service import get_redis

    try:
        r = await get_redis()
    except Exception:
        r = None

    if r is None:
        # Fail-closed: deny when the shared store is unavailable.
        return RateLimitCheckResponse(allowed=False, retry_after=body.window_seconds)

    try:
        rk = f"rl:{body.bucket}:{_safe_key(body.key)}"
        pipe = r.pipeline()
        pipe.incr(rk)
        pipe.expire(rk, body.window_seconds)
        results = await pipe.execute()
        count = int(results[0])

        if count > body.max:
            ttl = await r.ttl(rk)
            retry = ttl if (isinstance(ttl, int) and ttl > 0) else body.window_seconds
            return RateLimitCheckResponse(allowed=False, retry_after=retry)

        return RateLimitCheckResponse(allowed=True)

    except Exception as e:
        logger.error("ratelimit check failed: %s", e, extra={"service": "ratelimit"})
        # Fail-closed on any Redis error.
        return RateLimitCheckResponse(allowed=False, retry_after=body.window_seconds)
