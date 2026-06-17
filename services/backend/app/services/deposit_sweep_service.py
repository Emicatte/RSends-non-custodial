"""
RSend Backend — Deposit Sweep Service.

Orchestrates the sweep of funds from deposit addresses to merchant/treasury.
Manages intent status transitions: completed -> sweeping -> settled.
Platform fee (1% default) is split: merchant receives net, RSends treasury receives fee.

Separato da sweep_service.py (Command Center forwarding rules).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.models.merchant_models import PaymentIntent, IntentStatus
from app.db.session import async_session
from app.services.audit_service import log_event
from app.services.deposit_address_service import sweep_deposit, get_deposit_balance
from app.services.platform_fee_service import calculate_fee, token_decimals

logger = logging.getLogger(__name__)


async def execute_sweep(
    intent_id: str,
    currency: str,
    chain: str,
) -> None:
    """
    Esegue lo sweep completo per un intent:
      1. Marca intent come "sweeping"
      2. Legge balance on-chain e calcola fee
      3. Sweep 1: net amount al merchant (fail-closed)
      4. Sweep 2: fee al treasury (fail-open)
      5. Marca intent come "settled"

    Idempotente: se l'intent e' gia' settled o sweeping, non fa nulla.
    """
    from app.services.sweep_service import (
        acquire_sweep_lock,
        release_sweep_lock,
        start_sweep_heartbeat,
        stop_sweep_heartbeat,
    )

    from app.services.kill_switch import kill_switch

    allowed, reason = await kill_switch.can_execute()
    if not allowed:
        logger.warning("Sweep blocked by kill switch: intent=%s reason=%s", intent_id, reason)
        return

    lock_key = f"deposit:{intent_id}"
    if not await acquire_sweep_lock(lock_key, ttl=300):
        logger.info("Sweep already in progress for intent %s, skipping", intent_id)
        return

    heartbeat = start_sweep_heartbeat(lock_key)
    try:
        await _execute_sweep_inner(intent_id, currency, chain)
    finally:
        await stop_sweep_heartbeat(heartbeat)
        await release_sweep_lock(lock_key)


async def _execute_sweep_inner(
    intent_id: str,
    currency: str,
    chain: str,
) -> None:
    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent_id,
                ).with_for_update()
            )
            intent = result.scalar_one_or_none()

            if intent is None:
                logger.error("Deposit sweep: intent %s not found", intent_id)
                return

            if intent.status in (IntentStatus.sweeping, IntentStatus.settled):
                logger.info(
                    "Deposit sweep: intent %s already %s, skipping",
                    intent_id, intent.status.value,
                )
                return

            if intent.status != IntentStatus.completed:
                logger.warning(
                    "Deposit sweep: intent %s status=%s, expected completed — skipping",
                    intent_id, intent.status.value,
                )
                return

            destination = intent.recipient
            if not destination:
                logger.error(
                    "Deposit sweep: intent %s has no recipient address — cannot sweep",
                    intent_id,
                )
                return

            intent.status = IntentStatus.sweeping
            await db.flush()

            await log_event(
                db,
                "DEPOSIT_SWEEP_STARTED",
                "payment_intent",
                intent.intent_id,
                actor_type="system",
                changes={
                    "previous_status": "completed",
                    "new_status": "sweeping",
                    "destination": destination,
                    "currency": currency,
                    "chain": chain,
                },
            )

    # ── Read on-chain balance and calculate fee ─────────
    settings = get_settings()
    try:
        balance_raw = await get_deposit_balance(intent_id, currency, chain)
    except Exception:
        logger.exception("Failed to read deposit balance for intent=%s", intent_id)
        await _revert_to_completed(intent_id, "balance_read_failed")
        return

    if balance_raw == 0:
        async with async_session() as db:
            async with db.begin():
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
                )
                intent = result.scalar_one_or_none()
                if intent and intent.status == IntentStatus.sweeping:
                    intent.status = IntentStatus.completed
        logger.info("Deposit sweep skip: intent=%s balance=0", intent_id)
        return

    fee = calculate_fee(balance_raw)
    decimals = token_decimals(currency)

    # ── Store fee data on intent ────────────────────────
    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )
            intent = result.scalar_one_or_none()
            if intent:
                intent.fee_bps = fee.fee_bps
                intent.fee_amount = str(fee.fee_amount / 10 ** decimals)
                intent.merchant_sweep_amount = str(fee.merchant_amount / 10 ** decimals)

    # ── Sweep 1: net amount to merchant (fail-closed) ───
    merchant_amount = fee.merchant_amount if fee.enabled else None
    try:
        tx_hash = await sweep_deposit(
            intent_id=intent_id,
            destination=destination,
            currency=currency,
            chain=chain,
            amount=merchant_amount,
        )
    except Exception:
        logger.exception("Merchant sweep failed for intent=%s", intent_id)
        await _revert_to_completed(intent_id, "sweep_exception")
        return

    if not tx_hash:
        await _revert_to_completed(intent_id, "sweep_returned_none")
        return

    # ── Mark as settled ─────────────────────────────────
    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )
            intent = result.scalar_one_or_none()
            if intent:
                intent.status = IntentStatus.settled
                intent.sweep_tx_hash = tx_hash
                intent.swept_at = datetime.now(timezone.utc)

                await log_event(
                    db,
                    "DEPOSIT_SWEEP_COMPLETED",
                    "payment_intent",
                    intent_id,
                    actor_type="system",
                    changes={
                        "previous_status": "sweeping",
                        "new_status": "settled",
                        "sweep_tx_hash": tx_hash,
                        "destination": destination,
                        "merchant_amount": str(fee.merchant_amount),
                        "fee_amount": str(fee.fee_amount),
                        "fee_bps": fee.fee_bps,
                    },
                )

    logger.info("Merchant sweep settled: intent=%s tx=%s", intent_id, tx_hash)

    # ── Sweep 2: fee to RSends treasury (fail-open) ─────
    treasury = settings.platform_treasury_address
    if fee.enabled and fee.fee_amount > 0 and treasury:
        try:
            fee_tx = await sweep_deposit(
                intent_id=intent_id,
                destination=treasury,
                currency=currency,
                chain=chain,
                amount=fee.fee_amount,
            )
            if fee_tx:
                async with async_session() as db:
                    async with db.begin():
                        result = await db.execute(
                            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
                        )
                        intent = result.scalar_one_or_none()
                        if intent:
                            intent.fee_tx_hash = fee_tx
                            intent.fee_swept_at = datetime.now(timezone.utc)

                            await log_event(
                                db,
                                "PLATFORM_FEE_COLLECTED",
                                "payment_intent",
                                intent_id,
                                actor_type="system",
                                changes={
                                    "treasury": treasury,
                                    "fee_amount": str(fee.fee_amount),
                                    "fee_bps": fee.fee_bps,
                                    "tx_hash": fee_tx,
                                },
                            )

                logger.info(
                    "Platform fee collected: %s raw units (%d bps) from intent %s → %s tx=%s",
                    fee.fee_amount, fee.fee_bps, intent_id, treasury, fee_tx,
                )
        except Exception:
            logger.exception(
                "Fee sweep failed for %s — merchant sweep succeeded, fee pending",
                intent_id,
            )
            async with async_session() as db:
                async with db.begin():
                    await log_event(
                        db,
                        "PLATFORM_FEE_FAILED",
                        "payment_intent",
                        intent_id,
                        actor_type="system",
                        changes={
                            "fee_amount": str(fee.fee_amount),
                            "reason": "sweep_exception",
                        },
                    )
    elif fee.enabled and fee.fee_amount > 0 and not treasury:
        logger.warning(
            "No PLATFORM_TREASURY_ADDRESS configured — fee not collected for %s",
            intent_id,
        )


async def _revert_to_completed(intent_id: str, reason: str) -> None:
    """Revert intent status to completed for retry."""
    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )
            intent = result.scalar_one_or_none()
            if intent and intent.status == IntentStatus.sweeping:
                intent.status = IntentStatus.completed
                await log_event(
                    db,
                    "DEPOSIT_SWEEP_FAILED",
                    "payment_intent",
                    intent_id,
                    actor_type="system",
                    changes={"reverted_status": "completed", "reason": reason},
                )
