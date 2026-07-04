"""
RPagos Backend — End-user auth routes.

Endpoints (all under /api/v1/auth):
- POST   /google    exchange a Google ID token for an RPagos session
- POST   /refresh   rotate access + refresh token (one-time-use refresh)
- POST   /logout    revoke the current session
- GET    /me        return the authenticated user's profile

Security:
- Rate limits enforced globally via `ENDPOINT_LIMITS` in
  app/middleware/rate_limit.py (IP-scoped).
- Per-email quota (3/h) enforced in-route via Redis INCR helpers.
- httpOnly + Secure + SameSite=strict cookies, scoped to /api/v1/auth.
- Every branch emits an audit row via record_auth_event.
"""

import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.rate_limit import _redis_count, _redis_record
from app.models.auth_models import User, UserSession
from app.models.auth_schemas import (
    AuthResponse,
    GitHubLoginRequest,
    GoogleLoginRequest,
    UserMeResponse,
)
from app.security.trusted_proxy import get_real_client_ip
from app.services.auth_audit import record_auth_event
from app.services.auth_service import (
    REFRESH_TOKEN_TTL,
    ACCESS_TOKEN_TTL,
    AuthError,
    create_session,
    peek_unverified_email,
    revoke_session,
    rotate_refresh_token,
    verify_access_token,
    verify_google_id_token,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

COOKIE_REFRESH = "rsends_refresh"
COOKIE_SESSION = "rsends_sid"
COOKIE_PATH = "/api/v1/auth"

# Per-email login quota: 3 attempts / hour. Separate from the per-IP
# middleware quota (5 / 10 min) on POST /auth/google. Intended to prevent
# a distributed IP attack from credential-stuffing a single victim's email.
EMAIL_QUOTA_MAX = 30
EMAIL_QUOTA_WINDOW = 3600

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
#  POST /api/v1/auth/google
# ══════════════════════════════════════════════════════════════

@router.post("/google", response_model=AuthResponse)
async def google_login(
    payload: GoogleLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    ip = get_real_client_ip(request)
    ua = request.headers.get("User-Agent", "unknown")[:500]
    correlation_id = _correlation_id(request)

    # ── Per-email quota (in-route, separate from per-IP middleware) ──
    peeked_email = peek_unverified_email(payload.id_token)
    if peeked_email:
        key = f"rl:auth_email:{peeked_email.lower()}"
        try:
            current = await _redis_count(key, EMAIL_QUOTA_WINDOW)
            if current >= EMAIL_QUOTA_MAX:
                await record_auth_event(
                    event_type="rate_limit_exceeded",
                    ip_address=ip, user_agent=ua,
                    correlation_id=correlation_id,
                    details={"scope": "email", "email": peeked_email, "window_s": EMAIL_QUOTA_WINDOW},
                )
                raise HTTPException(
                    status_code=429,
                    detail={"code": "rate_limit_exceeded", "scope": "email"},
                )
            await _redis_record(key, EMAIL_QUOTA_WINDOW)
        except HTTPException:
            raise
        except Exception:
            # If Redis is unavailable the centralized middleware already
            # returns 503 for the per-IP limit. Tolerate here so auth can
            # proceed (Google itself rate-limits ID token issuance).
            pass

    # ── Verify Google ID token ──
    try:
        google_user = await verify_google_id_token(
            payload.id_token,
            expected_nonce=payload.nonce,
        )
    except AuthError as e:
        await record_auth_event(
            event_type="login_failure",
            ip_address=ip, user_agent=ua,
            google_sub=None,
            correlation_id=correlation_id,
            details={"code": e.code, "message": str(e)},
        )
        status = 503 if e.code == "server_misconfigured" else 401
        raise HTTPException(status_code=status, detail={"code": e.code, "message": str(e)})

    # One account per lowercase email: normalized here IN THE HANDLER (not
    # only in the verifier) so the guard and the stored value can't drift if
    # the service layer ever regresses.
    normalized_email = (google_user.email or "").strip().lower()

    # ── Upsert user ──
    res = await db.execute(select(User).where(User.google_sub == google_user.sub))
    user = res.scalar_one_or_none()

    is_new_user = user is None
    if user is None:
        # Account linking guard (parity with the GitHub path below): if the
        # email is already bound to another sign-in method, refuse — 409,
        # block-and-guide. No auto-linking; explicit settings-page linking is
        # the only merge path. func.lower() keeps the guard case-blind even
        # against legacy mixed-case rows.
        email_res = await db.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        collision = email_res.scalar_one_or_none()
        if collision is not None:
            await record_auth_event(
                event_type="login_failure",
                user_id=str(collision.id),
                ip_address=ip, user_agent=ua,
                correlation_id=correlation_id,
                details={
                    "code": "email_already_registered",
                    "google_sub": google_user.sub,
                },
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "email_already_registered",
                    "message": "This email is already registered with another sign-in method",
                },
            )

        user = User(
            id=str(uuid4()),
            google_sub=google_user.sub,
            email=normalized_email,
            email_verified=google_user.email_verified,
            # OAuth signups have no account-type chooser (that's the
            # email/password form); they onboard as individuals.
            account_type="individual",
            display_name=google_user.name,
            avatar_url=google_user.picture,
            locale=google_user.locale,
            last_login_at=datetime.now(timezone.utc),
            last_login_ip=ip,
        )
        db.add(user)
        await db.flush()
    else:
        if user.status != "active":
            await record_auth_event(
                event_type="login_failure",
                user_id=str(user.id), google_sub=user.google_sub,
                ip_address=ip, user_agent=ua,
                correlation_id=correlation_id,
                details={"code": "account_suspended", "status": user.status},
            )
            raise HTTPException(
                status_code=403,
                detail={"code": "account_suspended"},
            )
        user.last_login_at = datetime.now(timezone.utc)
        user.last_login_ip = ip
        # Email sync guard: the Google account's email can change upstream.
        # If the NEW address already belongs to ANOTHER user, keep the stored
        # one — overwriting would violate uq_users_email_lower (500) and
        # effectively absorb the other account's address. Login still works.
        if normalized_email != (user.email or "").lower():
            other = await db.execute(
                select(User).where(
                    func.lower(User.email) == normalized_email,
                    User.id != user.id,
                )
            )
            if other.scalar_one_or_none() is None:
                user.email = normalized_email
            else:
                log.warning(
                    "google_email_sync_skipped_collision",
                    extra={"user_id": str(user.id)},
                )
        user.display_name = google_user.name
        user.avatar_url = google_user.picture
        user.locale = google_user.locale

    # ── Create Redis-authoritative session ──
    try:
        session_id, access_token, refresh_token, refresh_hash = await create_session(
            user_id=str(user.id), ip=ip, user_agent=ua,
        )
    except AuthError as e:
        await record_auth_event(
            event_type="login_failure",
            user_id=str(user.id), google_sub=user.google_sub,
            ip_address=ip, user_agent=ua,
            correlation_id=correlation_id,
            details={"code": e.code},
        )
        raise HTTPException(status_code=503, detail={"code": e.code})

    # ── Persist session backup row (audit) ──
    session_row = UserSession(
        id=str(uuid4()),
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TOKEN_TTL),
        ip_address=ip,
        user_agent=ua,
    )
    db.add(session_row)
    await db.commit()

    # Auto-create the personal org for first-time sign-ins. Idempotent:
    # `create_personal_org` no-ops if one already exists. Deferred until
    # after the user/session commit so any failure here cannot roll back
    # the login itself — the Alembic 0030 backfill and the idempotent
    # re-check on next login will recover.
    if is_new_user:
        try:
            from app.services.org_service import create_personal_org
            await create_personal_org(db, user)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception(
                "personal_org_creation_failed",
                extra={"user_id": str(user.id)},
            )

    await record_auth_event(
        event_type="login_success",
        user_id=str(user.id), session_id=session_id,
        google_sub=user.google_sub,
        ip_address=ip, user_agent=ua,
        correlation_id=correlation_id,
    )

    _set_auth_cookies(response, session_id=session_id, refresh_token=refresh_token)

    return AuthResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_TTL,
        user=_user_to_response(user),
    )


