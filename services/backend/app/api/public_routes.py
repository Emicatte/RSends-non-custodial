"""Public (payer-facing) routes — intentionally unauthenticated, strictly limited.

Trust boundary: everything in this module is reachable WITHOUT an API key, in
production config (no RSEND_DEV_AUTH_BYPASS). Rules for anything added here:

- Access model is **id-as-secret**: the lookup key must be non-enumerable
  (intent_id = "pi_" + secrets.token_hex(16) → 128 bits CSPRNG).
- Single-object lookups only — no list routes, no filters, nothing that
  enables enumeration.
- Serialize an EXPLICIT allowlisted response model, never the ORM object:
  a future column must not leak by default.
- Read-only: no DB writes from a public handler.
- Per-IP rate limited (see ENDPOINT_LIMITS in app/middleware/rate_limit.py)
  and allowlisted in GET_PUBLIC_PREFIXES (app/security/api_keys.py).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.merchant_models import IntentStatus, OnchainPayment, PaymentIntent
from app.services.router_registry import build_onchain_payment

logger = logging.getLogger("rsend.public")

public_router = APIRouter(prefix="/api/v1/public", tags=["public"])


class PublicPaymentIntentResponse(BaseModel):
    """What a payer holding the /pay link needs to pay — and nothing else.

    Explicit allowlist (tests pin the exact key set). Deliberately absent:
    intent_id (already in the URL), reference_id (merchant-fingerprinted),
    metadata (merchant-private dict), expected_sender, matched_* internals,
    late_payment_policy, merchant_id. `onchain` is the full payment
    instruction set — every field is payer-facing (incl. permitType/
    permitVersion/calldata, required to actually execute the payment).
    """
    status: str
    amount: float
    currency: str
    chain: str
    expires_at: str
    merchant_name: Optional[str] = None   # display name only, from merchant metadata
    tx_hash: Optional[str] = None         # settlement receipt, null until completed
    onchain: Optional[OnchainPayment] = None


def _effective_status(intent: PaymentIntent) -> str:
    """Expired-pending intents are REPORTED as expired without persisting the
    flip — this route is read-only; the merchant GET / expiry task own the
    durable transition."""
    if intent.status == IntentStatus.pending:
        expires_at = intent.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return IntentStatus.expired.value
    return intent.status.value


def _merchant_display_name(intent: PaymentIntent) -> Optional[str]:
    """The one merchant-chosen value meant for payers. The metadata dict
    itself stays private."""
    meta = intent.metadata_ or {}
    name = meta.get("merchant_name") or meta.get("store_name")
    return name if isinstance(name, str) and name.strip() else None


@public_router.get(
    "/payment-intent/{intent_id}", response_model=PublicPaymentIntentResponse,
)
async def get_public_payment_intent(
    intent_id: str,
    db: AsyncSession = Depends(get_db),
) -> PublicPaymentIntentResponse:
    """Payment status + on-chain instructions for the hosted checkout (/pay).

    Id-as-secret: whoever holds the (unguessable) intent id may read this one
    intent's pay-relevant view. 404 on miss.
    """
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )
    intent = result.scalar_one_or_none()

    if intent is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "INTENT_NOT_FOUND",
                "message": f"Payment intent '{intent_id}' not found",
            },
        )

    onchain = await build_onchain_payment(intent)

    return PublicPaymentIntentResponse(
        status=_effective_status(intent),
        amount=intent.amount,
        currency=intent.currency,
        chain=intent.chain or "BASE",
        expires_at=intent.expires_at.isoformat(),
        merchant_name=_merchant_display_name(intent),
        tx_hash=intent.matched_tx_hash or intent.tx_hash,
        onchain=onchain,
    )
