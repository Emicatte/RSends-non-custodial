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
from app.services.router_registry import (
    build_onchain_payment,
    from_base_units,
    to_base_units,
    token_for,
)

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

    On a WATCH-ONLY chain (TRON) `onchain` is null by construction: there is no
    contract to call, and the payer sends the token straight to `recipient`.
    That makes `recipient` and `amount_exact` the entire payment instruction —
    the checkout has nothing else to render, and no way to derive either.
    They carry no information a payer holding this link does not already need,
    and on a router chain the same address already ships inside
    `onchain.merchant`.
    """
    status: str
    amount: float
    currency: str
    chain: str
    expires_at: str
    merchant_name: Optional[str] = None   # display name only, from merchant metadata
    tx_hash: Optional[str] = None         # settlement receipt, null until completed
    onchain: Optional[OnchainPayment] = None
    # The payee, byte-identical. On a base58check chain this address is
    # case-SENSITIVE and folding it does not merely change it, it stops it
    # decoding — so it is echoed verbatim, never normalized on the way out.
    # Null on a split intent, which has no single payee.
    recipient: Optional[str] = None
    # `amount` rendered as the EXACT decimal the settlement layer compares
    # against, so a payer typing it by hand types the value that matches.
    amount_exact: Optional[str] = None
    # Echoed as stored, exactly as the webhook payload carries them: in TOKEN
    # units like `amount`, and written only by the watch-only matcher. On every
    # other path `amount_received` stays at its "0" default and
    # `underpaid_amount` stays null, so read them only on `status == "partial"`.
    amount_received: Optional[str] = None
    underpaid_amount: Optional[str] = None


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


def _exact_amount(intent: PaymentIntent) -> Optional[str]:
    """`intent.amount` as the exact decimal the settlement layer compares to.

    `PaymentIntent.amount` is a `Float`, and on a watch-only chain a HUMAN
    retypes it into a wallet while the matcher compares base units with zero
    tolerance — one wrong character is an underpayment that cannot be undone.
    So the value the payer is shown is round-tripped through the very function
    that produces the expected base units, rather than through whatever
    `str(float)` happens to print.

    None when the token is not in the registry for this chain: better to render
    nothing than a number derived from a guessed scale.
    """
    token = token_for(intent.chain or "", intent.currency or "")
    if token is None:
        return None
    _address, decimals = token
    return from_base_units(to_base_units(intent.amount, decimals), decimals)


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
        recipient=intent.recipient,
        amount_exact=_exact_amount(intent),
        amount_received=intent.amount_received,
        underpaid_amount=intent.underpaid_amount,
    )
