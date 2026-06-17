"""
RSends Backend — Request Context Middleware.

Genera un request_id UUID per ogni richiesta HTTP e lo salva
in contextvars insieme a client_ip e user_agent.

Aggiunge l'header X-Request-ID alla risposta.
Tutti i log della richiesta includono automaticamente il request_id.
"""

import uuid
from contextvars import ContextVar
from typing import Optional
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Context variables ────────────────────────────────────────
_request_id_ctx: ContextVar[Optional[UUID]] = ContextVar("request_id", default=None)
_client_ip_ctx: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)
_user_agent_ctx: ContextVar[Optional[str]] = ContextVar("user_agent", default=None)


# ── Public accessors ─────────────────────────────────────────

def get_request_id() -> Optional[UUID]:
    return _request_id_ctx.get()


def get_client_ip() -> Optional[str]:
    return _client_ip_ctx.get()


def get_user_agent() -> Optional[str]:
    return _user_agent_ctx.get()


# ── Middleware ────────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Popola contextvars con request_id, client_ip, user_agent."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Genera o riusa il request_id dal client
        incoming_id = request.headers.get("X-Request-ID")
        if incoming_id:
            try:
                req_id = UUID(incoming_id)
            except ValueError:
                req_id = uuid.uuid4()
        else:
            req_id = uuid.uuid4()

        # Estrai client IP (validato via trusted proxy)
        from app.security.trusted_proxy import get_real_client_ip

        client_ip = get_real_client_ip(request)

        user_agent = request.headers.get("User-Agent")

        # Imposta le context variables
        tok_rid = _request_id_ctx.set(req_id)
        tok_ip = _client_ip_ctx.set(client_ip)
        tok_ua = _user_agent_ctx.set(user_agent)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = str(req_id)
            return response
        finally:
            # Ripristina i context variables
            _request_id_ctx.reset(tok_rid)
            _client_ip_ctx.reset(tok_ip)
            _user_agent_ctx.reset(tok_ua)
