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
from unittest.mock import AsyncMock

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import Base  # imports every model module → full metadata
from app.models.auth_models import User
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.org_models import Membership, Organization
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.models.user_wallets_models import UserWallet
import app.services.payment_indexer as idx
import app.api.merchant_routes as mr
import app.api.user_org_payments_routes as rt

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


# ═══════════════════════════════════════════════════════════════
#  Site 2 — cancel (F-5 guard) vs settlement ingest: TOCTOU
# ═══════════════════════════════════════════════════════════════


async def _seed_org(sm):
    """Org whose primary wallet resolves to OWNER — the session cancel path."""
    async with sm() as db:
        user = User(
            id=secrets.token_hex(16),
            email=f"{secrets.token_hex(6)}@example.com",
            account_type="individual",
        )
        db.add(user)
        await db.flush()
        org = Organization(
            name="Org " + secrets.token_hex(3),
            slug=secrets.token_hex(8),
            owner_user_id=user.id,
            is_personal=False,
            plan="free",
        )
        db.add(org)
        await db.flush()
        db.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        db.add(UserWallet(
            user_id=user.id,
            org_id=org.id,
            address=OWNER,
            display_address=OWNER,
            verified_chain_id=CHAIN,
            is_primary=True,
            chain_family="evm",
        ))
        await db.commit()
        return org.id


def _api_req(environment="test"):
    client = {"client_id": OWNER, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _drive_cancel(surface, sm, intent_id, org_id):
    """Run the real cancel handler in its own transaction; normalize outcome."""
    async with sm() as db:
        try:
            if surface == "api_key":
                await mr.cancel_payment_intent(intent_id, _api_req(), db=db)
            else:
                await rt.cancel_org_payment_intent(
                    intent_id=intent_id,
                    ctx=("user-unused", str(org_id), "operator"),
                    environment="test",
                    db=db,
                )
            return ("ok", 200)
        except HTTPException as e:
            return ("http", e.status_code)


def _payment_ev(invoice_id, tx_hash):
    """A decoded PaymentMade event for the REAL _record_settlement ingest."""
    return {
        "invoice_id": invoice_id,
        "merchant": MERCHANT.lower(),
        "payer": PAYER.lower(),
        "token": TOKEN,
        "amount": 100_000_000,
        "fee": 600000,
        "tx_hash": tx_hash,
        "log_index": 0,
        "block_number": 120,
        "block_hash": "0x" + secrets.token_hex(32),
        "block_timestamp": int(datetime.now(timezone.utc).timestamp()),
    }


def _patch_cancel_side_effects(monkeypatch, pg):
    async def _no_log(*a, **k):
        return None

    async def _no_onchain(intent):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)
    monkeypatch.setattr(rt, "log_event", _no_log)
    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    # The REAL ingest path opens its own session — point it at this Postgres.
    monkeypatch.setattr("app.db.session.async_session", pg)
    # Isolate serialization from event-validation details (suite pattern).
    monkeypatch.setattr(idx, "_validate_event_against_intent", lambda ev, intent: [])


async def _final_state(sm, intent_id, tx_hash):
    async with sm() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        settlement = (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == tx_hash)
        )).scalar_one_or_none()
        return intent, settlement


