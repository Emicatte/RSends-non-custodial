"""Public (payer-facing) routes — intentionally unauthenticated, strictly limited.

Trust boundary: everything in this module is reachable WITHOUT an API key, in
production config (no RSEND_DEV_AUTH_BYPASS). Rules for anything added here:

- Access model is **id-as-secret**: the lookup key must be non-enumerable
  (intent_id = "pi_" + secrets.token_hex(16) → 128 bits CSPRNG).
- Single-object lookups only — no list routes, no filters, nothing that
  enables enumeration.
- Serialize an EXPLICIT allowlisted response model, never the ORM object:
  a future column must not leak by default.
- Read-only, with ONE named exception: the TRON transaction hint POST at the
  bottom of this file. It writes a row recording which transaction the payer
  says they broadcast. It is allowed here because a caller can influence only
  two values — a transaction hash and their own address — and both are checked
  against the chain before anything follows from them. Recipient, amount, token
  and network are never accepted; they are re-derived from the intent. The row
  is a claim, not a credit. Any further write needs the same argument made
  again, in writing, or it does not belong on this surface.
- Per-IP rate limited (see ENDPOINT_LIMITS in app/middleware/rate_limit.py) and
  allowlisted in GET_PUBLIC_PREFIXES / POST_PUBLIC_PREFIXES
  (app/security/api_keys.py).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import re

from app.db.session import get_db
from app.security.input_validator import normalize_payment_address
from app.models.merchant_models import IntentStatus, OnchainPayment, PaymentIntent
from app.services.router_registry import (
    build_onchain_payment,
    from_base_units,
    to_base_units,
    token_for,
)

logger = logging.getLogger("rsend.public")

public_router = APIRouter(prefix="/api/v1/public", tags=["public"])

#: TRON txids are 64 hex characters and carry no `0x`, unlike EVM.
_TX_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


# ═══════════════════════════════════════════════════════════════
#  The TRON transaction hint (B1)
# ═══════════════════════════════════════════════════════════════
#
# The one WRITE on an otherwise read-only public surface. The module docstring
# names it as the single exception rather than leaving the rule quietly false.
# What makes it acceptable is what the payer can influence: a transaction hash and their own address, both of which are
# checked against the chain before anything follows from them. There is no
# recipient, amount, token or network on the schema, so there is no field a
# caller could use to redirect a payment. The row it writes is a claim, not a
# credit.

class TronTxHintRequest(BaseModel):
    """A hash, and who says they sent it. Nothing else is accepted."""

    tx_hash: str = Field(..., description="TRON txid: 64 hex characters, no 0x")
    payer_address: Optional[str] = Field(default=None)

    @field_validator("tx_hash")
    @classmethod
    def _hash_shape(cls, v: str) -> str:
        # TRON txids carry no `0x`, unlike EVM. Lowercased so the unique
        # constraint cannot be defeated by case alone.
        if not isinstance(v, str) or not _TX_HASH_RE.match(v):
            raise ValueError("tx_hash must be 64 hexadecimal characters")
        return v.lower()

    @field_validator("payer_address")
    @classmethod
    def _payer_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        # The conditional normaliser: base58 survives untouched, and anything
        # that is not an address at all is refused rather than stored.
        normalized = normalize_payment_address(v)
        if normalized is None:
            raise ValueError("payer_address is not a valid address")
        return normalized


class TronTxHintResponse(BaseModel):
    hint_state: str
    status: str
    rejection_reason: Optional[str] = None


@public_router.post(
    "/payment-intent/{intent_id}/tx-hint", response_model=TronTxHintResponse,
)
async def submit_tron_tx_hint(
    intent_id: str,
    body: TronTxHintRequest,
    db: AsyncSession = Depends(get_db),
    _source=None,
) -> TronTxHintResponse:
    """Record the hash the payer's wallet broadcast, and try to verify it now.

    Id-as-secret, exactly like the GET: whoever holds the intent link may tell
    us about a transaction for that one intent. `_source` is a test seam for the
    node reader and is never supplied over HTTP.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints
    from app.services.tron_poller import TRON_MAINNET, TRON_NILE
    from app.services.tron_verifier import Pending, Rejected, Verified

    intent = (await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )).scalar_one_or_none()
    if intent is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "INTENT_NOT_FOUND",
                    "message": f"Payment intent '{intent_id}' not found"},
        )

    chain = (intent.chain or "").lower()
    network = {TRON_MAINNET.chain_name: TRON_MAINNET,
               TRON_NILE.chain_name: TRON_NILE}.get(chain)
    if network is None:
        # An EVM intent has a router and an indexer; there is no hint path for
        # it, and pretending otherwise would invite a client to build one.
        raise HTTPException(
            status_code=409,
            detail={"error": "CHAIN_NOT_WATCH_ONLY",
                    "message": "Transaction hints apply to TRON intents only"},
        )

    # The same effective-status helper the public GET uses, so the two surfaces
    # can never disagree about whether an intent is still open.
    effective = _effective_status(intent)
    if effective == IntentStatus.expired.value:
        raise HTTPException(
            status_code=409,
            detail={"error": "INTENT_EXPIRED", "message": "This payment has expired"},
        )
    if effective not in (IntentStatus.pending.value, IntentStatus.partial.value):
        raise HTTPException(
            status_code=409,
            detail={"error": "INTENT_NOT_PAYABLE",
                    "message": f"This payment is {effective}"},
        )

    # A transaction already bound to a DIFFERENT intent cannot also be this one.
    from app.models.settlement_models import PaymentSettlement

    claimed = (await db.execute(
        select(PaymentSettlement.intent_id).where(
            PaymentSettlement.tx_hash == body.tx_hash,
            PaymentSettlement.intent_id.is_not(None),
            PaymentSettlement.intent_id != intent.intent_id,
        ).limit(1)
    )).scalar_one_or_none()
    if claimed is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "TX_ALREADY_SETTLED",
                    "message": "That transaction already settled another payment"},
        )

    # Insert first, catch the collision. A select-then-insert loses the race a
    # double-click creates, and the unique constraint is the thing that actually
    # decides — so it may as well be the thing that is asked.
    # In its OWN session: a failed INSERT leaves the object pending, and the
    # re-read that follows would autoflush it straight back into the same
    # collision. Isolating the write also keeps a lost race from poisoning the
    # request session that still has to answer.
    from app.db.session import async_session

    fresh = True
    async with async_session() as writer:
        writer.add(TronPaymentHint(
            intent_pk=intent.id,
            tx_hash=body.tx_hash,
            payer_address=body.payer_address,
        ))
        try:
            await writer.commit()
        except IntegrityError:
            await writer.rollback()
            fresh = False

    hint = (await db.execute(
        select(TronPaymentHint).where(
            TronPaymentHint.intent_pk == intent.id,
            TronPaymentHint.tx_hash == body.tx_hash,
        )
    )).scalar_one()

    # Verify immediately only when this submission is new. A resubmission of a
    # hint already pending or verified must not spend a node call: the tick pass
    # owns it from here.
    if fresh or hint.state == HintState.rejected:
        result = await tron_hints.verify_hint(
            network,
            tx_hash=body.tx_hash,
            payer_address=body.payer_address,
            intent=intent,
            source=_source,
        )
        await tron_hints.apply_result(network, hint.id, result)
        state = (
            HintState.verified if isinstance(result, Verified)
            else HintState.rejected if isinstance(result, Rejected)
            else HintState.pending
        )
        reason = result.reason if isinstance(result, Rejected) else None
    else:
        state, reason = hint.state, hint.rejection_reason

    refreshed = (await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )).scalar_one()
    await db.refresh(refreshed)
    return TronTxHintResponse(
        hint_state=state.value if hasattr(state, "value") else str(state),
        status=_effective_status(refreshed),
        rejection_reason=reason,
    )
