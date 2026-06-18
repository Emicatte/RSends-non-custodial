from __future__ import annotations

"""Celery shim for the daily scheduled-deletion cron.

Fires at 03:00 UTC (see `celery_app.beat_schedule`). All the real work lives
in `app.services.account_deletion_service.run_scheduled_deletions` — this
file only adapts the async coroutine to Celery's sync task contract.
"""

import asyncio
import logging

from app.celery_app import celery

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task. Mirrors email_tasks."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery.task(
    name="tasks.run_scheduled_deletions",
    bind=True,
    max_retries=0,
    soft_time_limit=600,
    time_limit=900,
)
def run_scheduled_deletions_task(self) -> dict:
    """Hard-delete every user past their 30-day grace cutoff. Idempotent."""
    from app.services.account_deletion_service import run_scheduled_deletions

    summary = _run_async(run_scheduled_deletions())
    logger.info("scheduled_deletions_task_complete", extra=summary)
    return summary
