"""
RSends Backend — Celery Beat Periodic Tasks.

Tasks:
  update_gas_oracle       — every 10s  — refresh cached gas prices
  check_stale_batches     — every 2min — find PROCESSING batches stuck >5min
  check_hot_wallet        — every 5min — balance check + refill alert
  aggregate_daily_stats   — daily 00:05 UTC — compute daily sweep aggregates
  cleanup_old_locks       — every 10min — remove expired Redis locks
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

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
#  update_gas_oracle — every 10 seconds
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.periodic_tasks.update_gas_oracle")
def update_gas_oracle() -> dict:
    """Refresh cached gas prices for all active chains.

    Stores gas prices in Redis for fast access by sweep tasks.
    Key: gas:{chain_id}  Value: {slow, normal, fast} in gwei.
    """
    return _run_async(_update_gas_oracle_async())


async def _update_gas_oracle_async() -> dict:
    from app.services.rpc_manager import get_rpc_manager
    from app.services.cache_service import get_redis

    r = await get_redis()
    chains = [8453, 1, 42161]  # Base, Ethereum, Arbitrum
    results = {}

    for chain_id in chains:
        try:
            rpc = get_rpc_manager(chain_id)
            gas_hex = await rpc.call("eth_gasPrice", [])
            gas_wei = int(gas_hex, 16)
            gas_gwei = gas_wei / 10**9

            # Store with tiers (simple multipliers for now)
            gas_data = {
                "slow": round(gas_gwei * 0.8, 2),
                "normal": round(gas_gwei, 2),
                "fast": round(gas_gwei * 1.3, 2),
                "wei": str(gas_wei),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            import json
            await r.setex(f"gas:{chain_id}", 30, json.dumps(gas_data))
            results[chain_id] = gas_data

        except Exception as exc:
            logger.debug("Gas oracle failed for chain %d: %s", chain_id, exc)
            results[chain_id] = {"error": str(exc)}

    return results


# ═══════════════════════════════════════════════════════════════
#  check_stale_batches — every 2 minutes
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.periodic_tasks.check_stale_batches")
def check_stale_batches() -> dict:
    """Find PROCESSING batches stuck for >5 minutes and mark FAILED.

    Also re-enqueues PENDING batches that were never picked up (>2 min old).
    """
    return _run_async(_check_stale_batches_async())


async def _check_stale_batches_async() -> dict:
    from sqlalchemy import select, update
    from app.db.session import async_session
    from app.models.command_models import SweepBatch
    from app.services.audit_service import log_event

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=5)
    pending_threshold = now - timedelta(minutes=2)
    stale_count = 0
    requeued_count = 0

    async with async_session() as session:
        async with session.begin():
            # ── Find stale PROCESSING batches ──────────────
            result = await session.execute(
                select(SweepBatch).where(
                    SweepBatch.status == "PROCESSING",
                    SweepBatch.created_at < stale_threshold,
                )
            )
            stale_batches = result.scalars().all()

            for batch in stale_batches:
                await session.execute(
                    update(SweepBatch)
                    .where(SweepBatch.id == batch.id)
                    .values(
                        status="FAILED",
                        error_message="Stale: stuck in PROCESSING >5min",
                    )
                )
                await log_event(
                    session,
                    event_type="ANOMALY_DETECTED",
                    entity_type="sweep_batch",
                    entity_id=str(batch.id),
                    actor_type="system",
                    actor_id="check_stale_batches",
                    changes={"reason": "stale_processing", "age_min": 5},
                )
                stale_count += 1

            # ── Re-enqueue stuck PENDING batches ───────────
            result = await session.execute(
                select(SweepBatch).where(
                    SweepBatch.status == "PENDING",
                    SweepBatch.created_at < pending_threshold,
                )
            )
            pending_batches = result.scalars().all()

    # Re-enqueue outside the transaction
    for batch in pending_batches:
        from app.tasks.sweep_tasks import execute_distribution
        execute_distribution.apply_async(args=[str(batch.id)])
        requeued_count += 1

    if stale_count or requeued_count:
        logger.info(
            "Stale batch check: %d marked failed, %d requeued",
            stale_count, requeued_count,
        )

    return {"stale_failed": stale_count, "requeued": requeued_count}


# ═══════════════════════════════════════════════════════════════
#  check_hot_wallet — every 5 minutes
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.periodic_tasks.check_hot_wallet")
def check_hot_wallet() -> dict:
    """Check hot wallet balance and trigger refill alert if low.

    Also syncs nonce from chain to catch externally-sent transactions.
    """
    return _run_async(_check_hot_wallet_async())


async def _check_hot_wallet_async() -> dict:
    from app.services.wallet_manager import get_wallet_manager
    from app.services.nonce_manager import get_nonce_manager

    results = {}
    chains = [8453]  # Primary chain; extend as needed

    for chain_id in chains:
        wm = get_wallet_manager(chain_id)
        nm = get_nonce_manager(chain_id)

        # Balance check
        try:
            balance = await wm.get_hot_balance()
            needs_refill = await wm.needs_refill()

            if needs_refill:
                await wm.alert_refill()

            results[chain_id] = {
                "balance_wei": str(balance),
                "needs_refill": needs_refill,
            }
        except Exception as exc:
            logger.error("Hot wallet check failed for chain %d: %s", chain_id, exc)
            results[chain_id] = {"error": str(exc)}

        # Nonce sync
        try:
            nonce = await nm.sync_from_chain()
            results[chain_id]["nonce"] = nonce
        except Exception as exc:
            logger.warning("Nonce sync failed for chain %d: %s", chain_id, exc)
            results[chain_id]["nonce_error"] = str(exc)

    return results


# ═══════════════════════════════════════════════════════════════
#  aggregate_daily_stats — daily 00:05 UTC
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.periodic_tasks.aggregate_daily_stats")
def aggregate_daily_stats() -> dict:
    """Compute daily sweep aggregates and store in Redis.

    Aggregates: total volume, batch count, success rate, avg gas cost.
    Key: stats:daily:{date}
    """
    return _run_async(_aggregate_daily_stats_async())


async def _aggregate_daily_stats_async() -> dict:
    from sqlalchemy import select, func
    from app.db.session import async_session
    from app.models.command_models import SweepBatch
    from app.services.cache_service import get_redis

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    day_start = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with async_session() as session:
        # Total batches by status
        result = await session.execute(
            select(
                SweepBatch.status,
                func.count(SweepBatch.id).label("count"),
            )
            .where(
                SweepBatch.created_at >= day_start,
                SweepBatch.created_at < day_end,
            )
            .group_by(SweepBatch.status)
        )
        status_counts = {row[0]: row[1] for row in result.all()}

        # Total volume
        result = await session.execute(
            select(SweepBatch.total_amount_wei)
            .where(
                SweepBatch.created_at >= day_start,
                SweepBatch.created_at < day_end,
                SweepBatch.status.in_(["COMPLETED", "PARTIAL"]),
            )
        )
        amounts = result.scalars().all()
        total_volume_wei = sum(int(a) for a in amounts)

    total_batches = sum(status_counts.values())
    completed = status_counts.get("COMPLETED", 0)
    success_rate = (completed / total_batches * 100) if total_batches > 0 else 0

    stats = {
        "date": str(yesterday),
        "total_batches": total_batches,
        "status_counts": status_counts,
        "total_volume_wei": str(total_volume_wei),
        "total_volume_eth": total_volume_wei / 10**18,
        "success_rate_pct": round(success_rate, 2),
    }

    # Store in Redis (30-day retention)
    import json
    r = await get_redis()
    await r.setex(
        f"stats:daily:{yesterday}",
        86400 * 30,
        json.dumps(stats, default=str),
    )

    logger.info(
        "Daily stats for %s: batches=%d volume=%.4f ETH success=%.1f%%",
        yesterday, total_batches, stats["total_volume_eth"], success_rate,
    )

    return stats


# ═══════════════════════════════════════════════════════════════
#  cleanup_old_locks — every 10 minutes
# ═══════════════════════════════════════════════════════════════

@celery.task(name="app.tasks.periodic_tasks.cleanup_old_locks")
def cleanup_old_locks() -> dict:
    """Remove expired Redis locks and stale cooldown keys.

    Scans for:
      - nonce:lock:* keys with no TTL
      - cooldown:* keys that should have expired
    """
    return _run_async(_cleanup_old_locks_async())


async def _cleanup_old_locks_async() -> dict:
    from app.services.cache_service import get_redis

    r = await get_redis()
    cleaned = 0

    # Clean nonce lock keys with no TTL (orphaned locks)
    async for key in r.scan_iter("nonce:lock:*", count=100):
        ttl = await r.ttl(key)
        if ttl == -1:  # no expiry — orphaned lock
            await r.delete(key)
            cleaned += 1
            logger.info("Cleaned orphaned lock: %s", key)

    # Clean stale cooldown keys
    async for key in r.scan_iter("cooldown:*", count=100):
        ttl = await r.ttl(key)
        if ttl == -1:
            await r.delete(key)
            cleaned += 1

    if cleaned:
        logger.info("Cleaned %d orphaned locks/keys", cleaned)

    return {"cleaned": cleaned}
