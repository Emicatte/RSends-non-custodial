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
  But never-raise is not never-notice: the failure path also carries a
  traceback and increments AUTH_AUDIT_WRITE_FAILURES, because a swallowed
  exception with no counter is how a schema defect ate EVERY audit write
  under SQLite for months while the suite stayed green.
- On PostgreSQL the table has BEFORE UPDATE/DELETE triggers; do not
  attempt to mutate rows after insert.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from prometheus_client import Counter as PromCounter

from app.db.session import async_session
from app.middleware.correlation import get_correlation_id
from app.models.auth_models import AuthAuditLog

logger = logging.getLogger(__name__)

# ── Metrics (registry pattern of payment_indexer) ────────────
AUTH_AUDIT_WRITE_FAILURES = PromCounter(
    "rsend_auth_audit_write_failures_total",
    "Auth audit rows that failed to reach the database",
    ["event_type"],
)


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

    `correlation_id` falls back to the request's correlation id (set by
    CorrelationMiddleware) when the caller does not pass one. Most callers
    never did — the email-auth service passes it at none of its five call
    sites — so every login, signup and verification event was written with an
    empty correlation_id and could not be joined to anything. Defaulting here
    fixes all call sites at once; an explicit argument still wins.
    """
    cid = correlation_id or get_correlation_id() or None
    try:
        entry = AuthAuditLog(
            created_at=datetime.now(timezone.utc),
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=(user_agent[:500] if user_agent else None),
            google_sub=google_sub,
            correlation_id=cid,
            details=details or {},
        )

        async with async_session() as db:
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            entry_id = entry.id

    except Exception as e:
        AUTH_AUDIT_WRITE_FAILURES.labels(event_type=event_type).inc()
        logger.error(
            "Failed to record auth audit: %s", e,
            exc_info=True,
            extra={"service": "auth_audit", "event_type": event_type},
        )
        return None

    # Logging the success sits OUTSIDE the try that guards the write, and under
    # its own guard: inside it, a raising formatter or filter returned None
    # after a COMMITTED row — a logging fault reported as a lost audit row, the
    # two failure modes that must never be confused. Its except cannot log.
    try:
        logger.info(
            "Auth audit recorded: id=%d event=%s user=%s",
            entry_id, event_type, (user_id or "-")[:16],
            extra={
                "service": "auth_audit",
                "event_type": event_type,
                "user_id": user_id,
                "correlation_id": cid,
            },
        )
    except Exception:  # noqa: BLE001 — the return must reflect the write, nothing else
        pass

    return entry_id
