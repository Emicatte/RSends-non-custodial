"""Router-level dependency: the merchant API-key surface requires an APPROVED org.

The API key's `client_id` (== owner wallet address) is resolved to its org —
the reverse of app/services/owner_identity.py's org->address resolution:

    1. a `user_wallets` row with that address -> its org;
    2. else an org whose `settlement_wallet` is that address (the
       email-onboarded merchant path).

Either way the resolution must be UNAMBIGUOUS (exactly one org) and that org
must be `approved`; declined orgs get the distinct `approval_declined` code.
Unresolvable or ambiguous owners are denied `approval_pending` — fail closed.
Every org that existed before the approval feature was backfilled 'approved'
by migration 0010, so no live key loses access at rollout.

An unauthenticated request (no `request.state.client`) is NOT this gate's job:
it falls through so the route's own `_get_merchant_id` raises its canonical
401 INVALID_API_KEY (the API-key middleware already blocks non-exempt paths).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet


def _deny(code: str, reason: str = "") -> HTTPException:
    detail: dict = {"code": code}
    if reason:
        detail["reason"] = reason
    return HTTPException(status_code=403, detail=detail)


async def require_approved_merchant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    client = getattr(request.state, "client", None)
    if not client or not isinstance(client, dict) or not client.get("client_id"):
        return  # handler's _get_merchant_id raises the canonical 401

    owner = str(client["client_id"]).lower()

    org_ids = (
        (
            await db.execute(
                select(UserWallet.org_id)
                .where(func.lower(UserWallet.address) == owner)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not org_ids:
        org_ids = (
            (
                await db.execute(
                    select(Organization.id).where(
                        func.lower(Organization.settlement_wallet) == owner
                    )
                )
            )
            .scalars()
            .all()
        )

    if len(org_ids) != 1:
        # No org, or an ambiguous claim: never guess a tenant — deny.
        raise _deny("approval_pending")

    row = (
        await db.execute(
            select(Organization.approval_status, Organization.decline_reason).where(
                Organization.id == org_ids[0]
            )
        )
    ).one_or_none()
    status = row[0] if row else None
    if status == "approved":
        return
    if status == "declined":
        raise _deny("approval_declined", row[1] or "")
    raise _deny("approval_pending")
