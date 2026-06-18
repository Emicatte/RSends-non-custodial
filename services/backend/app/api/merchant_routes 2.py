"""
RSend Backend — Merchant B2B API Routes v1.

Layer B2B per integrazioni merchant:
  POST /api/v1/merchant/payment-intent         → Crea un payment intent
  GET  /api/v1/merchant/payment-intent/{id}    → Status check
  POST /api/v1/merchant/webhook/register       → Registra URL webhook
  POST /api/v1/merchant/webhook/test           → Invia test event
  GET  /api/v1/merchant/transactions           → Lista TX del merchant

Autenticazione: Bearer API key (via APIKeyMiddleware).
Il merchant_id viene derivato dall'API key nel request.state.client.
"""

import secrets
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.merchant_models import (
    PaymentIntent, IntentStatus,
    MerchantWebhook,
    CreatePaymentIntentRequest,
    PaymentIntentResponse,
    RegisterWebhookRequest,
    RegisterWebhookResponse,
    TestWebhookRequest,
    TestWebhookResponse,
    ResolvePaymentRequest,
    MerchantTransactionItem,
    MerchantTransactionListResponse,
    generate_reference_id,
)
from app.services.webhook_service import send_test_event, _dispatch_event
from app.services.audit_service import log_event
from app.services.deposit_address_service import generate_deposit_address
from app.services.key_usage_service import increment_intent_count, check_monthly_limits

from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

merchant_router = APIRouter(prefix="/api/v1/merchant", tags=["merchant"])


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _get_merchant_id(request: Request) -> str:
    """Estrae il merchant_id dal client autenticato via APIKeyMiddleware."""
    client = getattr(request.state, "client", None)
    if client and isinstance(client, dict):
        return client.get("client_id", "unknown")
    return "unknown"


def _generate_intent_id() -> str:
    """Genera un ID univoco per il payment intent: pi_xxxx."""
    return f"pi_{secrets.token_hex(16)}"


