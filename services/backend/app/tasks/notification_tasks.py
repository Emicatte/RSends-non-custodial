from __future__ import annotations

"""
RSends Backend — Celery Notification Tasks.

Tasks:
  send_notification_task   — dispatch a typed notification (Telegram)
  send_daily_digest        — daily 00:30 UTC — build and send daily summary
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
#  send_notification_task — generic notification dispatch
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.notification_tasks.send_notification_task",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    soft_time_limit=30,
    time_limit=60,
)
def send_notification_task(
    self,
    notification_type: str,
    data: dict,
    chat_id: str | None = None,
) -> dict:
    """Dispatch a typed notification via Telegram.

    Args:
        notification_type: sweep_completed, sweep_failed, circuit_breaker,
                          spending_warning, daily_digest
        data: Notification payload.
        chat_id: Override Telegram chat_id.

    Returns:
        dict with sent status.
    """
    return _run_async(
        _send_notification_async(self, notification_type, data, chat_id)
    )


async def _send_notification_async(task, notification_type, data, chat_id):
    from app.services.notification_service import send_notification

    try:
        sent = await send_notification(notification_type, data, chat_id=chat_id)
        return {"sent": sent, "type": notification_type}
    except Exception as exc:
        logger.error(
            "Notification task failed (type=%s): %s", notification_type, exc,
        )
        raise task.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════
#  send_daily_digest — daily 00:30 UTC
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.notification_tasks.send_daily_digest",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=120,
    time_limit=180,
)
def send_daily_digest(self) -> dict:
    """Build daily summary from DB aggregates and send via Telegram.

    Queries yesterday's sweep batches, volume, success rate,
    gas cost, and active rule count.
    """
    return _run_async(_send_daily_digest_async(self))


async def _send_daily_digest_async(task) -> dict:
    import json as _json
    from sqlalchemy import select, func
    from app.db.session import async_session
    from app.models.command_models import SweepBatch
    from app.models.forwarding_models import ForwardingRule
    from app.services.notification_service import send_notification
    from app.services.cache_service import get_redis

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    day_start = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    # ── Try Redis cache first (populated by aggregate_daily_stats) ──
    try:
        r = await get_redis()
        cached = await r.get(f"stats:daily:{yesterday}")
        if cached:
            stats = _json.loads(cached)
        else:
            stats = None
    except Exception:
        stats = None

    # ── Fall back to DB query ──
    if stats is None:
        async with async_session() as session:
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

            result = await session.execute(
                select(SweepBatch.total_amount_wei)
                .where(
                    SweepBatch.created_at >= day_start,
                    SweepBatch.created_at < day_end,
                    SweepBatch.status.in_(["COMPLETED", "PARTIAL"]),
                )
            )
            amounts = result.scalars().all()
            total_volume_wei = sum(int(a) for a in amounts if a)

            # Active rules count
            rule_result = await session.execute(
                select(func.count()).select_from(ForwardingRule).where(
                    ForwardingRule.is_active == True,
                    ForwardingRule.is_paused == False,
                )
            )
            active_rules = rule_result.scalar() or 0

        total_batches = sum(status_counts.values())
        completed = status_counts.get("COMPLETED", 0)
        failed = status_counts.get("FAILED", 0)
        success_rate = (completed / total_batches * 100) if total_batches > 0 else 0

        stats = {
            "date": str(yesterday),
            "total_batches": total_batches,
            "completed": completed,
            "failed": failed,
            "volume_eth": total_volume_wei / 10**18,
            "success_rate_pct": round(success_rate, 2),
            "gas_total_eth": 0,  # approximation — not tracked per-day in cache
            "active_rules": active_rules,
        }
    else:
        # Normalize cached format
        status_counts = stats.get("status_counts", {})
        stats = {
            "date": stats.get("date", str(yesterday)),
            "total_batches": stats.get("total_batches", 0),
            "completed": status_counts.get("COMPLETED", 0),
            "failed": status_counts.get("FAILED", 0),
            "volume_eth": stats.get("total_volume_eth", 0),
            "success_rate_pct": stats.get("success_rate_pct", 0),
            "gas_total_eth": 0,
            "active_rules": 0,
        }

    # ── Send ──
    try:
        sent = await send_notification("daily_digest", stats)
        logger.info("Daily digest sent for %s", yesterday)
        return {"sent": sent, "date": str(yesterday), **stats}
    except Exception as exc:
        logger.error("Daily digest failed: %s", exc)
        raise task.retry(exc=exc)
