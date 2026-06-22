"""Servizio di fatturazione delle commissioni (Step 3).

- aggregate_fees(): conta i PaymentIntent fee-swept del cliente nel periodo e
  calcola il subtotale EUR (tx_count × €0,01). Decimal sempre, mai float.
- next_invoice_number(): numerazione progressiva ATOMICA gap-free (counter table
  + SELECT ... FOR UPDATE nella stessa transazione dell'emissione della fattura).
- _stamp_invoice_number(): assegna il numero ALL'EMISSIONE (anno = periodo
  fatturato), così i draft abbandonati non bruciano numeri della sequenza.
- create_invoice(): orchestrazione del draft (guard anti-doppione, aggregazione,
  snapshot immutabili, INSERT in stato draft SENZA numero).

IVA/regime restano PARAMETRICI-vuoti: nessun valore fiscale calcolato/inventato.
La fonte per-cliente è SOLO PaymentIntent (unica tabella con merchant_id); il
ledger (treasury condiviso) serve solo come controllo aggregato, mai per-cliente.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice_models import Invoice, InvoiceCounter
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.merchant_profile_models import MerchantProfile

logger = logging.getLogger(__name__)

UNIT_PRICE_EUR = Decimal("0.01")

# Dati emittente PLACEHOLDER finché non reali. NON inventare P.IVA italiana né
# DPR 633/72: l'entità reale sarà RPagos S.R.L. (Costa Rica).
# TODO(legal): sostituire con dati reali RPagos S.R.L. (Costa Rica).
ISSUER_SNAPSHOT = {
    "legal_name": "[EMITTENTE — DATI DA CONFIGURARE]",
    "vat_number": None,
    "address": None,
    "country": None,
    "email": None,
    "todo": "TODO(legal): RPagos S.R.L. (Costa Rica) — dati emittente da configurare",
}


class InvoiceExistsError(Exception):
    """Esiste già una fattura per lo stesso owner_address + periodo."""


async def aggregate_fees(
    db: AsyncSession,
    owner_address: str,
    period_start: datetime,
    period_end: datetime,
) -> dict:
    """Aggrega le commissioni del cliente nel periodo.

    NON-CUSTODIAL: la fatturazione non si basa più sul fee-sweep custodial
    (rimosso). Conta i PaymentIntent SETTLED on-chain — status `paid`/`completed`
    con `completed_at` dentro [period_start, period_end] — del merchant
    (case-insensitive). Il flat è già in EUR, nessuna conversione FX.

    Esclude gli intent non fatturabili (refunded/cancelled).
    """
    owner = (owner_address or "").lower()
    result = await db.execute(
        select(func.count())
        .select_from(PaymentIntent)
        .where(
            func.lower(PaymentIntent.merchant_id) == owner,
            PaymentIntent.status.in_([IntentStatus.paid, IntentStatus.completed]),
            PaymentIntent.completed_at.isnot(None),
            PaymentIntent.completed_at >= period_start,
            PaymentIntent.completed_at <= period_end,
        )
    )
    tx_count = int(result.scalar() or 0)
    subtotal = UNIT_PRICE_EUR * tx_count  # Decimal
    return {
        "owner_address": owner,
        "tx_count": tx_count,
        "unit_price_eur": UNIT_PRICE_EUR,
        "subtotal_eur": subtotal,
        "currency": "EUR",
        "period_start": period_start,
        "period_end": period_end,
    }


async def next_invoice_number(db: AsyncSession, year: int) -> str:
    """Numero progressivo atomico FAT-{year}-{seq:06d}.

    Blocca (o crea) la riga del contatore dell'anno con SELECT ... FOR UPDATE e
    incrementa last_seq. Da chiamare DENTRO la stessa transazione dell'INSERT
    della fattura: un rollback riporta indietro anche il contatore → gap-free.
    """
    counter = await db.get(InvoiceCounter, year, with_for_update=True)
    if counter is None:
        # Prima fattura dell'anno: crea la riga (race-safe via savepoint).
        try:
            async with db.begin_nested():
                db.add(InvoiceCounter(year=year, last_seq=0))
                await db.flush()
        except IntegrityError:
            pass  # creata concorrentemente da un'altra transazione
        counter = await db.get(InvoiceCounter, year, with_for_update=True)

    counter.last_seq = (counter.last_seq or 0) + 1
    seq = counter.last_seq
    return f"FAT-{year}-{seq:06d}"


async def _stamp_invoice_number(db: AsyncSession, invoice: Invoice) -> None:
    """Assegna il numero progressivo alla fattura AL MOMENTO DELL'EMISSIONE.

    L'anno della sequenza è quello del PERIODO fatturato (period_end.year), non
    quello di creazione: una fattura del periodo dicembre emessa a gennaio resta
    nella sequenza dell'anno corretto. Da chiamare DENTRO la stessa transazione
    che porta lo status a 'issued' (rollback → numero non bruciato → gap-free).
    """
    invoice.invoice_number = await next_invoice_number(db, invoice.period_end.year)


async def _build_client_snapshot(db: AsyncSession, owner: str) -> dict:
    result = await db.execute(
        select(MerchantProfile).where(MerchantProfile.owner_address == owner)
    )
    p: Optional[MerchantProfile] = result.scalar_one_or_none()
    return {
        "owner_address": owner,
        "billing_legal_name": getattr(p, "billing_legal_name", None),
        "billing_vat_number": getattr(p, "billing_vat_number", None),
        "billing_tax_code": getattr(p, "billing_tax_code", None),
        "billing_address_line": getattr(p, "billing_address_line", None),
        "billing_city": getattr(p, "billing_city", None),
        "billing_postal_code": getattr(p, "billing_postal_code", None),
        "billing_country": getattr(p, "billing_country", None),
        "billing_email": getattr(p, "billing_email", None),
        "billing_pec": getattr(p, "billing_pec", None),
    }


async def create_invoice(
    db: AsyncSession,
    owner_address: str,
    period_start: datetime,
    period_end: datetime,
) -> Invoice:
    """Crea una fattura draft per il cliente+periodo.

    Tutto in una sola transazione (commit a carico del chiamante/route):
    guard anti-doppione → aggregazione → snapshot immutabili. Il numero
    progressivo NON è assegnato qui (vedi _stamp_invoice_number all'emissione).
    IVA parametrica: tax_* restano None, total_eur = subtotal_eur.
    """
    owner = (owner_address or "").lower()

    # Guard anti-doppione (oltre allo UNIQUE constraint a livello DB).
    existing = await db.execute(
        select(Invoice).where(
            Invoice.owner_address == owner,
            Invoice.period_start == period_start,
            Invoice.period_end == period_end,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise InvoiceExistsError()

    agg = await aggregate_fees(db, owner, period_start, period_end)

    now = datetime.now(timezone.utc)

    subtotal: Decimal = agg["subtotal_eur"]
    # IVA parametrica-vuota → totale = imponibile.
    total: Decimal = subtotal

    invoice = Invoice(
        # Il numero progressivo NON viene assegnato qui: i draft non hanno numero.
        # Viene stampato solo all'emissione via _stamp_invoice_number() → niente
        # buchi nella sequenza emessa se un draft viene abbandonato/eliminato.
        invoice_number=None,
        owner_address=owner,
        period_start=period_start,
        period_end=period_end,
        tx_count=agg["tx_count"],
        unit_price_eur=UNIT_PRICE_EUR,
        subtotal_eur=subtotal,
        tax_regime=None,
        tax_rate=None,
        tax_amount_eur=None,
        tax_note=None,
        total_eur=total,
        status="draft",
        created_at=now,
        snapshot_issuer=dict(ISSUER_SNAPSHOT),
        snapshot_client=await _build_client_snapshot(db, owner),
    )
    db.add(invoice)
    await db.flush()
    return invoice
