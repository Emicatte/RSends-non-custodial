"""
RSends Backend — Celery Sweep Tasks.

Tasks:
  process_incoming_tx(payload)     — parse webhook, find rules, create batch,
                                     enqueue execute_distribution.
                                     MUST be FAST (<500ms), no RPC calls.

  execute_distribution(batch_id)   — load batch, pre-flight checks, calculate
                                     distribution, execute, post-execution.
                                     Retry: 3 attempts, 10s/30s/90s backoff.

  confirm_batch(batch_id, tx_hashes) — confirm N TXes in parallel via
                                       asyncio.gather (replaces sequential
                                       confirm_tx per single TX).

  confirm_tx(batch_id, tx_hash)    — wait for receipt, update status.
                                     Kept for individual retries.

  retry_failed_items(batch_id, items) — intelligent retry for failed items.
                                        Classifies errors and applies:
                                        bump_gas, resync_nonce, wait_and_retry.
                                        Max 3 retries per item.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.celery_app import celery

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  TX Error Classification
# ═══════════════════════════════════════════════════════════════

MAX_ITEM_RETRIES = 3

# Error → action mapping for retryable failures.
# Keys are matched case-insensitively against the error message.
RETRYABLE_ERRORS: dict[str, str] = {
    "replacement transaction underpriced": "bump_gas",
    "transaction underpriced": "bump_gas",
    "max fee per gas less than block base fee": "bump_gas",
    "nonce too low": "resync_nonce",
    "nonce has already been used": "resync_nonce",
    "insufficient funds for gas": "wait_and_retry",
    "insufficient funds": "wait_and_retry",
    "already known": "skip",
}

# Errors that should never be retried — the TX is fundamentally broken.
NON_RETRYABLE_ERRORS: set[str] = {
    "execution reverted",
    "gas required exceeds allowance",
    "invalid opcode",
    "out of gas",
    "invalid sender",
    "invalid signature",
}


def classify_tx_error(error_msg: str) -> tuple[str, str]:
    """Classify a TX error into an action.

    Returns:
        (action, matched_pattern) where action is one of:
        'bump_gas', 'resync_nonce', 'wait_and_retry', 'skip', 'fail'.
    """
    error_lower = error_msg.lower()
    for pattern, action in RETRYABLE_ERRORS.items():
        if pattern in error_lower:
            return action, pattern
    for pattern in NON_RETRYABLE_ERRORS:
        if pattern in error_lower:
            return "fail", pattern
    # Unknown errors default to non-retryable
    return "fail", ""


# ═══════════════════════════════════════════════════════════════
#  Helpers — run async code in sync Celery tasks
# ═══════════════════════════════════════════════════════════════

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
#  Task 1: process_incoming_tx
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.sweep_tasks.process_incoming_tx",
    bind=True,
    max_retries=1,
    default_retry_delay=5,
)
def process_incoming_tx(self, payload: dict) -> dict:
    """Parse incoming webhook payload, find matching rules, create batch records.

    This task must be FAST (<500ms). No RPC calls. Database reads only.

    Args:
        payload: Webhook payload with keys:
            - tx_hash (str): incoming transaction hash
            - from_address (str): sender address
            - to_address (str): recipient (our monitored address)
            - value_wei (str): amount in Wei
            - chain_id (int): EVM chain ID
            - token_address (str|None): ERC-20 contract or None for ETH
            - token_symbol (str): "ETH" or token symbol
            - block_number (int): block number

    Returns:
        dict with batch_id and status, or skip reason.
    """
    return _run_async(_process_incoming_tx_async(self, payload))


async def _process_incoming_tx_async(task, payload: dict) -> dict:
    """Async implementation of process_incoming_tx."""
    from sqlalchemy import select
    from app.db.session import async_session
    from app.models.forwarding_models import ForwardingRule
    from app.models.command_models import SweepBatch, SweepBatchItem
    from app.services.audit_service import log_event

    tx_hash = payload.get("tx_hash", "")
    from_address = payload.get("from_address", "")
    to_address = payload.get("to_address", "")
    value_wei = payload.get("value_wei", "0")
    chain_id = payload.get("chain_id", 8453)
    token_address = payload.get("token_address")
    token_symbol = payload.get("token_symbol", "ETH")

    logger.info(
        "Processing incoming TX: hash=%s from=%s to=%s value=%s chain=%d",
        tx_hash, from_address, to_address, value_wei, chain_id,
    )

    async with async_session() as session:
        async with session.begin():
            # ── Idempotency: check if batch already exists for this tx ──
            existing = await session.execute(
                select(SweepBatch).where(
                    SweepBatch.incoming_tx_hash == tx_hash
                )
            )
            if existing.scalar_one_or_none() is not None:
                logger.info("Duplicate TX ignored: %s", tx_hash)
                return {"status": "duplicate", "tx_hash": tx_hash}

            # ── Find matching forwarding rules ──
            query = (
                select(ForwardingRule)
                .where(
                    ForwardingRule.source_wallet == to_address.lower(),
                    ForwardingRule.chain_id == chain_id,
                    ForwardingRule.is_active == True,  # noqa: E712
                    ForwardingRule.is_paused == False,  # noqa: E712
                )
            )
            result = await session.execute(query)
            rules = result.scalars().all()

            if not rules:
                logger.info(
                    "No matching rules for %s on chain %d", to_address, chain_id
                )
                return {"status": "no_rules", "to_address": to_address}

            # ── Filter rules by token and threshold ──
            matched_rules = []
            amount_int = int(value_wei)

            for rule in rules:
                # Token filter: if rule has a token_address, it must match
                if token_address:
                    if rule.token_address and rule.token_address.lower() != token_address.lower():
                        continue
                else:
                    # Native ETH — skip rules that target a specific token
                    if rule.token_address:
                        continue

                # Threshold check (min_threshold is in ETH, convert)
                threshold_wei = int(rule.min_threshold * 10**18)
                if amount_int < threshold_wei:
                    continue

                matched_rules.append(rule)

            if not matched_rules:
                logger.info(
                    "No rules matched filters for TX %s", tx_hash
                )
                return {"status": "filtered_out", "tx_hash": tx_hash}

            # ── Use the first (highest priority) matching rule ──
            rule = matched_rules[0]

            # ── Create SweepBatch record ──
            batch_id = uuid.uuid4()
            batch = SweepBatch(
                id=batch_id,
                incoming_tx_hash=tx_hash,
                source_address=to_address.lower(),
                chain_id=chain_id,
                total_amount_wei=value_wei,
                token_address=token_address,
                token_symbol=token_symbol,
                status="PENDING",
                forwarding_rule_id=rule.id,
                distribution_list_id=rule.distribution_list_id,
                metadata_={
                    "from_address": from_address,
                    "block_number": payload.get("block_number"),
                    "rule_label": rule.label,
                },
            )
            session.add(batch)

            # ── Create batch items from distribution list or single dest ──
            if rule.distribution_list_id and rule.distribution_list:
                dist_list = rule.distribution_list
                active_recipients = [
                    r for r in dist_list.recipients if r.is_active
                ]

                for recipient in active_recipients:
                    # Integer math for Wei distribution
                    item_amount = (amount_int * recipient.percent_bps) // 10000
                    item = SweepBatchItem(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        recipient_address=recipient.address,
                        amount_wei=str(item_amount),
                        percent_bps=recipient.percent_bps,
                        status="PENDING",
                    )
                    session.add(item)
            else:
                # Single destination
                dest = rule.destination_wallet
                if not dest:
                    logger.error(
                        "Rule %d has no destination and no distribution list",
                        rule.id,
                    )
                    return {"status": "error", "reason": "no_destination"}

                # Handle split routing
                if rule.split_enabled and rule.split_destination:
                    primary_bps = rule.split_percent * 100  # percent → bps
                    split_bps = 10000 - primary_bps

                    primary_amount = (amount_int * primary_bps) // 10000
                    split_amount = amount_int - primary_amount

                    session.add(SweepBatchItem(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        recipient_address=dest,
                        amount_wei=str(primary_amount),
                        percent_bps=primary_bps,
                        status="PENDING",
                    ))
                    session.add(SweepBatchItem(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        recipient_address=rule.split_destination,
                        amount_wei=str(split_amount),
                        percent_bps=split_bps,
                        status="PENDING",
                    ))
                else:
                    session.add(SweepBatchItem(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        recipient_address=dest,
                        amount_wei=value_wei,
                        percent_bps=10000,
                        status="PENDING",
                    ))

            # ── Audit log ──
            await log_event(
                session,
                event_type="TX_CREATED",
                entity_type="sweep_batch",
                entity_id=str(batch_id),
                actor_type="system",
                actor_id="process_incoming_tx",
                changes={
                    "incoming_tx_hash": tx_hash,
                    "source": to_address,
                    "amount_wei": value_wei,
                    "rule_id": rule.id,
                },
            )

    # ── Enqueue execution (outside transaction) ──
    execute_distribution.apply_async(
        args=[str(batch_id)],
        countdown=2,  # slight delay for DB commit propagation
    )

    logger.info(
        "Batch created: batch_id=%s tx=%s rule=%d",
        batch_id, tx_hash, rule.id,
    )

    return {
        "status": "queued",
        "batch_id": str(batch_id),
        "rule_id": rule.id,
        "tx_hash": tx_hash,
    }


# ═══════════════════════════════════════════════════════════════
#  Task 2: execute_distribution
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.sweep_tasks.execute_distribution",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=90,
    default_retry_delay=10,
)
def execute_distribution(self, batch_id: str) -> dict:
    """Load batch, run pre-flight checks, execute distribution, post-execution.

    Pre-flight checks:
      1. Circuit breaker (RPC healthy)
      2. Spending policy (multi-tier limits)
      3. Wallet balance (enough for gas + value)
      4. Gas price (within limit)
      5. Rule cooldown (not too frequent)

    Execution:
      - <=5 recipients: sequential ETH transfers
      - >5 recipients: batch (sequential with nonce management)

    Post-execution:
      - Update DB (batch + items)
      - Update spending counters
      - WebSocket notification
      - Telegram alert

    Retry: 3 attempts with 10s/30s/90s backoff.
    """
    return _run_async(_execute_distribution_locked(self, batch_id))


async def _execute_distribution_locked(task, batch_id: str) -> dict:
    """C1 concurrency guard: serialize execution of a batch with a fail-closed
    Redis lock so two concurrent tasks can never both broadcast the same batch.

    The C1b nonce-reuse fix makes a SINGLE task's crash-retry idempotent, but it
    does NOT stop two CONCURRENT runs of the same batch (Celery visibility-timeout
    redelivery, or a webhook + periodic double-fire): each loads items with
    nonce=NULL, each reserves a DISJOINT nonce range, and both broadcast — paying
    every recipient twice. This lock makes only one task own a batch at a time.

    Mirrors the sweep execution-lock pattern
    (sweep_service.acquire_sweep_lock / release_sweep_lock).
    """
    from app.services.sweep_service import (
        acquire_sweep_lock,
        release_sweep_lock,
        start_sweep_heartbeat,
        stop_sweep_heartbeat,
    )

    lock_key = f"distrib_batch:{batch_id}"
    if not await acquire_sweep_lock(lock_key):
        # Concurrent run holds the lock, OR Redis is unreachable (fail-closed):
        # refuse to broadcast. A legitimate retry re-acquires once the holder
        # finishes (release) or the lock TTL expires after a hard crash.
        logger.warning(
            "Batch %s locked or Redis unavailable — skipping execution (fail-closed)",
            batch_id,
        )
        return {"status": "skipped", "reason": "locked"}
    # Renew the lock TTL every 60s while we run: a batch can carry up to
    # MAX_RECIPIENTS (500) items, each a slow on-chain broadcast, so the loop can
    # outlast the 300s TTL — without renewal the lock would lapse mid-loop and admit
    # a second concurrent run. On a hard crash the heartbeat task dies with the
    # process, so the lock still auto-expires within the TTL (never blocks forever).
    heartbeat = start_sweep_heartbeat(lock_key)
    try:
        return await _execute_distribution_async(task, batch_id)
    finally:
        await stop_sweep_heartbeat(heartbeat)
        await release_sweep_lock(lock_key)


async def _execute_distribution_async(task, batch_id: str) -> dict:
    """Async implementation of execute_distribution."""
    from sqlalchemy import select, update
    from app.db.session import async_session
    from app.models.command_models import SweepBatch, SweepBatchItem
    from app.models.forwarding_models import ForwardingRule
    from app.services.circuit_breaker import get_circuit_breaker, CircuitOpenError
    from app.services.spending_policy import get_spending_policy
    from app.services.wallet_manager import get_wallet_manager
    from app.services.nonce_manager import get_nonce_manager
    from app.services.key_manager import get_signer
    from app.services.rpc_manager import get_rpc_manager
    from app.services.audit_service import log_event
    from app.services.cache_service import get_redis

    batch_uuid = uuid.UUID(batch_id)

    # ── Load batch ────────────────────────────────────────
    async with async_session() as session:
        result = await session.execute(
            select(SweepBatch).where(SweepBatch.id == batch_uuid)
        )
        batch = result.scalar_one_or_none()

        if batch is None:
            logger.error("Batch not found: %s", batch_id)
            return {"status": "error", "reason": "batch_not_found"}

        if batch.status not in ("PENDING", "PROCESSING"):
            logger.info("Batch %s already in status %s, skipping", batch_id, batch.status)
            return {"status": "skipped", "reason": f"status={batch.status}"}

        # Load items. C1b: include SIGNING (items that were assigned a nonce
        # before a crash) so a retry reprocesses them reusing the SAME nonce
        # instead of re-broadcasting on a fresh nonce (which double-pays).
        items_result = await session.execute(
            select(SweepBatchItem)
            .where(SweepBatchItem.batch_id == batch_uuid)
            .where(SweepBatchItem.status.in_(("PENDING", "SIGNING")))
        )
        items = items_result.scalars().all()

        if not items:
            logger.info("No pending items in batch %s", batch_id)
            return {"status": "completed", "reason": "no_pending_items"}

        chain_id = batch.chain_id
        source_address = batch.source_address
        total_amount_wei = batch.total_amount_wei

    # ══════════════════════════════════════════════════════
    #  PRE-FLIGHT CHECKS
    # ══════════════════════════════════════════════════════

    # ── 1. Circuit breaker ────────────────────────────────
    rpc_cb = get_circuit_breaker(f"rpc_alchemy_{chain_id}")
    if rpc_cb is None:
        rpc_cb = get_circuit_breaker(f"rpc_base_primary_{chain_id}")

    if rpc_cb is not None:
        try:
            await rpc_cb.check()
        except CircuitOpenError as e:
            logger.warning("Circuit breaker OPEN, deferring batch %s: %s", batch_id, e)
            raise  # will trigger retry

    # ── 2. Spending policy ────────────────────────────────
    policy = get_spending_policy()
    spend_result = await policy.check_and_reserve(
        source=source_address,
        amount_wei=total_amount_wei,
        chain_id=chain_id,
    )
    if not spend_result.allowed:
        logger.warning(
            "Spending policy denied batch %s: %s", batch_id, spend_result.reason,
        )
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(SweepBatch)
                    .where(SweepBatch.id == batch_uuid)
                    .values(
                        status="FAILED",
                        error_message=f"Spending policy: {spend_result.reason}",
                    )
                )
                await log_event(
                    session,
                    event_type="TX_FAILED",
                    entity_type="sweep_batch",
                    entity_id=batch_id,
                    actor_type="system",
                    actor_id="execute_distribution",
                    changes={"reason": spend_result.reason, "tier": spend_result.tier},
                )
        return {"status": "denied", "reason": spend_result.reason}

    spending_reserved = True

    try:
        # ── 3. Wallet balance check ──────────────────────
        wm = get_wallet_manager(chain_id)
        gas_estimate = await wm.estimate_sweep_gas(
            recipient_count=len(items),
            mode="erc20" if batch.token_address else "eth",
        )

        if not await wm.check_hot_sufficient(gas_estimate):
            raise RuntimeError(
                f"Insufficient hot wallet balance for gas ({gas_estimate} wei)"
            )

        # ── 4. Gas price check + replacement detection ────
        rpc = get_rpc_manager(chain_id)
        gas_price_hex = await rpc.call("eth_gasPrice", [])
        gas_price_wei = int(gas_price_hex, 16)
        gas_price_gwei = gas_price_wei / 10**9

        # Check against rule gas limit if available
        if batch.forwarding_rule_id:
            async with async_session() as session:
                rule_result = await session.execute(
                    select(ForwardingRule).where(
                        ForwardingRule.id == batch.forwarding_rule_id
                    )
                )
                rule = rule_result.scalar_one_or_none()
                if rule and gas_price_gwei > rule.gas_limit_gwei:
                    raise RuntimeError(
                        f"Gas price {gas_price_gwei:.1f} gwei > limit "
                        f"{rule.gas_limit_gwei} gwei"
                    )

        # Detect if we're in replacement mode (nonce gap = pending TXes in mempool)
        from app.services.sweep_service import get_bumped_gas_params, _replacement_mode_active
        is_replacement = _replacement_mode_active()
        gas_params = await get_bumped_gas_params(
            chain_id, gas_price_wei, is_replacement=is_replacement,
        )
        if is_replacement:
            logger.warning(
                "Replacement mode active: gas bumped 15%% for chain=%d "
                "base=%d gwei",
                chain_id, gas_price_gwei,
            )

        # ── 5. Cooldown check ─────────────────────────────
        if batch.forwarding_rule_id:
            r = await get_redis()
            cooldown_key = f"cooldown:{chain_id}:{batch.forwarding_rule_id}"
            if await r.exists(cooldown_key):
                raise RuntimeError(
                    f"Rule {batch.forwarding_rule_id} is in cooldown"
                )

        # ══════════════════════════════════════════════════
        #  EXECUTION
        # ══════════════════════════════════════════════════

        # Update batch status to PROCESSING
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(SweepBatch)
                    .where(SweepBatch.id == batch_uuid)
                    .values(
                        status="PROCESSING",
                        gas_price_wei=str(gas_price_wei),
                    )
                )
                await log_event(
                    session,
                    event_type="TX_STATE_CHANGE",
                    entity_type="sweep_batch",
                    entity_id=batch_id,
                    actor_type="system",
                    actor_id="execute_distribution",
                    changes={"from": "PENDING", "to": "PROCESSING"},
                )

        # ── Get nonces and sign transactions ──────────────
        nm = get_nonce_manager(chain_id)
        signer = get_signer()
        hot_address = await signer.get_address()

        # ── Nonce assignment (C1b: idempotent against crash/retry) ──────
        # Reserve nonces ONLY for items that don't already have one, then
        # persist nonce + status='SIGNING' in ONE commit BEFORE broadcasting.
        # On a retry, items keep their original nonce (no fresh reserve), so a
        # re-broadcast reuses the SAME nonce and the chain rejects it (nonce
        # too low / already known) instead of sending a second distinct TX.
        items_without_nonce = [it for it in items if it.nonce is None]
        if items_without_nonce:
            start_nonce, _ = await nm.reserve_range(len(items_without_nonce))
            async with async_session() as session:
                async with session.begin():
                    for offset, it in enumerate(items_without_nonce):
                        assigned = start_nonce + offset
                        await session.execute(
                            update(SweepBatchItem)
                            .where(SweepBatchItem.id == it.id)
                            .values(status="SIGNING", nonce=assigned)
                        )
                        it.nonce = assigned  # reflect on the in-memory object

        completed_items = []
        failed_items = []
        tx_hashes = []
        retry_queue = []  # items to retry after the loop

        for item in items:
            nonce = item.nonce  # persisted nonce (assigned above or on a prior run)
            try:
                tx_hash = await _execute_single_transfer(
                    signer=signer,
                    rpc=rpc,
                    chain_id=chain_id,
                    nonce=nonce,
                    to_address=item.recipient_address,
                    amount_wei=int(item.amount_wei),
                    gas_price_wei=gas_price_wei,
                    token_address=batch.token_address,
                    from_address=hot_address,
                    gas_params=gas_params,
                )

                # Update item status
                async with async_session() as session:
                    async with session.begin():
                        await session.execute(
                            update(SweepBatchItem)
                            .where(SweepBatchItem.id == item.id)
                            .values(
                                status="SUBMITTED",
                                tx_hash=tx_hash,
                                nonce=nonce,
                                executed_at=datetime.now(timezone.utc),
                            )
                        )

                completed_items.append(item)
                tx_hashes.append(tx_hash)

            except Exception as exc:
                error_msg = str(exc)[:500]
                action, pattern = classify_tx_error(error_msg)

                logger.error(
                    "Failed to execute item %s in batch %s: %s "
                    "(action=%s pattern=%s)",
                    item.id, batch_id, error_msg[:100], action, pattern,
                )

                # C1b: a consumed nonce on an item we already assigned means
                # OUR transfer at that nonce already went through — the hot
                # wallet's nonces are reserved exclusively by us. Treat it as
                # already-sent: mark SUBMITTED, do NOT re-broadcast (a fresh
                # nonce here would double-pay). Worst case is a missing tx_hash
                # attribution (recoverable by reconciliation), never a 2nd TX.
                nonce_consumed = any(
                    s in error_msg.lower()
                    for s in (
                        "nonce too low",
                        "nonce has already been used",
                        "already known",
                    )
                )
                if nonce_consumed and item.nonce is not None:
                    logger.warning(
                        "Item %s nonce %s already consumed on-chain — marking "
                        "SUBMITTED (idempotent, no re-broadcast)",
                        item.id, nonce,
                    )
                    async with async_session() as session:
                        async with session.begin():
                            await session.execute(
                                update(SweepBatchItem)
                                .where(SweepBatchItem.id == item.id)
                                .values(
                                    status="SUBMITTED",
                                    nonce=nonce,
                                    executed_at=datetime.now(timezone.utc),
                                )
                            )
                    completed_items.append(item)
                    continue

                if action != "fail":
                    # Retryable — mark RETRYING, will be dispatched after loop
                    async with async_session() as session:
                        async with session.begin():
                            await session.execute(
                                update(SweepBatchItem)
                                .where(SweepBatchItem.id == item.id)
                                .values(
                                    status="RETRYING",
                                    error_message=error_msg,
                                    retry_count=1,
                                )
                            )
                    retry_queue.append({
                        "item_id": str(item.id),
                        "action": action,
                        "attempt": 1,
                        "nonce": nonce,
                        "recipient_address": item.recipient_address,
                        "amount_wei": item.amount_wei,
                    })
                else:
                    # Non-retryable — mark FAILED permanently
                    async with async_session() as session:
                        async with session.begin():
                            await session.execute(
                                update(SweepBatchItem)
                                .where(SweepBatchItem.id == item.id)
                                .values(
                                    status="FAILED",
                                    error_message=error_msg,
                                )
                            )

                failed_items.append(item)

        # ══════════════════════════════════════════════════
        #  POST-EXECUTION
        # ══════════════════════════════════════════════════

        # Determine final batch status
        if not completed_items:
            final_status = "FAILED"
        elif failed_items:
            final_status = "PARTIAL"
        else:
            final_status = "COMPLETED"

        total_gas_cost = gas_estimate  # approximate

        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(SweepBatch)
                    .where(SweepBatch.id == batch_uuid)
                    .values(
                        status=final_status,
                        total_gas_cost_wei=str(total_gas_cost),
                        completed_at=datetime.now(timezone.utc),
                        error_message=(
                            f"{len(failed_items)} items failed"
                            if failed_items else None
                        ),
                    )
                )

                event_type = "TX_COMPLETED" if final_status == "COMPLETED" else "TX_FAILED"
                await log_event(
                    session,
                    event_type=event_type,
                    entity_type="sweep_batch",
                    entity_id=batch_id,
                    actor_type="system",
                    actor_id="execute_distribution",
                    changes={
                        "status": final_status,
                        "completed": len(completed_items),
                        "failed": len(failed_items),
                        "tx_hashes": tx_hashes[:10],
                    },
                )

        # ── Set cooldown on rule ──────────────────────────
        if batch.forwarding_rule_id:
            try:
                r = await get_redis()
                cooldown_key = f"cooldown:{chain_id}:{batch.forwarding_rule_id}"
                if rule:
                    await r.setex(cooldown_key, rule.cooldown_sec, "1")
            except Exception:
                pass

        # ── WebSocket notification ────────────────────────
        try:
            await _notify_websocket(
                owner_address=source_address,
                event_type="sweep_completed" if final_status == "COMPLETED" else "sweep_error",
                data={
                    "batch_id": batch_id,
                    "status": final_status,
                    "tx_hashes": tx_hashes,
                    "total_amount_wei": total_amount_wei,
                    "completed": len(completed_items),
                    "failed": len(failed_items),
                    "retrying": len(retry_queue),
                },
            )
        except Exception as exc:
            logger.warning("WebSocket notify failed: %s", exc)

        # ── Telegram notification ─────────────────────────
        try:
            await _notify_telegram(batch_id, final_status, tx_hashes, total_amount_wei)
        except Exception as exc:
            logger.warning("Telegram notify failed: %s", exc)

        # ── Enqueue parallel confirmation for all submitted TXes ──
        if tx_hashes:
            confirm_batch.apply_async(
                args=[batch_id, tx_hashes],
                countdown=15,  # wait ~15s for first block confirmation
            )

        # ── Enqueue retries for retryable failures ───────
        if retry_queue:
            logger.info(
                "Batch %s: %d items queued for retry",
                batch_id[:8], len(retry_queue),
            )
            retry_failed_items.apply_async(
                args=[batch_id, retry_queue],
                countdown=10,  # short delay before first retry
            )

        return {
            "status": final_status,
            "batch_id": batch_id,
            "completed": len(completed_items),
            "failed": len(failed_items),
            "retrying": len(retry_queue),
            "tx_hashes": tx_hashes,
        }

    except Exception:
        # Release spending reservation on failure
        if spending_reserved:
            try:
                await policy.release(source_address, total_amount_wei, chain_id)
            except Exception as rel_exc:
                logger.error("Failed to release spending: %s", rel_exc)
        raise  # Celery will retry


# ═══════════════════════════════════════════════════════════════
#  Task 3: confirm_batch  (parallel confirmation via asyncio.gather)
# ═══════════════════════════════════════════════════════════════

CONFIRM_TX_TIMEOUT = 120  # seconds per TX
CONFIRM_POLL_INTERVAL = 3  # seconds between receipt polls


async def confirm_all_transactions(
    batch_id: str,
    tx_hashes: list[str],
    chain_id: int,
    timeout: int = CONFIRM_TX_TIMEOUT,
) -> list[dict]:
    """Confirm N transactions in parallel.

    Each TX is polled independently with its own timeout.  All polls
    run concurrently via asyncio.gather — 50 TXes still complete in
    ~the time of 1 TX (block confirmation time), not 50× sequential.

    Returns:
        List of result dicts, one per tx_hash:
        {tx_hash, status, gas_used, block_number} or
        {tx_hash, status='timeout'|'error', error?}
    """
    from app.services.rpc_manager import get_rpc_manager

    rpc = get_rpc_manager(chain_id)

    async def _poll_receipt(tx_hash: str) -> dict:
        """Poll until receipt appears. Runs forever — caller applies timeout."""
        while True:
            try:
                receipt = await rpc.call(
                    "eth_getTransactionReceipt", [tx_hash]
                )
            except Exception as exc:
                logger.debug(
                    "Receipt poll error for %s: %s", tx_hash, exc,
                )
                await asyncio.sleep(CONFIRM_POLL_INTERVAL)
                continue

            if receipt is not None:
                from app.services.gas_estimator import parse_receipt_fees
                status_hex = receipt.get("status", "0x0")
                tx_success = int(status_hex, 16) == 1
                block_number = int(
                    receipt.get("blockNumber", "0x0"), 16
                )
                fees = parse_receipt_fees(receipt, chain_id)
                return {
                    "tx_hash": tx_hash,
                    "status": "CONFIRMED" if tx_success else "FAILED",
                    "gas_used": fees["l2_gas_used"],
                    "l2_fee_wei": fees["l2_fee_wei"],
                    "l1_fee_wei": fees["l1_fee_wei"],
                    "total_fee_wei": fees["total_fee_wei"],
                    "block_number": block_number,
                }

            await asyncio.sleep(CONFIRM_POLL_INTERVAL)

    async def _confirm_one(tx_hash: str) -> dict:
        """Confirm a single TX with timeout."""
        try:
            return await asyncio.wait_for(
                _poll_receipt(tx_hash), timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "TX confirmation timeout after %ds: %s", timeout, tx_hash,
            )
            return {
                "tx_hash": tx_hash, "status": "timeout",
                "gas_used": 0, "l2_fee_wei": 0, "l1_fee_wei": 0,
                "total_fee_wei": 0,
            }
        except Exception as exc:
            logger.error(
                "TX confirmation error for %s: %s", tx_hash, exc,
            )
            return {
                "tx_hash": tx_hash, "status": "error",
                "error": str(exc)[:200],
                "gas_used": 0, "l2_fee_wei": 0, "l1_fee_wei": 0,
                "total_fee_wei": 0,
            }

    results = await asyncio.gather(*[_confirm_one(h) for h in tx_hashes])
    return list(results)


@celery.task(
    name="app.tasks.sweep_tasks.confirm_batch",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def confirm_batch(self, batch_id: str, tx_hashes: list[str]) -> dict:
    """Confirm all TXes in a batch in parallel.

    Single Celery task replaces N individual confirm_tx tasks.
    Uses asyncio.gather internally — O(1) wall time instead of O(N).
    """
    return _run_async(
        _confirm_batch_async(self, batch_id, tx_hashes)
    )


async def _confirm_batch_async(
    task, batch_id: str, tx_hashes: list[str],
) -> dict:
    """Async implementation of confirm_batch."""
    from sqlalchemy import select, update
    from app.db.session import async_session
    from app.models.command_models import SweepBatch, SweepBatchItem
    from app.services.audit_service import log_event

    batch_uuid = uuid.UUID(batch_id)

    # ── Get chain_id from batch ───────────────────────────
    async with async_session() as session:
        result = await session.execute(
            select(SweepBatch.chain_id).where(SweepBatch.id == batch_uuid)
        )
        row = result.first()
        if row is None:
            return {"status": "error", "reason": "batch_not_found"}
        chain_id = row[0]

    # ── Confirm all TXes in parallel ──────────────────────
    results = await confirm_all_transactions(
        batch_id=batch_id,
        tx_hashes=tx_hashes,
        chain_id=chain_id,
    )

    # ── Update DB for each result ─────────────────────────
    confirmed = 0
    failed = 0
    timed_out = 0
    batch_total_fee = 0  # accumulate real total (L2 + L1)
    batch_l1_fee = 0
    batch_l2_fee = 0

    async with async_session() as session:
        async with session.begin():
            for r in results:
                tx_hash = r["tx_hash"]
                status = r["status"]

                if status == "CONFIRMED":
                    confirmed += 1
                    new_status = "CONFIRMED"
                elif status == "FAILED":
                    failed += 1
                    new_status = "FAILED"
                elif status == "timeout":
                    timed_out += 1
                    new_status = "TIMEOUT"
                else:
                    failed += 1
                    new_status = "FAILED"

                batch_total_fee += r.get("total_fee_wei", 0)
                batch_l1_fee += r.get("l1_fee_wei", 0)
                batch_l2_fee += r.get("l2_fee_wei", 0)

                await session.execute(
                    update(SweepBatchItem)
                    .where(SweepBatchItem.tx_hash == tx_hash)
                    .values(
                        status=new_status,
                        gas_used=r.get("gas_used", 0),
                    )
                )

                await log_event(
                    session,
                    event_type="TX_STATE_CHANGE",
                    entity_type="sweep_batch_item",
                    entity_id=tx_hash,
                    actor_type="system",
                    actor_id="confirm_batch",
                    changes={
                        "status": new_status,
                        "gas_used": r.get("gas_used", 0),
                        "l2_fee_wei": r.get("l2_fee_wei", 0),
                        "l1_fee_wei": r.get("l1_fee_wei", 0),
                        "total_fee_wei": r.get("total_fee_wei", 0),
                        "block_number": r.get("block_number"),
                    },
                )

            # Update batch total_gas_cost_wei with real total (L2 + L1)
            if batch_total_fee > 0:
                await session.execute(
                    update(SweepBatch)
                    .where(SweepBatch.id == batch_uuid)
                    .values(
                        total_gas_cost_wei=str(batch_total_fee),
                        metadata_={
                            "l2_fee_wei": str(batch_l2_fee),
                            "l1_fee_wei": str(batch_l1_fee),
                            "total_fee_wei": str(batch_total_fee),
                            "l1_l2_ratio": round(
                                batch_l1_fee / batch_l2_fee, 4
                            ) if batch_l2_fee > 0 else 0,
                        },
                    )
                )

    logger.info(
        "Batch %s confirmation done: confirmed=%d failed=%d timeout=%d "
        "total=%d l2_fee=%s l1_fee=%s total_fee=%s",
        batch_id[:8], confirmed, failed, timed_out, len(results),
        batch_l2_fee, batch_l1_fee, batch_total_fee,
    )

    # ── Retry timed-out TXes individually ─────────────────
    timed_out_hashes = [
        r["tx_hash"] for r in results if r["status"] == "timeout"
    ]
    if timed_out_hashes:
        logger.warning(
            "Batch %s: %d TXes timed out — dispatching individual retries",
            batch_id[:8], len(timed_out_hashes),
        )
        for tx_hash in timed_out_hashes:
            confirm_tx.apply_async(
                args=[batch_id, tx_hash],
                countdown=15,
            )

    return {
        "batch_id": batch_id,
        "confirmed": confirmed,
        "failed": failed,
        "timed_out": timed_out,
        "total": len(results),
    }


# ═══════════════════════════════════════════════════════════════
#  Task 4: confirm_tx  (single TX — kept for individual retries)
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.sweep_tasks.confirm_tx",
    bind=True,
    max_retries=10,
    default_retry_delay=15,
)
def confirm_tx(self, batch_id: str, tx_hash: str) -> dict:
    """Wait for transaction receipt and update item status.

    Polls for receipt with retries. Updates batch item to CONFIRMED
    or FAILED based on receipt status.

    Retry: up to 10 attempts (covers ~2.5 min of block time).
    """
    return _run_async(_confirm_tx_async(self, batch_id, tx_hash))


async def _confirm_tx_async(task, batch_id: str, tx_hash: str) -> dict:
    """Async implementation of confirm_tx."""
    from sqlalchemy import select, update
    from app.db.session import async_session
    from app.models.command_models import SweepBatch, SweepBatchItem
    from app.services.rpc_manager import get_rpc_manager
    from app.services.audit_service import log_event

    batch_uuid = uuid.UUID(batch_id)

    # ── Get chain_id from batch ───────────────────────────
    async with async_session() as session:
        result = await session.execute(
            select(SweepBatch.chain_id).where(SweepBatch.id == batch_uuid)
        )
        row = result.first()
        if row is None:
            return {"status": "error", "reason": "batch_not_found"}
        chain_id = row[0]

    # ── Query receipt ─────────────────────────────────────
    rpc = get_rpc_manager(chain_id)
    try:
        receipt = await rpc.call(
            "eth_getTransactionReceipt", [tx_hash]
        )
    except Exception as exc:
        logger.warning("Receipt query failed for %s: %s", tx_hash, exc)
        raise task.retry(exc=exc)

    if receipt is None:
        # TX not yet mined — retry
        logger.debug("No receipt yet for %s, retrying", tx_hash)
        raise task.retry(
            exc=RuntimeError(f"No receipt for {tx_hash}"),
        )

    # ── Parse receipt ─────────────────────────────────────
    from app.services.gas_estimator import parse_receipt_fees

    status_hex = receipt.get("status", "0x0")
    tx_success = int(status_hex, 16) == 1
    block_number = int(receipt.get("blockNumber", "0x0"), 16)
    fees = parse_receipt_fees(receipt, chain_id)

    new_status = "CONFIRMED" if tx_success else "FAILED"

    # ── Update batch item ─────────────────────────────────
    async with async_session() as session:
        async with session.begin():
            await session.execute(
                update(SweepBatchItem)
                .where(SweepBatchItem.tx_hash == tx_hash)
                .values(
                    status=new_status,
                    gas_used=fees["l2_gas_used"],
                )
            )

            await log_event(
                session,
                event_type="TX_STATE_CHANGE",
                entity_type="sweep_batch_item",
                entity_id=tx_hash,
                actor_type="system",
                actor_id="confirm_tx",
                changes={
                    "status": new_status,
                    "gas_used": fees["l2_gas_used"],
                    "l2_fee_wei": fees["l2_fee_wei"],
                    "l1_fee_wei": fees["l1_fee_wei"],
                    "total_fee_wei": fees["total_fee_wei"],
                    "block_number": block_number,
                    "tx_success": tx_success,
                },
            )

    logger.info(
        "TX confirmed: hash=%s status=%s gas=%d l1_fee=%d total=%d block=%d",
        tx_hash, new_status, fees["l2_gas_used"],
        fees["l1_fee_wei"], fees["total_fee_wei"], block_number,
    )

    return {
        "status": new_status,
        "tx_hash": tx_hash,
        "gas_used": fees["l2_gas_used"],
        "l2_fee_wei": fees["l2_fee_wei"],
        "l1_fee_wei": fees["l1_fee_wei"],
        "total_fee_wei": fees["total_fee_wei"],
        "block_number": block_number,
    }


# ═══════════════════════════════════════════════════════════════
#  Task 5: retry_failed_items  (intelligent retry with gas bump)
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.sweep_tasks.retry_failed_items",
    bind=True,
    max_retries=0,  # retries are managed internally per-item
)
def retry_failed_items(self, batch_id: str, items_to_retry: list[dict]) -> dict:
    """Retry failed batch items with error-specific strategies.

    Each item dict contains:
        item_id (str), action (str), attempt (int), nonce (int|None),
        recipient_address (str), amount_wei (str).

    Actions:
        bump_gas       — same nonce, gas bumped by 1.15^attempt
        resync_nonce   — fresh nonce from chain, rebuild TX
        wait_and_retry — wait 30s * attempt, then retry with same params
    """
    return _run_async(
        _retry_failed_items_async(self, batch_id, items_to_retry)
    )


async def _retry_failed_items_async(
    task, batch_id: str, items_to_retry: list[dict],
) -> dict:
    """Async implementation of retry_failed_items."""
    from sqlalchemy import select, update
    from app.db.session import async_session
    from app.models.command_models import SweepBatch, SweepBatchItem
    from app.services.key_manager import get_signer
    from app.services.rpc_manager import get_rpc_manager
    from app.services.nonce_manager import get_nonce_manager
    from app.services.audit_service import log_event

    batch_uuid = uuid.UUID(batch_id)

    # ── Load batch for chain_id, token_address, gas_price ────
    async with async_session() as session:
        result = await session.execute(
            select(SweepBatch).where(SweepBatch.id == batch_uuid)
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            return {"status": "error", "reason": "batch_not_found"}

    chain_id = batch.chain_id
    token_address = batch.token_address
    base_gas_price = int(batch.gas_price_wei) if batch.gas_price_wei else 0

    signer = get_signer()
    rpc = get_rpc_manager(chain_id)
    nm = get_nonce_manager(chain_id)
    hot_address = await signer.get_address()

    retried = 0
    succeeded = 0
    gave_up = 0
    tx_hashes: list[str] = []

    for item_info in items_to_retry:
        item_id = item_info["item_id"]
        action = item_info["action"]
        attempt = item_info["attempt"]
        original_nonce = item_info.get("nonce")
        recipient = item_info["recipient_address"]
        amount_wei = int(item_info["amount_wei"])

        retried += 1

        # ── Check max retries ────────────────────────────
        if attempt > MAX_ITEM_RETRIES:
            logger.warning(
                "Item %s: max retries (%d) exceeded, marking FAILED",
                item_id, MAX_ITEM_RETRIES,
            )
            async with async_session() as session:
                async with session.begin():
                    await session.execute(
                        update(SweepBatchItem)
                        .where(SweepBatchItem.id == uuid.UUID(item_id))
                        .values(
                            status="FAILED",
                            error_message=f"Max retries exceeded ({action})",
                            retry_count=attempt,
                        )
                    )
                    await log_event(
                        session,
                        event_type="TX_RETRY_EXHAUSTED",
                        entity_type="sweep_batch_item",
                        entity_id=item_id,
                        actor_type="system",
                        actor_id="retry_failed_items",
                        changes={"action": action, "attempt": attempt},
                    )
            gave_up += 1

            # WebSocket: retry exhausted
            try:
                await _notify_websocket(
                    owner_address=batch.source_address,
                    event_type="item_retry",
                    data={
                        "batch_id": batch_id,
                        "recipient": recipient,
                        "attempt": attempt,
                        "reason": f"max_retries_exceeded ({action})",
                        "final": True,
                    },
                )
            except Exception:
                pass
            continue

        # ── WebSocket: retry starting ────────────────────
        try:
            await _notify_websocket(
                owner_address=batch.source_address,
                event_type="item_retry",
                data={
                    "batch_id": batch_id,
                    "recipient": recipient,
                    "attempt": attempt,
                    "reason": action,
                    "final": False,
                },
            )
        except Exception:
            pass

        # ── Determine gas params + nonce per action ──────
        try:
            if action == "bump_gas":
                # Same nonce, gas bumped by 1.15^attempt
                nonce = original_nonce
                if nonce is None:
                    # Fallback: get fresh nonce
                    nonce = await nm.get_next()

                bump_factor = 1.15 ** attempt
                bumped_gas = int(base_gas_price * bump_factor)

                # Refresh base gas if it's stale (> 2 blocks old)
                fresh_gas_hex = await rpc.call("eth_gasPrice", [])
                fresh_gas = int(fresh_gas_hex, 16)
                # Use whichever is higher: bumped original or current network
                effective_gas = max(bumped_gas, int(fresh_gas * 1.1))

                from app.services.sweep_service import get_bumped_gas_params
                gas_params = await get_bumped_gas_params(
                    chain_id, effective_gas, is_replacement=True,
                )

                logger.info(
                    "Retry item %s: bump_gas attempt=%d nonce=%d "
                    "base=%d bumped=%d effective=%d",
                    item_id[:8], attempt, nonce,
                    base_gas_price, bumped_gas, effective_gas,
                )

            elif action == "resync_nonce":
                # Sync nonce from chain, get fresh one
                await nm.sync_from_chain()
                nonce = await nm.get_next()
                gas_params = None  # use default gas

                logger.info(
                    "Retry item %s: resync_nonce attempt=%d new_nonce=%d",
                    item_id[:8], attempt, nonce,
                )

            elif action == "wait_and_retry":
                # Wait proportionally, then retry with same params
                wait_secs = 30 * attempt
                logger.info(
                    "Retry item %s: wait_and_retry attempt=%d waiting %ds",
                    item_id[:8], attempt, wait_secs,
                )
                await asyncio.sleep(wait_secs)

                nonce = original_nonce
                if nonce is None:
                    nonce = await nm.get_next()
                gas_params = None

            else:
                # Unknown action — skip
                logger.warning("Unknown retry action '%s' for item %s", action, item_id)
                gave_up += 1
                continue

            # ── Execute the transfer ─────────────────────
            tx_hash = await _execute_single_transfer(
                signer=signer,
                rpc=rpc,
                chain_id=chain_id,
                nonce=nonce,
                to_address=recipient,
                amount_wei=amount_wei,
                gas_price_wei=base_gas_price,
                token_address=token_address,
                from_address=hot_address,
                gas_params=gas_params,
            )

            # ── Success: update item to SUBMITTED ────────
            async with async_session() as session:
                async with session.begin():
                    await session.execute(
                        update(SweepBatchItem)
                        .where(SweepBatchItem.id == uuid.UUID(item_id))
                        .values(
                            status="SUBMITTED",
                            tx_hash=tx_hash,
                            nonce=nonce,
                            retry_count=attempt,
                            error_message=None,
                            executed_at=datetime.now(timezone.utc),
                        )
                    )
                    await log_event(
                        session,
                        event_type="TX_RETRY_SUCCESS",
                        entity_type="sweep_batch_item",
                        entity_id=item_id,
                        actor_type="system",
                        actor_id="retry_failed_items",
                        changes={
                            "action": action,
                            "attempt": attempt,
                            "tx_hash": tx_hash,
                            "nonce": nonce,
                        },
                    )

            succeeded += 1
            tx_hashes.append(tx_hash)
            logger.info(
                "Retry succeeded: item=%s action=%s attempt=%d hash=%s",
                item_id[:8], action, attempt, tx_hash,
            )

        except Exception as exc:
            # Retry failed again — classify and potentially re-queue
            error_msg = str(exc)[:500]
            new_action, _ = classify_tx_error(error_msg)

            logger.error(
                "Retry failed: item=%s action=%s attempt=%d error=%s "
                "next_action=%s",
                item_id[:8], action, attempt, error_msg[:100], new_action,
            )

            if new_action != "fail" and attempt < MAX_ITEM_RETRIES:
                # Schedule another retry with incremented attempt
                async with async_session() as session:
                    async with session.begin():
                        await session.execute(
                            update(SweepBatchItem)
                            .where(SweepBatchItem.id == uuid.UUID(item_id))
                            .values(
                                status="RETRYING",
                                error_message=error_msg,
                                retry_count=attempt,
                            )
                        )

                retry_failed_items.apply_async(
                    args=[
                        batch_id,
                        [{
                            "item_id": item_id,
                            "action": new_action,
                            "attempt": attempt + 1,
                            "nonce": original_nonce if new_action == "bump_gas" else None,
                            "recipient_address": recipient,
                            "amount_wei": str(amount_wei),
                        }],
                    ],
                    countdown=10 * attempt,  # increasing backoff
                )
            else:
                # Non-retryable or max retries — mark FAILED
                async with async_session() as session:
                    async with session.begin():
                        await session.execute(
                            update(SweepBatchItem)
                            .where(SweepBatchItem.id == uuid.UUID(item_id))
                            .values(
                                status="FAILED",
                                error_message=error_msg,
                                retry_count=attempt,
                            )
                        )
                gave_up += 1

    # ── Enqueue confirmation for successfully retried TXes ───
    if tx_hashes:
        confirm_batch.apply_async(
            args=[batch_id, tx_hashes],
            countdown=15,
        )

    return {
        "batch_id": batch_id,
        "retried": retried,
        "succeeded": succeeded,
        "gave_up": gave_up,
        "tx_hashes": tx_hashes,
    }


# ═══════════════════════════════════════════════════════════════
#  Internal Helpers
# ═══════════════════════════════════════════════════════════════

async def _execute_single_transfer(
    signer,
    rpc,
    chain_id: int,
    nonce: int,
    to_address: str,
    amount_wei: int,
    gas_price_wei: int,
    token_address: Optional[str],
    from_address: str,
    gas_params: Optional[dict] = None,
) -> str:
    """Sign and send a single transfer (ETH or ERC-20).

    Args:
        gas_params: If provided, overrides gas_price_wei with EIP-1559
            or legacy params (e.g. from get_bumped_gas_params).

    Returns:
        Transaction hash.
    """
    if token_address:
        # ERC-20 transfer
        # transfer(address,uint256) selector = 0xa9059cbb
        from eth_abi import encode
        data = "0xa9059cbb" + encode(
            ["address", "uint256"],
            [to_address, amount_wei],
        ).hex()

        tx_dict = {
            "to": token_address,
            "value": 0,
            "data": bytes.fromhex(data[2:]),
            "nonce": nonce,
            "gas": 65000,
            "chainId": chain_id,
        }
    else:
        # Native ETH transfer
        tx_dict = {
            "to": to_address,
            "value": amount_wei,
            "nonce": nonce,
            "gas": 21000,
            "chainId": chain_id,
        }

    # Apply gas params: EIP-1559 (maxFeePerGas) or legacy (gasPrice)
    if gas_params:
        tx_dict.update(gas_params)
    else:
        tx_dict["gasPrice"] = gas_price_wei

    # Sign
    raw_tx = await signer.sign_transaction(tx_dict)
    raw_hex = "0x" + raw_tx.hex()

    # Send via RPC (primary only — never broadcast to multiple)
    try:
        tx_hash = await rpc.send_raw_transaction(raw_hex)
    except Exception as exc:
        # "already known" means TX is in mempool — compute hash and succeed
        if "already known" in str(exc).lower():
            from eth_utils import keccak
            tx_hash = "0x" + keccak(bytes.fromhex(raw_hex[2:])).hex()
            logger.info(
                "TX already in mempool (not an error): hash=%s nonce=%d",
                tx_hash, nonce,
            )
        else:
            raise

    logger.info(
        "TX sent: hash=%s to=%s amount=%s nonce=%d chain=%d replacement=%s",
        tx_hash, to_address, amount_wei, nonce, chain_id,
        bool(gas_params),
    )
    return tx_hash


async def _notify_websocket(
    owner_address: str,
    event_type: str,
    data: dict,
) -> None:
    """Send event to WebSocket feed for the owner address."""
    from app.api.websocket_routes import feed_manager

    await feed_manager.broadcast(
        owner_address=owner_address,
        event_type=event_type,
        data=data,
    )


async def _notify_telegram(
    batch_id: str,
    status: str,
    tx_hashes: list[str],
    total_amount_wei: str,
) -> None:
    """Send Telegram notification about batch completion."""
    from app.config import get_settings
    import httpx

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    amount_eth = int(total_amount_wei) / 10**18
    status_emoji = {
        "COMPLETED": "OK",
        "PARTIAL": "WARN",
        "FAILED": "FAIL",
    }.get(status, status)

    message = (
        f"[{status_emoji}] Sweep Batch {batch_id[:8]}...\n"
        f"Status: {status}\n"
        f"Amount: {amount_eth:.6f} ETH\n"
        f"TXs: {len(tx_hashes)}"
    )

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
