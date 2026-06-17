"""Global error handler — catches unhandled exceptions and returns structured errors."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.config import get_settings
import logging
import traceback

logger = logging.getLogger("error_handler")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            settings = get_settings()
            logger.exception("Unhandled error: %s", exc)

            # In production: mai esporre dettagli interni
            if settings.debug:
                detail = str(exc)
            else:
                detail = None

            return JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                    "detail": detail,
                }
            )
