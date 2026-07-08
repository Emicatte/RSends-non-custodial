"""Payment-intent creation helpers (Phase B).

`resolve_recipient` is the single recipient gate: an intent CANNOT be created
without a resolvable on-chain recipient. It is wired at the one PaymentIntent
construction site (app/api/merchant_routes.py) and is reused by the session
creation path (Phase D) via the `org_id` argument. Fail-closed everywhere —
never silently default a recipient.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_models import (
    IntentStatus,
    MerchantTransactionItem,
    MerchantTransactionListResponse,
    PaymentIntent,
)
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


# ── Shared intent-list query (Phase C) ───────────────────────────
#
# One query, two callers: the API-key `GET /merchant/transactions` path and the
# session `GET /user/org/payment-intents` path both delegate here, so the list
# view can never drift between the programmatic and browser surfaces. Tenant +
# environment isolation live IN the query (both predicates required — an owner's
# test and live keys share the same merchant_id).

def _intent_to_item(i: PaymentIntent) -> MerchantTransactionItem:
    """Serialize an intent to the allowlisted transaction record (both paths)."""
    return MerchantTransactionItem(
        intent_id=i.intent_id,
        onchain_invoice_id=i.onchain_invoice_id,
        amount=i.amount,
        currency=i.currency,
        chain=i.chain or "BASE",
        status=i.status.value,
        recipient=i.recipient,
        tx_hash=i.tx_hash,
        matched_tx_hash=i.matched_tx_hash,
        metadata=i.metadata_,
        completed_late=i.completed_late,
        late_minutes=i.late_minutes,
        amount_received=i.amount_received,
        overpaid_amount=i.overpaid_amount,
        underpaid_amount=i.underpaid_amount,
        created_at=i.created_at.isoformat(),
        expires_at=i.expires_at.isoformat() if i.expires_at else None,
        completed_at=i.completed_at.isoformat() if i.completed_at else None,
    )


async def list_org_intents(
    db: AsyncSession,
    merchant_id: str,
    environment: str,
    status: str | None = None,
    currency: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> MerchantTransactionListResponse:
    """Paginated payment-intents for `merchant_id` within `environment`.

    Most-recent-first. Optional `status` (validated against IntentStatus — an
    unknown value is rejected 400 INVALID_STATUS, never coerced) and `currency`
    filters. The single source of truth for the merchant transaction list.
    """
    filters = [
        PaymentIntent.merchant_id == merchant_id,
        PaymentIntent.environment == environment,
    ]

    if status:
        try:
            filters.append(PaymentIntent.status == IntentStatus(status))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_STATUS",
                    "message": (
                        f"Status '{status}' non valido. Validi: pending, "
                        "completed, expired, cancelled, review, refunded, "
                        "partial, overpaid"
                    ),
                },
            )

    if currency:
        filters.append(PaymentIntent.currency == currency)

    total = (
        await db.execute(
            select(func.count(PaymentIntent.id)).where(and_(*filters))
        )
    ).scalar() or 0

    offset = (page - 1) * per_page
    intents = (
        await db.execute(
            select(PaymentIntent)
            .where(and_(*filters))
            .order_by(PaymentIntent.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
    ).scalars().all()

    return MerchantTransactionListResponse(
        total=total,
        page=page,
        per_page=per_page,
        records=[_intent_to_item(i) for i in intents],
    )
