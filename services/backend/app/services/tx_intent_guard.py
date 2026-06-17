"""Broadcast-idempotency guard.

Closes the crash-after-broadcast-before-commit window for on-chain sweeps.

The Redis SETNX lock (``acquire_sweep_lock``) guards concurrent *entry* but NOT
a crash between ``send_raw_transaction`` and the DB commit — on retry the old
code would re-sign and re-broadcast, risking an irreversible double spend.

This module adds an orthogonal, crash-safe guard keyed on the broadcast itself:

  1. ``claim_or_reconcile`` atomically INSERTs a ``TxIntent`` row
     (UNIQUE(idempotency_key)) with status ``broadcasting`` BEFORE the caller
     broadcasts. The UNIQUE constraint makes the claim atomic across workers and
     across process restarts — something an in-memory/Redis lock cannot survive.
  2. If the row already exists, we NEVER re-broadcast. We reconcile against the
     chain by nonce: if a transaction already occupies the reserved nonce, the
     prior broadcast landed → treat as sent. Only when the chain *proves* the
     nonce is still unused do we allow a fresh claim and a (first) broadcast.

Additive: no existing flow depends on this to function. Reuses ``async_session``
and the caller's existing RPC/web3 client for chain reads.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session
from app.models.command_models import TxIntent

logger = logging.getLogger(__name__)

# A 'broadcasting' claim younger than this is assumed to belong to a concurrent
# in-flight attempt and is NEVER stolen (would risk a double broadcast). Only an
# older claim — left behind by a crashed run that the chain proves never sent —
# is reclaimed. Comfortably longer than any single sign+broadcast attempt.
RECLAIM_STALE_AFTER_S = 120

# A reconcile callback receives the existing (broadcasting) TxIntent row and
# returns a verdict dict derived from the chain:
#   {"status": "completed", "tx_hash": <hash or None>}  → already on-chain
#   {"status": "not_sent"}                              → provably never sent
ReconcileFn = Callable[[TxIntent], Awaitable[dict]]

_MAX_CLAIM_ATTEMPTS = 3


async def claim_or_reconcile(
    key: str,
    *,
    site: str,
    chain_id: int,
    from_addr: str,
    nonce: int | None,
    reconcile_fn: ReconcileFn,
    tx_hash: str | None = None,
) -> tuple[str, dict | None]:
    """Atomically claim the right to broadcast for ``key``.

    ``tx_hash`` (the hash of the just-signed tx this call will broadcast) is
    persisted in the ``broadcasting`` row BEFORE the send, enabling hash-aware
    reconcile on retry. It is written on every (re-)INSERT inside the loop, so a
    stale-reclaim re-INSERT records THIS call's freshly-signed hash — never an
    older attempt's. When omitted (sites not wired for hash-persist), reconcile
    falls back to count-only behaviour.

    Returns:
      ("proceed", None)        → caller OWNS the broadcast; go ahead and send.
      ("already", verdict)     → a prior attempt already (maybe) broadcast;
                                 ``verdict["status"]`` is one of
                                 completed | reverted | pending | needs_review.
                                 Caller MUST NOT re-broadcast.
    """
    for _attempt in range(_MAX_CLAIM_ATTEMPTS):
        # ── Atomic claim: INSERT or UNIQUE-violation ──────────────────
        async with async_session() as db:
            db.add(
                TxIntent(
                    idempotency_key=key,
                    site=site,
                    chain_id=chain_id,
                    from_address=from_addr,
                    nonce=nonce,
                    status="broadcasting",
                    tx_hash=tx_hash,
                )
            )
            try:
                await db.commit()
                return ("proceed", None)  # we hold the claim
            except IntegrityError:
                await db.rollback()  # someone else claimed first

        # ── A row already exists — decide WITHOUT re-broadcasting ─────
        async with async_session() as db:
            row = (
                await db.execute(
                    select(TxIntent).where(TxIntent.idempotency_key == key)
                )
            ).scalar_one_or_none()

        if row is None:
            continue  # raced with a delete; retry the claim

        if row.status == "confirmed":
            return ("already", {"status": "completed", "tx_hash": row.tx_hash})

        if row.status == "failed":
            # A prior attempt failed BEFORE any send (see mark_failed). Safe to
            # reclaim: delete and loop. The UNIQUE re-insert serializes racers.
            async with async_session() as db:
                await db.execute(
                    delete(TxIntent).where(
                        TxIntent.idempotency_key == key,
                        TxIntent.status == "failed",
                    )
                )
                await db.commit()
            continue

        # status == "broadcasting": a broadcast MAY already be on-chain. Never
        # re-broadcast — ask the chain. Hash-aware when a tx_hash was persisted,
        # else count-only (legacy fallback). reconcile returns one of:
        # completed | reverted | pending | needs_review | not_sent.
        verdict = await reconcile_fn(row)
        vstatus = verdict.get("status")

        if vstatus == "completed":
            # Mined OK → persist what we learned, do NOT re-broadcast.
            await mark_confirmed(key, verdict.get("tx_hash"))
            return ("already", verdict)

        if vstatus == "reverted":
            # Our tx mined but FAILED on-chain (receipt status=0). The nonce is
            # burned, so reclaiming would only hit 'nonce too low'. Mark failed
            # and let the caller refuse to settle.
            await mark_failed(key, "reverted on-chain (receipt status=0)")
            return ("already", verdict)

        if vstatus == "needs_review":
            # Nonce consumed but OUR hash is absent from the network — ambiguous.
            # Hold: never complete, never reclaim/resend. Flag for manual review.
            await _mark_needs_review(
                key, verdict.get("reason", "nonce consumed but our tx hash absent")
            )
            logger.error(
                "tx_intent %s NEEDS REVIEW — nonce consumed but our tx hash absent; "
                "holding (no complete, no resend)", key,
            )
            return ("already", verdict)

        if vstatus == "pending":
            # Our tx is in the mempool, not yet mined → back off, do not resend.
            return ("already", verdict)

        # vstatus == "not_sent": the chain proves the nonce is unused.
        if not _is_stale(row):
            # Fresh claim → a concurrent attempt likely holds it and is
            # mid-broadcast. Back off WITHOUT broadcasting (never steal).
            logger.warning(
                "tx_intent %s held by a concurrent in-flight broadcast — "
                "backing off (no re-broadcast)",
                key,
            )
            return ("already", {"status": "pending", "tx_hash": None})
        # Stale claim from a crashed run that the chain proves never sent →
        # drop it and loop to re-claim + (first) broadcast.
        async with async_session() as db:
            await db.execute(
                delete(TxIntent).where(
                    TxIntent.idempotency_key == key,
                    TxIntent.status == "broadcasting",
                )
            )
            await db.commit()
        logger.info(
            "tx_intent %s stale + reconciled not_sent — reclaiming for broadcast",
            key,
        )
        continue

    # Exhausted attempts (pathological contention) — fail closed, do not send.
    raise RuntimeError(f"tx_intent claim contention for key={key}")


def _is_stale(row: TxIntent) -> bool:
    """True if a 'broadcasting' claim is old enough to belong to a crashed run
    rather than a live concurrent attempt."""
    created = row.created_at
    if created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() >= RECLAIM_STALE_AFTER_S


async def get_intent_nonce(key: str) -> int | None:
    """Return the nonce persisted on an intent's TxIntent row, or None if absent.

    Lets the sweep orchestrator reuse a leg's already-reserved nonce on retry
    (instead of re-deriving it) so a crash between legs never shifts a nonce.
    """
    async with async_session() as db:
        return (
            await db.execute(
                select(TxIntent.nonce).where(TxIntent.idempotency_key == key)
            )
        ).scalar_one_or_none()


async def mark_confirmed(key: str, tx_hash: str | None, *, raw_tx: str | None = None) -> None:
    """Mark a claimed intent as broadcast+committed.

    Idempotent: a no-op if the row is already confirmed.
    """
    async with async_session() as db:
        await db.execute(
            update(TxIntent)
            .where(TxIntent.idempotency_key == key)
            .values(status="confirmed", tx_hash=tx_hash, raw_tx=raw_tx)
        )
        await db.commit()


NEEDS_REVIEW_PREFIX = "NEEDS_REVIEW: "


async def _mark_needs_review(key: str, reason: str) -> None:
    """Flag an ambiguous claim for manual reconciliation WITHOUT changing its
    status (stays ``broadcasting`` so it is never reclaimed/resent). The marker
    lives in ``error_message`` (no new enum value → no migration); the
    orchestrator detects it via ``get_intent_state`` and holds settlement."""
    async with async_session() as db:
        await db.execute(
            update(TxIntent)
            .where(TxIntent.idempotency_key == key)
            .values(error_message=(NEEDS_REVIEW_PREFIX + str(reason))[:2000])
        )
        await db.commit()


async def get_intent_state(key: str) -> tuple[str | None, str | None, str | None]:
    """Return (status, error_message, tx_hash) for an intent row, or (None,…) if
    absent. Lets the orchestrator resolve the three-state outcome of a leg whose
    sweep_deposit returned no hash: failed→reverted, NEEDS_REVIEW marker→hold,
    plain broadcasting→pending."""
    async with async_session() as db:
        row = (
            await db.execute(
                select(TxIntent.status, TxIntent.error_message, TxIntent.tx_hash)
                .where(TxIntent.idempotency_key == key)
            )
        ).first()
    if row is None:
        return (None, None, None)
    return (row[0], row[1], row[2])


async def mark_failed(key: str, error_message: str) -> None:
    """Mark a claim as failed BEFORE any broadcast was attempted.

    ONLY call this when it is certain ``send_raw_transaction`` was never invoked
    (e.g. a pre-send error after the claim). If the broadcast itself raised, do
    NOT call this — leave the row ``broadcasting`` so a retry reconciles against
    the chain instead of risking a second send.
    """
    async with async_session() as db:
        await db.execute(
            update(TxIntent)
            .where(TxIntent.idempotency_key == key)
            .values(status="failed", error_message=str(error_message)[:2000])
        )
        await db.commit()


# ──────────────────────────────────────────────────────────────────────────
#  Reconciliation helpers.
#
#  HASH-AWARE (when row.tx_hash is set — wired for #4): reconcile by receipt of
#  OUR exact tx:
#    receipt status=1            → completed
#    receipt status=0            → reverted
#    no receipt, tx in mempool   → pending
#    hash unknown to network:
#        nonce free              → not_sent (safe to (re)broadcast @ same nonce)
#        nonce consumed          → needs_review (our tx absent — NEVER complete)
#  This is STRICTLY MORE conservative than count-only: rebroadcast now requires
#  (nonce free) AND (hash unknown), and the old count>nonce false-complete
#  becomes needs_review.
#
#  COUNT-ONLY fallback (row.tx_hash is None — legacy / sites #2/#3/#5): a tx
#  occupying the reserved nonce (pending count > nonce) ⇒ completed, else
#  not_sent. Unchanged behaviour.
# ──────────────────────────────────────────────────────────────────────────

def _receipt_ok(status) -> bool:
    """True if a receipt indicates success. Handles hex ('0x1'), int (1), and
    pre-Byzantium (None ⇒ assume success)."""
    if status is None:
        return True
    if isinstance(status, int):
        return status == 1
    return int(str(status), 16) == 1


async def reconcile_via_rpc(rpc, from_addr: str, row: TxIntent) -> dict:
    """Reconcile using an RpcManager (consensus_call). For execute_single_sweep."""
    if row.tx_hash:
        receipt = await rpc.consensus_call("eth_getTransactionReceipt", [row.tx_hash])
        if receipt is not None:
            ok = _receipt_ok(receipt.get("status"))
            return {"status": "completed" if ok else "reverted", "tx_hash": row.tx_hash}
        tx = await rpc.consensus_call("eth_getTransactionByHash", [row.tx_hash])
        if tx is not None:
            return {"status": "pending", "tx_hash": row.tx_hash}
        # hash unknown to the network → consult the nonce
        if row.nonce is None:
            return {"status": "not_sent"}
        count = int(await rpc.consensus_call(
            "eth_getTransactionCount", [from_addr, "pending"]), 16)
        if count > row.nonce:
            return {"status": "needs_review",
                    "reason": "nonce consumed but our tx hash unknown to network",
                    "tx_hash": row.tx_hash}
        return {"status": "not_sent"}

    # ── count-only fallback (no persisted hash) ──
    if row.nonce is None:
        return {"status": "not_sent"}
    count = int(await rpc.consensus_call(
        "eth_getTransactionCount", [from_addr, "pending"]), 16)
    if count > row.nonce:
        return {"status": "completed", "tx_hash": row.tx_hash}
    return {"status": "not_sent"}


async def reconcile_via_web3(w3, from_addr: str, row: TxIntent) -> dict:
    """Reconcile using a raw web3 client. For sweep_deposit."""
    import asyncio

    def _not_found_to_none(call):
        # web3.py raises TransactionNotFound for unmined/unknown hashes; treat as
        # absent. Matched by class name to avoid importing web3.exceptions.
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "TransactionNotFound":
                return None
            raise

    if row.tx_hash:
        receipt = await asyncio.to_thread(
            _not_found_to_none, lambda: w3.eth.get_transaction_receipt(row.tx_hash)
        )
        if receipt is not None:
            ok = _receipt_ok(receipt.get("status"))
            return {"status": "completed" if ok else "reverted", "tx_hash": row.tx_hash}
        tx = await asyncio.to_thread(
            _not_found_to_none, lambda: w3.eth.get_transaction(row.tx_hash)
        )
        if tx is not None:
            return {"status": "pending", "tx_hash": row.tx_hash}
        if row.nonce is None:
            return {"status": "not_sent"}
        count = await asyncio.to_thread(
            w3.eth.get_transaction_count, from_addr, "pending")
        if count > row.nonce:
            return {"status": "needs_review",
                    "reason": "nonce consumed but our tx hash unknown to network",
                    "tx_hash": row.tx_hash}
        return {"status": "not_sent"}

    # ── count-only fallback (no persisted hash) ──
    if row.nonce is None:
        return {"status": "not_sent"}
    count = await asyncio.to_thread(
        w3.eth.get_transaction_count, from_addr, "pending")
    if count > row.nonce:
        return {"status": "completed", "tx_hash": row.tx_hash}
    return {"status": "not_sent"}
