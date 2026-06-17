"""Deny-by-default, FAIL-CLOSED email-verification gate for JWT-session routes.

Scope — this gate acts ONLY within the JWT-session namespace:
    /api/v1/user, /api/v1/organizations, /api/v1/invites
(the only route groups authenticated by the email/password access-token JWT;
confirmed via app/security/api_keys.py EXEMPT_PATHS + the route inventory — all
of these are fully auth-required, including the /invites preview/accept/decline
endpoints). Requests to ANY other path are passed through untouched.

Scoping by PATH (not by Bearer presence) is deliberate and load-bearing:
merchant API keys ride on the SAME `Authorization: Bearer` header
(`Bearer rsend_…`), and wallet-signature routes use `X-Wallet-*` headers. Path
scoping is what guarantees the gate never touches wallet-signature
(/forwarding, /splits, /distributions, /dashboard), merchant API-key
(/merchant), payment, internal, public-auth, or health routes — even though a
fail-CLOSED policy denies on token-verification failure.

Within the namespace:
- Allowlisted (method, path) — auth lifecycle + account self-management — pass
  through so an authenticated-but-unverified user can see their state, manage
  sessions, resend verification, or leave.
- Everything else is FAIL-CLOSED: the request proceeds ONLY when we positively
  confirm a verified user. If we cannot confirm verification (missing/invalid
  token, no subject claim, user row missing, DB/Redis error, or any unexpected
  exception) the request is DENIED. This is a custodial system; an inability to
  evaluate email_verified must never grant access.

Denials:
- missing Bearer              → 401 {code: no_token}
- token invalid / expired     → 401 {code: invalid_token}
- auth backend unavailable    → 503 {code: auth_unavailable}
- cannot confirm / unverified → 403 {code: email_not_verified}

The success `call_next` runs OUTSIDE the try/except, so a downstream route error
is never mis-reported as a gate 403.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── JWT-session namespace (the only route groups this gate acts on) ──
_GATED_PREFIXES: tuple[str, ...] = (
    "/api/v1/user",
    "/api/v1/organizations",
    "/api/v1/invites",
)


def _in_namespace(path: str) -> bool:
    """True if `path` is a JWT-session route (exact prefix or a sub-path)."""
    for prefix in _GATED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


# ── Allowlist (product decision: "Minimal + account self-management") ──
# (METHOD, exact-path) reachable by an authenticated-but-unverified user.
_ALLOWLIST_EXACT: set[tuple[str, str]] = {
    # Auth lifecycle. These live under /api/v1/auth, which is outside the gated
    # namespace (so already passes through); kept here as defense in depth in
    # case the namespace is ever widened.
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


def _unauthorized(code: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": {"code": code, "message": "Authentication required."}},
    )


def _service_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "auth_unavailable",
                "message": "Authentication is temporarily unavailable.",
            }
        },
    )


class EmailVerifiedGateMiddleware(BaseHTTPMiddleware):
    """See module docstring."""

    async def dispatch(self, request: Request, call_next):
        # CORS preflight is never gated.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Only the JWT-session namespace is gated. Everything else — wallet-
        # signature, merchant API-key, payment, internal, public auth, health —
        # passes through untouched, regardless of the Authorization header.
        if not _in_namespace(path):
            return await call_next(request)

        # Allowlisted routes stay reachable by unverified users.
        if _is_allowlisted(request.method, path):
            return await call_next(request)

        # ── FAIL-CLOSED: only a positively-confirmed verified user proceeds ──
        try:
            # Local imports keep app construction free of import cycles.
            from app.services.auth_service import AuthError, verify_access_token
            from app.db.session import async_session
            from app.models.auth_models import User

            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return _unauthorized("no_token")

            token = auth[7:]
            try:
                claims = await verify_access_token(token)
            except AuthError as e:
                # Token invalid/expired/revoked → 401. Auth backend down
                # (e.g. Redis) → 503. Either way DENY (fail-closed).
                if e.code == "auth_unavailable":
                    return _service_unavailable()
                return _unauthorized("invalid_token")

            user_id = claims.get("sub")
            if not user_id:
                return _unauthorized("invalid_token")

            async with async_session() as db:
                user = (
                    await db.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()

            # Cannot confirm a verified user → DENY (fail-closed).
            if user is None or not user.email_verified:
                return _blocked_response()
        except Exception:  # noqa: BLE001 — fail-CLOSED on any unexpected error
            logger.warning("email_verified_gate_error", exc_info=True)
            return _blocked_response()

        # Confirmed verified user. call_next runs OUTSIDE the try so a downstream
        # route error is never mis-reported as a gate 403.
        return await call_next(request)
