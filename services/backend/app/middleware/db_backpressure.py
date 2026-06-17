"""DB backpressure middleware.

Application-level semaphore that bounds concurrent DB work BELOW the pool
capacity. This keeps a few pool connections reserved for non-critical work
(health checks, metrics, audit reads) even under write burst.

Sizing: if pool total = 50, semaphore = 40 for write paths. The remaining 10
slots absorb read-only probes without being starved by writes.

Applied only to endpoints flagged DB_HEAVY_PATHS. Health/metrics endpoints
bypass entirely.
"""
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

DB_HEAVY_SEMAPHORE_LIMIT = 40

DB_HEAVY_PATHS = (
    "/api/v1/merchant/payment-intent",
    "/api/v1/tx/callback",
    "/api/v1/sweep/execute",
    "/api/v1/execution/plan",
    "/api/v1/distribution/execute",
    "/api/v1/split",
    "/api/v1/strategies",
    "/api/v1/aml/check",
)

_db_semaphore = asyncio.Semaphore(DB_HEAVY_SEMAPHORE_LIMIT)


def _is_db_heavy(path: str) -> bool:
    return any(path.startswith(p) for p in DB_HEAVY_PATHS)


class DBBackpressureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _is_db_heavy(request.url.path):
            return await call_next(request)

        try:
            await asyncio.wait_for(_db_semaphore.acquire(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning(
                "DB backpressure: rejecting %s %s (semaphore saturated)",
                request.method, request.url.path,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "SERVICE_OVERLOADED",
                    "message": "Server momentaneamente sovraccarico — riprova tra qualche secondo",
                },
                headers={"Retry-After": "3"},
            )

        try:
            return await call_next(request)
        finally:
            _db_semaphore.release()


def get_db_semaphore_state() -> dict:
    """For /health/deep observability."""
    return {
        "limit": DB_HEAVY_SEMAPHORE_LIMIT,
        "available": _db_semaphore._value,
        "in_use": DB_HEAVY_SEMAPHORE_LIMIT - _db_semaphore._value,
    }
