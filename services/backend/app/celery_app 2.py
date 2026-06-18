"""
RSends Backend — Celery Application Configuration.

Broker: Redis (DB 1)
Result backend: Redis (DB 2)

Task routes:
  sweep.*     → queue "sweep"    (8 workers)
  confirm.*   → queue "confirm"  (4 workers)
  notify.*    → queue "notify"   (2 workers)
  analytics.* → queue "analytics" (1 worker)

Settings:
  acks_late=True          — ack after execution (at-least-once)
  reject_on_worker_lost   — requeue if worker crashes mid-task
  prefetch_multiplier=1   — no prefetch; one task at a time per worker
"""

from celery import Celery, signals
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "rsend",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# ═══════════════════════════════════════════════════════════════
#  Core Settings
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  Queue Definitions (with Dead Letter Queue)
# ═══════════════════════════════════════════════════════════════

_default_exchange = Exchange("default", type="direct")
_dlq_exchange = Exchange("dlq", type="direct")

celery.conf.task_queues = (
    # High priority — sweep & confirmation
    Queue("sweep", _default_exchange, routing_key="sweep"),
    Queue("confirm", _default_exchange, routing_key="confirm"),
    # Medium priority — notifications & webhooks
    Queue("notify", _default_exchange, routing_key="notify"),
    # Low priority — analytics & reports
    Queue("analytics", _default_exchange, routing_key="analytics"),
    # Default
    Queue("default", _default_exchange, routing_key="default"),
    # Dead Letter Queue — tasks that failed after max retries
    Queue("dlq", _dlq_exchange, routing_key="dlq"),
)

celery.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # Result expiry (24h)
    result_expires=86400,

    # Broker settings
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 3600,  # 1h — must be > longest task
        "socket_connect_timeout": 2,  # fail fast if Redis is down
        "socket_timeout": 2,
    },
    broker_connection_timeout=2,  # kombu connection timeout

    # Dead Letter Queue — failed tasks after retries go here
    task_default_delivery_mode="persistent",

    # Task routing
    task_routes={
        "app.tasks.sweep_tasks.process_incoming_tx": {"queue": "sweep"},
        "app.tasks.sweep_tasks.execute_distribution": {"queue": "sweep"},
        "app.tasks.sweep_tasks.confirm_batch": {"queue": "confirm"},
        "app.tasks.sweep_tasks.confirm_tx": {"queue": "confirm"},
        "app.tasks.sweep_tasks.retry_failed_items": {"queue": "sweep"},
        "app.tasks.periodic_tasks.update_gas_oracle": {"queue": "analytics"},
        "app.tasks.periodic_tasks.check_stale_batches": {"queue": "sweep"},
        "app.tasks.periodic_tasks.check_hot_wallet": {"queue": "sweep"},
        "app.tasks.periodic_tasks.aggregate_daily_stats": {"queue": "analytics"},
        "app.tasks.periodic_tasks.cleanup_old_locks": {"queue": "analytics"},
        "app.tasks.notification_tasks.send_notification_task": {"queue": "notify"},
        "app.tasks.notification_tasks.send_daily_digest": {"queue": "notify"},
        "app.tasks.email_tasks.send_new_device_email_task": {"queue": "notify"},
        "app.tasks.webhook_tasks.process_webhook_deliveries": {"queue": "notify"},
        "app.tasks.webhook_tasks.expire_pending_intents": {"queue": "notify"},
        "app.tasks.matching_tasks.match_transaction_task": {"queue": "default"},
    },

    # Default queue for unrouted tasks
    task_default_queue="default",

    # Task discovery
    include=[
        "app.tasks.sweep_tasks",
        "app.tasks.periodic_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.email_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.matching_tasks",
        "app.tasks.deletion_tasks",
    ],
)

# ═══════════════════════════════════════════════════════════════
#  Celery Beat Schedule
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  Correlation ID Propagation
#
#  Before a task is published, the current correlation_id is
#  injected into the message headers. When a worker picks up
#  the task, the correlation_id is restored into contextvars
#  so that all logs within the task carry the same ID.
# ═══════════════════════════════════════════════════════════════

@signals.before_task_publish.connect
def _inject_correlation_id(headers: dict, **kwargs):
    """Inject correlation_id into Celery message headers before publishing."""
    try:
        from app.middleware.correlation import get_correlation_id
        cid = get_correlation_id()
        if cid:
            headers["correlation_id"] = cid
    except Exception:
        pass


@signals.task_prerun.connect
def _restore_correlation_id(task, **kwargs):
    """Restore correlation_id from task headers into contextvars on the worker."""
    try:
        from app.middleware.correlation import set_correlation_id
        cid = getattr(task.request, "correlation_id", None)
        if not cid:
            # Fallback: check headers dict
            headers = getattr(task.request, "headers", None) or {}
            cid = headers.get("correlation_id", "")
        if cid:
            set_correlation_id(cid)
    except Exception:
        pass


celery.conf.beat_schedule = {
    "update-gas-oracle": {
        "task": "app.tasks.periodic_tasks.update_gas_oracle",
        "schedule": 10.0,  # every 10 seconds
    },
    "check-stale-batches": {
        "task": "app.tasks.periodic_tasks.check_stale_batches",
        "schedule": 120.0,  # every 2 minutes
    },
    "check-hot-wallet": {
        "task": "app.tasks.periodic_tasks.check_hot_wallet",
        "schedule": 300.0,  # every 5 minutes
    },
    "aggregate-daily-stats": {
        "task": "app.tasks.periodic_tasks.aggregate_daily_stats",
        "schedule": crontab(hour=0, minute=5),  # daily 00:05 UTC
    },
    "cleanup-old-locks": {
        "task": "app.tasks.periodic_tasks.cleanup_old_locks",
        "schedule": 600.0,  # every 10 minutes
    },
    "send-daily-digest": {
        "task": "app.tasks.notification_tasks.send_daily_digest",
        "schedule": crontab(hour=0, minute=30),  # daily 00:30 UTC
    },
    "process-webhook-deliveries": {
        "task": "app.tasks.webhook_tasks.process_webhook_deliveries",
        "schedule": 15.0,  # every 15 seconds
    },
    "expire-pending-intents": {
        "task": "app.tasks.webhook_tasks.expire_pending_intents",
        "schedule": 60.0,  # every 60 seconds
    },
    "run-scheduled-account-deletions": {
        # GDPR art. 17 hard-delete cron — scans users past their 30-day
        # grace window and purges them (row-drop cascades to all children).
        "task": "tasks.run_scheduled_deletions",
        "schedule": crontab(hour=3, minute=0),  # daily 03:00 UTC
    },
}
