"""
RSends Backend — Ledger Models (Double-Entry Bookkeeping).

Tabelle:
  - accounts: conti contabili (merchant, fee, escrow, ecc.)
  - transactions: transazioni di alto livello con state machine
  - ledger_entries: scritture di partita doppia (DEBIT/CREDIT)
  - transaction_state_log: audit trail delle transizioni di stato
  - audit_log: audit log di sistema (BIGSERIAL, append-only)

Compatibilità cross-dialect:
  - PostgreSQL: JSONB, INET nativi
  - SQLite (dev): JSON, VARCHAR(45) via TypeDecorator
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    JSON,
    Uuid,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import relationship

from sqlalchemy.sql import func as sa_func

from app.models.db_models import Base


# ═══════════════════════════════════════════════════════════════
#  TypeDecorators — cross-dialect compatibility
# ═══════════════════════════════════════════════════════════════

class JSONBType(TypeDecorator):
    """JSONB su PostgreSQL, JSON su SQLite/altri dialect."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class InetType(TypeDecorator):
    """INET su PostgreSQL, VARCHAR(45) su SQLite/altri dialect."""
    impl = String(45)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(INET())
        return dialect.type_descriptor(String(45))


class BigIntegerType(TypeDecorator):
    """BIGINT su PostgreSQL, INTEGER su SQLite (per autoincrement)."""
    impl = BigInteger
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        return dialect.type_descriptor(BigInteger())


# ═══════════════════════════════════════════════════════════════
#  Account
# ═══════════════════════════════════════════════════════════════

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_type = Column(String(64), nullable=False)
    address = Column(String(42), nullable=True)
    currency = Column(String(16), nullable=False)
    label = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, server_default=sa.true(), nullable=False)
    # ATTENZIONE: "metadata" è attributo riservato su DeclarativeBase →
    # attributo Python = metadata_, colonna DB = metadata
    metadata_ = Column("metadata", JSONBType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    ledger_entries = relationship(
        "LedgerEntry", back_populates="account", lazy="selectin"
    )


# ═══════════════════════════════════════════════════════════════
#  Transaction (double-entry) — diversa dalla legacy transaction_logs
# ═══════════════════════════════════════════════════════════════

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    tx_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    tx_hash = Column(String(66), nullable=True)
    chain_id = Column(Integer, nullable=True)
    reference = Column(String(256), nullable=True)
    metadata_ = Column("metadata", JSONBType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    ledger_entries = relationship(
        "LedgerEntry", back_populates="transaction", lazy="selectin"
    )
    state_logs = relationship(
        "TransactionStateLog", back_populates="transaction", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','AUTHORIZED','PROCESSING','COMPLETED','FAILED','REVERSED')",
            name="ck_transaction_status",
        ),
        Index("idx_tx_idempotency", "idempotency_key"),
        Index("idx_tx_status", "status"),
        Index("idx_tx_hash", "tx_hash"),
    )


# ═══════════════════════════════════════════════════════════════
#  LedgerEntry — scrittura contabile DEBIT/CREDIT
# ═══════════════════════════════════════════════════════════════

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    account_id = Column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    entry_type = Column(String(6), nullable=False)
    # NUMERIC(28,18): mai Float per campi monetari
    amount = Column(Numeric(28, 18), nullable=False)
    currency = Column(String(16), nullable=False)
    balance_after = Column(Numeric(28, 18), nullable=False)
    metadata_ = Column("metadata", JSONBType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    transaction = relationship("Transaction", back_populates="ledger_entries")
    account = relationship("Account", back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('DEBIT','CREDIT')", name="ck_entry_type"
        ),
        CheckConstraint("amount > 0", name="ck_ledger_amount_positive"),
        Index("idx_ledger_account", "account_id", "created_at"),
        Index("idx_ledger_tx", "transaction_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  TransactionStateLog — audit trail transizioni di stato
# ═══════════════════════════════════════════════════════════════

class TransactionStateLog(Base):
    __tablename__ = "transaction_state_log"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    triggered_by = Column(String(64), nullable=True)
    ip_address = Column(InetType, nullable=True)
    user_agent = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONBType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    transaction = relationship("Transaction", back_populates="state_logs")

    __table_args__ = (
        Index("idx_state_log_tx", "transaction_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  LedgerAuditLog — audit log di sistema (append-only, BIGSERIAL)
#  NOTA: tabella "audit_log" (singolare) ≠ "audit_logs" (plurale,
#        già esistente in forwarding_models.py per le forwarding rules)
# ═══════════════════════════════════════════════════════════════

class LedgerAuditLog(Base):
    """Append-only audit log with chain hash for tamper detection.

    chain_hash = SHA-256(previous_hash || event_type || entity_type ||
                         entity_id || actor_id || created_at)
    First entry uses previous_hash = "0" * 64.
    Any gap in sequence_number or broken hash chain indicates tampering.
    """
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


# ═══════════════════════════════════════════════════════════════
#  DailySnapshot — immutable daily reconciliation snapshots
# ═══════════════════════════════════════════════════════════════

class DailySnapshot(Base):
    """Immutable daily snapshot of on-chain vs ledger balances.

    One row per (date, chain_id) pair. Status:
      - 'ok': discrepancy within threshold
      - 'mismatch': discrepancy > threshold but < critical
      - 'critical': discrepancy triggered circuit breaker
    """
    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(sa.Date, nullable=False)
    chain_id = Column(Integer, nullable=False)
    treasury_address = Column(String(42), nullable=False)
    on_chain_balance = Column(Numeric(28, 18), nullable=False)
    ledger_balance = Column(Numeric(28, 18), nullable=False)
    diff = Column(Numeric(28, 18), nullable=False)
    diff_pct = Column(Numeric(10, 6), nullable=False)
    status = Column(String(16), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=sa_func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','mismatch','critical')",
            name="ck_snapshot_status",
        ),
        Index("ix_daily_snapshot_date_chain", "date", "chain_id", unique=True),
    )
