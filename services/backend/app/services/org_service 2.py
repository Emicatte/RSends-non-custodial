"""Core organization management + RBAC helpers.

Responsibilities
----------------
- Personal org auto-creation at first Google login (idempotent).
- Non-personal org creation (user becomes admin).
- Membership role queries + `require_role` guard for routes.
- Member removal + role updates with "last admin" / "owner" invariants.
- Active org switching (sets `users.active_org_id`).

Not responsible for
-------------------
- Invite lifecycle (see `org_invite_service.py`).
- Deleting organizations (out of scope for this prompt).
- Transferring ownership (out of scope).

All service functions receive an `AsyncSession` and DO NOT commit —
callers (route handlers) decide when to commit. Audit events use
`record_auth_event`, which opens its own session, so audit durability
is preserved independently of the caller's transaction.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_models import User
from app.models.org_models import Membership, Organization
from app.services.auth_audit import record_auth_event

log = logging.getLogger(__name__)

MAX_MEMBERS_PER_ORG = 10
VALID_ROLES: frozenset[str] = frozenset({"admin", "operator", "viewer"})

_ROLE_HIERARCHY: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


class OrgError(Exception):
    """Canonical error for org operations. Routes translate `code` to HTTP."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


# ─── Slug helpers ─────────────────────────────────────────────────

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Lowercase, alphanumeric + dashes, max 50 chars."""
    base = _SLUG_UNSAFE.sub("-", text.lower()).strip("-")
    base = base[:50] or "workspace"
    return base


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Append a random suffix when the base slug collides.

    Five-attempt bounded loop → final fallback appends an 8-char token.
    """
    slug = base
    for _ in range(5):
        exists = await db.execute(
            select(Organization.id).where(Organization.slug == slug).limit(1)
        )
        if not exists.scalar_one_or_none():
            return slug
        suffix = secrets.token_urlsafe(4).replace("_", "").replace("-", "")[:5].lower()
        slug = f"{base}-{suffix}" if suffix else f"{base}-{secrets.token_hex(3)}"
    return f"{base}-{secrets.token_urlsafe(8)}"


# ─── Org creation ─────────────────────────────────────────────────

async def create_personal_org(db: AsyncSession, user: User) -> Organization:
    """Create the user's personal org (idempotent).

    If the user already owns a personal org, return it unchanged. Otherwise
    create one named "{display}'s workspace" with the user as admin, and
    set `user.active_org_id` if the user had no active org yet.
    """
    existing = await db.execute(
        select(Organization).where(
            Organization.owner_user_id == user.id,
            Organization.is_personal.is_(True),
            Organization.deleted_at.is_(None),
        ).limit(1)
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        return existing_row

    display = user.display_name or (
        user.email.split("@")[0] if user.email else "My"
    )
    name = f"{display}'s workspace"
    base_slug = _slugify(display)
    slug = await _unique_slug(db, base_slug)

    org = Organization(
        name=name,
        slug=slug,
        owner_user_id=user.id,
        is_personal=True,
        plan="free",
    )
    db.add(org)
    await db.flush()

    membership = Membership(
        user_id=user.id,
        org_id=org.id,
        role="admin",
    )
    db.add(membership)

    if getattr(user, "active_org_id", None) is None:
        user.active_org_id = org.id

    await record_auth_event(
        event_type="org_personal_created",
        user_id=str(user.id),
        details={"org_id": str(org.id), "slug": slug},
    )

    return org


async def create_org(db: AsyncSession, user: User, name: str) -> Organization:
    """Create a non-personal org; user becomes admin."""
    slug = await _unique_slug(db, _slugify(name))

    org = Organization(
        name=name[:100],
        slug=slug,
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
    )
    db.add(org)
    await db.flush()

    membership = Membership(
        user_id=user.id,
        org_id=org.id,
        role="admin",
    )
    db.add(membership)

    await record_auth_event(
        event_type="org_created",
        user_id=str(user.id),
        details={"org_id": str(org.id), "name": name[:100], "slug": slug},
    )

    return org


# ─── Queries ──────────────────────────────────────────────────────

async def get_user_orgs(db: AsyncSession, user_id: str) -> list[dict]:
    """Return [{'org': Organization, 'role': str, 'member_count': int}, ...]."""
    result = await db.execute(
        select(Organization, Membership.role)
        .select_from(Organization)
        .join(Membership, Membership.org_id == Organization.id)
        .where(
            Membership.user_id == user_id,
            Organization.deleted_at.is_(None),
        )
        .order_by(Organization.created_at.asc())
    )
    entries: list[dict] = []
    for org, role in result.all():
        count_res = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.org_id == org.id
            )
        )
        entries.append(
            {
                "org": org,
                "role": role,
                "member_count": count_res.scalar() or 0,
            }
        )
    return entries


