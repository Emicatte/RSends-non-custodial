"""
RSend Backend — Transaction Matcher Service.

Quando arriva una TX confermata (via webhook Alchemy o POST /tx/callback),
il matcher cerca se corrisponde a un PaymentIntent pendente.

Logica di matching:
  1. Cerca intent con status=pending e deposit_address == tx.recipient (case insensitive)
  2. Verifica: currency match, amount nella tolleranza, non scaduto
  3. Se OK → completa l'intent, triggera webhook al merchant
  4. Gestisce underpayment (rifiuto), overpayment (accetta con log)
  5. Anti-duplicati: intent già matchato o TX già usata → skip
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_models import PaymentIntent, IntentStatus
from app.services.audit_service import log_event
from app.services.webhook_service import _dispatch_event

logger = logging.getLogger(__name__)


def _schedule_sweep(intent_id: str, currency: str, chain: str) -> None:
    """
    Schedula lo sweep dei fondi dal deposit address come background task.

    Prova prima Celery (se disponibile), altrimenti fallback a asyncio task.
    Lo sweep e' asincrono — non blocca il response della TX callback.
    """
    try:
        from app.tasks.sweep_tasks import sweep_intent_task
        sweep_intent_task.delay(intent_id, currency, chain)
        logger.info("Sweep scheduled via Celery for intent=%s", intent_id)
    except (ImportError, Exception) as exc:
        # Celery non disponibile o non connesso — fallback a asyncio
        logger.info(
            "Celery unavailable (%s), scheduling sweep via asyncio for intent=%s",
            type(exc).__name__, intent_id,
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_sweep_fallback(intent_id, currency, chain))
        except RuntimeError:
            logger.warning("No running event loop — sweep for intent=%s must be triggered manually", intent_id)


async def _async_sweep_fallback(intent_id: str, currency: str, chain: str) -> None:
    """Fallback: esegue lo sweep come asyncio task (senza Celery)."""
    from app.services.deposit_sweep_service import execute_sweep
    try:
        await execute_sweep(intent_id, currency, chain)
    except Exception:
        logger.exception("Async sweep fallback failed for intent=%s", intent_id)


# ═══════════════════════════════════════════════════════════════
#  Result types
# ═══════════════════════════════════════════════════════════════

@dataclass
class MatchResult:
    matched: bool
    intent_id: Optional[str] = None
    event: Optional[str] = None
    reason: Optional[str] = None
    expected: Optional[float] = None
    received: Optional[float] = None
    overpaid_amount: Optional[float] = None
    webhook_triggered: bool = False


@dataclass
class IncomingTx:
    """Dati della transazione in arrivo necessari per il matching."""
    tx_hash: str
    recipient: str
    amount: float
    currency: str


# ═══════════════════════════════════════════════════════════════
#  Anti-duplicati: check se una TX ha già matchato un intent
# ═══════════════════════════════════════════════════════════════

async def _tx_already_matched(db: AsyncSession, tx_hash: str) -> bool:
    """Verifica se una TX ha già matchato un intent (idempotenza)."""
    result = await db.execute(
        select(func.count(PaymentIntent.id)).where(
            PaymentIntent.matched_tx_hash == tx_hash,
        )
    )
    count = result.scalar() or 0
    return count > 0


# ═══════════════════════════════════════════════════════════════
#  Core matching
# ═══════════════════════════════════════════════════════════════

async def match_transaction(
    db: AsyncSession,
    tx: IncomingTx,
) -> MatchResult:
    """
    Cerca un PaymentIntent pendente che corrisponde alla TX in arrivo.

    Matching per deposit_address (case insensitive):
      - Currency deve corrispondere
      - Amount entro la tolleranza configurata sull'intent
      - Intent non scaduto
      - Intent non già matchato (matched_tx_hash == null)

    Returns:
        MatchResult con esito e dettagli del matching.
    """
    tx_hash = tx.tx_hash.lower()
    recipient = tx.recipient.lower()

    # ── Anti-duplicato TX ────────────────────────────────────
    if await _tx_already_matched(db, tx_hash):
        logger.info(
            "TX %s already matched to an intent — skipping",
            tx_hash[:16],
        )
        return MatchResult(
            matched=False,
            reason="tx_already_matched",
        )

    # ── Cerca intent per deposit_address ─────────────────────
    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                func.lower(PaymentIntent.deposit_address) == recipient,
                PaymentIntent.matched_tx_hash.is_(None),
            )
        )
        .with_for_update(skip_locked=True)
        .order_by(PaymentIntent.created_at.asc())
        .limit(1)
    )
    intent = result.scalar_one_or_none()

    if intent is None:
        logger.info(
            "No matching intent for deposit_address=%s (tx=%s)",
            recipient, tx_hash[:16],
        )
        return MatchResult(
            matched=False,
            reason="no_matching_intent",
        )

    # ── Intent già completato/cancellato? ────────────────────
    if intent.status not in (IntentStatus.pending,):
        logger.info(
            "Intent %s found but status=%s, not pending — skipping",
            intent.intent_id, intent.status.value,
        )
        return MatchResult(
            matched=False,
            reason=f"intent_status_{intent.status.value}",
            intent_id=intent.intent_id,
        )

    now = datetime.now(timezone.utc)

    # ── Scaduto? ─────────────────────────────────────────────
    # SQLite non preserva timezone info — normalize per confronto sicuro
    expires_at = intent.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        intent.status = IntentStatus.expired
        await db.flush()

        await log_event(
            db,
            "TX_STATE_CHANGE",
            "payment_intent",
            intent.intent_id,
            actor_type="system",
            changes={
                "previous_status": "pending",
                "new_status": "expired",
                "reason": "expired_at_match_time",
                "tx_hash": tx_hash,
            },
        )

        logger.warning(
            "Intent %s expired at match time (expired_at=%s, now=%s, tx=%s)",
            intent.intent_id, intent.expires_at.isoformat(), now.isoformat(), tx_hash[:16],
        )
        return MatchResult(
            matched=False,
            reason="intent_expired",
            intent_id=intent.intent_id,
        )

    # ── Currency match ───────────────────────────────────────
    if intent.currency.upper() != tx.currency.upper():
        logger.info(
            "Intent %s currency mismatch: expected=%s, got=%s (tx=%s)",
            intent.intent_id, intent.currency, tx.currency, tx_hash[:16],
        )
        return MatchResult(
            matched=False,
            reason="currency_mismatch",
            intent_id=intent.intent_id,
        )

    # ── Amount tolerance check ───────────────────────────────
    tolerance_pct = intent.amount_tolerance_percent or 1.0
    tolerance_ratio = tolerance_pct / 100.0
    diff_ratio = (tx.amount - intent.amount) / intent.amount if intent.amount > 0 else 0.0

    # Underpayment: amount ricevuto sotto la tolleranza
    if diff_ratio < -tolerance_ratio:
        logger.warning(
            "Underpayment for intent %s: expected=%.6f, received=%.6f, diff=%.2f%% (tolerance=%.2f%%) tx=%s",
            intent.intent_id, intent.amount, tx.amount,
            diff_ratio * 100, tolerance_pct, tx_hash[:16],
        )

        await log_event(
            db,
            "TX_STATE_CHANGE",
            "payment_intent",
            intent.intent_id,
            actor_type="system",
            changes={
                "event": "underpayment_rejected",
                "expected_amount": str(intent.amount),
                "received_amount": str(tx.amount),
                "diff_percent": f"{diff_ratio * 100:.2f}",
                "tolerance_percent": str(tolerance_pct),
                "tx_hash": tx_hash,
            },
        )

        return MatchResult(
            matched=False,
            reason="underpayment",
            intent_id=intent.intent_id,
            expected=intent.amount,
            received=tx.amount,
        )

    # Overpayment: amount ricevuto sopra la tolleranza
    is_overpayment = diff_ratio > tolerance_ratio
    overpaid_amt: Optional[float] = None

    if is_overpayment:
        overpaid_amt = tx.amount - intent.amount
        logger.info(
            "Overpayment for intent %s: expected=%.6f, received=%.6f, overpaid=%.6f tx=%s — completing anyway",
            intent.intent_id, intent.amount, tx.amount, overpaid_amt, tx_hash[:16],
        )

    # ── Match! Completa l'intent ─────────────────────────────
    intent.status = IntentStatus.completed
    intent.matched_tx_hash = tx_hash
    intent.matched_at = now
    intent.completed_at = now
    intent.amount_received = str(tx.amount)

    if is_overpayment:
        intent.overpaid_amount = str(overpaid_amt)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.info("tx_already_matched (unique constraint): tx=%s", tx_hash)
        return MatchResult(matched=False, reason="tx_already_matched")

    # ── Track volume on the API key that created this intent ──
    try:
        from app.services.key_usage_service import add_volume
        from app.models.api_key_models import ApiKey
        from decimal import Decimal
        _key_q = select(ApiKey).where(
            ApiKey.owner_address == intent.merchant_id,
            ApiKey.is_active == True,  # noqa: E712
        ).limit(1)
        _key_result = await db.execute(_key_q)
        _key = _key_result.scalar_one_or_none()
        if _key:
            await add_volume(db, _key.id, Decimal(str(tx.amount)))
    except Exception:
        logger.debug("Volume tracking failed for intent %s", intent.intent_id, exc_info=True)

    # ── Audit log ────────────────────────────────────────────
    event_type = "payment.completed"
    changes = {
        "previous_status": "pending",
        "new_status": "completed",
        "matched_tx_hash": tx_hash,
        "expected_amount": str(intent.amount),
        "received_amount": str(tx.amount),
    }
    if is_overpayment:
        changes["overpaid_amount"] = str(overpaid_amt)
        changes["note"] = "overpayment_accepted"

    await log_event(
        db,
        "TX_COMPLETED",
        "payment_intent",
        intent.intent_id,
        actor_type="system",
        changes=changes,
    )

    # ── Fee preview for webhook ─────────────────────────────
    from app.services.platform_fee_service import calculate_fee, token_decimals
    decimals = token_decimals(intent.currency)
    try:
        received_raw = int(float(str(tx.amount)) * 10 ** decimals)
        fee_preview = calculate_fee(received_raw)
    except Exception:
        fee_preview = None
        logger.debug("Fee preview calc failed for intent %s", intent.intent_id, exc_info=True)

    fee_payload = {}
    if fee_preview and fee_preview.enabled:
        fee_payload = {
            "fee_bps": fee_preview.fee_bps,
            "estimated_fee": str(fee_preview.fee_amount / 10 ** decimals),
            "estimated_net": str(fee_preview.merchant_amount / 10 ** decimals),
        }

    # ── Webhook al merchant ──────────────────────────────────
    webhook_triggered = False
    try:
        await _dispatch_event(
            db,
            merchant_id=intent.merchant_id,
            event_type=event_type,
            intent=intent,
            extra_payload={
                "matched_tx_hash": tx_hash,
                "amount_received": str(tx.amount),
                "overpaid_amount": str(overpaid_amt) if overpaid_amt else None,
                **fee_payload,
            },
        )
        webhook_triggered = True
    except Exception:
        logger.exception(
            "Failed to dispatch webhook for intent %s (tx=%s)",
            intent.intent_id, tx_hash[:16],
        )

    logger.info(
        "TX %s matched intent %s: %.6f %s → completed (webhook=%s, overpaid=%s)",
        tx_hash[:16], intent.intent_id, tx.amount, tx.currency,
        webhook_triggered, overpaid_amt,
    )

    # ── Notify checkout WebSocket clients ────────────────────
    try:
        from app.api.payment_ws import notify_payment_completed
        ws_count = await notify_payment_completed(intent.intent_id, tx_hash)
        if ws_count:
            logger.info("WS notified %d checkout client(s) for intent %s", ws_count, intent.intent_id)
    except Exception:
        logger.debug("WS notification skipped for intent %s", intent.intent_id, exc_info=True)

    # ── Trigger sweep as background task ─────────────────────
    _schedule_sweep(intent.intent_id, intent.currency, intent.chain)

    return MatchResult(
        matched=True,
        intent_id=intent.intent_id,
        event=event_type,
        overpaid_amount=overpaid_amt,
        webhook_triggered=webhook_triggered,
    )
