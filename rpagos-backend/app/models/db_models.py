"""
RPagos Backend Core — Modelli SQLAlchemy.

Mappatura 1:1 con i dati generati da TransactionStatus.tsx:
  - TransactionLog: ogni callback POST ricevuto
  - ComplianceSnapshot: record MiCA collegato
  - AnomalyAlert: segnalazioni generate dall'analizzatore
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, Integer,
    Text, ForeignKey, Index, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class TxStatus(str, enum.Enum):
    completed = "completed"
    failed = "failed"
    pending = "pending"
    cancelled = "cancelled"


class AnomalyType(str, enum.Enum):
    volume_spike = "volume_spike"
    amount_outlier = "amount_outlier"
    frequency_burst = "frequency_burst"
    unusual_network = "unusual_network"


# ═══════════════════════════════════════════════════════════════
#  TransactionLog — ricezione callback dal frontend
# ═══════════════════════════════════════════════════════════════

class TransactionLog(Base):
    __tablename__ = "transaction_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificativi
    fiscal_ref = Column(String(128), unique=True, nullable=False, index=True)
    payment_ref = Column(String(128), nullable=True)
    tx_hash = Column(String(66), unique=True, nullable=False, index=True)

    # Importi (dal frontend: grossStr, netStr, feeStr)
    gross_amount = Column(Float, nullable=False)
    net_amount = Column(Float, nullable=False)
    fee_amount = Column(Float, nullable=False)
    currency = Column(String(16), nullable=False)          # "USDC", "ETH"
    eur_value = Column(Float, nullable=True)               # eurValue dal frontend

    # Rete e stato
    network = Column(String(32), nullable=False)           # "BASE_MAINNET", "BASE_SEPOLIA"
    status = Column(SAEnum(TxStatus), nullable=False, default=TxStatus.completed)
    recipient = Column(String(42), nullable=True)

    # Sicurezza
    x_signature = Column(String(256), nullable=False)
    signature_valid = Column(Boolean, default=False)

    # Timestamps
    tx_timestamp = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relazione con compliance
    compliance = relationship(
        "ComplianceSnapshot", back_populates="transaction", uselist=False
    )

    __table_args__ = (
        Index("ix_tx_currency_date", "currency", "tx_timestamp"),
        Index("ix_tx_status_date", "status", "tx_timestamp"),
    )


# ═══════════════════════════════════════════════════════════════
#  ComplianceSnapshot — record MiCA
# ═══════════════════════════════════════════════════════════════

class ComplianceSnapshot(Base):
    __tablename__ = "compliance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(
        Integer, ForeignKey("transaction_logs.id"), unique=True, nullable=False
    )

    # Dati dal ComplianceRecord del frontend
    compliance_id = Column(String(64), unique=True, nullable=False)
    block_timestamp = Column(String(64), nullable=True)
    fiat_rate = Column(Float, nullable=True)               # tasso di cambio crypto→EUR
    asset = Column(String(16), nullable=True)              # simbolo crypto
    fiat_gross = Column(Float, nullable=True)              # controvalore EUR lordo
    ip_jurisdiction = Column(String(8), nullable=True)     # es. "IT"
    mica_applicable = Column(Boolean, default=False)
    network = Column(String(32), nullable=True)

    # Fiscal
    fiscal_ref = Column(String(128), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    transaction = relationship("TransactionLog", back_populates="compliance")


# ═══════════════════════════════════════════════════════════════
#  AnomalyAlert — segnalazioni dall'analizzatore
# ═══════════════════════════════════════════════════════════════

class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anomaly_type = Column(SAEnum(AnomalyType), nullable=False)
    z_score = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    affected_tx_count = Column(Integer, default=0)
    resolved = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