async def get_user_role_in_org(
    db: AsyncSession, user_id: str, org_id: str
) -> Optional[str]:
    result = await db.execute(
        select(Membership.role).where(
            Membership.user_id == user_id,
            Membership.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def require_role(
    db: AsyncSession, user_id: str, org_id: str, min_role: str
) -> str:
    """Raise OrgError("not_a_member") if no membership, or
    OrgError("insufficient_role") if role rank < min_role rank.

    Returns the actual role on success.
    """
    role = await get_user_role_in_org(db, user_id, org_id)
    if role is None:
        raise OrgError("not_a_member")

    actual_rank = _ROLE_HIERARCHY.get(role, -1)
    required_rank = _ROLE_HIERARCHY.get(min_role, 99)
    if actual_rank < required_rank:
        raise OrgError("insufficient_role", f"required: {min_role}")

    return role


# ─── Active org switching ─────────────────────────────────────────

async def set_active_org(
    db: AsyncSession, user_id: str, org_id: str
) -> None:
    """Set users.active_org_id after verifying membership."""
    role = await get_user_role_in_org(db, user_id, org_id)
    if role is None:
        raise OrgError("not_a_member")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.active_org_id = org_id
    user.updated_at = datetime.now(timezone.utc)


# ─── Membership mutations ─────────────────────────────────────────

async def remove_member(
    db: AsyncSession,
    acting_user_id: str,
    org_id: str,
    target_user_id: str,
) -> None:
    """Admin removes a member. Blocked for the owner and the last admin."""
    await require_role(db, acting_user_id, org_id, "admin")

    org_res = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_res.scalar_one_or_none()
    if org is None:
        raise OrgError("not_found")

    if str(org.owner_user_id) == str(target_user_id):
        raise OrgError("cannot_remove_owner")

    mem_res = await db.execute(
        select(Membership).where(
            Membership.user_id == target_user_id,
            Membership.org_id == org_id,
        )
    )
    target_mem = mem_res.scalar_one_or_none()
    if target_mem is None:
        raise OrgError("not_found")

    if target_mem.role == "admin":
        admin_count_res = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.org_id == org_id,
                Membership.role == "admin",
            )
        )
        if (admin_count_res.scalar() or 0) <= 1:
            raise OrgError("cannot_remove_last_admin")

    await db.delete(target_mem)

    await record_auth_event(
        event_type="org_member_removed",
        user_id=acting_user_id,
        details={"org_id": str(org_id), "target_user_id": str(target_user_id)},
    )


async def update_member_role(
    db: AsyncSession,
    acting_user_id: str,
    org_id: str,
    target_user_id: str,
    new_role: str,
) -> Membership:
    await require_role(db, acting_user_id, org_id, "admin")

    if new_role not in VALID_ROLES:
        raise OrgError("invalid_role")

    mem_res = await db.execute(
        select(Membership).where(
            Membership.user_id == target_user_id,
            Membership.org_id == org_id,
        )
    )
    mem = mem_res.scalar_one_or_none()
    if mem is None:
        raise OrgError("not_found")

    if mem.role == "admin" and new_role != "admin":
        admin_count_res = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.org_id == org_id,
                Membership.role == "admin",
            )
        )
        if (admin_count_res.scalar() or 0) <= 1:
            raise OrgError("cannot_demote_last_admin")

    mem.role = new_role
    mem.updated_at = datetime.now(timezone.utc)

    await record_auth_event(
        event_type="org_member_role_changed",
        user_id=acting_user_id,
        details={
            "org_id": str(org_id),
            "target_user_id": str(target_user_id),
            "new_role": new_role,
        },
    )

    return mem
