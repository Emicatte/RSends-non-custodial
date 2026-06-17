"""Pydantic schemas per le fatture delle commissioni (Step 3).

- InvoiceCreateRequest: body del POST (periodo; owner_address opzionale → di
  default risolto dal wallet primario dell'org attiva, come Step 2).
- InvoiceResponse / InvoiceListResponse: lettura. Gli importi sono Decimal
  (serializzati come stringa in JSON da FastAPI) per non perdere precisione.
  I campi tax_* sono nullable (PARAMETRICI-vuoti).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class InvoiceCreateRequest(BaseModel):
    period_start: datetime
    period_end: datetime
    # Opzionale: se assente, la route usa il wallet primario dell'org attiva.
    owner_address: Optional[str] = None

    @field_validator("owner_address")
    @classmethod
    def _norm_owner(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        return v or None

    @model_validator(mode="after")
    def _check_period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end_before_start")
        return self


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # NULL finché draft: il numero è assegnato solo all'emissione.
    invoice_number: Optional[str] = None
    owner_address: str
    period_start: datetime
    period_end: datetime

    tx_count: int
    unit_price_eur: Decimal
    subtotal_eur: Decimal

    tax_regime: Optional[str] = None
    tax_rate: Optional[Decimal] = None
    tax_amount_eur: Optional[Decimal] = None
    tax_note: Optional[str] = None

    total_eur: Decimal
    status: str

    issued_at: Optional[datetime] = None
    created_at: datetime

    snapshot_issuer: Optional[dict] = None
    snapshot_client: Optional[dict] = None

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v):
        return str(v) if v is not None else v


class InvoiceListResponse(BaseModel):
    invoices: List[InvoiceResponse]
