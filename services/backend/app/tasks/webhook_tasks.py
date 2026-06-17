"""
RSend Backend — Celery Tasks for Webhook Delivery & Intent Expiration.

Tasks:
  process_webhook_deliveries  — every 15s  — retry pending deliveries
  expire_pending_intents      — every 60s  — expire stale PaymentIntents + webhook

Fallback: se Celery non e' disponibile (dev mode), usa asyncio background tasks
registrati nel lifespan di FastAPI (vedi main.py).
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.celery_app import celery

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════
#  process_webhook_deliveries — every 15 seconds
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.webhook_tasks.process_webhook_deliveries")
def process_webhook_deliveries() -> dict:
    """
    Processa tutte le WebhookDelivery pending il cui next_retry_at e' passato.

    Chiamato ogni 15s da Celery beat.
    Per ogni delivery:
      - POST al webhook URL con HMAC signature
      - Se 2xx → delivered
      - Altrimenti → retry con backoff (30s, 2m, 8m, 32m, 2h)
      - Max 5 tentativi, poi failed
      - Ogni tentativo loggato con attempt_number, status_code, response_body
    """
    return _run_async(_process_webhook_deliveries_async())


async def _process_webhook_deliveries_async() -> dict:
    from app.db.session import async_session
    from app.services.webhook_service import process_pending_deliveries

    async with async_session() as session:
        async with session.begin():
            processed = await process_pending_deliveries(session)

    return {"processed": processed}


# ═══════════════════════════════════════════════════════════════
#  expire_pending_intents — every 60 seconds
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.webhook_tasks.expire_pending_intents")
def expire_pending_intents() -> dict:
    """
    Trova tutti i PaymentIntent con status=pending e expires_at < now().
    Li aggiorna a status=expired e triggera webhook "payment.expired".

    Chiamato ogni 60s da Celery beat.
    """
    return _run_async(_expire_pending_intents_async())


async def _expire_pending_intents_async() -> dict:
    from app.db.session import async_session
    from app.services.webhook_service import expire_stale_intents, send_webhook
    from app.models.merchant_models import PaymentIntent, IntentStatus
    from sqlalchemy import select, and_
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    async with async_session() as session:
        async with session.begin():
            # Trova intent pendenti scaduti
            result = await session.execute(
                select(PaymentIntent).where(
                    and_(
                        PaymentIntent.status == IntentStatus.pending,
                        PaymentIntent.expires_at <= now,
                    )
                )
            )
            expired_intents = result.scalars().all()

            expired_count = 0
            webhook_count = 0

            for intent in expired_intents:
                intent.status = IntentStatus.expired
                expired_count += 1

                # Triggera webhook "payment.expired" via send_webhook
                try:
                    sent = await send_webhook(
                        session,
                        merchant_id=intent.merchant_id,
                        event="payment.expired",
                        intent=intent,
                    )
                    webhook_count += sent
                except Exception:
                    logger.exception(
                        "Failed to send expiration webhook for intent %s",
                        intent.intent_id,
                    )

                # Notify checkout WebSocket clients
                try:
                    from app.api.payment_ws import notify_payment_expired
                    await notify_payment_expired(intent.intent_id)
                except Exception:
                    pass  # WS notification is best-effort

            if expired_count:
                logger.info(
                    "Expired %d stale intents, triggered %d webhooks",
                    expired_count, webhook_count,
                )

    return {"expired": expired_count, "webhooks_triggered": webhook_count}


# ═══════════════════════════════════════════════════════════════
#  Asyncio fallback — per dev senza Celery
# ═══════════════════════════════════════════════════════════════

async def webhook_delivery_loop(interval: float = 15.0) -> None:
    """
    Background loop asyncio: processa pending deliveries ogni `interval` secondi.
    Usato come fallback quando Celery non e' disponibile.
    Registrato nel lifespan di FastAPI.
    """
    logger.info("Webhook delivery loop started (interval=%.0fs, asyncio fallback)", interval)
    while True:
        try:
            result = await _process_webhook_deliveries_async()
            if result.get("processed", 0) > 0:
                logger.debug("Webhook delivery loop: processed %d", result["processed"])
        except Exception:
            logger.exception("Webhook delivery loop error")
        await asyncio.sleep(interval)


async def intent_expiration_loop(interval: float = 60.0) -> None:
    """
    Background loop asyncio: scade intent pending ogni `interval` secondi.
    Usato come fallback quando Celery non e' disponibile.
    Registrato nel lifespan di FastAPI.
    """
    logger.info("Intent expiration loop started (interval=%.0fs, asyncio fallback)", interval)
    while True:
        try:
            result = await _expire_pending_intents_async()
            expired = result.get("expired", 0)
            if expired > 0:
                logger.info("Expiration loop: expired %d intents", expired)
        except Exception:
            logger.exception("Intent expiration loop error")
        await asyncio.sleep(interval)
