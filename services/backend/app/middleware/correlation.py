"""
RSends Backend — Correlation ID Middleware.

Genera un X-Correlation-ID (UUID4) per ogni request in ingresso,
o riusa quello presente nell'header (propagato da un altro servizio).

Il correlation_id è salvato in un contextvars.ContextVar accessibile
da qualsiasi punto del codice, inclusi i task Celery.

Differenza con request_id:
  - request_id  → identifica una singola richiesta HTTP
  - correlation_id → segue un'operazione attraverso tutti i servizi
    (API → Celery → RPC → notifiche)
"""

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Context variable ────────────────────────────────────────
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


# ── Public accessors ────────────────────────────────────────

def get_correlation_id() -> str:
    """Return the current correlation ID, or empty string if not set."""
    return correlation_id.get()


def set_correlation_id(cid: str) -> contextvars.Token:
    """Set the correlation ID (used by Celery task bootstrap)."""
    return correlation_id.set(cid)


# ── Middleware ───────────────────────────────────────────────

class CorrelationMiddleware(BaseHTTPMiddleware):
    """Popola correlation_id da header o lo genera come UUID4."""

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        tok = correlation_id.set(cid)

        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id.reset(tok)
