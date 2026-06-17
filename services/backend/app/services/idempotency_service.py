"""
RSends Backend — Idempotency Service.

Due livelli di idempotency:

1. WEBHOOK DEDUP (Redis SETNX) — previeni doppia esecuzione di webhook Alchemy.
   REGOLA: Se Redis è down, il webhook viene RIFIUTATO (fail-closed).
   Meglio perdere un webhook (Alchemy lo re-invia) che eseguire un doppio pagamento.

2. TRANSACTION DEDUP (DB) — previeni doppia esecuzione di transazioni ledger.
   - Se la chiave non esiste → None (procedi con l'operazione)
   - Se esiste e status COMPLETED → restituisce la Transaction (skip riesecuzione)
   - Se esiste e status PENDING/PROCESSING → solleva ConflictError (409)
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_models import Transaction

logger = logging.getLogger("idempotency")

# TTL di 2 ore: Alchemy non re-invia dopo 1h, ma teniamo margine
WEBHOOK_DEDUP_TTL = 7200


# ═══════════════════════════════════════════════════════════════
#  1. Webhook Dedup (Redis — fail-closed)
# ═══════════════════════════════════════════════════════════════


async def check_and_mark(webhook_id: str, tx_hash: str = "") -> tuple:
    """
    Verifica se questo webhook è già stato processato.
    Retries once (100ms delay) on transient Redis failures before rejecting.

    Returns:
        (is_new: bool, reason: str):
        - (True, "new") → webhook nuovo, deve essere processato
        - (False, "duplicate") → già processato, skip
        - (False, "redis_unavailable") → Redis down, rifiuta (fail-closed)
        - (False, "redis_error") → errore Redis, rifiuta (fail-closed)
    """
    from app.services.cache_service import get_redis

    # Componi dedup key: combina webhook_id e tx_hash per sicurezza
    dedup_key = f"wh:idem:{webhook_id}" + (f":{tx_hash}" if tx_hash else "")

    for attempt in range(2):  # max 2 attempts (original + 1 retry)
        r = await get_redis()
        if r is None:
            if attempt == 0:
                await asyncio.sleep(0.1)  # 100ms retry on transient unavailability
                continue
            # Redis down → RIFIUTA il webhook (fail-closed)
            # Alchemy lo re-invierà, e quando Redis torna su, lo processeremo
            logger.warning(
                "Redis unavailable — rejecting webhook %s for safety (will be retried by Alchemy)",
                webhook_id[:12],
            )
            return False, "redis_unavailable"

        try:
            # SETNX atomico: se la key non esiste, la crea e ritorna True
            is_new = await r.set(dedup_key, "1", nx=True, ex=WEBHOOK_DEDUP_TTL)
            if not is_new:
                logger.info("Duplicate webhook detected: %s (tx: %s)", webhook_id[:12], tx_hash[:16] if tx_hash else "n/a")
                return False, "duplicate"
            return True, "new"
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(0.1)  # 100ms retry on transient error
                continue
            logger.error("Idempotency check failed: %s — rejecting for safety", e)
            return False, "redis_error"

    return False, "redis_unavailable"  # unreachable safety fallback


async def is_tx_processed(tx_hash: str) -> bool:
    """Check if a TX hash has already been processed (for polling fallback)."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        return False
    try:
        return bool(await r.exists(f"wh:idem:poll:{tx_hash}"))
    except Exception:
        return False


async def mark_tx_processed(tx_hash: str) -> None:
    """Mark a TX hash as processed (for polling fallback)."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        return
    try:
        await r.set(f"wh:idem:poll:{tx_hash}", "1", ex=WEBHOOK_DEDUP_TTL)
    except Exception:
        pass


async def claim_tx_processed(tx_hash: str) -> tuple[bool, str]:
    """Atomically claim a TX hash for processing (poll-fallback dedup).

    Replaces the non-atomic is_tx_processed()+mark_tx_processed() pair, whose
    read-then-write left a TOCTOU window where two concurrent deliveries of the
    same tx_hash could both proceed. A single SETNX makes exactly one caller win.

    Returns (claimed, reason):
      (True,  "new")               → first to claim — proceed.
      (False, "duplicate")         → already claimed/processed — skip.
      (False, "redis_unavailable") → Redis down — skip (fail-closed; the
                                     webhook is re-delivered / re-polled later).
    """
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        return False, "redis_unavailable"
    try:
        is_new = await r.set(f"wh:idem:poll:{tx_hash}", "1", nx=True, ex=WEBHOOK_DEDUP_TTL)
        return (True, "new") if is_new else (False, "duplicate")
    except Exception as e:
        logger.error("claim_tx_processed failed: %s — skipping for safety", e)
        return False, "redis_error"


# ═══════════════════════════════════════════════════════════════
#  2. Transaction Dedup (DB)
# ═══════════════════════════════════════════════════════════════


class ConflictError(Exception):
    """La transazione con questa idempotency_key è già in corso."""

    def __init__(self, transaction: Transaction):
        self.transaction = transaction
        super().__init__(
            f"Transaction {transaction.id} is already {transaction.status}"
        )


async def check_idempotency(
    session: AsyncSession,
    key: str,
) -> Optional[Transaction]:
    """Controlla se esiste già una transazione con questa idempotency_key.

    Returns:
        None se la chiave non esiste (procedi).
        Transaction se lo status è COMPLETED (restituisci il risultato).

    Raises:
        ConflictError se lo status è PENDING, AUTHORIZED, o PROCESSING.
    """
    result = await session.execute(
        select(Transaction).where(Transaction.idempotency_key == key)
    )
    tx = result.scalar_one_or_none()

    if tx is None:
        return None

    if tx.status == "COMPLETED":
        return tx

    if tx.status in ("PENDING", "AUTHORIZED", "PROCESSING"):
        raise ConflictError(tx)

    # FAILED o REVERSED → tratta come "non esiste", permetti retry
    return None
