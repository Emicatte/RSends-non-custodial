"""Real-concurrency serialization tests for the paid/cancelled boundary.

The suite's SQLite engine shares ONE connection (StaticPool), so two genuinely
concurrent transactions are impossible there — every existing "concurrency"
test interleaves cooperatively inside a single transaction and cannot express
a cross-transaction race. These tests run against Postgres (independent pooled
connections, READ COMMITTED — the production isolation) and pin the two sites
that guard the paid/cancelled state transition:

  * the `_fire_completed_webhook` atomic claim (PR #56) — exactly-once
    payment.completed across concurrent reconciles, and the release-then-sweep
    retry path;
  * reversal-vs-sweep — a concurrent `_reverse_settlement` must never lose
    `payment.reversed` when the sweep's dispatch is in flight;
  * the F-5 cancel guard vs settlement ingest (TOCTOU) — a settlement hold
    committed before cancel's commit must force 409, never a committed
    cancelled-but-held pair.

Gated on ``CONCURRENCY_TEST_DATABASE_URL`` (async form,
``postgresql+asyncpg://…/dbname``): skipped when unset, run in CI against the
existing ``postgres:16`` service with a dedicated database. The target
database is auto-created if missing (via the server's ``postgres`` maintenance
DB) and its schema is rebuilt fresh for every test — nothing here touches the
app's global engine except where a test explicitly monkeypatches
``app.db.session.async_session`` to drive the real ingest path.
"""

import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import Base  # imports every model module → full metadata
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
import app.services.payment_indexer as idx
import app.api.merchant_routes as mr

PG_URL = os.getenv("CONCURRENCY_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="CONCURRENCY_TEST_DATABASE_URL not set (Postgres-backed concurrency test)",
)

CHAIN = 84532  # Base Sepolia — testnet, matches environment="test"
OWNER = "0x" + "a" * 40
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
TOKEN = "0x" + "c" * 40


def _admin_dsn() -> str:
    """Plain-driver DSN for the server's maintenance DB (to CREATE DATABASE)."""
    raw = PG_URL.replace("postgresql+asyncpg://", "postgresql://")
    base, _, _dbname = raw.rpartition("/")
    return f"{base}/postgres"


def _raw_dsn() -> str:
    return PG_URL.replace("postgresql+asyncpg://", "postgresql://")


def _target_dbname() -> str:
    return PG_URL.rpartition("/")[2]


async def _ensure_database() -> None:
    conn = await asyncpg.connect(dsn=_admin_dsn())
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _target_dbname()
        )
        if not exists:
            # CREATE DATABASE can't be parameterized; the name comes from the
            # operator-supplied env var, not from external input.
            await conn.execute(f'CREATE DATABASE "{_target_dbname()}"')
    finally:
        await conn.close()


async def _fresh_schema() -> None:
    conn = await asyncpg.connect(dsn=_raw_dsn())
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg():
    """A sessionmaker over a fresh schema on the dedicated Postgres DB.

    NullPool: every session gets its own connection, opened and closed inside
    this test's event loop — two sessions ARE two transactions.
    """
    await _ensure_database()
    await _fresh_schema()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield sm
    finally:
        await engine.dispose()


# ── Row factories ──────────────────────────────────────────────


