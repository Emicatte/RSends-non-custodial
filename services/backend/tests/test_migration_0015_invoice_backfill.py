"""Migration 0015 — backfill NULL onchain_invoice_id with the LEGACY formula.

Pre-fix-A intents have onchain_invoice_id NULL: they were already unmatchable
(NULL matches no event), and their historical /pay links advertised the legacy
keccak(reference_id) id via the derive fallback. With derive_invoice_id now
folding the chain id (F-3), that fallback would silently CHANGE their
displayed invoiceId — so 0015 freezes the legacy id into the column: the row
becomes matchable exactly as if fix-A had stamped it, and the new formula
applies to new intents only.

Direct pins on the importable backfill (0014 pattern).
"""

import importlib.util
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from eth_utils import keccak
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import PaymentIntent

# Load the migration module by path (0014 test pattern — the local alembic/
# package shadows the installed library outside the alembic CLI runtime).
_MIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic" / "versions" / "0015_backfill_onchain_invoice_id.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0015", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


invoice_backfill = _load_migration()


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    import app.models.merchant_models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentIntent.__table__.delete())
    yield


async def _mk_intent(*, reference_id, onchain_invoice_id):
    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=reference_id,
            merchant_id="m_0015",
            environment="test",
            amount=100.0,
            currency="USDC",
            chain="base_sepolia",
            recipient="0x" + "1" * 40,
            onchain_invoice_id=onchain_invoice_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


async def _invoice_id(iid):
    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent.onchain_invoice_id).where(
                PaymentIntent.intent_id == iid
            )
        )).scalar_one()


@pytest.mark.asyncio
async def test_null_rows_get_legacy_formula():
    ref = "ref_legacy_1"
    iid = await _mk_intent(reference_id=ref, onchain_invoice_id=None)

    async with engine.begin() as conn:
        await conn.run_sync(invoice_backfill.backfill_onchain_invoice_ids)

    expected = "0x" + keccak(ref.encode("utf-8")).hex()
    assert await _invoice_id(iid) == expected


@pytest.mark.asyncio
async def test_stamped_rows_are_untouched():
    """A stored id is what the /pay link advertised — 0015 must never rewrite it."""
    stored = "0x" + "ab" * 32
    iid = await _mk_intent(reference_id="ref_stamped", onchain_invoice_id=stored)

    async with engine.begin() as conn:
        await conn.run_sync(invoice_backfill.backfill_onchain_invoice_ids)

    assert await _invoice_id(iid) == stored


@pytest.mark.asyncio
async def test_idempotent():
    ref = "ref_idem"
    iid = await _mk_intent(reference_id=ref, onchain_invoice_id=None)

    async with engine.begin() as conn:
        await conn.run_sync(invoice_backfill.backfill_onchain_invoice_ids)
    first = await _invoice_id(iid)
    async with engine.begin() as conn:
        await conn.run_sync(invoice_backfill.backfill_onchain_invoice_ids)

    assert await _invoice_id(iid) == first == "0x" + keccak(ref.encode()).hex()