def _intent_to_response(intent: PaymentIntent) -> PaymentIntentResponse:
    """Converte un PaymentIntent SQLAlchemy → PaymentIntentResponse Pydantic."""
    return PaymentIntentResponse(
        intent_id=intent.intent_id,
        reference_id=intent.reference_id,
        deposit_address=intent.deposit_address,
        amount=intent.amount,
        currency=intent.currency,
        chain=intent.chain or "BASE",
        recipient=intent.recipient,
        network=intent.network,
        expected_sender=intent.expected_sender,
        status=intent.status.value,
        metadata=intent.metadata_,
        tx_hash=intent.tx_hash,
        matched_tx_hash=intent.matched_tx_hash,
        matched_at=intent.matched_at.isoformat() if intent.matched_at else None,
        completed_late=intent.completed_late,
        late_minutes=intent.late_minutes,
        late_payment_policy=intent.late_payment_policy,
        amount_received=intent.amount_received,
        overpaid_amount=intent.overpaid_amount,
        underpaid_amount=intent.underpaid_amount,
        sweep_tx_hash=intent.sweep_tx_hash,
        swept_at=intent.swept_at.isoformat() if intent.swept_at else None,
        fee_bps=intent.fee_bps,
        fee_amount=intent.fee_amount,
        fee_tx_hash=intent.fee_tx_hash,
        merchant_sweep_amount=intent.merchant_sweep_amount,
        expires_at=intent.expires_at.isoformat(),
        created_at=intent.created_at.isoformat(),
        completed_at=intent.completed_at.isoformat() if intent.completed_at else None,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/merchant/payment-intent
# ═══════════════════════════════════════════════════════════════

@merchant_router.post("/payment-intent", response_model=PaymentIntentResponse)
async def create_payment_intent(
    payload: CreatePaymentIntentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """
    Crea un nuovo payment intent.

    Il merchant invia amount, currency, e metadata opzionali.
    Riceve un intent_id da passare al pagatore per completare il pagamento.
    L'intent scade dopo expires_in_minutes (default 30 min).
    """
    merchant_id = _get_merchant_id(request)
    client = getattr(request.state, "client", None)
    key_id = client.get("key_id") if client else None
    env = client.get("environment", "live") if client else "live"

    # Environment enforcement: test keys ↔ testnet, live keys ↔ mainnet
    TESTNET_CHAINS = {"base_sepolia", "sepolia", "goerli", "nile", "shasta", "devnet"}
    MAINNET_CHAINS = {"base", "ethereum", "eth", "arbitrum", "optimism", "polygon", "bnb", "avalanche", "tron", "solana"}
    requested_chain = (payload.chain or "base").lower()

    if env == "test" and requested_chain in MAINNET_CHAINS:
        raise HTTPException(400, {
            "error": "TESTNET_ONLY",
            "message": f"Test API keys can only create intents on testnet chains. Requested: {requested_chain}.",
            "allowed_chains": sorted(TESTNET_CHAINS),
        })
    if env == "live" and requested_chain in TESTNET_CHAINS:
        raise HTTPException(400, {
            "error": "MAINNET_ONLY",
            "message": f"Live API keys cannot create intents on testnet chains. Requested: {requested_chain}.",
        })

    # Monthly limits
    if key_id:
        limit_check = await check_monthly_limits(db, key_id)
        if not limit_check["allowed"]:
            raise HTTPException(429, {
                "error": "MONTHLY_LIMIT_EXCEEDED",
                "message": limit_check["reason"],
            })

    now = datetime.now(timezone.utc)
    intent_id = _generate_intent_id()

    # Genera deposit address unico per questo intent
    try:
        deposit_addr = generate_deposit_address(intent_id)
    except ValueError:
        deposit_addr = None
        logger.warning("DEPOSIT_MASTER_SEED not set — deposit_address will be null for %s", intent_id)

    intent = PaymentIntent(
        intent_id=intent_id,
        reference_id=generate_reference_id(merchant_id),
        merchant_id=merchant_id,
        amount=payload.amount,
        currency=payload.currency,
        chain=payload.chain,
        recipient=payload.recipient,
        network=payload.network,
        expected_sender=payload.expected_sender,
        deposit_address=deposit_addr,
        late_payment_policy=payload.late_payment_policy,
        amount_tolerance_percent=payload.amount_tolerance_percent,
        allow_partial=payload.allow_partial,
        allow_overpayment=payload.allow_overpayment,
        status=IntentStatus.pending,
        metadata_=payload.metadata,
        expires_at=now + timedelta(minutes=payload.expires_in_minutes),
    )
    db.add(intent)
    await db.flush()

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
            "deposit_address": deposit_addr,
            "expected_sender": payload.expected_sender,
            "late_payment_policy": payload.late_payment_policy,
            "amount_tolerance_percent": payload.amount_tolerance_percent,
            "allow_partial": payload.allow_partial,
            "allow_overpayment": payload.allow_overpayment,
            "expires_in_minutes": payload.expires_in_minutes,
        },
    )

    # Track usage
    if key_id:
        await increment_intent_count(db, key_id)

    await db.commit()

    logger.info(
        "PaymentIntent created: %s ref=%s deposit=%s (merchant=%s, %.6f %s, chain=%s, sender=%s, expires=%s)",
        intent.intent_id, intent.reference_id, deposit_addr or "none",
        merchant_id, payload.amount, payload.currency, payload.chain,
        payload.expected_sender or "any",
        intent.expires_at.isoformat(),
    )

    return _intent_to_response(intent)


# ═══════════════════════════════════════════════════════════════
#  GET /api/v1/merchant/payment-intent/{intent_id}
# ═══════════════════════════════════════════════════════════════

@merchant_router.get("/payment-intent/{intent_id}", response_model=PaymentIntentResponse)
async def get_payment_intent(
    intent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """
    Recupera lo status di un payment intent.

    Il merchant può fare polling su questo endpoint per verificare
    se il pagamento è stato completato.
    """
    merchant_id = _get_merchant_id(request)

    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                PaymentIntent.intent_id == intent_id,
                PaymentIntent.merchant_id == merchant_id,
            )
        )
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

    # Auto-expire se scaduto ma ancora pending
    # SQLite non preserva timezone info — normalize per confronto sicuro
    expires_at = intent.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if intent.status == IntentStatus.pending and expires_at < datetime.now(timezone.utc):
        intent.status = IntentStatus.expired
        await db.commit()

    return _intent_to_response(intent)


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/merchant/webhook/register
# ═══════════════════════════════════════════════════════════════

