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

# NON-CUSTODIAL: send_daily_digest removed — it aggregated custodial sweep
# batches (SweepBatch/ForwardingRule), which no longer exist.
