"""Account settings service — add/remove password for already-authenticated
users.

Mutates the existing `users` row (password_hash). No schema changes. Social
login (Google/GitHub) was removed from the product; the orphan google_sub /
github_sub / github_username columns stay in place untouched.

Invariant: a user must always retain at least one active sign-in method.
`remove_password` raises `last_auth_method` when the password is the only
method left (post-OAuth-removal it always is), blocking the user from locking
themselves out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_models import User
from app.services.auth_audit import record_auth_event
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


def _count_auth_methods(user: User) -> int:
    return 1 if user.password_hash else 0


def view_methods(user: User) -> AuthMethodsView:
    return AuthMethodsView(has_password=user.password_hash is not None)


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
