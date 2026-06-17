"""Account linking service — add/remove password + link/unlink Google/GitHub
for already-authenticated users.

Mutates the existing `users` row (password_hash / google_sub / github_sub +
github_username). All fields already exist in schema via migration 0032.
No schema changes.

Invariant: a user must always retain at least one active sign-in method.
`remove_password`, `unlink_google`, `unlink_github` raise `last_auth_method`
when `_count_auth_methods(user) <= 1`, blocking the user from locking
themselves out.

Email-match and sub-uniqueness guards on OAuth linking prevent a user from
linking someone else's Google/GitHub account or hijacking one that's
already in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_models import User
from app.services.auth_audit import record_auth_event
from app.services.auth_service import AuthError, verify_google_id_token
from app.services.github_oauth_service import (
    GitHubOAuthError,
    verify_github_access_token,
)
from app.services.password_service import (
    PasswordPolicyError,
    hash_password,
    validate_policy,
)


class AccountLinkingError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass
class AuthMethodsView:
    has_password: bool
    has_google: bool
    has_github: bool
    google_email: Optional[str]
    github_username: Optional[str]


def _count_auth_methods(user: User) -> int:
    n = 0
    if user.password_hash:
        n += 1
    if user.google_sub:
        n += 1
    if user.github_sub:
        n += 1
    return n


def view_methods(user: User) -> AuthMethodsView:
    return AuthMethodsView(
        has_password=user.password_hash is not None,
        has_google=user.google_sub is not None,
        has_github=user.github_sub is not None,
        google_email=user.email if user.google_sub else None,
        github_username=user.github_username,
    )


async def add_password(
    db: AsyncSession,
    user: User,
    new_password: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.password_hash is not None:
        raise AccountLinkingError("password_already_set")

    try:
        await validate_policy(new_password)
    except PasswordPolicyError as e:
        raise AccountLinkingError(e.code, e.detail)

    user.password_hash = hash_password(new_password)
    user.password_set_at = datetime.now(timezone.utc)

    await record_auth_event(
        event_type="password_added",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        details={"email": user.email},
    )


async def remove_password(
    db: AsyncSession,
    user: User,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.password_hash is None:
        raise AccountLinkingError("password_not_set")
    if _count_auth_methods(user) <= 1:
        raise AccountLinkingError("last_auth_method")

    user.password_hash = None
    user.password_set_at = None

    await record_auth_event(
        event_type="password_removed",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        details={"email": user.email},
    )


async def link_google(
    db: AsyncSession,
    user: User,
    id_token: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.google_sub is not None:
        raise AccountLinkingError("google_already_linked")

    try:
        info = await verify_google_id_token(id_token)
    except AuthError as e:
        raise AccountLinkingError("invalid_token", e.message)

    if not info.sub:
        raise AccountLinkingError("invalid_token", "missing sub")

    if (info.email or "").lower() != (user.email or "").lower():
        raise AccountLinkingError("email_mismatch")

    existing = await db.execute(
        select(User.id).where(User.google_sub == info.sub)
    )
    if existing.scalar_one_or_none() is not None:
        raise AccountLinkingError("google_sub_in_use")

    user.google_sub = info.sub

    await record_auth_event(
        event_type="google_linked",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        google_sub=info.sub,
        details={"email": user.email},
    )


async def unlink_google(
    db: AsyncSession,
    user: User,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.google_sub is None:
        raise AccountLinkingError("google_not_linked")
    if _count_auth_methods(user) <= 1:
        raise AccountLinkingError("last_auth_method")

    previous_sub = user.google_sub
    user.google_sub = None

    await record_auth_event(
        event_type="google_unlinked",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        details={"email": user.email, "previous_google_sub": previous_sub},
    )


async def link_github(
    db: AsyncSession,
    user: User,
    access_token: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.github_sub is not None:
        raise AccountLinkingError("github_already_linked")

    try:
        profile = await verify_github_access_token(access_token)
    except GitHubOAuthError as e:
        raise AccountLinkingError("invalid_token", e.detail)

    if (profile.email or "").lower() != (user.email or "").lower():
        raise AccountLinkingError("email_mismatch")

    existing = await db.execute(
        select(User.id).where(User.github_sub == profile.sub)
    )
    if existing.scalar_one_or_none() is not None:
        raise AccountLinkingError("github_sub_in_use")

    user.github_sub = profile.sub
    user.github_username = profile.username

    await record_auth_event(
        event_type="github_linked",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        details={
            "email": user.email,
            "github_sub": profile.sub,
            "github_username": profile.username,
        },
    )


async def unlink_github(
    db: AsyncSession,
    user: User,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if user.github_sub is None:
        raise AccountLinkingError("github_not_linked")
    if _count_auth_methods(user) <= 1:
        raise AccountLinkingError("last_auth_method")

    previous_sub = user.github_sub
    previous_username = user.github_username
    user.github_sub = None
    user.github_username = None

    await record_auth_event(
        event_type="github_unlinked",
        user_id=str(user.id),
        ip_address=ip,
        user_agent=user_agent,
        details={
            "email": user.email,
            "previous_github_sub": previous_sub,
            "previous_github_username": previous_username,
        },
    )
