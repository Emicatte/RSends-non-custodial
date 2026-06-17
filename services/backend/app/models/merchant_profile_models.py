"""MerchantProfile — anagrafica di fatturazione B2B del merchant.

Ancorata al wallet (owner_address). Destinatario delle future fatture aggregate (Step 3).
owner_address == ApiKey.owner_address == PaymentIntent.merchant_id (per valore).
Tutti i campi billing_* sono nullable: un merchant senza profilo resta valido finché non si fattura.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text, Uuid

from app.models.db_models import Base
from app.models.ledger_models import JSONBType


class MerchantProfile(Base):
    __tablename__ = "merchant_profiles"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Ancora del merchant — chiave di join verso PaymentIntent.merchant_id
    owner_address = Column(String(42), nullable=False, unique=True, index=True)

    # Dati di fatturazione (tutti nullable, additivi)
    billing_legal_name = Column(Text, nullable=True)    # ragione sociale legale
    billing_vat_number = Column(Text, nullable=True)    # VAT / tax id (UE + extra-UE)
    billing_tax_code = Column(Text, nullable=True)      # codice fiscale (opzionale)
    billing_address_line = Column(Text, nullable=True)
    billing_city = Column(Text, nullable=True)
    billing_postal_code = Column(Text, nullable=True)
    billing_country = Column(Text, nullable=True)       # ISO/nome — serve per regime IVA Step 3
    billing_email = Column(Text, nullable=True)         # email amministrativa fattura
    billing_pec = Column(Text, nullable=True)           # opzionale, solo clienti IT

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    metadata_ = Column("metadata", JSONBType, nullable=True)
