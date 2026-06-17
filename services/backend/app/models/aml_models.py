"""
RSend AML Models — Anti-Money Laundering tables.

Tables:
  - BlacklistedWallet: legacy compatibility (existing migration)
  - SanctionEntry:     structured sanctions list (OFAC, EU, manual)
  - AMLAlert:          transaction alerts pending review
  - AMLConfig:         configurable thresholds

Separated from aml_service.py to avoid circular imports with db/session.py.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, Boolean, Text, Integer, Float, Index,
    Enum as SAEnum,
)
import enum

from app.models.db_models import Base


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class AlertType(str, enum.Enum):
    sanctions_hit = "sanctions_hit"
    threshold_single = "threshold_single"
    threshold_daily = "threshold_daily"
    threshold_monthly = "threshold_monthly"
    velocity = "velocity"
    structuring = "structuring"
    round_trip = "round_trip"
    new_wallet_high_value = "new_wallet_high_value"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    blocked = "blocked"


class AlertStatus(str, enum.Enum):
    pending = "pending"
    reviewed = "reviewed"
    escalated = "escalated"
    dismissed = "dismissed"


# ═══════════════════════════════════════════════════════════════
#  BlacklistedWallet (legacy — kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════

class BlacklistedWallet(Base):
    __tablename__ = "blacklisted_wallets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(42), unique=True, nullable=False, index=True)
    reason = Column(Text, nullable=False)  # "OFAC SDN", "Tornado Cash", "Manual"
    source = Column(String(50), nullable=False)  # "ofac", "eu", "manual", "chainalysis"
    added_by = Column(String(42), nullable=True)  # chi ha aggiunto (per manual)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
#  SanctionEntry — structured sanctions list
# ═══════════════════════════════════════════════════════════════

class SanctionEntry(Base):
    """Structured sanctions list entry (OFAC SDN, EU Consolidated, manual)."""

    __tablename__ = "sanctions_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(42), nullable=False, index=True)
    name = Column(String(200), nullable=True)           # e.g. "Tornado Cash"
    program = Column(String(50), nullable=True)          # e.g. "CYBER2", "SDGT"
    source = Column(String(50), nullable=False)          # "ofac", "eu", "manual"
    source_id = Column(String(100), nullable=True)       # ID in source list
    is_active = Column(Boolean, default=True, nullable=False)
    added_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_sanctions_address_active", "address", "is_active"),
    )


# ═══════════════════════════════════════════════════════════════
#  AMLAlert — transaction monitoring alerts
# ═══════════════════════════════════════════════════════════════

class AMLAlert(Base):
    """Transaction monitoring alert pending review by compliance officer."""

    __tablename__ = "aml_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Transaction details
    tx_hash = Column(String(66), nullable=True)
    sender = Column(String(42), nullable=False, index=True)
    recipient = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=True)
    amount_eur = Column(Float, nullable=True)
    token_symbol = Column(String(20), nullable=True)

    # Alert classification
    alert_type = Column(SAEnum(AlertType), nullable=False)
    risk_level = Column(SAEnum(RiskLevel), nullable=False)
    details = Column(Text, nullable=True)

    # Review workflow
    status = Column(SAEnum(AlertStatus), nullable=False, default=AlertStatus.pending)
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)

    requires_kyc = Column(Boolean, default=False, nullable=False)
    sar_filed = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_aml_alerts_status", "status"),
        Index("ix_aml_alerts_sender_ts", "sender", "created_at"),
    )


# ═══════════════════════════════════════════════════════════════
#  AMLConfig — configurable thresholds
# ═══════════════════════════════════════════════════════════════

class AMLConfig(Base):
    """AML threshold configuration (single row, updated by admin)."""

    __tablename__ = "aml_config"

    id = Column(Integer, primary_key=True, default=1)

    # Transaction thresholds (EUR)
    threshold_single_eur = Column(Float, nullable=False, default=1000.0)
    threshold_daily_eur = Column(Float, nullable=False, default=5000.0)
    threshold_monthly_eur = Column(Float, nullable=False, default=15000.0)

    # Velocity limits
    velocity_limit_per_hour = Column(Integer, nullable=False, default=10)

    # Structuring detection
    structuring_window_hours = Column(Integer, nullable=False, default=24)
    structuring_min_count = Column(Integer, nullable=False, default=5)
    structuring_threshold_pct = Column(Float, nullable=False, default=0.9)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
