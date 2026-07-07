"""Payment-intent creation helpers (Phase B).

`resolve_recipient` is the single recipient gate: an intent CANNOT be created
without a resolvable on-chain recipient. It is wired at the one PaymentIntent
construction site (app/api/merchant_routes.py) and is reused by the session
creation path (Phase D) via the `org_id` argument. Fail-closed everywhere —
never silently default a recipient.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet

_MISSING = {
    "error": "SETTLEMENT_WALLET_MISSING",
    "message": (
        "Set your organization's settlement wallet in Settings to receive "
        "payments, or pass an explicit recipient."
    ),
}
_AMBIGUOUS = {
    "error": "SETTLEMENT_WALLET_AMBIGUOUS",
    "message": (
        "This wallet belongs to multiple organizations; pass an explicit "
        "recipient."
    ),
}


async def _org_settlement_wallet(db: AsyncSession, org_id) -> str | None:
    return (
        await db.execute(
            select(Organization.settlement_wallet).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()


async def resolve_recipient(
    db: AsyncSession,
    merchant_id: str,
    payload_recipient: str | None,
    org_id: str | None = None,
) -> str:
    """Resolve the on-chain recipient for a new intent, or raise 422.

    Precedence:
      1. explicit per-intent override (already regex-validated + lowercased by
         Pydantic) — wins over any default;
      2. session path (org_id known) → that org's settlement_wallet;
      3. API-key path (org_id is None) → reverse-lookup the key owner's wallet to
         its org, and use that org's settlement_wallet — but only when the wallet
         maps to exactly one org (ambiguity fails closed; the owner may not be a
         linked org wallet at all).

    Raises HTTPException(422, SETTLEMENT_WALLET_MISSING | SETTLEMENT_WALLET_AMBIGUOUS).
    """
    # 1. explicit override wins.
    if payload_recipient:
        return payload_recipient

    # 2. session path: the org is known, use its default directly.
    if org_id is not None:
        wallet = await _org_settlement_wallet(db, org_id)
        if wallet:
            return wallet.lower()
        raise HTTPException(status_code=422, detail=_MISSING)

    # 3. API-key path: reverse-lookup owner wallet → org(s).
    merchant = (merchant_id or "").lower()
    org_ids = (
        await db.execute(
            select(UserWallet.org_id)
            .where(
                func.lower(UserWallet.address) == merchant,
                UserWallet.is_primary.is_(True),
                UserWallet.chain_family == "evm",
                UserWallet.unlinked_at.is_(None),
            )
            .distinct()
        )
    ).scalars().all()

    if len(org_ids) > 1:
        # Same wallet primary in multiple orgs — never guess fund routing.
        raise HTTPException(status_code=422, detail=_AMBIGUOUS)
    if len(org_ids) == 0:
        raise HTTPException(status_code=422, detail=_MISSING)

    wallet = await _org_settlement_wallet(db, org_ids[0])
    if wallet:
        return wallet.lower()
    raise HTTPException(status_code=422, detail=_MISSING)
