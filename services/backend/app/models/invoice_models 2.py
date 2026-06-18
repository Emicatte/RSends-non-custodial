"""Modelli Invoice + InvoiceCounter — fattura aggregata delle commissioni.

Scenario: RPagos EMETTE la fattura al cliente. Modello: N transazioni del periodo
× €0,01 flat. Importi sempre in EUR/Decimal (Numeric), mai float.

- Invoice: la fattura emessa, ancorata a owner_address (== PaymentIntent.merchant_id
  == MerchantProfile.owner_address). snapshot_issuer/snapshot_client sono copie
  IMMUTABILI dei dati emittente+cliente al momento della creazione (una fattura non
  deve cambiare se l'anagrafica cambia dopo).
- InvoiceCounter: contatore progressivo per-anno per la numerazione FAT-{anno}-{seq:06d}.
  La progressività atomica gap-free è garantita nel service (SELECT ... FOR UPDATE
  nella stessa transazione dell'INSERT della fattura). Vedi invoice_service.py.

Il blocco IVA/regime (tax_*) resta PARAMETRICO-vuoto: nullable, lo riempie il
commercialista. Nessun valore fiscale è calcolato/inventato qui.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)

from app.models.db_models import Base
from app.models.ledger_models import JSONBType


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Numero progressivo globale RPagos — formato FAT-{YEAR}-{seq:06d}.
    # NULL finché la fattura è draft: il numero viene assegnato SOLO all'emissione
    # (issue), così i draft abbandonati non bruciano numeri della sequenza emessa.
    # Postgres/SQLite ammettono più NULL sotto un indice unique → nessun conflitto.
    invoice_number = Column(String(32), nullable=True, unique=True, index=True)

    # Cliente fatturato — join a MerchantProfile/PaymentIntent.merchant_id (lowercase).
    owner_address = Column(String(42), nullable=False, index=True)

    # Periodo di riferimento (datetime UTC espliciti).
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    # Aggregazione commissioni (EUR, Decimal).
    tx_count = Column(Integer, nullable=False)
    unit_price_eur = Column(Numeric(28, 18), nullable=False)
    subtotal_eur = Column(Numeric(28, 18), nullable=False)

    # ── Blocco IVA/regime PARAMETRICO (nullable, riempito dal commercialista) ──
    tax_regime = Column(String(64), nullable=True)
    tax_rate = Column(Numeric(9, 6), nullable=True)
    tax_amount_eur = Column(Numeric(28, 18), nullable=True)
    tax_note = Column(Text, nullable=True)

    # Totale = subtotal + (tax_amount o 0).
    total_eur = Column(Numeric(28, 18), nullable=False)

    status = Column(String(16), nullable=False, default="draft")  # draft | issued

    issued_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Snapshot immutabili al momento della creazione.
    snapshot_issuer = Column(JSONBType, nullable=True)
    snapshot_client = Column(JSONBType, nullable=True)

    __table_args__ = (
        # Anti-doppione: una sola fattura per cliente+periodo.
        UniqueConstraint(
            "owner_address",
            "period_start",
            "period_end",
            name="uq_invoices_owner_period",
        ),
        Index("ix_invoices_owner_created", "owner_address", "created_at"),
    )


class InvoiceCounter(Base):
    """Contatore progressivo per-anno della numerazione fatture.

    Una riga per anno. Il service blocca la riga con SELECT ... FOR UPDATE e
    incrementa last_seq nella stessa transazione dell'INSERT della fattura →
    numerazione gap-free e senza duplicati sotto concorrenza.
    """

    __tablename__ = "invoice_counters"

    year = Column(Integer, primary_key=True)
    last_seq = Column(Integer, nullable=False, default=0)
