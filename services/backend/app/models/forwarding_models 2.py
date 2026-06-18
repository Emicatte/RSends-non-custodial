"""
RSends Backend — Forwarding Models (Command Center)

Modelli:
  - ForwardingRule: regola di auto-forwarding con split routing, swap, scheduling
  - SweepLog: log di ogni operazione di sweep eseguita
  - AuditLog: audit trail per ogni modifica alle regole
"""

import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, Boolean, CheckConstraint, DateTime, Integer,
    BigInteger, Text, Index, Numeric, ForeignKey, Uuid,
    Enum as SAEnum, JSON,
)
from sqlalchemy.orm import relationship
from app.models.db_models import Base


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class GasStrategy(str, enum.Enum):
    fast = "fast"
    normal = "normal"
    slow = "slow"


class SweepStatus(str, enum.Enum):
    pending = "pending"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    gas_too_high = "gas_too_high"
    skipped = "skipped"


# ═══════════════════════════════════════════════════════════════
#  ForwardingRule — regola di auto-forwarding
# ═══════════════════════════════════════════════════════════════

class ForwardingRule(Base):
    __tablename__ = "forwarding_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    source_wallet = Column(String(42), nullable=False, index=True)
    destination_wallet = Column(String(42), nullable=True)

    # ── V2: Distribution list support ───────────────────────
    distribution_list_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("distribution_lists.id"),
        nullable=True,
    )

    # ── Label ───────────────────────────────────────────────
    label = Column(String(100), nullable=True)

    # ── Split Routing ───────────────────────────────────────
    split_enabled = Column(Boolean, default=False, nullable=False)
    split_percent = Column(Integer, default=100, nullable=False)
    split_destination = Column(String(42), nullable=True)

    # ── Condizioni ──────────────────────────────────────────
    is_active = Column(Boolean, default=True, nullable=False)
    is_paused = Column(Boolean, default=False, nullable=False)
    min_threshold = Column(Float, default=0.001, nullable=False)
    gas_strategy = Column(SAEnum(GasStrategy), default=GasStrategy.normal)
    max_gas_percent = Column(Float, default=10.0)
    gas_limit_gwei = Column(Integer, default=50, nullable=False)
    cooldown_sec = Column(Integer, default=60, nullable=False)
    max_daily_vol = Column(Numeric(28, 18), nullable=True)

    # ── Token filter ────────────────────────────────────────
    # token_address: specific ERC-20 contract address (exact match only)
    # token_filter (JSON list):
    #   []                              → match ALL tokens (ETH + any ERC-20)
    #   ["0x833589fCD6eDb6..."]         → only USDC (by address)
    #   ["native", "0x833589fCD6..."]   → ETH + USDC
    #   ["ETH", "USDC"]                → legacy symbol-based matching
    token_address = Column(String(42), nullable=True)
    token_symbol = Column(String(16), default="ETH")
    token_filter = Column(JSON, default=list)

    # ── Auto-swap ───────────────────────────────────────────
    auto_swap = Column(Boolean, default=False, nullable=False)
    swap_to_token = Column(String(42), nullable=True)

    # ── Notifiche ───────────────────────────────────────────
    notify_enabled = Column(Boolean, default=True, nullable=False)
    notify_channel = Column(String(20), default="telegram", nullable=False)
    telegram_chat_id = Column(String(50), nullable=True)
    email_address = Column(String(255), nullable=True)

    # ── Scheduling ──────────────────────────────────────────
    schedule_json = Column(JSON, nullable=True)

    # ── Chain ───────────────────────────────────────────────
    chain_id = Column(Integer, default=8453, nullable=False)

    # ── Optimistic locking ──────────────────────────────────
    version = Column(Integer, default=1, nullable=False)

    # ── Timestamps ──────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ───────────────────────────────────────
    sweep_logs = relationship("SweepLog", back_populates="rule", lazy="selectin")
    audit_logs = relationship("AuditLog", back_populates="rule", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True)
    distribution_list = relationship(
        "DistributionList", back_populates="forwarding_rules", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "destination_wallet IS NOT NULL OR distribution_list_id IS NOT NULL",
            name="ck_fwd_dest_or_distlist",
        ),
        Index("ix_fwd_source_active", "source_wallet", "is_active"),
        Index("ix_fwd_user_chain", "user_id", "chain_id"),
        Index("ix_fwd_paused", "is_paused", "is_active"),
        Index("ix_fwd_dist_list", "distribution_list_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  SweepLog — log di ogni operazione di sweep
# ═══════════════════════════════════════════════════════════════

class SweepLog(Base):
    __tablename__ = "sweep_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("forwarding_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    source_wallet = Column(String(42), nullable=False)
    destination_wallet = Column(String(42), nullable=False)

    # ── Split info ──────────────────────────────────────────
    is_split = Column(Boolean, default=False)
    split_index = Column(Integer, default=0)
    split_percent = Column(Integer, default=100)
    split_tx_hash = Column(String(66), nullable=True)

    # ── Amounts ─────────────────────────────────────────────
    amount_wei = Column(String(78), nullable=False)
    amount_human = Column(Float, nullable=False)
    amount_display = Column(Numeric(28, 18), nullable=False, default=0)
    amount_usd = Column(Numeric(18, 2), nullable=True)
    primary_amount = Column(Numeric(28, 18), nullable=True)
    split_amount = Column(Numeric(28, 18), nullable=True)
    token_symbol = Column(String(16), default="ETH")

    # ── Gas ──────────────────────────────────────────────────
    gas_used = Column(BigInteger, nullable=True)
    gas_price_gwei = Column(Numeric(12, 4), nullable=True)
    gas_cost_eth = Column(Numeric(28, 18), nullable=True)
    gas_percent = Column(Float, nullable=True)

    # ── Status ──────────────────────────────────────────────
    status = Column(SAEnum(SweepStatus), default=SweepStatus.pending)
    tx_hash = Column(String(66), nullable=True, unique=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    trigger_tx_hash = Column(String(66), nullable=True)

    # ── Compliance ──────────────────────────────────────────
    fiscal_ref = Column(String(50), nullable=True)
    compliance_check = Column(Boolean, default=False, nullable=False)

    # ── Timestamps ──────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ───────────────────────────────────────
    rule = relationship("ForwardingRule", back_populates="sweep_logs")

    __table_args__ = (
        Index("ix_sweep_status", "status", "created_at"),
        Index("ix_sweep_rule_status", "rule_id", "status"),
        Index("ix_sweep_executed", "executed_at"),
        Index("ix_sweep_fiscal", "fiscal_ref"),
        Index("ix_sweep_trigger_rule", "trigger_tx_hash", "rule_id"),
    )


# ═══════════════════════════════════════════════════════════════
#  AuditLog — audit trail modifiche regole
# ═══════════════════════════════════════════════════════════════

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id = Column(
        Integer,
        ForeignKey("forwarding_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = Column(String(50), nullable=False)
    actor = Column(String(42), nullable=False)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # ── Relationships ───────────────────────────────────────
    rule = relationship("ForwardingRule", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_rule_action", "rule_id", "action"),
        Index("ix_audit_actor", "actor"),
        Index("ix_audit_created", "created_at"),
    )
