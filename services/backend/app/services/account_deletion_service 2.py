"""GDPR-compliant account deletion — 30-day grace period + hard-delete cascade.

Flow
1. User requests deletion via POST /api/v1/user/account/delete (typed confirmation).
   → `request_deletion` stamps (deletion_requested_at, deletion_scheduled_for,
     deletion_reason), audits `account_deletion_requested`, emails confirmation.
2. During the grace window the user may cancel via POST /delete/cancel. Login
   is still allowed (they must be able to reach the cancel button).
3. Daily Celery beat task at 03:00 UTC runs `run_scheduled_deletions` which
   hard-deletes every user whose `deletion_scheduled_for < now()`.
4. `hard_delete_user` removes Redis session keys for the user (best-effort) and
   issues a single `DELETE FROM users` — every child FK (user_sessions,
   user_routes, user_transactions, user_contacts, notifications,
   notification_preferences, known_devices, user_wallets, auth_audit_log) has
   `ondelete=CASCADE`, so one row-drop purges the entire account graph.
5. A final `account_hard_deleted` audit event is written with `user_id=None`
   (the FK target is gone) + the purged id in `details` — GDPR art. 30
   "record of erasure" evidence.

All functions are idempotent (safe to re-run on partial failure). Emails are
fire-and-forget via `send_email` which never raises.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import async_session
from app.models.auth_models import User
from app.services.auth_audit import record_auth_event
from app.services.cache_service import get_redis
from app.services.email_service import send_email

log = logging.getLogger(__name__)

GRACE_PERIOD_DAYS = 30
REQUIRED_CONFIRMATION = "DELETE MY ACCOUNT"
SESSION_REDIS_MATCH = "auth:session:*"


class DeletionError(Exception):
    """Non-fatal: raised by request_deletion / cancel_deletion on lookup failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def request_deletion(
    db: AsyncSession,
    user_id: str,
    reason: Optional[str] = None,
) -> User:
    """Mark a user's account for hard-deletion in GRACE_PERIOD_DAYS.

    Idempotent: if the user is already scheduled, returns the existing row
    unchanged — does NOT reset the countdown. The confirmation email is sent
    only on the first request; no duplicates.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise DeletionError("user_not_found")

    if user.deletion_scheduled_for is not None:
        return user

    now = datetime.now(timezone.utc)
    user.deletion_requested_at = now
    user.deletion_scheduled_for = now + timedelta(days=GRACE_PERIOD_DAYS)
    user.deletion_reason = (reason or "").strip()[:500] or None
    await db.commit()
    await db.refresh(user)

    await record_auth_event(
        event_type="account_deletion_requested",
        user_id=user_id,
        details={
            "scheduled_for": user.deletion_scheduled_for.isoformat(),
            "reason_preview": (reason or "")[:50],
            "grace_days": GRACE_PERIOD_DAYS,
        },
    )

    settings = get_settings()
    await send_email(
        to=user.email,
        template_name="deletion_scheduled",
        subject="Your RSends account is scheduled for deletion",
        context={
            "user_name": user.display_name or user.email,
            "scheduled_date": user.deletion_scheduled_for.strftime("%B %d, %Y"),
            "grace_days": GRACE_PERIOD_DAYS,
            "cancel_url": f"{settings.frontend_url.rstrip('/')}/en/settings/security",
        },
    )

    return user


async def cancel_deletion(db: AsyncSession, user_id: str) -> User:
    """Cancel a pending deletion — idempotent no-op if not scheduled."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise DeletionError("user_not_found")

    if user.deletion_scheduled_for is None:
        return user

    user.deletion_requested_at = None
    user.deletion_scheduled_for = None
    user.deletion_reason = None
    await db.commit()
    await db.refresh(user)

    await record_auth_event(
        event_type="account_deletion_cancelled",
        user_id=user_id,
        details={},
    )

    settings = get_settings()
    await send_email(
        to=user.email,
        template_name="deletion_cancelled",
        subject="Your RSends account deletion was cancelled",
        context={
            "user_name": user.display_name or user.email,
            "settings_url": f"{settings.frontend_url.rstrip('/')}/en/settings/security",
        },
    )

    return user


async def _purge_redis_sessions(user_id: str) -> int:
    """Best-effort: delete every Redis session key whose stored user_id matches.

    Returns the count of keys deleted. Any exception is logged and swallowed —
    DB is the truth; Redis TTL (7d) cleans stragglers.
    """
    deleted = 0
    try:
        r = await get_redis()
        if r is None:
            return 0
        async for key in r.scan_iter(match=SESSION_REDIS_MATCH, count=200):
            try:
                raw = await r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
                if data.get("user_id") == user_id:
                    await r.delete(key)
                    deleted += 1
            except Exception:
                # Per-key failure (decode, parse, delete) — keep scanning.
                log.exception("redis_session_purge_per_key_failed")
                continue
    except Exception:
        log.exception(
            "redis_session_purge_scan_failed",
            extra={"user_id_prefix": (user_id or "")[:8]},
        )
    return deleted


async def hard_delete_user(db: AsyncSession, user_id: str) -> dict:
    """Irreversibly delete a user + every row that FKs to users.id.

    Idempotent: if the user row is already gone, returns `rows_deleted=0`.
    All user-scoped child tables declare `ondelete=CASCADE`, so the single
    `DELETE FROM users` wipes the entire graph atomically.

    NOT user-callable — only invoked by the daily Celery beat task.
    """
    log.warning(
        "hard_delete_start", extra={"user_id_prefix": (user_id or "")[:8]}
    )

    redis_deleted = await _purge_redis_sessions(user_id)

    result = await db.execute(sql_delete(User).where(User.id == user_id))
    rows = int(result.rowcount or 0)
    await db.commit()

    # Audit is logged after commit — the user_id FK is gone, so we log with
    # user_id=None and keep the purged id in details for compliance (GDPR
    # art. 30 record-of-erasure).
    await record_auth_event(
        event_type="account_hard_deleted",
        user_id=None,
        details={
            "user_id_purged": user_id,
            "rows_deleted": rows,
            "redis_sessions_deleted": redis_deleted,
        },
    )

    log.warning(
        "hard_delete_complete",
        extra={
            "user_id_prefix": (user_id or "")[:8],
            "rows_deleted": rows,
            "redis_sessions_deleted": redis_deleted,
        },
    )
    return {"rows_deleted": rows, "redis_sessions_deleted": redis_deleted}


async def run_scheduled_deletions() -> dict:
    """Daily cron entrypoint. Hard-deletes users past their grace cutoff.

    Per-user failure isolation: each user is deleted in its own session so one
    failure doesn't poison the whole batch. Summary is logged + returned.
    """
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        result = await db.execute(
            select(User.id).where(
                User.deletion_scheduled_for.isnot(None),
                User.deletion_scheduled_for < now,
            )
        )
        user_ids = [str(r[0]) for r in result.all()]

    summary: dict = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "user_ids_purged": [],
    }

    for uid in user_ids:
        summary["processed"] += 1
        try:
            async with async_session() as db:
                await hard_delete_user(db, uid)
            summary["succeeded"] += 1
            summary["user_ids_purged"].append(uid)
        except Exception as e:
            summary["failed"] += 1
            log.exception(
                "scheduled_deletion_failed",
                extra={
                    "user_id_prefix": (uid or "")[:8],
                    "error": str(e)[:200],
                },
            )

    log.info("scheduled_deletions_run", extra=summary)
    return summary
