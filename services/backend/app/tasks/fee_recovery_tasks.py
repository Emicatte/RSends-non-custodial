"""
Fee-recovery periodic task.

Closes the fee-leg crash hole on the custodial #4 path: when the platform-fee
sweep crashes AFTER the intent is marked ``settled`` (fail-open), the normal
orchestrator never retries it (it short-circuits on ``settled``), so the fee can
sit uncollected. This Celery-beat job finds those settlements and completes the
fee leg through the SAME guarded ``sweep_deposit`` path.

Idempotent by construction:
  - The fee leg uses key ``deposit_sweep:{intent_id}:fee`` with its persisted /
    N+1 nonce. A ``confirmed`` row makes the guard reconcile-and-skip; running
    the job twice never double-collects.
  - The fee AMOUNT is read from the intent record (``intent.fee_amount``), never
    recomputed, so the recovered tx matches what settlement intended.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.celery_app import celery

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task (mirrors periodic_tasks)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery.task(name="app.tasks.fee_recovery_tasks.recover_pending_fees")
def recover_pending_fees() -> dict:
    """Find settled intents that still owe an uncollected platform fee and
    complete the fee leg idempotently."""
    return _run_async(_recover_pending_fees_async())


async def _recover_pending_fees_async() -> dict:
    from sqlalchemy import select
    from app.config import get_settings
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus
    from app.services.platform_fee_service import token_decimals
    from app.services.tx_intent_guard import (
        get_intent_nonce,
        get_intent_state,
        NEEDS_REVIEW_PREFIX,
    )
    from app.services.deposit_address_service import sweep_deposit
    from app.services.audit_service import log_event

    settings = get_settings()
    treasury = settings.platform_treasury_address
    recovered = 0
    held = 0
    scanned = 0

    if not treasury:
        logger.warning("Fee recovery: no PLATFORM_TREASURY_ADDRESS configured")
        return {"recovered": 0, "held": 0, "scanned": 0, "reason": "no_treasury"}

    # Target set: settled, owes a fee, fee not yet collected.
    async with async_session() as db:
        intents = (await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.status == IntentStatus.settled,
                PaymentIntent.fee_amount.isnot(None),
                PaymentIntent.fee_amount != "0",
                PaymentIntent.fee_tx_hash.is_(None),
            )
        )).scalars().all()

    for intent in intents:
        scanned += 1
        intent_id = intent.intent_id
        fee_key = f"deposit_sweep:{intent_id}:fee"

        # Skip self-unhealable rows: a reverted fee burned its nonce (retrying
        # would only hit 'nonce too low'); an ambiguous one needs manual review.
        f_status, f_err, _ = await get_intent_state(fee_key)
        if f_status == "failed" or (f_err or "").startswith(NEEDS_REVIEW_PREFIX):
            held += 1
            logger.error(
                "Fee recovery: intent=%s not self-healing (state=%s err=%s) — skipping",
                intent_id, f_status, f_err,
            )
            continue

        # Reconstruct the fee leg IDENTICALLY: amount from the record (not
        # recomputed), treasury destination, fee nonce = persisted or merchant+1.
        try:
            decimals = token_decimals(intent.currency)
            fee_raw = int((Decimal(intent.fee_amount) * (Decimal(10) ** decimals)).to_integral_value())
        except Exception:
            logger.exception("Fee recovery: bad fee_amount for intent=%s", intent_id)
            continue
        if fee_raw <= 0:
            continue

        fee_nonce = await get_intent_nonce(fee_key)
        if fee_nonce is None:
            merchant_nonce = await get_intent_nonce(f"deposit_sweep:{intent_id}:merchant")
            if merchant_nonce is None:
                # Can't sequence safely without the merchant nonce anchor.
                held += 1
                logger.error("Fee recovery: intent=%s missing merchant nonce — skipping", intent_id)
                continue
            fee_nonce = merchant_nonce + 1

        try:
            fee_tx = await sweep_deposit(
                intent_id=intent_id,
                destination=treasury,
                currency=intent.currency,
                chain=intent.chain,
                amount=fee_raw,
                leg="fee",
                nonce=fee_nonce,
            )
        except Exception:
            logger.exception("Fee recovery: sweep failed for intent=%s", intent_id)
            continue

        if not fee_tx:
            # pending / reverted / needs_review — not collected this round.
            held += 1
            continue

        async with async_session() as db:
            async with db.begin():
                row = (await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
                )).scalar_one_or_none()
                if row and row.fee_tx_hash is None:
                    row.fee_tx_hash = fee_tx
                    row.fee_swept_at = datetime.now(timezone.utc)
                    await log_event(
                        db, "PLATFORM_FEE_RECOVERED", "payment_intent", intent_id,
                        actor_type="system",
                        changes={"treasury": treasury, "fee_amount": intent.fee_amount,
                                 "tx_hash": fee_tx},
                    )
        recovered += 1
        logger.info("Fee recovery: collected fee for intent=%s tx=%s", intent_id, fee_tx)

    if scanned:
        logger.info("Fee recovery: scanned=%d recovered=%d held=%d", scanned, recovered, held)
    return {"recovered": recovered, "held": held, "scanned": scanned}
