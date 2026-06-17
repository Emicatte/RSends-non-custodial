"""Request timeout middleware.

Cancels requests that exceed a configurable timeout to prevent blocking
handlers (synchronous Web3 calls in deposit_address_service.py, slow
external HTTP) from holding connections indefinitely.

Timeout ladder:
  - Sweep-related routes: 120s (on-chain operations are slow)
  - All other routes: 30s
"""
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30
SWEEP_TIMEOUT_S = 120
SWEEP_PATH_MARKERS = ("/sweep", "/execution/plan", "/distribution/execute", "/split")


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        timeout = SWEEP_TIMEOUT_S if any(m in path for m in SWEEP_PATH_MARKERS) else DEFAULT_TIMEOUT_S

        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except asyncio.TimeoutError:
            correlation_id = request.headers.get("x-correlation-id", "-")
            logger.error(
                "Request timeout after %ss: %s %s (correlation_id=%s)",
                timeout, request.method, path, correlation_id,
            )
            return JSONResponse(
                status_code=504,
                content={
                    "error": "REQUEST_TIMEOUT",
                    "message": f"Request exceeded {timeout}s timeout",
                },
            )
