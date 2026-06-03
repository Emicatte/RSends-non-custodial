"""Email+password auth lifecycle: signup, login, verify, reset.

Parallel path to Google OAuth. Both live in the same `users` table — a user
may have google_sub, password_hash, or (after Prompt 15) both. Existing
Google users are implicitly email_verified; new email signups must verify
before they can log in.

Architectural notes:
- Sessions are created via `auth_service.create_session` (unchanged). The
  tuple it returns is handed to the route, which persists the `UserSession`
  audit row and sets cookies — mirroring the Google flow in `auth_routes.py`.
- Password reset invalidates every session by scanning `user_sessions`
  (active rows only) and calling `revoke_session` on each. Done here rather
  than in `auth_service` to keep that module untouched per Prompt 12
  constraints.
- Idempotent responses (`resend_verification`, `request_password_reset`) to
  prevent email enumeration.
- Rate limits use Redis INCR with fixed windows; fail-open on Redis errors.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_models import User, UserSession
from app.models.email_auth_models import EmailVerificationToken, PasswordResetToken
from app.services.auth_audit import record_auth_event
from app.services.auth_service import create_session, revoke_session
from app.services.cache_service import get_redis
from app.services.email_service import send_email
from app.services.password_service import (
    hash_password, verify_password, validate_policy, PasswordPolicyError,
)

log = logging.getLogger(__name__)

VERIFICATION_TTL_HOURS = 24
RESET_TTL_HOURS = 1

LOGIN_RL_IP_MAX = 5
LOGIN_RL_IP_WINDOW = 15 * 60
LOGIN_RL_EMAIL_MAX = 10
LOGIN_RL_EMAIL_WINDOW = 60 * 60
SIGNUP_RL_IP_MAX = 10
SIGNUP_RL_IP_WINDOW = 60 * 60
RESET_RL_EMAIL_MAX = 3
RESET_RL_EMAIL_WINDOW = 60 * 60
VERIFY_RESEND_RL_MAX = 3
VERIFY_RESEND_RL_WINDOW = 60 * 60

# Dummy bcrypt hash used in the invalid-credentials path so verify_password
# runs in the same time envelope whether the user exists or not. This is a
# valid bcrypt string that will never match any real password.
_DUMMY_BCRYPT = "$2b$12$" + "." * 53


class EmailAuthError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _rate_limit_check(key: str, max_count: int, window_seconds: int) -> None:
    """Fixed-window Redis rate limit. Raises EmailAuthError on hit.
    Fail-open on Redis errors (auth_service treats Redis outage as fail-closed;
    here we stay fail-open so a Redis hiccup doesn't block legitimate signups)."""
    r = await get_redis()
    if r is None:
        return

    try:
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, window_seconds)
        if current > max_count:
            raise EmailAuthError("rate_limit_exceeded", "too many requests")
    except EmailAuthError:
        raise
    except Exception as e:
        log.warning("rate_limit_redis_error", extra={"error": str(e)[:100]})


async def _invalidate_all_user_sessions(db: AsyncSession, user_id) -> int:
    """Revoke every active session for this user.

    Returns the count revoked. Scans the `user_sessions` audit table for
    active rows, revokes each in Redis, and marks `revoked_at/revoked_reason`
    so the audit trail reflects the reason.
    """
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    )
    rows = result.scalars().all()
    now = datetime.now(timezone.utc)

    for row in rows:
        try:
            await revoke_session(row.session_id)
        except Exception:
            log.exception(
                "session_revoke_failed",
                extra={"session_id": row.session_id},
            )
        row.revoked_at = now
        row.revoked_reason = "password_reset"

    return len(rows)


