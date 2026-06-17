"""
RSends Backend — Audit Service (Immutable Audit Trail).

Scrive nella tabella audit_log (append-only, BIGSERIAL).
L'utente database dell'applicazione non deve avere permessi
UPDATE o DELETE su audit_log.

Every entry carries a chain_hash (SHA-256 of previous_hash + entry data)
that creates a tamper-evident chain. Gaps in sequence_number or broken
hashes indicate data manipulation.

Event types:
  TX_CREATED, TX_STATE_CHANGE, TX_COMPLETED, TX_FAILED,
  LEDGER_ENTRY_CREATED, BALANCE_QUERY, ANOMALY_DETECTED,
  ADMIN_ACTION, AUTH_FAILURE
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ledger_models import LedgerAuditLog
from app.middleware.request_context import get_request_id, get_client_ip, get_user_agent

logger = logging.getLogger(__name__)

# Event types ammessi
EVENT_TYPES = frozenset({
    "TX_CREATED",
    "TX_STATE_CHANGE",
    "TX_COMPLETED",
    "TX_FAILED",
    "LEDGER_ENTRY_CREATED",
    "BALANCE_QUERY",
    "ANOMALY_DETECTED",
    "ADMIN_ACTION",
    "AUTH_FAILURE",
})


GENESIS_HASH = "0" * 64


def _compute_hmac_signature(
    chain_hash: str,
    sequence_number: int,
    event_type: str,
    entity_id: str,
    created_at: str,
    changes: Optional[dict],
) -> str:
    """Compute HMAC-SHA256 signature for tamper-proof audit record.

    Uses HMAC_SECRET from settings. Returns empty string if secret is
    not configured (dev mode).
    """
    secret = get_settings().hmac_secret
    if not secret or secret == "change-me-in-production":
        return ""

    payload = (
        f"{chain_hash}|{sequence_number}|{event_type}"
        f"|{entity_id}|{created_at}"
        f"|{json.dumps(changes, sort_keys=True, default=str) if changes else ''}"
    )
    return hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256,
    ).hexdigest()


def _compute_chain_hash(
    previous_hash: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_id: Optional[str],
    created_at: str,
) -> str:
    """Compute SHA-256 chain hash for tamper detection."""
    payload = (
        f"{previous_hash}|{event_type}|{entity_type}"
        f"|{entity_id}|{actor_id or ''}|{created_at}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _next_sequence(session: AsyncSession) -> tuple[int, str]:
    """Get next sequence number and the previous entry's chain_hash.

    Returns:
        (next_seq, previous_hash) — for the first entry, returns (1, GENESIS_HASH).
    """
    result = await session.execute(
        select(
            LedgerAuditLog.sequence_number,
            LedgerAuditLog.chain_hash,
        )
        .order_by(LedgerAuditLog.sequence_number.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return 1, GENESIS_HASH
    return row[0] + 1, row[1]


async def log_event(
    session: AsyncSession,
    event_type: str,
    entity_type: str,
    entity_id: str,
    *,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    changes: Optional[dict] = None,
    request_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> LedgerAuditLog:
    """Scrive un record immutabile nella tabella audit_log.

    Every entry includes a chain_hash = SHA-256(previous_hash + entry_data)
    and a monotonic sequence_number for tamper detection.

    Args:
        session: AsyncSession (il chiamante gestisce commit/rollback)
        event_type: Tipo evento (es. TX_CREATED)
        entity_type: Tipo entità (es. "transaction", "ledger_entry")
        entity_id: ID dell'entità (stringa)
        actor_type: "system", "user", "admin", ecc.
        actor_id: Identificativo dell'attore
        changes: Dict con le modifiche
        request_id: UUID della richiesta HTTP (auto da context se None)
        ip_address: IP del client (auto da context se None)
        user_agent: User-Agent (auto da context se None)
        metadata: Dati extra da salvare nel campo metadata

    Returns:
        Il record LedgerAuditLog creato.
    """
    if event_type not in EVENT_TYPES:
        logger.warning("Unknown audit event_type=%s, logging anyway", event_type)

    # Auto-fill dal request context se non specificato
    if request_id is None:
        ctx_rid = get_request_id()
        if ctx_rid is not None:
            request_id = ctx_rid

    if ip_address is None:
        ip_address = get_client_ip()

    if user_agent is None:
        user_agent = get_user_agent()

    # Chain hash computation
    now = datetime.now(timezone.utc)
    seq, prev_hash = await _next_sequence(session)
    chain_hash = _compute_chain_hash(
        prev_hash, event_type, entity_type, str(entity_id),
        actor_id, now.isoformat(),
    )

    hmac_sig = _compute_hmac_signature(
        chain_hash, seq, event_type, str(entity_id),
        now.isoformat(), changes,
    )

    entry = LedgerAuditLog(
        sequence_number=seq,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor_type=actor_type,
        actor_id=actor_id,
        ip_address=ip_address,
        user_agent=user_agent,
        changes=changes,
        request_id=request_id,
        previous_hash=prev_hash,
        chain_hash=chain_hash,
        hmac_signature=hmac_sig or None,
        created_at=now,
    )
    # metadata va nel campo metadata_ (Python) → metadata (DB)
    if metadata is not None:
        entry.metadata_ = metadata

    session.add(entry)
    await session.flush()

    logger.info(
        "audit.%s entity=%s:%s actor=%s:%s seq=%d",
        event_type,
        entity_type,
        entity_id,
        actor_type or "-",
        actor_id or "-",
        seq,
        extra={
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "audit_log_id": entry.id,
            "sequence_number": seq,
        },
    )

    return entry
