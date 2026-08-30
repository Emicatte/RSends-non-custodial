"""
RSends Backend — On-Chain Settlement Record (non-custodial).

Replaces the custodial double-entry ledger. In the non-custodial model RSends
never holds funds: the payer pays the `RSendsRouter` contract directly and the
contract forwards funds to the merchant atomically, emitting a `PaymentMade`
event. We do NOT track internal balances — we persist the on-chain settlement
facts (the decoded `PaymentMade` events) and use them to mark invoices paid.

PaymentMade(
    bytes32 indexed invoiceId,
    address indexed merchant,
    address indexed payer,
    address token,          # address(0) == native ETH
    uint256 amount,
    uint256 fee,            # paid payer -> feeCollector (on top of amount)
    uint256 blockTimestamp
)

Idempotency: a log is uniquely identified on-chain by (chain_id, tx_hash,
log_index). The UniqueConstraint makes re-processing the same event a no-op,
so the indexer can safely re-scan overlapping block ranges.

Reorg safety: every row stores its `block_hash` and a `status` lifecycle
(pending -> final, pending/final -> reorged, or rejected on validation
mismatch). An invoice is marked paid and its webhook fired ONLY when the
settlement reaches `final` with a still-canonical block hash; if a later
canonical-hash check fails the row is flipped to `reorged` and the effect is
reversed. See app/services/payment_indexer.py.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)

from app.models.db_models import Base


class SettlementStatus(str, enum.Enum):
    """Lifecycle of an on-chain settlement record."""
    pending = "pending"    # log seen, not yet final — invoice NOT paid yet
    final = "final"        # finalized + canonical hash verified — invoice paid, webhook fired
    reorged = "reorged"    # block hash no longer canonical / log gone — effect reversed
    rejected = "rejected"  # correct invoiceId but failed merchant/token/amount validation


class PaymentSettlement(Base):
    """One row per on-chain RSendsRouter.PaymentMade event."""
    __tablename__ = "payment_settlements"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Decoded event fields ────────────────────────────────────
    # invoiceId is a bytes32; stored as 0x-prefixed 66-char hex string.
    # NULLABLE since 0018: only a router emits an invoiceId. A watch-only
    # settlement is a bare TRC-20 Transfer to the merchant's own address and has
    # none — and a synthetic value would make this table, which records what
    # happened on-chain, claim a contract emitted something it never did.
    # Dedup does not depend on it: the idempotency key is
    # (chain_id, tx_hash, log_index), see uq_settlement_onchain_log below.
    invoice_id = Column(String(66), nullable=True, index=True)
    merchant = Column(String(42), nullable=False, index=True)
    payer = Column(String(42), nullable=False)
    # token == "0x0000...0000" for native ETH.
    token = Column(String(42), nullable=False)
    # On-chain base units (wei / token decimals). Numeric, never float.
    amount = Column(Numeric(78, 0), nullable=False)
    # Flat on-chain fee paid payer -> feeCollector (base units). Nullable for rows
    # settled before the router emitted `fee`; new settlements always populate it.
    fee = Column(Numeric(78, 0), nullable=True)
    block_timestamp = Column(DateTime(timezone=True), nullable=True)

    # ── On-chain coordinates (idempotency key) ──────────────────
    # BigInteger, not Integer (widened in migration 0020): a TRON chain id is
    # the low 4 bytes of that network's genesis hash read as UNSIGNED, and
    # Nile's (3448148188) is past the 2147483647 ceiling of a Postgres INTEGER.
    # SQLite stores it either way, so the suite cannot catch a regression here —
    # test_migrations_postgres.py::test_a_tron_testnet_chain_id_fits_after_0020
    # is the one that can.
    chain_id = Column(BigInteger, nullable=False, index=True)
    tx_hash = Column(String(66), nullable=False)
    log_index = Column(Integer, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    # Canonical block hash this log was observed in. Used for reorg detection:
    # a re-inclusion in a different block changes this; a reorged-out log fails
    # the canonical-hash check at finalization. Nullable for legacy rows.
    block_hash = Column(String(66), nullable=True)

    # ── Reorg-safe lifecycle ────────────────────────────────────
    status = Column(
        SAEnum(SettlementStatus, name="settlement_status"),
        default=SettlementStatus.pending,
        nullable=False,
        index=True,
    )
    # When the row reached `final` (canonical + finalized).
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    # "Fire webhook exactly once" guard — set when payment.completed is dispatched.
    # Claimed via an atomic conditional UPDATE so two concurrent finalizations of
    # the same settlement can't double-fire. See payment_indexer._finalize_settlement.
    webhook_fired_at = Column(DateTime(timezone=True), nullable=True)
    # Same guard for the payment.reversed webhook on a reorg-after-finalize, so
    # two concurrent reconciles can't double-fire the reversal.
    reversal_fired_at = Column(DateTime(timezone=True), nullable=True)

    # ── Linkage to the off-chain intent (best-effort match) ─────
    intent_id = Column(String(64), nullable=True, index=True)

    # ── Split fan-out detail (RSendsSplitRouter.SplitPaymentMade) ─
    # One settlement row per split payment (the event is aggregate — atomicity
    # is structural); the validated per-leg breakdown is recorded here:
    # [{"address", "share_bps", "amount"}], index 0 = primary. NULL for
    # single-recipient (PaymentMade) settlements.
    split_legs = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # Same on-chain log can never produce two settlement rows.
        UniqueConstraint(
            "chain_id", "tx_hash", "log_index", name="uq_settlement_onchain_log"
        ),
        Index("ix_settlement_invoice", "invoice_id", "chain_id"),
        Index("ix_settlement_merchant_created", "merchant", "created_at"),
        # Drives the finalize/reconcile query (pending + recent final per chain).
        Index("ix_settlement_chain_status", "chain_id", "status"),
    )
