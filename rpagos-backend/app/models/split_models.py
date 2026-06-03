"""
Multi-Wallet Split System — Data Models

Un SplitContract è una configurazione immutabile che definisce
come un pagamento viene diviso tra N destinatari.

Ogni SplitContract è legato a un cliente e viene creato
al momento della firma del contratto. Non è modificabile:
per cambiare, si crea una nuova versione.

Note:
  - Le percentuali sono SEMPRE in basis points (interi).
    10000 = 100.00%, 9500 = 95.00%, 300 = 3.00%, 1 = 0.01%.
  - La somma degli share_bps dei recipient attivi di un contratto
    deve essere ESATTAMENTE 10000. Il vincolo sum==10000 non è
    esprimibile come CheckConstraint di colonna (è cross-row);
    va applicato dal service layer prima del commit.
  - Il sistema split N-wallet COESISTE con il vecchio split 2-way
    in forwarding_rules: non tocca ForwardingRule, è additivo.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.orm import relationship

# Base è definito in db_models.py (come per forwarding_models, ledger_models, ecc.)
from app.models.db_models import Base


class SplitContract(Base):
    """
    Configurazione split per un cliente.
    Immutabile dopo creazione — modifiche = nuova versione.
    """
    __tablename__ = "split_contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificazione cliente/contratto
    client_id = Column(String, nullable=False, index=True)   # ID univoco cliente
    client_name = Column(String, nullable=True)               # Nome/ragione sociale
    contract_ref = Column(String, nullable=True)              # Riferimento contratto esterno
    version = Column(Integer, nullable=False, default=1)      # Versione config

    # Master wallet (riceve il pagamento iniziale)
    master_wallet = Column(String(42), nullable=False)        # 0x... address

    # Owner del contratto (chi può modificarlo via wallet auth).
    # nullable=True in questa migration additiva — verrà reso NOT NULL
    # in commit successivo dopo backfill verificato.
    # String(42) per wallet EVM ("0x" + 40 hex), normalizzato lowercase.
    owner_address = Column(String(42), nullable=True, index=True)

    # Chain
    chain_id = Column(Integer, nullable=False, default=8453)  # Base default
    chain_family = Column(String(10), default="evm")

    # Token supportati (null = tutti)
    allowed_tokens = Column(String, nullable=True)            # JSON: ["USDC","USDT","ETH"] o null

    # Stato
    is_active = Column(Boolean, default=True)
    is_locked = Column(Boolean, default=False)                # True dopo prima esecuzione
    superseded_by = Column(Integer, nullable=True)            # ID della versione successiva

    # Fee RSend (in BPS, es: 50 = 0.50%)
    rsend_fee_bps = Column(Integer, default=50)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    locked_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)

    # Relationships
    recipients = relationship(
        "SplitRecipient",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="SplitRecipient.position",
    )
    executions = relationship(
        "SplitExecution",
        back_populates="contract",
        cascade="all, delete-orphan",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("client_id", "version", name="uq_client_version"),
        CheckConstraint("rsend_fee_bps >= 0", name="ck_split_contract_fee_nonneg"),
        CheckConstraint("rsend_fee_bps <= 10000", name="ck_split_contract_fee_max"),
        Index("ix_split_contract_client_active", "client_id", "is_active"),
    )


class SplitRecipient(Base):
    """
    Singolo destinatario in un SplitContract.
    Le percentuali sono in basis points (BPS): 10000 = 100.00%.
    La somma degli share_bps dei recipient attivi per uno stesso
    contract_id deve essere ESATTAMENTE 10000 (invariante applicato
    dal service layer — non esprimibile come CheckConstraint).
    """
    __tablename__ = "split_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(
        Integer,
        ForeignKey("split_contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Destinatario
    wallet_address = Column(String(42), nullable=False)       # 0x... address
    label = Column(String, nullable=True)                      # "Azienda", "Affiliato", etc.
    role = Column(String(20), default="recipient")             # "primary", "commission", "fee"

    # Percentuale in BASIS POINTS (interi)
    # 9500 = 95.00%, 300 = 3.00%, 200 = 2.00%, 1 = 0.01%
    share_bps = Column(Integer, nullable=False)

    # Ordine (per determinismo nella distribuzione)
    position = Column(Integer, nullable=False, default=0)

    # Metadata
    is_active = Column(Boolean, default=True)

    # Relationships
    contract = relationship("SplitContract", back_populates="recipients")

    # Constraints
    __table_args__ = (
        CheckConstraint("share_bps > 0", name="ck_share_positive"),
        CheckConstraint("share_bps <= 10000", name="ck_share_max"),
        UniqueConstraint("contract_id", "position", name="uq_split_recipient_position"),
        Index("ix_split_recipient_contract", "contract_id", "is_active"),
    )


class SplitExecution(Base):
    """
    Record di una singola esecuzione split.
    Traccia ogni distribuzione per audit e compliance.
    """
    __tablename__ = "split_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(
        Integer,
        ForeignKey("split_contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Input
    source_tx_hash = Column(String, nullable=False)           # TX che ha triggerato lo split
    input_amount = Column(String, nullable=False)              # Importo ricevuto (stringa per precisione)
    input_token = Column(String, nullable=False)               # "USDC", "ETH", etc.
    input_decimals = Column(Integer, nullable=False)           # 6 per USDC, 18 per ETH

    # Stato esecuzione
    status = Column(String(20), default="pending")
    # pending → executing → completed / partial_failure / failed

    # Output
    total_distributed = Column(String, nullable=True)          # Somma effettivamente distribuita
    rsend_fee = Column(String, nullable=True)                  # Fee RSend trattenuta
    remainder = Column(String, default="0")                    # Resto da rounding (in unità minime)

    # Timing
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Dettagli per recipient (JSON array serializzato come stringa)
    # [{"wallet": "0x...", "share_bps": 9500, "amount": "950000", "tx_hash": "0x...", "status": "sent"}]
    distribution_detail = Column(String, nullable=True)

    # Relationships
    contract = relationship("SplitContract", back_populates="executions")

    __table_args__ = (
        Index("ix_split_execution_contract_status", "contract_id", "status"),
        Index("ix_split_execution_source_tx", "source_tx_hash"),
        # Idempotency gate (C1a): one execution per (contract, source TX).
        # Enforces atomically — under concurrent webhook deliveries the 2nd
        # INSERT fails with IntegrityError BEFORE any on-chain TX is sent,
        # preventing a double split payout.
        UniqueConstraint(
            "contract_id", "source_tx_hash", name="uq_split_exec_contract_srctx"
        ),
    )
