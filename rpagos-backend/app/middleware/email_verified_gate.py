"""Deny-by-default email-verification gate for JWT-session routes.

Any request that carries a *verifying* access-token JWT (Authorization: Bearer)
must belong to a user with email_verified=true, UNLESS its (method, path) is on
the allowlist below. This is deny-by-default: a newly added JWT-session route is
gated automatically — it has to be explicitly allowlisted to be reachable by an
unverified user.

What is NOT affected:
- Requests without a Bearer token (public auth endpoints, cookie-based
  /refresh + /logout) → passed through.
- Wallet-signature routes (X-Wallet-* headers) and the merchant API-key routes
  → they never carry an access-token JWT, so verify_access_token fails and the
  request is passed through.
- Tokens that don't verify → passed through; the route's own dependency returns
  the appropriate 401.

Fail-open: on any verification / DB / Redis error the request is passed
through. The gate only ever *adds* a 403 for a confirmed-unverified user on a
non-allowlisted route, so a verified user is never wrongly blocked and an infra
hiccup cannot lock everyone out. The route dependencies remain the real
authn/authz enforcement.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── Allowlist (product decision: "Minimal + account self-management") ──
# (METHOD, exact-path) reachable by an authenticated-but-unverified user.
_ALLOWLIST_EXACT: set[tuple[str, str]] = {
    # Auth lifecycle — the user must be able to see they're unverified, refresh
    # their session, log out, and (re)trigger verification.
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/resend-verification"),
    ("POST", "/api/v1/auth/verify-email"),
    # Account self-management — view status/sessions, secure the account, leave.
    ("GET", "/api/v1/user/account/status"),
    ("GET", "/api/v1/user/account/sessions"),
    ("POST", "/api/v1/user/account/sessions/revoke-all"),
    ("POST", "/api/v1/user/account/delete"),
    ("POST", "/api/v1/user/account/delete/cancel"),
}

# (METHOD, path-pattern) for dynamic segments.
_ALLOWLIST_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    # DELETE /api/v1/user/account/sessions/{session_id} — revoke one session.
    ("DELETE", re.compile(r"^/api/v1/user/account/sessions/[^/]+$")),
]


def _is_allowlisted(method: str, path: str) -> bool:
    if (method, path) in _ALLOWLIST_EXACT:
        return True
    for m, pattern in _ALLOWLIST_PATTERNS:
        if m == method and pattern.match(path):
            return True
    return False


def _blocked_response() -> JSONResponse:
    # Mirror the {"detail": {"code", "message"}} error shape used across the
    # auth routes so the frontend's existing error handling recognizes it.
    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "code": "email_not_verified",
                "message": "Please verify your email to access this feature.",
            }
        },
    )


class EmailVerifiedGateMiddleware(BaseHTTPMiddleware):
    """See module docstring."""

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")

        # Fast path: no Bearer token (or CORS preflight) → never our concern.
        if request.method == "OPTIONS" or not auth.startswith("Bearer "):
            return await call_next(request)

        path = request.url.path
        if _is_allowlisted(request.method, path):
            return await call_next(request)

        try:
            # Local imports keep app construction free of import cycles.
            from app.services.auth_service import AuthError, verify_access_token
            from app.db.session import async_session
            from app.models.auth_models import User

            token = auth[7:]
            try:
                claims = await verify_access_token(token)
            except AuthError:
                # Not a valid session access token → let the route's own
                # dependency decide (401/403). Not a gate concern.
                return await call_next(request)

            user_id = claims.get("sub")
            if not user_id:
                return await call_next(request)

            async with async_session() as db:
                user = (
                    await db.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()

            if user is not None and not user.email_verified:
                return _blocked_response()
        except Exception:  # noqa: BLE001 — fail-open on any unexpected error
            logger.warning("email_verified_gate_error", exc_info=True)
            return await call_next(request)

        return await call_next(request)
