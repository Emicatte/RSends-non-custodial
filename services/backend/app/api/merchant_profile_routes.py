"""Route dashboard org-scoped per l'anagrafica di fatturazione del merchant.

Scenario: RPagos EMETTE le fatture delle commissioni; il cliente compila QUI i
PROPRI dati di fatturazione (MerchantProfile, Step 1). Traffico dashboard
(sessione utente next-auth), NON le ApiKey B2B.

Ponte identità: org attiva → wallet PRIMARIO EVM dell'org → owner_address
(lowercase) == ApiKey.owner_address == PaymentIntent.merchant_id ==
MerchantProfile.owner_address. owner_address è normalizzato a lowercase su
entrambi i lati del lookup/upsert.

Endpoints:
- GET /api/v1/merchant/profile  (viewer+): risolve owner_address dal wallet
  primario; ritorna il profilo o un oggetto vuoto (exists=False) se non esiste.
- PUT /api/v1/merchant/profile  (operator+): upsert dei campi billing_*.

Identità: wallet primario EVM se collegato, altrimenti fallback fail-closed sul
settlement_wallet dell'org (vedi app/services/owner_identity.py). Senza nessuno
dei due → 409 {"code":"no_primary_wallet"}: il cliente collega un wallet in
Settings → Wallets o imposta il settlement wallet.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.merchant_profile_models import MerchantProfile
from app.models.merchant_profile_schemas import (
    MerchantProfileResponse,
    MerchantProfileUpdateRequest,
)
# Resolver condiviso: wallet primario → fallback settlement_wallet (fail-closed).
# Re-export sotto il vecchio nome — user_org_*_routes e merchant_invoice_routes
# lo importano da qui.
from app.services.owner_identity import resolve_owner_address as _resolve_owner_address

router = APIRouter(prefix="/api/v1/merchant/profile", tags=["merchant-profile"])


def _to_response(owner_address: str, profile: Optional[MerchantProfile]) -> MerchantProfileResponse:
    if profile is None:
        return MerchantProfileResponse(owner_address=owner_address, exists=False)
    return MerchantProfileResponse(
        owner_address=owner_address,
        exists=True,
        billing_legal_name=profile.billing_legal_name,
        billing_vat_number=profile.billing_vat_number,
        billing_tax_code=profile.billing_tax_code,
        billing_address_line=profile.billing_address_line,
        billing_city=profile.billing_city,
        billing_postal_code=profile.billing_postal_code,
        billing_country=profile.billing_country,
        billing_email=profile.billing_email,
        billing_pec=profile.billing_pec,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=MerchantProfileResponse)
async def get_profile(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(MerchantProfile).where(
            MerchantProfile.owner_address == owner_address
        )
    )
    profile = result.scalar_one_or_none()
    return _to_response(owner_address, profile)


@router.put("", response_model=MerchantProfileResponse)
async def upsert_profile(
    payload: MerchantProfileUpdateRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(MerchantProfile).where(
            MerchantProfile.owner_address == owner_address
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = MerchantProfile(owner_address=owner_address)
        db.add(profile)

    # Applica solo i campi effettivamente inviati (già normalizzati a None se
    # vuoti dal validator). Permette di "svuotare" un campo passando "".
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(profile, field, value)

    profile.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(profile)

    return _to_response(owner_address, profile)
