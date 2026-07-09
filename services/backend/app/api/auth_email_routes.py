"""Email+password auth endpoints (Prompt 12 / Fase 3 start).

Parallel to `auth_routes.py` (Google OAuth), which stays untouched. The
login flow reproduces the Google flow's UserSession-row-persist + cookie
steps so both methods share the same downstream session semantics.

All endpoints live under /api/v1/auth, matching the Google router's
prefix so cookie path scoping (/api/v1/auth) remains consistent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import UserSession
from app.models.email_auth_schemas import (
    CheckEmailResponse,
    LoginRequest,
    LoginResponse,
    PasswordResetComplete,
    PasswordResetRequest,
    ResendVerificationRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
)
from app.security.trusted_proxy import get_real_client_ip
from app.services.auth_service import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL
from app.services.email_auth_service import (
    EmailAuthError,
    check_email,
    login,
    request_password_reset,
    resend_verification,
    reset_password,
    signup,
    verify_email,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth-email"])

# Mirror auth_routes.py cookie semantics exactly so both auth paths share
# the same cookie names/path and /refresh + /logout keep working on either.
COOKIE_REFRESH = "rsends_refresh"
COOKIE_SESSION = "rsends_sid"
COOKIE_PATH = "/api/v1/auth"


_ERROR_STATUS = {
    "email_already_exists": 409,
    "invalid_credentials": 401,
    "email_not_verified": 403,
    "password_not_set": 403,
    "account_suspended": 403,
    "account_deleted": 410,
    "rate_limit_exceeded": 429,
    "invalid_token": 400,
    "token_expired": 400,
    "token_already_used": 400,
    "email_mismatch": 400,
    "user_not_found": 400,
    "password_too_short": 400,
    "password_too_long": 400,
    "password_too_common": 400,
    "password_breached": 400,
    "terms_not_accepted": 400,
    "invalid_email_format": 400,
}


def _err_to_status(code: str) -> int:
    return _ERROR_STATUS.get(code, 400)


def _as_http(err: EmailAuthError) -> HTTPException:
    return HTTPException(
        status_code=_err_to_status(err.code),
        detail={"code": err.code, "message": err.detail},
    )


def _set_auth_cookies(
    response: Response, *, session_id: str, refresh_token: str
) -> None:
    response.set_cookie(
        COOKIE_REFRESH,
        refresh_token,
        max_age=REFRESH_TOKEN_TTL,
        httponly=True,
        secure=True,
        samesite="strict",
        path=COOKIE_PATH,
    )
    response.set_cookie(
        COOKIE_SESSION,
        session_id,
        max_age=REFRESH_TOKEN_TTL,
        httponly=True,
        secure=True,
        samesite="strict",
        path=COOKIE_PATH,
    )


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup_route(
    payload: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SignupResponse:
    try:
        user = await signup(
            db,
            email=payload.email,
            password=payload.password,
            first_name=payload.first_name,
            last_name=payload.last_name,
            date_of_birth=payload.date_of_birth,
            country_of_residence=payload.country_of_residence,
            account_type=payload.account_type,
            newsletter_opt_in=payload.newsletter_opt_in,
            display_name=payload.display_name,
            locale=payload.locale,
            ip=get_real_client_ip(request),
        )
    except EmailAuthError as e:
        raise _as_http(e)

    await db.commit()
    await db.refresh(user)

    return SignupResponse(
        user_id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        account_type=user.account_type,
        display_name=user.display_name,
        created_at=user.created_at,
    )


@router.post("/login", response_model=LoginResponse)
async def login_route(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    ip = get_real_client_ip(request)
    ua = request.headers.get("User-Agent", "")

    try:
        user, session_id, access_token, refresh_token, refresh_hash = await login(
            db,
            email=payload.email,
            password=payload.password,
            ip=ip,
            user_agent=ua,
        )
    except EmailAuthError as e:
        raise _as_http(e)

    # Persist UserSession audit row (mirrors auth_routes.py:219-228 Google flow).
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

    # Recovery hook for the email path: verified users whose personal org was
    # never created (dev-posture auto-verify bypasses verify_email; legacy
    # accounts). Idempotent and commit-isolated like the OAuth first-login
    # hook (auth_routes.py) — a failure here never rolls back the login.
    if user.email_verified and user.active_org_id is None:
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

    _set_auth_cookies(response, session_id=session_id, refresh_token=refresh_token)

    return LoginResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_TTL,
        user_id=user.id,
        email=user.email,
        email_verified=user.email_verified,
    )


@router.post("/verify-email", status_code=200)
async def verify_email_route(
    payload: VerifyEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        user = await verify_email(
            db, token=payload.token, ip=get_real_client_ip(request)
        )
    except EmailAuthError as e:
        raise _as_http(e)

    await db.commit()
    return {"status": "verified", "email": user.email}


@router.post("/resend-verification", status_code=200)
async def resend_verification_route(
    payload: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await resend_verification(
            db, email=payload.email, ip=get_real_client_ip(request)
        )
    except EmailAuthError as e:
        raise _as_http(e)

    await db.commit()
    return {"status": "ok"}


@router.post("/request-password-reset", status_code=200)
async def request_reset_route(
    payload: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await request_password_reset(
            db, email=payload.email, ip=get_real_client_ip(request)
        )
    except EmailAuthError as e:
        raise _as_http(e)

    await db.commit()
    return {
        "status": "ok",
        "message": "If an account exists with this email, a reset link has been sent",
    }


@router.post("/reset-password", status_code=200)
async def reset_password_route(
    payload: PasswordResetComplete,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        user = await reset_password(
            db,
            token=payload.token,
            new_password=payload.new_password,
            ip=get_real_client_ip(request),
        )
    except EmailAuthError as e:
        raise _as_http(e)

    await db.commit()
    return {"status": "reset", "email": user.email}


@router.get("/check-email", response_model=CheckEmailResponse)
async def check_email_route(
    email: str = Query(..., max_length=254),
    db: AsyncSession = Depends(get_db),
) -> CheckEmailResponse:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_email_format"}
        )
    data = await check_email(db, normalized)
    return CheckEmailResponse(**data)