@pytest.mark.parametrize("surface", ["api_key", "session"])
@pytest.mark.asyncio
async def test_cancel_vs_ingest_serializes_on_the_intent_row(pg, monkeypatch, surface):
    """The F-5 TOCTOU: cancel is frozen exactly between its hold check and its
    commit while the REAL ingest (_record_settlement) commits a pending
    settlement for the same intent.

    Invariant: a settlement hold committed BEFORE cancel's commit must force
    409 — the committed state must never pair `cancelled` with a hold that
    preceded it. The two transactions must serialize on the intent row: with
    the cancel in flight, ingest blocks until the cancel commits (legal serial
    late payment) or the cancel sees the hold and refuses."""
    intent_id = await _seed_intent(pg)
    org_id = await _seed_org(pg) if surface == "session" else None
    async with pg() as db:
        invoice_id = (await db.execute(
            select(PaymentIntent.onchain_invoice_id)
            .where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
    tx = "0x" + secrets.token_hex(32)

    _patch_cancel_side_effects(monkeypatch, pg)

    window_open = asyncio.Event()
    resume = asyncio.Event()
    mod = mr if surface == "api_key" else rt
    real_hold = mod.has_settlement_hold

    async def gated_hold(db, iid):
        held = await real_hold(db, iid)
        window_open.set()
        await resume.wait()
        return held

    monkeypatch.setattr(mod, "has_settlement_hold", gated_hold)

    cancel_task = asyncio.create_task(_drive_cancel(surface, pg, intent_id, org_id))
    await asyncio.wait_for(window_open.wait(), timeout=5)

    # Cancel is inside the TOCTOU window — now the payer's tx gets ingested.
    ingest_task = asyncio.create_task(
        idx._record_settlement(CHAIN, _payment_ev(invoice_id, tx))
    )
    await asyncio.sleep(0.4)
    ingest_landed_in_window = ingest_task.done()

    resume.set()
    outcome = await asyncio.wait_for(cancel_task, timeout=10)
    assert await asyncio.wait_for(ingest_task, timeout=10) == "new"

    intent, settlement = await _final_state(pg, intent_id, tx)
    assert settlement is not None and settlement.intent_id == intent_id
    assert settlement.status is SettlementStatus.pending  # it IS a hold

    if ingest_landed_in_window:
        assert outcome == ("http", 409), (
            "cancelled-but-held: a settlement hold was committed inside the "
            f"cancel's TOCTOU window, yet cancel returned {outcome} — the payer "
            "sees cancelled and finalize will silently flip it to paid"
        )
    assert not ingest_landed_in_window, (
        "ingest committed inside the cancel's TOCTOU window — the two "
        "transactions did not serialize on the intent row"
    )
    # Cancel-first order: the cancel committed, then the late payment landed —
    # the legal serial case (finalize treats a cancelled intent as terminal).
    assert outcome == ("ok", 200)
    assert intent.status is IntentStatus.cancelled


@pytest.mark.parametrize("surface", ["api_key", "session"])
@pytest.mark.asyncio
async def test_cancel_after_committed_ingest_refuses(pg, monkeypatch, surface):
    """Ingest-first order on Postgres through the REAL ingest: the committed
    pending settlement holds, cancel refuses with 409 (F-5 pin)."""
    intent_id = await _seed_intent(pg)
    org_id = await _seed_org(pg) if surface == "session" else None
    async with pg() as db:
        invoice_id = (await db.execute(
            select(PaymentIntent.onchain_invoice_id)
            .where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
    tx = "0x" + secrets.token_hex(32)

    _patch_cancel_side_effects(monkeypatch, pg)

    assert await idx._record_settlement(CHAIN, _payment_ev(invoice_id, tx)) == "new"
    outcome = await _drive_cancel(surface, pg, intent_id, org_id)

    assert outcome == ("http", 409)
    intent, settlement = await _final_state(pg, intent_id, tx)
    assert intent.status is IntentStatus.pending
    assert settlement.status is SettlementStatus.pending


# ═══════════════════════════════════════════════════════════════
#  Site 4 — expire task: pending→expired claim, single winner
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_expire_workers_fire_expired_exactly_once(pg, monkeypatch):
    """Celery beat and the asyncio fallback loop can run the expire task
    concurrently. Both select the same overdue pending intent; the flip must
    be an atomic claim: the loser's UPDATE blocks on the winner's row lock,
    re-evaluates `status == pending` on the committed row, and skips — no
    IntegrityError on the UNIQUE idempotency_key, no second delivery, no
    lost expiration. Redis is absent by construction (its pre-claim was
    fail-open, i.e. no guarantee): exactly-once must hold from the DB alone."""
    from app.models.merchant_models import MerchantWebhook, WebhookDelivery
    import app.db.session as dbs
    import app.tasks.webhook_tasks as wt

    intent_id = await _seed_intent(pg)
    async with pg() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        intent.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.add(MerchantWebhook(
            merchant_id=OWNER,
            environment="test",
            url="https://merchant.example/hook",
            secret="whsec_" + secrets.token_hex(16),
            events=[],
            is_active=True,
        ))
        await db.commit()

    monkeypatch.setattr(dbs, "async_session", pg)
    monkeypatch.setattr(  # Redis unavailable — the no-guarantee scenario
        "app.services.cache_service.get_redis", AsyncMock(return_value=None)
    )

    async def _slow_delivery(delivery, wh):
        await asyncio.sleep(0.3)  # hold the winner's tx open past the loser's SELECT
        return True

    monkeypatch.setattr(
        "app.services.webhook_service._attempt_delivery", _slow_delivery
    )

    results = await asyncio.gather(
        wt._expire_pending_intents_async(),
        wt._expire_pending_intents_async(),
    )

    assert sum(r["expired"] for r in results) == 1
    assert sum(r["webhooks_triggered"] for r in results) == 1
    async with pg() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        assert intent.status is IntentStatus.expired
        rows = (await db.execute(select(WebhookDelivery))).scalars().all()
        assert len(rows) == 1
        assert rows[0].event_type == "payment.expired"
