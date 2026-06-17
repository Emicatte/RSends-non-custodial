"""
RSend Backend — Celery Matching Tasks.

Task:
  match_transaction_task(tx_id, tx_hash, recipient, amount, currency)
    — Load TX from DB, run transaction matcher, update intent + webhook.
    — Retry: 3 attempts with backoff 5s, 30s, 2min on DB errors.
"""

import asyncio
import logging

from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    name="app.tasks.matching_tasks.match_transaction_task",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def match_transaction_task(
    self,
    tx_id: int,
    tx_hash: str,
    recipient: str,
    gross_amount: float,
    currency: str,
) -> dict:
    """
    Esegue il transaction matching in background.

    Carica la TX dal DB, cerca un PaymentIntent corrispondente,
    e se trovato aggiorna lo stato e triggera il webhook.

    Retry policy: 5s → 30s → 120s su errori DB/transitori.
    """
    try:
        result = asyncio.run(
            _do_match(tx_id, tx_hash, recipient, gross_amount, currency)
        )
        return result
    except Exception as exc:
        retry_delays = [5, 30, 120]
        retry_idx = min(self.request.retries, len(retry_delays) - 1)
        countdown = retry_delays[retry_idx]

        logger.warning(
            "match_transaction_task failed for tx_id=%s (attempt %d/%d), "
            "retrying in %ds: %s",
            tx_id, self.request.retries + 1, self.max_retries + 1,
            countdown, exc,
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _do_match(
    tx_id: int,
    tx_hash: str,
    recipient: str,
    gross_amount: float,
    currency: str,
) -> dict:
    """Async matching logic — runs inside Celery worker via asyncio.run()."""
    from sqlalchemy import select

    from app.db.session import async_session
    from app.models.db_models import TransactionLog
    from app.services.transaction_matcher import match_transaction, IncomingTx

    async with async_session() as db:
        async with db.begin():
            # Verifica che la TX esista ancora
            result = await db.execute(
                select(TransactionLog).where(TransactionLog.id == tx_id)
            )
            tx = result.scalar_one_or_none()
            if tx is None:
                logger.error("TX id=%s not found in DB — skipping match", tx_id)
                return {"matched": False, "reason": "tx_not_found"}

            # Esegui il matching
            match_result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=tx_hash,
                    recipient=recipient,
                    amount=gross_amount,
                    currency=currency,
                ),
            )

            if match_result.matched:
                logger.info(
                    "Async match: tx=%s → intent=%s (webhook=%s)",
                    tx_hash[:16], match_result.intent_id,
                    match_result.webhook_triggered,
                )
            else:
                logger.debug(
                    "Async match: tx=%s no match, reason=%s",
                    tx_hash[:16], match_result.reason,
                )

            return {
                "matched": match_result.matched,
                "intent_id": match_result.intent_id,
                "reason": match_result.reason,
                "webhook_triggered": match_result.webhook_triggered,
            }
