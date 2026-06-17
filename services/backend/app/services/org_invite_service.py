"""Org invite lifecycle: create, preview, accept, decline, revoke, list.

Token design
------------
- Plaintext token = `secrets.token_urlsafe(32)` (~43 chars, 192 bits of entropy).
- Stored as SHA-256 hex of the plaintext (`token_hash`, unique index).
- Constant-time comparison happens via DB lookup by hash — we never store
  the plaintext, so leaking the DB cannot replay active invites.
- TTL 7 days. Partial unique index blocks concurrent pending invites for
  the same (org, email).

Accept flow
-----------
- Must be invoked from an authenticated session (Google-verified email).
- Requires `user.email.lower() == invite.email` to prevent a leaked token
  from onboarding an attacker's Google account into someone else's org.
- Double-checks `MAX_MEMBERS_PER_ORG` since the window between `create`
  and `accept` is 0–7 days and membership state can have changed.
- Sets `user.active_org_id = invite.org_id` so the accepting user lands
  in the newly joined org.

Email dispatch uses `send_email` which never raises — a Resend outage
cannot break invite creation.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_models import User
from app.models.org_models import Membership, Organization, OrgInvite
from app.services.auth_audit import record_auth_event
from app.services.email_service import send_email
from app.services.org_service import (
    MAX_MEMBERS_PER_ORG,
    OrgError,
    VALID_ROLES,
    require_role,
)

log = logging.getLogger(__name__)

INVITE_TTL_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ─── Create ──────────────────────────────────────────────────────

async def create_invite(
    db: AsyncSession,
    acting_user_id: str,
    org_id: str,
    email: str,
    role: str,
) -> tuple[OrgInvite, str]:
    """Create a pending invite and dispatch the invite email.

    Returns (invite_row, plaintext_token). Caller commits.
    """
    await require_role(db, acting_user_id, org_id, "admin")

    if role not in VALID_ROLES:
        raise OrgError("invalid_role")

    email_lower = email.lower().strip()

    count_res = await db.execute(
        select(func.count(Membership.id)).where(Membership.org_id == org_id)
    )
    if (count_res.scalar() or 0) >= MAX_MEMBERS_PER_ORG:
        raise OrgError("max_members_reached")

    existing_mem = await db.execute(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.org_id == org_id,
            func.lower(User.email) == email_lower,
        )
    )
    if existing_mem.scalar_one_or_none():
        raise OrgError("already_member")

    existing_inv = await db.execute(
        select(OrgInvite).where(
            OrgInvite.org_id == org_id,
            func.lower(OrgInvite.email) == email_lower,
            OrgInvite.status == "pending",
        )
    )
    if existing_inv.scalar_one_or_none():
        raise OrgError("invite_already_pending")

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)

    invite = OrgInvite(
        org_id=org_id,
        email=email_lower,
        role=role,
        token_hash=token_hash,
        invited_by_user_id=acting_user_id,
        status="pending",
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.flush()

    org_res = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_res.scalar_one()
    inviter_res = await db.execute(
        select(User).where(User.id == acting_user_id)
    )
    inviter = inviter_res.scalar_one()

    settings = get_settings()
    invite_url = f"{settings.frontend_url}/en/invite/{token}"

    await send_email(
        to=email_lower,
        template_name="org_invite",
        subject=f"You're invited to join {org.name}",
        context={
            "inviter_name": inviter.display_name or inviter.email,
            "org_name": org.name,
            "role": role,
            "invite_url": invite_url,
            "expires_days": str(INVITE_TTL_DAYS),
        },
    )

    await record_auth_event(
        event_type="org_invite_sent",
        user_id=acting_user_id,
        details={
            "org_id": str(org_id),
            "email": email_lower,
            "role": role,
            "invite_id": str(invite.id),
        },
    )

    return invite, token


# ─── Preview (for landing page) ──────────────────────────────────

async def preview_invite(
    db: AsyncSession, token: str, viewing_user: User
) -> dict:
    """Return a summary of the invite for the accept landing page.

    Does NOT mutate invite state. Caller must be authenticated (to enforce
    that the preview is only shown to a logged-in user, so the email-match
    warning is meaningful).
    """
    token_hash = _hash_token(token)
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise OrgError("invite_not_found")

    org_res = await db.execute(
        select(Organization).where(Organization.id == invite.org_id)
    )
    org = org_res.scalar_one_or_none()

    email_matches = (
        (viewing_user.email or "").lower() == invite.email.lower()
    )

    return {
        "org_name": org.name if org else "Unknown",
        "role": invite.role,
        "invite_email": invite.email,
        "status": invite.status,
        "email_matches": email_matches,
        "user_email": viewing_user.email,
        "expires_at": invite.expires_at,
    }


# ─── Accept ──────────────────────────────────────────────────────

async def accept_invite(
    db: AsyncSession, token: str, accepting_user: User
) -> Membership:
    token_hash = _hash_token(token)
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise OrgError("invite_not_found")

    if invite.status != "pending":
        raise OrgError(f"invite_{invite.status}")

    now = datetime.now(timezone.utc)
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        invite.status = "expired"
        raise OrgError("invite_expired")

    if (accepting_user.email or "").lower() != invite.email.lower():
        raise OrgError("invite_email_mismatch")

    count_res = await db.execute(
        select(func.count(Membership.id)).where(
            Membership.org_id == invite.org_id
        )
    )
    if (count_res.scalar() or 0) >= MAX_MEMBERS_PER_ORG:
        raise OrgError("max_members_reached")

    existing = await db.execute(
        select(Membership).where(
            Membership.user_id == accepting_user.id,
            Membership.org_id == invite.org_id,
        )
    )
    if existing.scalar_one_or_none():
        invite.status = "accepted"
        invite.accepted_at = now
        invite.accepted_by_user_id = accepting_user.id
        raise OrgError("already_member")

    membership = Membership(
        user_id=accepting_user.id,
        org_id=invite.org_id,
        role=invite.role,
        invited_by_user_id=invite.invited_by_user_id,
    )
    db.add(membership)

    invite.status = "accepted"
    invite.accepted_at = now
    invite.accepted_by_user_id = accepting_user.id

    accepting_user.active_org_id = invite.org_id

    if invite.invited_by_user_id is not None:
        inviter_res = await db.execute(
            select(User).where(User.id == invite.invited_by_user_id)
        )
        inviter = inviter_res.scalar_one_or_none()
        if inviter is not None:
            org_res = await db.execute(
                select(Organization).where(Organization.id == invite.org_id)
            )
            org = org_res.scalar_one_or_none()
            settings = get_settings()
            org_url = f"{settings.frontend_url}/en/settings/organization"
            if org is not None:
                await send_email(
                    to=inviter.email,
                    template_name="org_invite_accepted",
                    subject=(
                        f"{accepting_user.display_name or accepting_user.email}"
                        f" joined {org.name}"
                    ),
                    context={
                        "inviter_name": inviter.display_name or inviter.email,
                        "acceptor_name": (
                            accepting_user.display_name
                            or accepting_user.email
                        ),
                        "org_name": org.name,
                        "role": invite.role,
                        "org_url": org_url,
                    },
                )

    await record_auth_event(
        event_type="org_invite_accepted",
        user_id=str(accepting_user.id),
        details={
            "invite_id": str(invite.id),
            "org_id": str(invite.org_id),
            "role": invite.role,
        },
    )

    return membership


# ─── Decline ─────────────────────────────────────────────────────

async def decline_invite(
    db: AsyncSession, token: str, declining_user: User
) -> None:
    token_hash = _hash_token(token)
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise OrgError("invite_not_found")
    if invite.status != "pending":
        raise OrgError(f"invite_{invite.status}")

    invite.status = "declined"
    invite.declined_at = datetime.now(timezone.utc)

    await record_auth_event(
        event_type="org_invite_declined",
        user_id=str(declining_user.id),
        details={"invite_id": str(invite.id), "org_id": str(invite.org_id)},
    )


# ─── Revoke (admin, by id) ───────────────────────────────────────

async def revoke_invite(
    db: AsyncSession, acting_user_id: str, invite_id: str
) -> None:
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.id == invite_id)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise OrgError("not_found")

    await require_role(db, acting_user_id, str(invite.org_id), "admin")

    if invite.status != "pending":
        raise OrgError(f"invite_{invite.status}")

    invite.status = "revoked"

    await record_auth_event(
        event_type="org_invite_revoked",
        user_id=acting_user_id,
        details={"invite_id": str(invite_id), "org_id": str(invite.org_id)},
    )


# ─── List (admin view) ───────────────────────────────────────────

async def list_invites(
    db: AsyncSession, acting_user_id: str, org_id: str
) -> list[OrgInvite]:
    await require_role(db, acting_user_id, org_id, "admin")
    result = await db.execute(
        select(OrgInvite)
        .where(
            OrgInvite.org_id == org_id,
            OrgInvite.status == "pending",
        )
        .order_by(OrgInvite.created_at.desc())
    )
    return list(result.scalars().all())