async def signup(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    account_type: str,
    ip: Optional[str] = None,
) -> User:
    """Create a new user with email+password. Sends verification email."""
    if ip:
        await _rate_limit_check(
            f"auth_rl:signup:ip:{ip}", SIGNUP_RL_IP_MAX, SIGNUP_RL_IP_WINDOW
        )

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailAuthError("email_already_exists")

    try:
        await validate_policy(password)
    except PasswordPolicyError as e:
        raise EmailAuthError(e.code, e.detail)

    now = datetime.now(timezone.utc)
    user = User(
        id=str(uuid4()),
        email=email,
        display_name=display_name[:100],
        password_hash=hash_password(password),
        password_set_at=now,
        email_verified=False,
        email_verified_at=None,
        # TODO(account_type): post-verification onboarding diverges on this —
        # 'individual' -> KYC, 'merchant' -> KYB. Only persisted here for now.
        account_type=account_type,
    )
    db.add(user)
    await db.flush()

    token = secrets.token_urlsafe(32)
    verification = EmailVerificationToken(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=_hash_token(token),
        email_at_issue=email,
        created_at=now,
        expires_at=now + timedelta(hours=VERIFICATION_TTL_HOURS),
        ip_at_issue=ip,
    )
    db.add(verification)

    settings = get_settings()
    verify_url = f"{settings.frontend_url}/en/verify-email?token={token}"

    await send_email(
        to=email,
        template_name="verify_email",
        subject="Verify your rsend account",
        context={
            "display_name": display_name,
            "verify_url": verify_url,
            "expires_hours": VERIFICATION_TTL_HOURS,
        },
    )

    await record_auth_event(
        event_type="email_signup",
        user_id=str(user.id),
        ip_address=ip,
        details={"email": email, "display_name": display_name},
    )

    return user


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[User, str, str, str, str]:
    """Verify credentials and mint a session.

    Returns (user, session_id, access_token, refresh_token, refresh_hash).
    The route handler is responsible for:
      - persisting the UserSession audit row
      - setting cookies via the same helper Google uses
    """
    if ip:
        await _rate_limit_check(
            f"auth_rl:login:ip:{ip}", LOGIN_RL_IP_MAX, LOGIN_RL_IP_WINDOW
        )
    await _rate_limit_check(
        f"auth_rl:login:email:{email}", LOGIN_RL_EMAIL_MAX, LOGIN_RL_EMAIL_WINDOW
    )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not user.password_hash:
        # Constant-time: always run bcrypt to avoid revealing enumeration
        # via timing differences.
        _ = verify_password(password, _DUMMY_BCRYPT)
        if user is not None and not user.password_hash:
            raise EmailAuthError(
                "password_not_set",
                "this account uses another sign-in method",
            )
        raise EmailAuthError("invalid_credentials")

    if not verify_password(password, user.password_hash):
        await record_auth_event(
            event_type="email_login_failure",
            user_id=str(user.id),
            ip_address=ip,
            user_agent=user_agent,
            details={"code": "invalid_credentials"},
        )
        raise EmailAuthError("invalid_credentials")

    if not user.email_verified:
        raise EmailAuthError(
            "email_not_verified",
            "please verify your email before logging in",
        )

    if user.status != "active":
        raise EmailAuthError("account_suspended")

    if user.deletion_scheduled_for is not None:
        now = datetime.now(timezone.utc)
        if user.deletion_scheduled_for < now:
            raise EmailAuthError("account_deleted")

    session_id, access_token, refresh_token, refresh_hash = await create_session(
        user_id=str(user.id),
        ip=ip or "",
        user_agent=user_agent or "",
    )

    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip

    await record_auth_event(
        event_type="email_login",
        user_id=str(user.id),
        session_id=session_id,
        ip_address=ip,
        user_agent=user_agent,
        details={"method": "email_password"},
    )

    return user, session_id, access_token, refresh_token, refresh_hash


