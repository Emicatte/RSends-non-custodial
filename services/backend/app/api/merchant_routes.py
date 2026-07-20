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
from app.services.webhook_service import (
    send_test_event,
    _dispatch_event,
    create_merchant_webhook,
    WebhookEgressError,
)
from app.services.audit_service import log_event
from app.services.intent_service import (
    resolve_recipient,
    list_org_intents,
    create_intent,
    has_settlement_hold,
    split_out,
)
from app.services.router_registry import (
    derive_invoice_id,
    build_onchain_payment,
    chain_is_supported,
    token_is_enabled,
)
from app.services.key_usage_service import increment_intent_count, check_monthly_limits

from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Router-level gate: EVERY merchant API-key route requires the key owner's org
# to be approved (fail closed; unauthenticated requests fall through to the
# handlers' canonical 401). See app/api/deps/require_approved_merchant.py.
from app.api.deps.require_approved_merchant import require_approved_merchant

merchant_router = APIRouter(
    prefix="/api/v1/merchant",
    tags=["merchant"],
    dependencies=[Depends(require_approved_merchant)],
)


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _get_merchant_id(request: Request) -> str:
    """Estrae il merchant_id dal client autenticato via APIKeyMiddleware.

    Fail-closed: nessun client autenticato (o un client senza client_id) è un
    401 — mai un bucket condiviso tipo "unknown". Nessuna route merchant è
    pubblica: il checkout /pay legge dalla view limitata in
    app/api/public_routes.py (id-as-secret), non da qui.
    """
    client = getattr(request.state, "client", None)
    if client and isinstance(client, dict):
        merchant_id = client.get("client_id")
        if merchant_id:
            return merchant_id
    raise HTTPException(
        status_code=401,
        detail={"error": "INVALID_API_KEY", "message": "Valid API key required"},
    )


def _get_environment(request: Request) -> str:
    """Environment ("test"|"live") of the authenticated key.

    merchant_id (== owner address) is shared across an owner's test and live
    keys, so reads/mutates must additionally scope by this to keep test and live
    data isolated. Defaults to "live" when absent (unauthenticated public GET),
    which combined with the merchant_id filter still yields no rows.
    """
    client = getattr(request.state, "client", None)
    if client and isinstance(client, dict):
        return client.get("environment", "live")
    return "live"


def _generate_intent_id() -> str:
    """Genera un ID univoco per il payment intent: pi_xxxx."""
    return f"pi_{secrets.token_hex(16)}"


async def _intent_to_response(intent: PaymentIntent) -> PaymentIntentResponse:
    """Converte un PaymentIntent SQLAlchemy → PaymentIntentResponse Pydantic.

    Async because the on-chain payload reads the fee LIVE from RSendsRouter.quoteFee.
    """
    onchain = await build_onchain_payment(intent)
    return PaymentIntentResponse(
        intent_id=intent.intent_id,
        reference_id=intent.reference_id,
        onchain_invoice_id=intent.onchain_invoice_id,
        onchain=onchain,
        amount=intent.amount,
        currency=intent.currency,
        chain=intent.chain or "BASE",
        recipient=intent.recipient,
        split=split_out(intent),
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
    # Thin wrapper over the shared constructor (intent_service.create_intent) —
    # the single PaymentIntent construction site + Phase B recipient gate live
    # there, shared with the session path. Only the key-scoped bits (merchant_id
    # + environment from the API key, monthly-limit + usage-increment via key_id)
    # are resolved here; the session path passes org_id instead.
    merchant_id = _get_merchant_id(request)
    client = getattr(request.state, "client", None)
    key_id = client.get("key_id") if client else None
    env = client.get("environment", "live") if client else "live"

    intent = await create_intent(
        db, merchant_id, env, payload, org_id=None, key_id=key_id
    )
    return await _intent_to_response(intent)


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
                PaymentIntent.environment == _get_environment(request),
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

    # Auto-expire se scaduto ma ancora pending — MAI se esiste un settlement
    # on-chain osservato/finale (B-1: i soldi vincono sul timer).
    # SQLite non preserva timezone info — normalize per confronto sicuro
    expires_at = intent.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        intent.status == IntentStatus.pending
        and expires_at < datetime.now(timezone.utc)
        and not await has_settlement_hold(db, intent.intent_id)
    ):
        intent.status = IntentStatus.expired
        await db.commit()

    return await _intent_to_response(intent)


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

    try:
        webhook = await create_merchant_webhook(
            db,
            merchant_id=merchant_id,
            environment=_get_environment(request),
            url=payload.url,
            events=payload.events,
        )
    except WebhookEgressError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "WEBHOOK_URL_FORBIDDEN",
                "message": f"Webhook URL is not an allowed target ({exc.reason})",
            },
        )

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
        secret=webhook.secret,
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
                MerchantWebhook.environment == _get_environment(request),
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

    Supporta filtri per status e currency per la riconciliazione. Delega alla
    query condivisa `list_org_intents` (stessa logica del path session-authed
    /api/v1/user/org/payment-intents) — scoped al merchant dell'API key E al suo
    environment (test/live condividono il merchant_id, servono entrambi).
    """
    merchant_id = _get_merchant_id(request)
    return await list_org_intents(
        db,
        merchant_id,
        _get_environment(request),
        status=status,
        currency=currency,
        page=page,
        per_page=per_page,
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
                PaymentIntent.environment == _get_environment(request),
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

    return await _intent_to_response(intent)


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
                PaymentIntent.environment == _get_environment(request),
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

    # F-5: un pagamento on-chain osservato (settlement pending/final) vince sul
    # cancel — stesso guard dei writer di expiry. rejected/reorged NON bloccano.
    if await has_settlement_hold(db, intent.intent_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "SETTLEMENT_IN_FLIGHT",
                "message": "An on-chain payment for this intent has been observed; it can no longer be cancelled.",
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

    return await _intent_to_response(intent)
