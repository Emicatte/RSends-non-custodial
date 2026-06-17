"""Route dashboard org-scoped per le fatture delle commissioni (Step 3).

Scenario: RPagos EMETTE la fattura; il cliente la consulta/genera dalla propria
dashboard (sessione utente). owner_address è SEMPRE derivato dal wallet primario
dell'org attiva (il payload.owner_address è ignorato per sicurezza: un merchant non
può fatturare per conto di un altro), riusando _resolve_owner_address dello Step 2.

Endpoints (prefix /api/v1/merchant/invoices):
- POST ""               (operator+): genera la fattura draft del periodo.
- GET  ""               (viewer+):  lista le fatture dell'org.
- GET  "/{invoice_id}"  (viewer+):  singola fattura (scoped all'owner_address).
- POST "/{invoice_id}/issue" (operator+): draft→issued (solo se cliente completo).

IVA/regime restano parametrici-vuoti: la POST non calcola alcun valore fiscale.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.api.merchant_profile_routes import _resolve_owner_address
from app.db.session import get_db
from app.models.invoice_models import Invoice
from app.models.invoice_schemas import (
    InvoiceCreateRequest,
    InvoiceListResponse,
    InvoiceResponse,
)
from app.models.merchant_profile_models import MerchantProfile
from app.services.invoice_service import (
    InvoiceExistsError,
    _build_client_snapshot,
    _stamp_invoice_number,
    aggregate_fees,
    create_invoice,
)

router = APIRouter(prefix="/api/v1/merchant/invoices", tags=["merchant-invoices"])


@router.post("", response_model=InvoiceResponse, status_code=201)
async def create(
    payload: InvoiceCreateRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    # owner_address SEMPRE dall'org attiva (payload.owner_address ignorato).
    owner_address = await _resolve_owner_address(db, org_id)

    try:
        invoice = await create_invoice(
            db, owner_address, payload.period_start, payload.period_end
        )
        await db.commit()
    except InvoiceExistsError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "invoice_exists"})
    except IntegrityError:
        # Race concorrente: due create per lo stesso owner+periodo passano la
        # guard non-locking e collidono sullo UNIQUE constraint al commit.
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "invoice_exists"})

    await db.refresh(invoice)
    return InvoiceResponse.model_validate(invoice)


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(Invoice)
        .where(Invoice.owner_address == owner_address)
        .order_by(desc(Invoice.created_at))
    )
    rows = list(result.scalars().all())
    return InvoiceListResponse(
        invoices=[InvoiceResponse.model_validate(r) for r in rows]
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.owner_address == owner_address,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return InvoiceResponse.model_validate(invoice)


@router.post("/{invoice_id}/issue", response_model=InvoiceResponse)
async def issue_invoice(
    invoice_id: uuid.UUID,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """draft → issued. Solo se l'anagrafica cliente è completa
    (snapshot_client con billing_legal_name + billing_vat_number);
    altrimenti 409 client_incomplete e la fattura resta draft.

    All'emissione la fattura viene RI-AGGREGATA (tx_count/subtotal/total dal
    periodo, così intervenute tra draft ed emissione sono incluse) e SOLO ora
    riceve il numero progressivo (anno = periodo). Aggregazione + numerazione +
    flip di stato avvengono in un'unica transazione atomica.
    """
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.owner_address == owner_address,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if invoice.status == "issued":
        return InvoiceResponse.model_validate(invoice)  # idempotente

    snap = invoice.snapshot_client or {}
    if not (snap.get("billing_legal_name") and snap.get("billing_vat_number")):
        raise HTTPException(status_code=409, detail={"code": "client_incomplete"})

    # 1. Ri-aggregazione dal periodo memorizzato (importi sempre Decimal).
    agg = await aggregate_fees(
        db, owner_address, invoice.period_start, invoice.period_end
    )
    invoice.tx_count = agg["tx_count"]
    invoice.subtotal_eur = agg["subtotal_eur"]
    invoice.total_eur = agg["subtotal_eur"] + (invoice.tax_amount_eur or Decimal(0))

    # 2. Numero progressivo (anno del periodo) — solo all'emissione.
    await _stamp_invoice_number(db, invoice)

    # 3. Flip di stato.
    invoice.status = "issued"
    invoice.issued_at = datetime.now(timezone.utc)

    # 4. Commit atomico unico: ri-aggregazione + numerazione + stato.
    await db.commit()
    await db.refresh(invoice)
    return InvoiceResponse.model_validate(invoice)


@router.delete("/{invoice_id}", status_code=204)
async def delete_invoice(
    invoice_id: uuid.UUID,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Elimina una fattura SOLO se ancora draft (le emesse sono immutabili).

    Consente di scartare un draft sbagliato senza bruciare numeri della
    sequenza emessa (i draft non hanno numero). 409 se già issued."""
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.owner_address == owner_address,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if invoice.status != "draft":
        raise HTTPException(
            status_code=409, detail={"code": "only_draft_deletable"}
        )

    await db.delete(invoice)
    await db.commit()
    return Response(status_code=204)


@router.post("/{invoice_id}/refresh-snapshot", response_model=InvoiceResponse)
async def refresh_snapshot(
    invoice_id: uuid.UUID,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Ri-allinea lo snapshot_client del draft all'anagrafica corrente.

    Lo snapshot è immutabile per le fatture emesse, ma un draft creato PRIMA di
    completare il profilo di fatturazione resterebbe altrimenti non emettibile:
    qui si rinfresca da MerchantProfile. 409 se non draft o anagrafica incompleta.
    """
    _user_id, org_id, _role = ctx
    owner_address = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.owner_address == owner_address,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if invoice.status != "draft":
        raise HTTPException(
            status_code=409, detail={"code": "only_draft_refreshable"}
        )

    profile_result = await db.execute(
        select(MerchantProfile).where(
            MerchantProfile.owner_address == owner_address
        )
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None or not (
        profile.billing_legal_name and profile.billing_vat_number
    ):
        raise HTTPException(status_code=409, detail={"code": "client_incomplete"})

    # Riusa il costruttore di snapshot del service per mantenere un solo set di campi.
    invoice.snapshot_client = await _build_client_snapshot(db, owner_address)
    await db.commit()
    await db.refresh(invoice)
    return InvoiceResponse.model_validate(invoice)
