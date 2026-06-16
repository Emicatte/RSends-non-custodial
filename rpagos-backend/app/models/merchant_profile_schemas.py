"""Pydantic schemas per MerchantProfile (anagrafica di fatturazione B2B).

Usate dalle route dashboard org-scoped (merchant_profile_routes.py):
- MerchantProfileResponse  → GET/PUT response (owner_address risolto + 9 campi billing_*)
- MerchantProfileUpdateRequest → PUT body (tutti i campi opzionali, normalizzati)

I 9 campi billing_* sono singolarmente opzionali. Le stringhe vuote/whitespace
vengono normalizzate a None (così il form può "svuotare" un campo). Validazione
soft: billing_email deve somigliare a un'email se presente.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


def _blank_to_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


class MerchantProfileResponse(BaseModel):
    """Profilo di fatturazione risolto per l'org attiva.

    `exists=False` + campi null = nessun profilo ancora salvato (il form mostra
    campi vuoti da compilare). `owner_address` è il wallet primario EVM dell'org.
    """

    model_config = ConfigDict(from_attributes=True)

    owner_address: str
    exists: bool

    billing_legal_name: Optional[str] = None
    billing_vat_number: Optional[str] = None
    billing_tax_code: Optional[str] = None
    billing_address_line: Optional[str] = None
    billing_city: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: Optional[str] = None
    billing_email: Optional[str] = None
    billing_pec: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MerchantProfileUpdateRequest(BaseModel):
    """Body del PUT. Tutti i campi opzionali; solo i campi inviati vengono
    applicati (semantica exclude_unset lato route)."""

    billing_legal_name: Optional[str] = None
    billing_vat_number: Optional[str] = None
    billing_tax_code: Optional[str] = None
    billing_address_line: Optional[str] = None
    billing_city: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: Optional[str] = None
    billing_email: Optional[str] = None
    billing_pec: Optional[str] = None

    @field_validator(
        "billing_legal_name",
        "billing_vat_number",
        "billing_tax_code",
        "billing_address_line",
        "billing_city",
        "billing_postal_code",
        "billing_country",
        "billing_email",
        "billing_pec",
    )
    @classmethod
    def _normalize_blank(cls, v: Optional[str]) -> Optional[str]:
        return _blank_to_none(v)

    @field_validator("billing_email")
    @classmethod
    def _soft_email(cls, v: Optional[str]) -> Optional[str]:
        # Soft check (non bloccante oltre il ragionevole): se presente deve
        # contenere "@" e un "." nel dominio. Niente dipendenza email-validator.
        if v is None:
            return None
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("invalid_email")
        return v
