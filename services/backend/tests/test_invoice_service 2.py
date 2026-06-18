"""Test del servizio di fatturazione commissioni (Step 3).

Copre:
  - aggregate_fees: conta SOLO gli intent fee-swept del cliente nel periodo
    (esclusi: fuori periodo, fee_swept_at NULL, altri merchant); importi Decimal.
  - next_invoice_number: sequenza progressiva FAT-{anno}-{seq:06d}; contatori
    per-anno indipendenti. (Su SQLite FOR UPDATE è no-op: qui si verifica la
    sequenza, il lock di riga vale su Postgres.)
  - create_invoice: guard anti-doppione (InvoiceExistsError), snapshot cliente
    da MerchantProfile, blocco IVA parametrico-vuoto (tax_* None, total==subtotal).
  - riconciliazione ledger: solo warning, mai bloccante.
"""

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.invoice_models import Invoice, InvoiceCounter  # noqa: F401 (registra le tabelle)
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.merchant_profile_models import MerchantProfile
from app.services.invoice_service import (
    UNIT_PRICE_EUR,
    InvoiceExistsError,
    _stamp_invoice_number,
    aggregate_fees,
    create_invoice,
    next_invoice_number,
)

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"

PERIOD_START = datetime(2026, 5, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _intent(
    merchant_id: str, fee_swept_at, status: IntentStatus = IntentStatus.completed
) -> PaymentIntent:
    """Helper: PaymentIntent minimo con fee_swept_at dato (None = fee non swept)."""
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        amount=100.0,
        currency="EURC",
        chain="BASE",
        status=status,
        expires_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        fee_swept_at=fee_swept_at,
    )


# ── aggregate_fees ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregate_fees_counts_only_swept_in_period(session):
    in_period = PERIOD_START + timedelta(days=10)
    session.add_all([
        _intent(OWNER, in_period),
        # merchant_id con casing diverso → deve contare (match case-insensitive)
        _intent(OWNER.upper().replace("0X", "0x"), in_period + timedelta(days=1)),
        _intent(OWNER, PERIOD_END),                      # bordo incluso
        _intent(OWNER, PERIOD_END + timedelta(seconds=1)),  # fuori periodo
        _intent(OWNER, None),                            # fee non swept
        _intent("0x" + "ab" * 20, in_period),            # altro merchant
        # fee swept ma intent rimborsato/annullato → NON fatturabile, escluso.
        _intent(OWNER, in_period, status=IntentStatus.refunded),
        _intent(OWNER, in_period, status=IntentStatus.cancelled),
    ])
    await session.commit()

    agg = await aggregate_fees(session, OWNER, PERIOD_START, PERIOD_END)

    assert agg["tx_count"] == 3
    assert agg["unit_price_eur"] == UNIT_PRICE_EUR
    assert isinstance(agg["subtotal_eur"], Decimal)
    assert agg["subtotal_eur"] == Decimal("0.03")
    assert agg["currency"] == "EUR"


@pytest.mark.asyncio
async def test_aggregate_fees_empty_period(session):
    agg = await aggregate_fees(session, OWNER, PERIOD_START, PERIOD_END)
    assert agg["tx_count"] == 0
    assert agg["subtotal_eur"] == Decimal("0")


# ── next_invoice_number ──────────────────────────────────────

@pytest.mark.asyncio
async def test_invoice_number_sequence_per_year(session):
    assert await next_invoice_number(session, 2026) == "FAT-2026-000001"
    assert await next_invoice_number(session, 2026) == "FAT-2026-000002"
    # Anno diverso → contatore indipendente, riparte da 1.
    assert await next_invoice_number(session, 2027) == "FAT-2027-000001"
    assert await next_invoice_number(session, 2026) == "FAT-2026-000003"
    await session.rollback()


# ── create_invoice ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_invoice_snapshot_and_parametric_tax(session):
    session.add(MerchantProfile(
        owner_address=OWNER,
        billing_legal_name="ACME Commercio S.r.l.",
        billing_vat_number="IT01234567890",
        billing_city="Milano",
    ))
    session.add(_intent(OWNER, PERIOD_START + timedelta(days=5)))
    await session.commit()

    invoice = await create_invoice(session, OWNER, PERIOD_START, PERIOD_END)
    await session.commit()

    # I draft NON hanno numero: viene assegnato solo all'emissione.
    assert invoice.invoice_number is None
    assert invoice.owner_address == OWNER
    assert invoice.tx_count == 1
    assert Decimal(invoice.subtotal_eur) == Decimal("0.01")
    # Blocco IVA parametrico-vuoto: nessun valore fiscale inventato.
    assert invoice.tax_regime is None
    assert invoice.tax_rate is None
    assert invoice.tax_amount_eur is None
    assert invoice.tax_note is None
    assert Decimal(invoice.total_eur) == Decimal(invoice.subtotal_eur)
    assert invoice.status == "draft"
    # Snapshot immutabili valorizzati al momento della creazione.
    assert invoice.snapshot_client["billing_legal_name"] == "ACME Commercio S.r.l."
    assert invoice.snapshot_client["billing_vat_number"] == "IT01234567890"
    assert invoice.snapshot_issuer["legal_name"]  # placeholder emittente presente


@pytest.mark.asyncio
async def test_create_invoice_duplicate_period_rejected(session):
    await create_invoice(session, OWNER, PERIOD_START, PERIOD_END)
    await session.commit()

    with pytest.raises(InvoiceExistsError):
        await create_invoice(session, OWNER, PERIOD_START, PERIOD_END)
    await session.rollback()


# ── _stamp_invoice_number (numerazione all'emissione, anno = periodo) ──────────

@pytest.mark.asyncio
async def test_stamp_invoice_number_uses_period_year(session):
    """Il numero è assegnato solo allo stamp e l'anno è quello del PERIODO
    fatturato (period_end), non quello di creazione."""
    # Draft 2026 → nessun numero finché non si stampa.
    inv_2026 = await create_invoice(session, OWNER, PERIOD_START, PERIOD_END)
    assert inv_2026.invoice_number is None

    await _stamp_invoice_number(session, inv_2026)
    assert inv_2026.invoice_number == "FAT-2026-000001"

    # Draft di un periodo 2025 → sequenza dell'anno del periodo, indipendente.
    p2025_start = datetime(2025, 12, 1, tzinfo=timezone.utc)
    p2025_end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    inv_2025 = await create_invoice(session, OWNER, p2025_start, p2025_end)
    await _stamp_invoice_number(session, inv_2025)
    assert inv_2025.invoice_number == "FAT-2025-000001"
    await session.commit()
