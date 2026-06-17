"""
RSends Backend — Signing Audit Log Model.

Immutable append-only table for every oracle signature request.
Never deleted — used for forensics, compliance, and anomaly detection.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, Text, BigInteger, Index,
)

from app.models.db_models import Base


class SigningAuditLog(Base):
    """Immutable log of every oracle signature request (approved or denied)."""

    __tablename__ = "signing_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # ── Request context ─────────────────────────────────
    correlation_id = Column(String(64), nullable=True)
    ip_address = Column(String(45), nullable=True)      # IPv4 or IPv6
    user_agent = Column(String(512), nullable=True)

    # ── Signature parameters ────────────────────────────
    signer_address = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=False)
    sender = Column(String(42), nullable=False)
    recipient = Column(String(42), nullable=False)
    token_in = Column(String(42), nullable=False)
    amount_in_wei = Column(String(78), nullable=False)   # uint256 as string
    nonce = Column(String(66), nullable=False)            # bytes32 hex
    deadline = Column(BigInteger, nullable=False)

    # ── Result ──────────────────────────────────────────
    approved = Column(Boolean, nullable=False)
    denial_reason = Column(Text, nullable=True)
    risk_score = Column(Integer, nullable=True)
    risk_level = Column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_signing_audit_sender", "sender"),
        Index("ix_signing_audit_nonce", "nonce", unique=True),
        Index("ix_signing_audit_chain_ts", "chain_id", "created_at"),
    )

    def __repr__(self) -> str:
        status = "APPROVED" if self.approved else f"DENIED({self.denial_reason})"
        return (
            f"<SigningAuditLog id={self.id} chain={self.chain_id} "
            f"sender={self.sender[:10]}... {status}>"
        )
