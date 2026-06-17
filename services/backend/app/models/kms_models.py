"""
RSends Backend — KMS Audit Log Model.

Immutable append-only table for every KMS operation (sign, verify, rotate).
Never deleted — used for forensics, compliance, and anomaly detection.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, Text, Index, JSON,
)

from app.models.db_models import Base


class KMSAuditLog(Base):
    """Immutable log of every KMS operation."""

    __tablename__ = "kms_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── KMS context ────────────────────────────────────
    key_id = Column(String(256), nullable=False)
    operation = Column(String(50), nullable=False)   # sign, verify, rotate
    chain_id = Column(Integer, nullable=True)

    # ── Transaction context (no private keys) ──────────
    context = Column(JSON, nullable=True)             # sender, recipient, amount

    # ── Result ─────────────────────────────────────────
    success = Column(Boolean, nullable=False)
    error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_kms_audit_created_at", "created_at"),
        Index("ix_kms_audit_key_id", "key_id"),
    )

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL({self.error})"
        return (
            f"<KMSAuditLog id={self.id} op={self.operation} "
            f"key={self.key_id[:16]}... {status}>"
        )