@merchant_router.post("/webhook/register", response_model=RegisterWebhookResponse)
async def register_webhook(
    payload: RegisterWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterWebhookResponse:
    """
    Registra un nuovo URL webhook per ricevere notifiche eventi.

    Il secret HMAC viene generato e restituito UNA SOLA VOLTA.
    Il merchant lo usa per verificare la firma X-RSend-Signature
    su ogni evento ricevuto.
    """
    merchant_id = _get_merchant_id(request)
    webhook_secret = secrets.token_hex(32)

    webhook = MerchantWebhook(
        merchant_id=merchant_id,
        url=payload.url,
        secret=webhook_secret,
        events=payload.events,
        is_active=True,
    )
    db.add(webhook)
    await db.flush()

    await log_event(
        db,
        "WEBHOOK_REGISTERED",
        "merchant_webhook",
        str(webhook.id),
        actor_type="merchant",
        actor_id=merchant_id,
        changes={
            "url": payload.url,
            "events": payload.events,
        },
    )

    await db.commit()

    logger.info(
        "Webhook registered: id=%d merchant=%s url=%s events=%s",
        webhook.id, merchant_id, payload.url, payload.events,
    )

    return RegisterWebhookResponse(
        webhook_id=webhook.id,
        url=webhook.url,
        secret=webhook_secret,
        events=webhook.events,
        is_active=webhook.is_active,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/merchant/webhook/test
# ═══════════════════════════════════════════════════════════════

@merchant_router.post("/webhook/test", response_model=TestWebhookResponse)
async def test_webhook(
    payload: TestWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TestWebhookResponse:
    """
    Invia un evento di test al webhook registrato.

    Utile per verificare che l'endpoint del merchant sia raggiungibile
    e che la verifica HMAC funzioni correttamente.
    """
    merchant_id = _get_merchant_id(request)

    result = await db.execute(
        select(MerchantWebhook).where(
            and_(
                MerchantWebhook.id == payload.webhook_id,
                MerchantWebhook.merchant_id == merchant_id,
            )
        )
    )
    webhook = result.scalar_one_or_none()

    if webhook is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "WEBHOOK_NOT_FOUND",
                "message": f"Webhook {payload.webhook_id} not found",
            },
        )

    if not webhook.is_active:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "WEBHOOK_INACTIVE",
                "message": "Cannot test an inactive webhook",
            },
        )

    success, status_code, message = await send_test_event(webhook)

    return TestWebhookResponse(
        status="ok" if success else "failed",
        response_code=status_code,
        message=message,
    )


# ═══════════════════════════════════════════════════════════════
#  GET /api/v1/merchant/transactions
# ═══════════════════════════════════════════════════════════════

