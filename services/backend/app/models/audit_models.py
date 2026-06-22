"""
RSends Backend — Tamper-Evident Audit Log model.

This is a cross-cutting, NON-custodial audit trail (append-only, hash-chained)
used by audit_service for ADMIN_ACTION / AUTH_FAILURE / generic entity change
events. It was extracted verbatim from the removed custodial ledger_models
module because the audit trail itself is unrelated to custody of funds.

chain_hash = SHA-256(previous_hash || event_type || entity_type ||
                     entity_id || actor_id || created_at)
First entry uses previous_hash = "0" * 64. Any gap in sequence_number or
broken hash chain indicates tampering.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    String,
    Text,
    Uuid,
)

from app.models.db_models import Base
from app.models.db_types import BigIntegerType, InetType, JSONBType


class LedgerAuditLog(Base):
    """Append-only audit log with chain hash for tamper detection."""
    __tablename__ = "audit_log"

    id = Column(BigIntegerType, primary_key=True, autoincrement=True)
    sequence_number = Column(BigInteger, nullable=False, unique=True)
    event_type = Column(String(64), nullable=False)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(128), nullable=False)
    actor_type = Column(String(32), nullable=True)
    actor_id = Column(String(128), nullable=True)
    ip_address = Column(InetType, nullable=True)
    user_agent = Column(Text, nullable=True)
    changes = Column(JSONBType, nullable=True)
    request_id = Column(Uuid(as_uuid=True), nullable=True)
    chain_hash = Column(String(64), nullable=False)
    previous_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    hmac_signature = Column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_audit_log_entity", "entity_type", "entity_id"),
        Index("idx_audit_log_created", "created_at"),
        Index("idx_audit_log_seq", "sequence_number"),
    )