async def verify_email(
    db: AsyncSession,
    *,
    token: str,
    ip: Optional[str] = None,
) -> User:
    """Consume verification token. Marks user.email_verified = True."""
    token_hash = _hash_token(token)

    vt = (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash
            )
        )
    ).scalar_one_or_none()
    if vt is None:
        raise EmailAuthError("invalid_token")

    now = datetime.now(timezone.utc)
    if vt.used_at is not None:
        raise EmailAuthError("token_already_used")
    if vt.expires_at < now:
        raise EmailAuthError("token_expired")

    user = (
        await db.execute(select(User).where(User.id == vt.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise EmailAuthError("user_not_found")

    if user.email.lower() != vt.email_at_issue.lower():
        raise EmailAuthError(
            "email_mismatch",
            "email has changed since token was issued",
        )

    user.email_verified = True
    user.email_verified_at = now
    vt.used_at = now

    settings = get_settings()
    await send_email(
        to=user.email,
        template_name="welcome",
        subject="Welcome to rsend",
        context={
            "display_name": user.display_name or user.email,
            "dashboard_url": f"{settings.frontend_url}/en/app",
        },
    )

    await record_auth_event(
        event_type="email_verified",
        user_id=str(user.id),
        ip_address=ip,
        details={"email": user.email},
    )

    return user


async def resend_verification(
    db: AsyncSession,
    *,
    email: str,
    ip: Optional[str] = None,
) -> None:
    """Idempotent: never reveals whether the email exists."""
    await _rate_limit_check(
        f"auth_rl:verify_resend:email:{email}",
        VERIFY_RESEND_RL_MAX,
        VERIFY_RESEND_RL_WINDOW,
    )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        return
    if user.email_verified:
        return
    if not user.password_hash:
        return

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)

    vt = EmailVerificationToken(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=_hash_token(token),
        email_at_issue=email,
        created_at=now,
        expires_at=now + timedelta(hours=VERIFICATION_TTL_HOURS),
        ip_at_issue=ip,
    )
    db.add(vt)

    settings = get_settings()
    verify_url = f"{settings.frontend_url}/en/verify-email?token={token}"

    await send_email(
        to=email,
        template_name="verify_email",
        subject="Verify your rsend account",
        context={
            "display_name": user.display_name or email,
            "verify_url": verify_url,
            "expires_hours": VERIFICATION_TTL_HOURS,
        },
    )

    await record_auth_event(
        event_type="email_verification_resent",
        user_id=str(user.id),
        ip_address=ip,
        details={"email": email},
    )


async def request_password_reset(
    db: AsyncSession,
    *,
    email: str,
    ip: Optional[str] = None,
) -> None:
    """Idempotent: response identical whether the email exists or not."""
    await _rate_limit_check(
        f"auth_rl:reset:email:{email}",
        RESET_RL_EMAIL_MAX,
        RESET_RL_EMAIL_WINDOW,
    )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or not user.password_hash:
        return

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)

    rt = PasswordResetToken(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=_hash_token(token),
        created_at=now,
        expires_at=now + timedelta(hours=RESET_TTL_HOURS),
        ip_at_issue=ip,
    )
    db.add(rt)

    settings = get_settings()
    reset_url = f"{settings.frontend_url}/en/reset-password?token={token}"

    await send_email(
        to=email,
        template_name="password_reset",
        subject="Reset your rsend password",
        context={
            "display_name": user.display_name or email,
            "reset_url": reset_url,
            "expires_hours": RESET_TTL_HOURS,
        },
    )

    await record_auth_event(
        event_type="password_reset_requested",
        user_id=str(user.id),
        ip_address=ip,
        details={"email": email},
    )


async def reset_password(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
    ip: Optional[str] = None,
) -> User:
    """Consume reset token, update hash, invalidate every session."""
    token_hash = _hash_token(token)

    rt = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )
    ).scalar_one_or_none()
    if rt is None:
        raise EmailAuthError("invalid_token")

    now = datetime.now(timezone.utc)
    if rt.used_at is not None:
        raise EmailAuthError("token_already_used")
    if rt.expires_at < now:
        raise EmailAuthError("token_expired")

    try:
        await validate_policy(new_password)
    except PasswordPolicyError as e:
        raise EmailAuthError(e.code, e.detail)

    user = (
        await db.execute(select(User).where(User.id == rt.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise EmailAuthError("user_not_found")

    user.password_hash = hash_password(new_password)
    user.password_set_at = now
    rt.used_at = now
    rt.ip_at_use = ip

    revoked = await _invalidate_all_user_sessions(db, user.id)

    await record_auth_event(
        event_type="password_reset_completed",
        user_id=str(user.id),
        ip_address=ip,
        details={"email": user.email, "sessions_revoked": revoked},
    )

    return user


async def check_email(db: AsyncSession, email: str) -> dict:
    """Expose which sign-in methods exist for this email.

    Used by the frontend signup/login pages to offer account-linking UX
    (e.g. "this email already has a Google account — log in instead").
    No rate limit: low-risk read-only lookup.
    """
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        return {
            "exists": False,
            "has_google": False,
            "has_password": False,
            "has_github": False,
        }
    return {
        "exists": True,
        "has_google": user.google_sub is not None,
        "has_password": user.password_hash is not None,
        "has_github": user.github_sub is not None,
    }