@merchant_router.get("/transactions", response_model=MerchantTransactionListResponse)
async def list_merchant_transactions(
    request: Request,
    status: Optional[str] = Query(None, description="Filtra per status: pending, completed, expired, cancelled, review, refunded, partial, overpaid"),
    currency: Optional[str] = Query(None, description="Filtra per currency: USDC, ETH, ecc."),
    page: int = Query(1, ge=1, description="Numero pagina"),
    per_page: int = Query(20, ge=1, le=100, description="Risultati per pagina"),
    db: AsyncSession = Depends(get_db),
) -> MerchantTransactionListResponse:
    """
    Lista paginata dei payment intents del merchant.

    Supporta filtri per status e currency per la riconciliazione.
    """
    merchant_id = _get_merchant_id(request)

    # Base query
    base_filter = PaymentIntent.merchant_id == merchant_id
    filters = [base_filter]

    if status:
        try:
            status_enum = IntentStatus(status)
            filters.append(PaymentIntent.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_STATUS",
                    "message": f"Status '{status}' non valido. Validi: pending, completed, expired, cancelled, review, refunded, partial, overpaid",
                },
            )

    if currency:
        filters.append(PaymentIntent.currency == currency)

    # Count totale
    count_result = await db.execute(
        select(func.count(PaymentIntent.id)).where(and_(*filters))
    )
    total = count_result.scalar() or 0

    # Fetch pagina
    offset = (page - 1) * per_page
    result = await db.execute(
        select(PaymentIntent)
        .where(and_(*filters))
        .order_by(PaymentIntent.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    intents = result.scalars().all()

    records = [
        MerchantTransactionItem(
            intent_id=i.intent_id,
            deposit_address=i.deposit_address,
            amount=i.amount,
            currency=i.currency,
            chain=i.chain or "BASE",
            status=i.status.value,
            tx_hash=i.tx_hash,
            matched_tx_hash=i.matched_tx_hash,
            metadata=i.metadata_,
            completed_late=i.completed_late,
            late_minutes=i.late_minutes,
            amount_received=i.amount_received,
            overpaid_amount=i.overpaid_amount,
            underpaid_amount=i.underpaid_amount,
            created_at=i.created_at.isoformat(),
            completed_at=i.completed_at.isoformat() if i.completed_at else None,
        )
        for i in intents
    ]

    return MerchantTransactionListResponse(
        total=total,
        page=page,
        per_page=per_page,
        records=records,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/merchant/payment-intent/{intent_id}/resolve
# ═══════════════════════════════════════════════════════════════

@merchant_router.post("/payment-intent/{intent_id}/resolve", response_model=PaymentIntentResponse)
async def resolve_late_payment(
    intent_id: str,
    payload: ResolvePaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """
    Risolve un pagamento in stato 'review'.

    Dopo che un pagamento arriva in ritardo con policy=review,
    il merchant può completarlo o richiedere un refund.

    Actions:
      - "complete": completa il pagamento (status → completed)
      - "refund": segna come refunded (status → refunded, trigger refund flow futuro)
    """
    merchant_id = _get_merchant_id(request)

    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                PaymentIntent.intent_id == intent_id,
                PaymentIntent.merchant_id == merchant_id,
            )
        )
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

    if intent.status != IntentStatus.review:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_STATE",
                "message": f"Intent is in '{intent.status.value}' state, not 'review'. Only review intents can be resolved.",
            },
        )

    now = datetime.now(timezone.utc)

    if payload.action == "complete":
        intent.status = IntentStatus.completed
        intent.completed_at = now
        await _dispatch_event(
            db,
            merchant_id=intent.merchant_id,
            event_type="payment.completed_late",
            intent=intent,
        )
        logger.info(
            "Late payment RESOLVED (complete): %s by merchant=%s",
            intent.intent_id, merchant_id,
        )

    elif payload.action == "refund":
        intent.status = IntentStatus.refunded
        # TODO: trigger refund flow on-chain (future)
        logger.info(
            "Late payment RESOLVED (refund): %s by merchant=%s",
            intent.intent_id, merchant_id,
        )

    await log_event(
        db,
        "INTENT_RESOLVED",
        "payment_intent",
        intent.intent_id,
        actor_type="merchant",
        actor_id=merchant_id,
        changes={
            "action": payload.action,
            "previous_status": "review",
            "new_status": intent.status.value,
        },
    )

    await db.commit()

    return _intent_to_response(intent)


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/merchant/payment-intent/{intent_id}/cancel
# ═══════════════════════════════════════════════════════════════

@merchant_router.post("/payment-intent/{intent_id}/cancel", response_model=PaymentIntentResponse)
async def cancel_payment_intent(
    intent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """
    Cancella un payment intent ancora in stato 'pending'.

    Ritorna 400 se l'intent è già completed, expired, o in altro stato non-pending.
    """
    merchant_id = _get_merchant_id(request)

    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                PaymentIntent.intent_id == intent_id,
                PaymentIntent.merchant_id == merchant_id,
            )
        )
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

    if intent.status != IntentStatus.pending:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_STATE",
                "message": f"Cannot cancel intent in '{intent.status.value}' state. Only 'pending' intents can be cancelled.",
            },
        )

    intent.status = IntentStatus.cancelled

    await log_event(
        db,
        "INTENT_CANCELLED",
        "payment_intent",
        intent.intent_id,
        actor_type="merchant",
        actor_id=merchant_id,
        changes={
            "previous_status": "pending",
            "new_status": "cancelled",
        },
    )

    await db.commit()

    logger.info(
        "PaymentIntent cancelled: %s by merchant=%s",
        intent.intent_id, merchant_id,
    )

    return _intent_to_response(intent)
