"""Payment-intent creation helpers (Phase B).

`resolve_recipient` is the single recipient gate: an intent CANNOT be created
without a resolvable on-chain recipient. It is wired at the one PaymentIntent
construction site (app/api/merchant_routes.py) and is reused by the session
creation path (Phase D) via the `org_id` argument. Fail-closed everywhere —
never silently default a recipient.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_models import (
    CreatePaymentIntentRequest,
    IntentStatus,
    MerchantTransactionItem,
    MerchantTransactionListResponse,
    PaymentIntent,
    PaymentIntentRecipient,
    SplitRecipientOut,
    generate_reference_id,
)
from app.models.api_key_models import ApiKey
from app.models.org_models import Organization
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.models.user_wallets_models import UserWallet
from app.services.audit_service import log_event
from app.services.key_usage_service import (
    check_monthly_limits,
    increment_intent_count,
)
from app.services.router_registry import (
    chain_id_for,
    chain_is_supported,
    derive_invoice_id,
    network_name_for_chain_id,
    split_router_address_for,
    token_is_enabled,
)

logger = logging.getLogger(__name__)

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


# ── Settlement hold (B-1) ────────────────────────────────────────
#
# Money on-chain wins over the expiry timer, always. An intent with an observed
# (pending) or final settlement must never be flipped to expired — the indexer
# will finalize it (or rescue it if expiry already won a race). `rejected`
# (validation mismatch) and `reorged` (rolled back) settlements do NOT hold.

SETTLEMENT_HOLD_STATUSES = (SettlementStatus.pending, SettlementStatus.final)


def settlement_hold_exists():
    """Correlated EXISTS for queries over PaymentIntent: true when the intent
    has a settlement that must win over the expiry timer."""
    return (
        select(PaymentSettlement.id)
        .where(
            PaymentSettlement.intent_id == PaymentIntent.intent_id,
            PaymentSettlement.status.in_(SETTLEMENT_HOLD_STATUSES),
        )
        .exists()
    )


async def has_settlement_hold(db: AsyncSession, intent_id: str) -> bool:
    """Single-intent form of the same predicate (read-time expiry guards)."""
    row = (await db.execute(
        select(PaymentSettlement.id)
        .where(
            PaymentSettlement.intent_id == intent_id,
            PaymentSettlement.status.in_(SETTLEMENT_HOLD_STATUSES),
        )
        .limit(1)
    )).scalar_one_or_none()
    return row is not None


# ── Shared intent-list query (Phase C) ───────────────────────────
#
# One query, two callers: the API-key `GET /merchant/transactions` path and the
# session `GET /user/org/payment-intents` path both delegate here, so the list
# view can never drift between the programmatic and browser surfaces. Tenant +
# environment isolation live IN the query (both predicates required — an owner's
# test and live keys share the same merchant_id).

def split_out(i: PaymentIntent) -> list[SplitRecipientOut] | None:
    """The intent's split legs as response models, or None for a single-payee
    intent. Shared by every serializer (merchant GET/list, session list) so the
    split view can never drift between surfaces. Uses the load-safe accessor —
    never triggers an async lazy-load."""
    from app.services.router_registry import loaded_split_recipients

    legs = loaded_split_recipients(i)
    if not legs:
        return None
    return [
        SplitRecipientOut(
            address=leg.address,
            share_bps=leg.share_bps,
            position=leg.position,
            label=leg.label,
        )
        for leg in legs
    ]


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
        split=split_out(i),
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


# ── The single intent construction site (Phase D) ────────────────
#
# BOTH the API-key path (merchant_routes.create_payment_intent) and the session
# path (user_org_payments_routes.create_org_payment_intent) call `create_intent`,
# so Phase B's recipient gate and every validation apply uniformly — no second
# construction path can bypass them. `key_id` gates the two API-key-only steps
# (monthly limits + usage increment); the session path passes key_id=None.
# `org_id` (session) makes resolve_recipient use the org's settlement_wallet
# directly instead of the reverse wallet→org lookup.

_TESTNET_CHAINS = {"base_sepolia", "sepolia"}
_MAINNET_CHAINS = {"base", "ethereum", "eth"}


async def create_intent(
    db: AsyncSession,
    merchant_id: str,
    environment: str,
    payload: CreatePaymentIntentRequest,
    org_id: str | None = None,
    key_id: int | str | None = None,
) -> PaymentIntent:
    """Create + persist a PaymentIntent, or raise the appropriate 4xx.

    Order (preserved from the original API-key handler): chain gate → env↔chain →
    token gate → (monthly limit, key only) → id gen → recipient gate → construct →
    add/flush → audit → (usage increment, key only) → commit. Returns the intent;
    the caller serializes it with `_intent_to_response`.
    """
    # `key_id` must compare against ApiKey.id (Integer): callers pass it as int
    # (middleware client dict) or numeric str (session/test callers) — Postgres
    # has no `integer = varchar` operator, so normalize once here for every
    # downstream ApiKey.id lookup (monthly limit, org lookup, usage increment).
    if key_id is not None:
        try:
            key_id = int(key_id)
        except (TypeError, ValueError):
            key_id = None  # non-numeric (e.g. debug bypass) — skip key-gated steps

    requested_chain = (payload.chain or "base").lower()

    # Categorical settlement gate: a chain that doesn't canonicalize into the
    # token registry has no settlement path at all. Reject before the env check.
    if not chain_is_supported(requested_chain):
        raise HTTPException(400, {
            "error": "UNSUPPORTED_CHAIN",
            "message": f"Unsupported chain for settlement: {requested_chain}.",
        })

    if environment == "test" and requested_chain in _MAINNET_CHAINS:
        raise HTTPException(400, {
            "error": "TESTNET_ONLY",
            "message": f"Test API keys can only create intents on testnet chains. Requested: {requested_chain}.",
            "allowed_chains": sorted(_TESTNET_CHAINS),
        })
    if environment == "live" and requested_chain in _TESTNET_CHAINS:
        raise HTTPException(400, {
            "error": "MAINNET_ONLY",
            "message": f"Live API keys cannot create intents on testnet chains. Requested: {requested_chain}.",
        })

    # Token policy gate (single source of truth: app/token_registry.json).
    if not token_is_enabled(requested_chain, payload.currency):
        raise HTTPException(400, {
            "error": "UNSUPPORTED_TOKEN",
            "message": f"Token {payload.currency} is not enabled on chain {requested_chain}.",
        })

    # Monthly limits — API-key path only.
    if key_id:
        limit_check = await check_monthly_limits(db, key_id)
        if not limit_check["allowed"]:
            raise HTTPException(429, {
                "error": "MONTHLY_LIMIT_EXCEEDED",
                "message": limit_check["reason"],
            })

    now = datetime.now(timezone.utc)
    intent_id = f"pi_{secrets.token_hex(16)}"
    reference_id = generate_reference_id(merchant_id)
    onchain_invoice_id = derive_invoice_id(reference_id)

    # RECIPIENT GATE (Phase B): explicit override OR settlement_wallet default —
    # org_id set (session) resolves the org's wallet directly. On the API-key
    # path, a session-minted key carries its minting org (migration 0011):
    # resolve via THAT org — a settlement-wallet-only merchant has no
    # SIWE-linked wallet for the reverse lookup, but its keys are org-stamped.
    # Wallet-minted keys (org_id NULL) keep the reverse lookup. Fail-closed 422.
    #
    # SPLIT: a valid split set (schema-gated: 2..20 legs, no dupes, bps sum
    # EXACTLY 10000, mutually exclusive with `recipient`) IS the recipient set —
    # `recipient` stays NULL and the legs go to payment_intent_recipients.
    # Fail-closed on config: without a deployed+configured RSendsSplitRouter
    # for the chain, no split intent may exist (it would be unpayable and the
    # indexer couldn't validate it).
    if payload.split is not None:
        if split_router_address_for(requested_chain) is None:
            raise HTTPException(422, {
                "error": "SPLIT_UNAVAILABLE",
                "message": (
                    f"Split payments are not enabled on chain {requested_chain}."
                ),
            })
        recipient = None
    else:
        recipient_org = org_id
        if recipient_org is None and key_id is not None:
            recipient_org = (
                await db.execute(
                    select(ApiKey.org_id).where(ApiKey.id == key_id)
                )
            ).scalar_one_or_none()
        recipient = await resolve_recipient(
            db, merchant_id, payload.recipient, org_id=recipient_org
        )

    # NETWORK is DERIVED from the (already validated + env-gated) chain, never
    # trusted from merchant free-text: `payload.network` is unvalidated and can
    # contradict the chain (e.g. "BASE_MAINNET" on a base_sepolia intent), which
    # would then leak into lifecycle webhooks. Normalizing here keeps it always
    # consistent with `chain` (None for a chain with no network-name mapping).
    derived_network = network_name_for_chain_id(chain_id_for(requested_chain))

    intent = PaymentIntent(
        intent_id=intent_id,
        reference_id=reference_id,
        merchant_id=merchant_id,
        environment=environment,
        amount=payload.amount,
        currency=payload.currency,
        chain=payload.chain,
        recipient=recipient,
        network=derived_network,
        expected_sender=payload.expected_sender,
        onchain_invoice_id=onchain_invoice_id,
        late_payment_policy=payload.late_payment_policy,
        amount_tolerance_percent=payload.amount_tolerance_percent,
        allow_partial=payload.allow_partial,
        allow_overpayment=payload.allow_overpayment,
        status=IntentStatus.pending,
        metadata_=payload.metadata,
        expires_at=now + timedelta(minutes=payload.expires_in_minutes),
    )
    db.add(intent)
    if payload.split is not None:
        # Same transaction as the intent — a split intent can never exist
        # without its legs (position 0 = primary, receives the remainder).
        for position, leg in enumerate(payload.split):
            db.add(PaymentIntentRecipient(
                intent_id=intent_id,
                position=position,
                address=leg.address,
                share_bps=leg.share_bps,
                label=leg.label,
            ))
    await db.flush()
    # Populate the (selectin) relationship on the freshly built instance — an
    # async lazy-load on attribute access would raise MissingGreenlet when the
    # caller serializes the response. Split: read the flushed legs back; single:
    # empty by construction, no query needed.
    if payload.split is not None:
        await db.refresh(intent, ["split_recipients"])
    else:
        from sqlalchemy.orm.attributes import set_committed_value

        set_committed_value(intent, "split_recipients", [])

    await log_event(
        db,
        "INTENT_CREATED",
        "payment_intent",
        intent.intent_id,
        actor_type="merchant",
        actor_id=merchant_id,
        changes={
            "amount": str(payload.amount),
            "currency": payload.currency,
            "chain": payload.chain,
            "reference_id": intent.reference_id,
            "onchain_invoice_id": onchain_invoice_id,
            "expected_sender": payload.expected_sender,
            "late_payment_policy": payload.late_payment_policy,
            "amount_tolerance_percent": payload.amount_tolerance_percent,
            "allow_partial": payload.allow_partial,
            "allow_overpayment": payload.allow_overpayment,
            "expires_in_minutes": payload.expires_in_minutes,
            "split": (
                [
                    {"address": leg.address, "share_bps": leg.share_bps}
                    for leg in payload.split
                ]
                if payload.split is not None
                else None
            ),
        },
    )

    # Usage tracking — API-key path only.
    if key_id:
        await increment_intent_count(db, key_id)

    await db.commit()

    logger.info(
        "PaymentIntent created: %s ref=%s invoiceId=%s (merchant=%s, %.6f %s, chain=%s, sender=%s, expires=%s)",
        intent.intent_id, intent.reference_id, onchain_invoice_id,
        merchant_id, payload.amount, payload.currency, payload.chain,
        payload.expected_sender or "any",
        intent.expires_at.isoformat(),
    )

    return intent
