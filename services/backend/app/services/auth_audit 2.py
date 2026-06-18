"""
RPagos Backend — Auth audit service.

Immutable append-only log for every auth event (login success/failure,
logout, refresh, token rotation, refresh-token reuse detection,
rate-limit violations, etc.).

Pattern cloned from `app.services.signing_audit`:
- Opens its OWN async_session so the audit row commits independently
  of the caller's DB transaction. Audit durability is preserved even
  if the parent route later fails or rolls back.
- Exceptions are logged but never raised — the audit must not block auth.
- On PostgreSQL the table has BEFORE UPDATE/DELETE triggers; do not
  attempt to mutate rows after insert.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.session import async_session
from app.models.auth_models import AuthAuditLog

logger = logging.getLogger(__name__)


async def record_auth_event(
    *,
    event_type: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    google_sub: Optional[str] = None,
    correlation_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> Optional[int]:
    """Record an auth event. Returns entry ID or None on failure.

    `event_type` is one of:
      login_success, login_failure, logout, refresh, token_rotation,
      session_revoked, rate_limit_exceeded, id_token_invalid,
      refresh_reuse_detected, account_suspended.
    """
    try:
        entry = AuthAuditLog(
            created_at=datetime.now(timezone.utc),
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=(user_agent[:500] if user_agent else None),
            google_sub=google_sub,
            correlation_id=correlation_id,
            details=details or {},
        )

        async with async_session() as db:
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            logger.info(
                "Auth audit recorded: id=%d event=%s user=%s",
                entry.id, event_type, (user_id or "-")[:16],
                extra={
                    "service": "auth_audit",
                    "event_type": event_type,
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                },
            )
            return entry.id

    except Exception as e:
        logger.error(
            "Failed to record auth audit: %s", e,
            extra={"service": "auth_audit", "event_type": event_type},
        )
        return None
