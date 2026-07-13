"""
RPagos Backend — End-user auth routes.

Endpoints (all under /api/v1/auth):
- POST   /refresh   rotate access + refresh token (one-time-use refresh)
- POST   /logout    revoke the current session
- GET    /me        return the authenticated user's profile

Login/signup is email/password only (app/api/auth_email_routes.py) — social
login (Google/GitHub) was removed from the product.

Security:
- Rate limits enforced globally via `ENDPOINT_LIMITS` in
  app/middleware/rate_limit.py (IP-scoped).
- httpOnly + Secure + SameSite=strict cookies, scoped to /api/v1/auth.
- Every branch emits an audit row via record_auth_event.
"""

import logging
from datetime import datetime, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User, UserSession
from app.models.auth_schemas import AuthResponse, UserMeResponse
from app.security.trusted_proxy import get_real_client_ip
from app.services.auth_audit import record_auth_event
from app.services.auth_service import (
    REFRESH_TOKEN_TTL,
    ACCESS_TOKEN_TTL,
    AuthError,
    revoke_session,
    rotate_refresh_token,
    verify_access_token,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

COOKIE_REFRESH = "rsends_refresh"
COOKIE_SESSION = "rsends_sid"
COOKIE_PATH = "/api/v1/auth"


# Fallback correlation id reader (middleware stores it in request.state.correlation_id).
def _correlation_id(request: Request) -> str | None:
    cid = getattr(request.state, "correlation_id", None)
    if cid:
        return str(cid)
    return request.headers.get("X-Correlation-ID")


def _set_auth_cookies(
    response: Response,
    *,
    session_id: str,
    refresh_token: str,
) -> None:
    response.set_cookie(
        COOKIE_REFRESH, refresh_token,
        max_age=REFRESH_TOKEN_TTL,
        httponly=True, secure=True, samesite="strict",
        path=COOKIE_PATH,
    )
    response.set_cookie(
        COOKIE_SESSION, session_id,
        max_age=REFRESH_TOKEN_TTL,
        httponly=True, secure=True, samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE_REFRESH, path=COOKIE_PATH)
    response.delete_cookie(COOKIE_SESSION, path=COOKIE_PATH)


def _user_to_response(user: User) -> UserMeResponse:
    return UserMeResponse(
        id=str(user.id),
        email=user.email,
        email_verified=bool(user.email_verified),
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        locale=user.locale,
    )


# ══════════════════════════════════════════════════════════════
#  POST /api/v1/auth/refresh
# ══════════════════════════════════════════════════════════════

@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    session_id = request.cookies.get(COOKIE_SESSION)
    refresh_token = request.cookies.get(COOKIE_REFRESH)
    if not session_id or not refresh_token:
        raise HTTPException(status_code=401, detail={"code": "no_session"})

    ip = get_real_client_ip(request)
    correlation_id = _correlation_id(request)

    try:
        new_access, new_refresh, user_id = await rotate_refresh_token(
            session_id=session_id, old_refresh_token=refresh_token, ip=ip,
        )
    except AuthError as e:
        await record_auth_event(
            event_type=(
                "refresh_reuse_detected"
                if e.code == "refresh_reuse_detected"
                else "login_failure"
            ),
            session_id=session_id, ip_address=ip,
            correlation_id=correlation_id,
            details={"code": e.code},
        )
        _clear_auth_cookies(response)
        status = 503 if e.code == "auth_unavailable" else 401
        raise HTTPException(status_code=status, detail={"code": e.code})

    await record_auth_event(
        event_type="token_rotation",
        user_id=user_id, session_id=session_id,
        ip_address=ip, correlation_id=correlation_id,
    )

    # Mirror the new hash into the DB backup row (best effort)
    try:
        res = await db.execute(
            select(UserSession).where(UserSession.session_id == session_id)
        )
        row = res.scalar_one_or_none()
        if row is not None:
            row.refresh_token_hash = sha256(new_refresh.encode()).hexdigest()
            row.last_used_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception:
        await db.rollback()

    response.set_cookie(
        COOKIE_REFRESH, new_refresh,
        max_age=REFRESH_TOKEN_TTL,
        httponly=True, secure=True, samesite="strict",
        path=COOKIE_PATH,
    )

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or user.status != "active":
        _clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail={"code": "user_not_found"})

    return AuthResponse(
        access_token=new_access,
        expires_in=ACCESS_TOKEN_TTL,
        user=_user_to_response(user),
    )


# ══════════════════════════════════════════════════════════════
#  POST /api/v1/auth/logout
# ══════════════════════════════════════════════════════════════

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    session_id = request.cookies.get(COOKIE_SESSION)
    ip = get_real_client_ip(request)
    correlation_id = _correlation_id(request)

    if session_id:
        await revoke_session(session_id)

        try:
            res = await db.execute(
                select(UserSession).where(UserSession.session_id == session_id)
            )
            row = res.scalar_one_or_none()
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(timezone.utc)
                row.revoked_reason = "logout"
                await db.commit()
        except Exception:
            await db.rollback()

        await record_auth_event(
            event_type="logout",
            session_id=session_id,
            ip_address=ip,
            correlation_id=correlation_id,
        )

    _clear_auth_cookies(response)
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════
#  GET /api/v1/auth/me
# ══════════════════════════════════════════════════════════════

@router.get("/me", response_model=UserMeResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserMeResponse:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "no_token"})
    token = auth[7:]

    try:
        claims = await verify_access_token(token)
    except AuthError as e:
        status = 503 if e.code == "auth_unavailable" else 401
        raise HTTPException(status_code=status, detail={"code": e.code})

    res = await db.execute(select(User).where(User.id == claims["sub"]))
    user = res.scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail={"code": "user_not_found"})

    return _user_to_response(user)