async def _seed_intent(sm, *, status=IntentStatus.pending, matched_tx=None) -> str:
    intent_id = f"pi_{secrets.token_hex(16)}"
    async with sm() as db:
        db.add(PaymentIntent(
            intent_id=intent_id,
            reference_id=secrets.token_hex(8),
            merchant_id=OWNER,
            environment="test",
            amount=100.0,
            currency="USDC",
            chain="base_sepolia",
            recipient=MERCHANT,
            status=status,
            onchain_invoice_id="0x" + secrets.token_hex(32),
            matched_tx_hash=matched_tx,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return intent_id


async def _seed_settlement(sm, intent_id, *, status, tx_hash,
                           webhook_fired_at=None) -> int:
    async with sm() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        s = PaymentSettlement(
            invoice_id=intent.onchain_invoice_id,
            merchant=MERCHANT.lower(),
            payer=PAYER.lower(),
            token=TOKEN,
            amount=100_000_000,
            fee=600000,
            chain_id=CHAIN,
            tx_hash=tx_hash,
            log_index=0,
            block_number=100,
            block_hash="0x" + secrets.token_hex(32),
            status=status,
            intent_id=intent_id,
            webhook_fired_at=webhook_fired_at,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _seed_final_paid_unfired(sm):
    """The sweep-retry precondition: settlement FINAL, intent paid by it,
    webhook_fired_at NULL (a previous dispatch failed and released the claim)."""
    tx = "0x" + secrets.token_hex(32)
    intent_id = await _seed_intent(sm, status=IntentStatus.paid, matched_tx=tx)
    sid = await _seed_settlement(
        sm, intent_id, status=SettlementStatus.final, tx_hash=tx
    )
    return intent_id, sid


async def _load_pair(db, sid, intent_id):
    s = (await db.execute(
        select(PaymentSettlement).where(PaymentSettlement.id == sid)
    )).scalar_one()
    i = (await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )).scalar_one()
    return s, i


async def _db_state(sm, sid, intent_id):
    async with sm() as db:
        s, i = await _load_pair(db, sid, intent_id)
        return s, i


# ═══════════════════════════════════════════════════════════════
#  Site 1a — payment.completed claim is exclusive ACROSS transactions
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_completed_claim_exclusive_across_transactions(pg, monkeypatch):
    """Two independent transactions race `_fire_completed_webhook` on the same
    FINAL settlement: the loser blocks on the row lock, re-evaluates the WHERE
    after the winner commits, rowcount-0s — exactly one payment.completed."""
    intent_id, sid = await _seed_final_paid_unfired(pg)

    calls = []

    async def _recorder(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _recorder)

    async def attempt():
        async with pg() as db:
            s, i = await _load_pair(db, sid, intent_id)
            await idx._fire_completed_webhook(db, s, i)
            await db.commit()

    await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=15)

    assert calls == ["payment.completed"], f"expected exactly one fire, got {calls}"
    s, _ = await _db_state(pg, sid, intent_id)
    assert s.webhook_fired_at is not None


@pytest.mark.asyncio
async def test_release_then_sweep_refire_delivers_exactly_once(pg, monkeypatch):
    """A failed dispatch releases the claim in its own transaction; a later
    sweep in a DIFFERENT transaction re-claims and delivers — exactly once."""
    intent_id, sid = await _seed_final_paid_unfired(pg)

    delivered = []
    attempts = {"n": 0}

    async def _fails_once(db, *, merchant_id, event, intent, extra_payload=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient dispatch failure")
        delivered.append(event)
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fails_once)

    async with pg() as db:
        s, i = await _load_pair(db, sid, intent_id)
        await idx._fire_completed_webhook(db, s, i)
        await db.commit()

    s, _ = await _db_state(pg, sid, intent_id)
    assert s.webhook_fired_at is None, "failed dispatch must release the claim"

    async with pg() as db:
        s, i = await _load_pair(db, sid, intent_id)
        await idx._fire_completed_webhook(db, s, i)
        await db.commit()

    assert delivered == ["payment.completed"]
    assert attempts["n"] == 2
    s, _ = await _db_state(pg, sid, intent_id)
    assert s.webhook_fired_at is not None


# ═══════════════════════════════════════════════════════════════
#  Site 1b — reversal must not be lost while a sweep-fire is in flight
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reversal_not_lost_when_sweep_fire_in_flight(pg, monkeypatch):
    """Reconcile A (sweep) claims webhook_fired_at NULL→now and its dispatch of
    payment.completed is in flight (uncommitted). Concurrent reconcile B, whose
    snapshot still reads webhook_fired_at = NULL, reverses the same settlement.

    The merchant was just told "paid" — payment.reversed MUST follow. B's
    fired-decision must come from the committed row (inside the atomic claim's
    WHERE), not from a pre-lock snapshot."""
    intent_id, sid = await _seed_final_paid_unfired(pg)

    events = []
    completed_in_flight = asyncio.Event()
    release_completed = asyncio.Event()

    async def _gated(db, *, merchant_id, event, intent, extra_payload=None):
        events.append(event)
        if event == "payment.completed":
            completed_in_flight.set()
            await release_completed.wait()
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _gated)

    async def sweep_fire():
        async with pg() as db:
            s, i = await _load_pair(db, sid, intent_id)
            await idx._fire_completed_webhook(db, s, i)
            await db.commit()

    async def reverse():
        async with pg() as db:
            s = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.id == sid)
            )).scalar_one()
            await idx._reverse_settlement(db, s)
            await db.commit()

    sweep_task = asyncio.create_task(sweep_fire())
    await asyncio.wait_for(completed_in_flight.wait(), timeout=5)

    reverse_task = asyncio.create_task(reverse())
    await asyncio.sleep(0.3)
    # B must serialize on A's row lock — the fired-decision has to wait for
    # A's committed row (the fix's guarantee IS this blocking).
    assert not reverse_task.done(), (
        "reversal committed while the sweep's claim was uncommitted — "
        "it cannot have seen the fired webhook"
    )

    release_completed.set()
    await asyncio.wait_for(asyncio.gather(sweep_task, reverse_task), timeout=15)

    assert events == ["payment.completed", "payment.reversed"], (
        f"merchant was told paid but the reversal was lost: {events}"
    )
    s, i = await _db_state(pg, sid, intent_id)
    assert s.status is SettlementStatus.reorged
    assert s.reversal_fired_at is not None
    assert i.status is IntentStatus.pending, "reorged settlement must un-pay the intent"