# ══════════════════════════════════════════════════════════════
#  POST /api/v1/auth/github
# ══════════════════════════════════════════════════════════════

@router.post("/github", response_model=AuthResponse)
async def github_login(
    payload: GitHubLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    from app.services.github_oauth_service import (
        GitHubOAuthError,
        verify_github_access_token,
    )

    ip = get_real_client_ip(request)
    ua = request.headers.get("User-Agent", "unknown")[:500]
    correlation_id = _correlation_id(request)

    # ── Verify GitHub access token + fetch profile ──
    try:
        profile = await verify_github_access_token(payload.access_token)
    except GitHubOAuthError as e:
        await record_auth_event(
            event_type="login_failure",
            ip_address=ip, user_agent=ua,
            correlation_id=correlation_id,
            details={"code": f"github_{e.code}", "message": e.detail},
        )
        status = 401 if e.code == "invalid_token" else 400
        if e.code in ("github_api_error", "network_error"):
            status = 503
        raise HTTPException(
            status_code=status,
            detail={"code": f"github_{e.code}", "message": e.detail},
        )

    # Normalized in the handler (see google_login) — the guard and the stored
    # value must not depend on the service layer's casing.
    normalized_email = (profile.email or "").strip().lower()

    # ── Lookup by github_sub first ──
    res = await db.execute(select(User).where(User.github_sub == profile.sub))
    user = res.scalar_one_or_none()

    is_new_user = user is None
    if user is None:
        # Account linking guard: if email already bound to another provider,
        # refuse (409, block-and-guide — no auto-merge). func.lower() keeps
        # the guard case-blind even against legacy mixed-case rows.
        email_res = await db.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        collision = email_res.scalar_one_or_none()
        if collision is not None:
            await record_auth_event(
                event_type="login_failure",
                user_id=str(collision.id),
                ip_address=ip, user_agent=ua,
                correlation_id=correlation_id,
                details={
                    "code": "email_already_registered",
                    "github_sub": profile.sub,
                    "github_username": profile.username,
                },
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "email_already_registered",
                    "message": "This email is already registered with another sign-in method",
                },
            )

        user = User(
            id=str(uuid4()),
            github_sub=profile.sub,
            github_username=profile.username,
            email=normalized_email,
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
            # OAuth signups have no account-type chooser — see Google path.
            account_type="individual",
            display_name=profile.display_name or profile.username,
            avatar_url=profile.avatar_url,
            last_login_at=datetime.now(timezone.utc),
            last_login_ip=ip,
        )
        db.add(user)
        await db.flush()
    else:
        if user.status != "active":
            await record_auth_event(
                event_type="login_failure",
                user_id=str(user.id),
                ip_address=ip, user_agent=ua,
                correlation_id=correlation_id,
                details={
                    "code": "account_suspended",
                    "status": user.status,
                    "github_sub": user.github_sub,
                },
            )
            raise HTTPException(
                status_code=403,
                detail={"code": "account_suspended"},
            )
        user.last_login_at = datetime.now(timezone.utc)
        user.last_login_ip = ip
        user.github_username = profile.username
        if profile.avatar_url:
            user.avatar_url = profile.avatar_url
        if profile.display_name:
            user.display_name = profile.display_name

    # ── Create Redis-authoritative session ──
    try:
        session_id, access_token, refresh_token, refresh_hash = await create_session(
            user_id=str(user.id), ip=ip, user_agent=ua,
        )
    except AuthError as e:
        await record_auth_event(
            event_type="login_failure",
            user_id=str(user.id),
            ip_address=ip, user_agent=ua,
            correlation_id=correlation_id,
            details={"code": e.code, "github_sub": user.github_sub},
        )
        raise HTTPException(status_code=503, detail={"code": e.code})

    # ── Persist session backup row (audit) ──
    session_row = UserSession(
        id=str(uuid4()),
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TOKEN_TTL),
        ip_address=ip,
        user_agent=ua,
    )
    db.add(session_row)
    await db.commit()

    # Auto-create the personal org for first-time sign-ins (idempotent).
    if is_new_user:
        try:
            from app.services.org_service import create_personal_org
            await create_personal_org(db, user)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception(
                "personal_org_creation_failed",
                extra={"user_id": str(user.id)},
            )

    await record_auth_event(
        event_type="login_success",
        user_id=str(user.id), session_id=session_id,
        ip_address=ip, user_agent=ua,
        correlation_id=correlation_id,
        details={
            "provider": "github",
            "github_sub": user.github_sub,
            "github_username": user.github_username,
            "is_new_user": is_new_user,
        },
    )

    _set_auth_cookies(response, session_id=session_id, refresh_token=refresh_token)

    return AuthResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_TTL,
        user=_user_to_response(user),
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
