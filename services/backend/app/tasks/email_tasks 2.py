from __future__ import annotations

"""
RSends Backend — Email tasks (Celery).

Tasks:
  send_new_device_email_task — record a KnownDevice row for this login and,
                               if it's a new-but-not-first device AND the
                               user has the pref enabled, send a security
                               email via Resend.

Fired fire-and-forget from auth_service.create_session after the Redis
session is confirmed, so a broker/worker outage never blocks login.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

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
#  send_new_device_email_task — post-login security notification
# ═══════════════════════════════════════════════════════════════

@celery.task(
    name="app.tasks.email_tasks.send_new_device_email_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=30,
    time_limit=60,
)
def send_new_device_email_task(
    self,
    user_id: str,
    ip: str,
    user_agent: str,
) -> dict:
    """Record device + conditionally send the "new device" email.

    Returns a small dict describing what happened (for observability + tests).
    """
    return _run_async(_handle_new_device_login(user_id, ip, user_agent))


async def _handle_new_device_login(
    user_id: str, ip: str, user_agent: str
) -> dict:
    from app.config import get_settings
    from app.db.session import async_session
    from app.models.auth_models import User
    from app.models.notification_models import KnownDevice, NotificationPreference
    from app.services.auth_audit import record_auth_event
    from app.services.device_fingerprint import (
        compute_fingerprint,
        format_device_label,
    )
    from app.services.email_service import send_email

    settings = get_settings()
    fingerprint = compute_fingerprint(user_id, user_agent, ip)

    async with async_session() as db:
        # ── 1. Is this fingerprint already known? ────────────
        existing_q = select(KnownDevice).where(
            KnownDevice.user_id == user_id,
            KnownDevice.fingerprint == fingerprint,
        )
        device = (await db.execute(existing_q)).scalar_one_or_none()

        if device is not None:
            device.last_seen_at = datetime.now(timezone.utc)
            device.ip_last_seen = ip
            device.login_count = (device.login_count or 0) + 1
            await db.commit()
            return {"action": "repeat_device", "fingerprint_prefix": fingerprint[:16]}

        # ── 2. Does the user have ANY prior known devices? ───
        first_known_q = (
            select(KnownDevice.id).where(KnownDevice.user_id == user_id).limit(1)
        )
        is_first_login_ever = (
            await db.execute(first_known_q)
        ).scalar_one_or_none() is None

        # ── 3. Record the new device row (idempotent via UNIQUE) ──
        new_device = KnownDevice(
            id=str(uuid.uuid4()),
            user_id=user_id,
            fingerprint=fingerprint,
            user_agent_snippet=(user_agent or "")[:200] or None,
            ip_first_seen=ip or None,
            ip_last_seen=ip or None,
            login_count=1,
        )
        db.add(new_device)
        try:
            await db.commit()
        except Exception:
            # UNIQUE(user_id, fingerprint) race with a concurrent login —
            # treat as repeat; don't email twice.
            await db.rollback()
            return {"action": "race_treated_as_repeat", "fingerprint_prefix": fingerprint[:16]}

        if is_first_login_ever:
            # No previous device to contrast against — silent first login.
            return {"action": "first_login_silent", "fingerprint_prefix": fingerprint[:16]}

        # ── 4. Fetch user + preference ───────────────────────
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.email:
            return {"action": "no_user_or_email"}

        pref = (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        email_enabled = pref.email_login_new_device if pref is not None else True

        if not email_enabled:
            return {"action": "pref_off"}

        # ── 5. Build context + send ──────────────────────────
        settings_url = f"{settings.frontend_url.rstrip('/')}/en/settings/notifications"
        context = {
            "user_name": user.display_name or user.email,
            "device": format_device_label(user_agent),
            "ip": ip or "unknown",
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "settings_url": settings_url,
        }

        email_id = await send_email(
            to=user.email,
            template_name="login_new_device",
            subject="New login to your RSends account",
            context=context,
        )

    # audit outside the session block — record_auth_event opens its own
    await record_auth_event(
        event_type="email_sent_new_device",
        user_id=user_id,
        ip_address=ip or None,
        user_agent=user_agent or None,
        details={
            "fingerprint_prefix": fingerprint[:16],
            "email_id": email_id,
            "template": "login_new_device",
        },
    )

    return {
        "action": "email_dispatched",
        "email_id": email_id,
        "fingerprint_prefix": fingerprint[:16],
    }
