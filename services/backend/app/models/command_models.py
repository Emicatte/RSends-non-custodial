"""
RSends Backend — Command Center Models.

Tabelle:
  - distribution_lists: liste di distribuzione multi-destinatario
  - distribution_recipients: destinatari di una lista (bps sum = 10000 in app layer)
  - sweep_batches: batch di sweep con idempotenza su incoming_tx_hash
  - sweep_batch_items: singoli trasferimenti dentro un batch
  - spending_ledger: log persistente di reserve/release spending policy
  - nonce_tracker: gestione nonce per hot wallet
  - circuit_breaker_states: stato persistente dei circuit breaker
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from app.models.db_models import Base
from app.models.ledger_models import JSONBType


# ═══════════════════════════════════════════════════════════════
#  DistributionList — lista di distribuzione multi-destinatario
# ═══════════════════════════════════════════════════════════════

class DistributionList(Base):
    __tablename__ = "distribution_lists"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_address = Column(String(42), nullable=False)
    label = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    chain_id = Column(Integer, default=8453, nullable=False)
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

    # Relationships
    recipients = relationship(
        "DistributionRecipient",
        back_populates="distribution_list",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    forwarding_rules = relationship(
        "ForwardingRule",
        back_populates="distribution_list",
        lazy="selectin",
    )
    sweep_batches = relationship(
        "SweepBatch",
        back_populates="distribution_list",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_dist_list_owner", "owner_address", "chain_id"),
        Index("ix_dist_list_active", "is_active"),
    )


# ═══════════════════════════════════════════════════════════════
#  DistributionRecipient — destinatario in una lista
#
#  Vincolo: SUM(percent_bps) per list_id = 10000 → app layer
#  DB enforces: 1 ≤ percent_bps ≤ 10000, no duplicate (list,addr)
# ═══════════════════════════════════════════════════════════════

class DistributionRecipient(Base):
    __tablename__ = "distribution_recipients"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("distribution_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    address = Column(String(42), nullable=False)
    percent_bps = Column(Integer, nullable=False)
    label = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    distribution_list = relationship(
        "DistributionList", back_populates="recipients"
    )

    __table_args__ = (
        CheckConstraint(
            "percent_bps >= 1 AND percent_bps <= 10000",
            name="ck_recipient_bps_range",
        ),
        UniqueConstraint("list_id", "address", name="uq_recipient_list_addr"),
        Index("ix_recipient_list_active", "list_id", "is_active"),
    )


# ═══════════════════════════════════════════════════════════════
#  SweepBatch — batch di sweep, idempotent su incoming_tx_hash
# ═══════════════════════════════════════════════════════════════

class SweepBatch(Base):
    __tablename__ = "sweep_batches"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incoming_tx_hash = Column(String(66), nullable=False, unique=True)
    source_address = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=False)
    total_amount_wei = Column(String(78), nullable=False)
    token_address = Column(String(42), nullable=True)
    token_symbol = Column(String(16), default="ETH", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    forwarding_rule_id = Column(
        Integer,
        ForeignKey("forwarding_rules.id"),
        nullable=True,
    )
    distribution_list_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("distribution_lists.id"),
        nullable=True,
    )
    gas_price_wei = Column(String(78), nullable=True)
    total_gas_cost_wei = Column(String(78), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    metadata_ = Column("metadata", JSONBType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    items = relationship(
        "SweepBatchItem",
        back_populates="batch",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    forwarding_rule = relationship("ForwardingRule", lazy="selectin")
    distribution_list = relationship(
        "DistributionList", back_populates="sweep_batches"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','FAILED','PARTIAL')",
            name="ck_sweep_batch_status",
        ),
        Index("ix_batch_status_created", "status", "created_at"),
        Index("ix_batch_source_chain", "source_address", "chain_id"),
        Index("ix_batch_rule", "forwarding_rule_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  SweepBatchItem — singolo trasferimento in un batch
# ═══════════════════════════════════════════════════════════════

class SweepBatchItem(Base):
    __tablename__ = "sweep_batch_items"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("sweep_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_address = Column(String(42), nullable=False)
    amount_wei = Column(String(78), nullable=False)
    percent_bps = Column(Integer, nullable=False)
    tx_hash = Column(String(66), nullable=True, unique=True)
    status = Column(String(32), default="PENDING", nullable=False)
    nonce = Column(Integer, nullable=True)
    gas_used = Column(BigInteger, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    batch = relationship("SweepBatch", back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','SIGNING','SUBMITTED','CONFIRMED','FAILED','RETRYING')",
            name="ck_batch_item_status",
        ),
        CheckConstraint(
            "percent_bps >= 1 AND percent_bps <= 10000",
            name="ck_batch_item_bps_range",
        ),
        Index("ix_item_batch_status", "batch_id", "status"),
    )


# ═══════════════════════════════════════════════════════════════
#  SpendingLedger — log persistente delle reserve/release
# ═══════════════════════════════════════════════════════════════

class SpendingLedger(Base):
    __tablename__ = "spending_ledger"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_address = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=False)
    amount_wei = Column(String(78), nullable=False)
    direction = Column(String(8), nullable=False)
    tier = Column(String(32), nullable=False)
    sweep_batch_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("sweep_batches.id"),
        nullable=True,
    )
    reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "direction IN ('RESERVE','RELEASE')",
            name="ck_spending_direction",
        ),
        CheckConstraint(
            "tier IN ('per_tx','per_hour','per_day','global_daily','velocity')",
            name="ck_spending_tier",
        ),
        Index("ix_spending_source_chain", "source_address", "chain_id", "created_at"),
        Index("ix_spending_created", "created_at"),
        Index("ix_spending_batch", "sweep_batch_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  NonceTracker — gestione nonce hot wallet
# ═══════════════════════════════════════════════════════════════

class NonceTracker(Base):
    __tablename__ = "nonce_tracker"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain_id = Column(Integer, nullable=False)
    address = Column(String(42), nullable=False)
    current_nonce = Column(Integer, nullable=False, default=0)
    last_confirmed_nonce = Column(Integer, nullable=False, default=0)
    pending_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("chain_id", "address", name="uq_nonce_chain_addr"),
        CheckConstraint(
            "current_nonce >= last_confirmed_nonce",
            name="ck_nonce_ordering",
        ),
        CheckConstraint("pending_count >= 0", name="ck_nonce_pending_gte0"),
    )


# ═══════════════════════════════════════════════════════════════
#  CircuitBreakerState — stato persistente dei circuit breaker
# ═══════════════════════════════════════════════════════════════

class CircuitBreakerState(Base):
    __tablename__ = "circuit_breaker_states"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), unique=True, nullable=False)
    state = Column(String(16), default="CLOSED", nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    force_reason = Column(Text, nullable=True)
    error_rate = Column(Float, nullable=True)
    metadata_ = Column("metadata", JSONBType, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('CLOSED','OPEN','HALF_OPEN')",
            name="ck_cb_state_valid",
        ),
        CheckConstraint("failure_count >= 0", name="ck_cb_failures_gte0"),
        CheckConstraint("success_count >= 0", name="ck_cb_successes_gte0"),
    )
