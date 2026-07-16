"""B-1: a settled payment must NEVER be denied as expired.

Intents expire on a timer (default 30 min) while settlement finalization waits
for L1 finality (~13 min on Base). Money on-chain wins over the timer, always:

  - the expiry writers (Celery sweep, merchant GET auto-expire, service fn)
    must NOT expire an intent that has an observed (pending) or final
    settlement — `rejected`/`reorged` settlements do NOT hold the timer;
  - a settlement finalizing AFTER expiry already flipped the intent must
    rescue it: expired → paid, firing the payment.completed webhook that
    expiry suppressed (exactly once, via the webhook_fired_at claim).

All RPC is mocked (FakeChain, as in test_payment_indexer_reorg). Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_late_settlement_rescue.py
"""

import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.payment_indexer import _record_settlement, _finalize_and_reconcile
from app.services.router_registry import token_for, to_base_units
from app.tasks.webhook_tasks import _expire_pending_intents_async

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
AMT = to_base_units(100.0, USDC_DEC)


# ── DB + webhook fixtures (house pattern: delete rows, never drop) ──
@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.settlement_models import PaymentSettlement
    from app.models.merchant_models import PaymentIntent
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


@pytest.fixture
def webhook_calls(monkeypatch):
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers ──────────────────────────────────────────────────
async def _make_intent(*, invoice_id, status=None, expires_delta_minutes=30,
                       merchant_id="m_rescue_test", environment=None):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id=merchant_id,
            environment=environment,
            amount=100.0,
            currency="USDC",
            chain="base",
            recipient=MERCHANT,
            onchain_invoice_id=invoice_id.lower(),
            status=status or IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_delta_minutes),
        ))
        await db.commit()
    return iid


def _ev(*, invoice_id, tx_hash, block_number, block_hash, log_index=0):
    return {
        "invoice_id": invoice_id.lower(),
        "merchant": MERCHANT.lower(),
        "payer": PAYER.lower(),
        "token": USDC_ADDR.lower(),
        "amount": AMT,
        "fee": 600000,
        "block_timestamp": 1_700_000_000,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "block_number": block_number,
        "block_hash": block_hash.lower(),
    }


class FakeChain:
    """eth_getBlockByNumber-only mock — enough for _finalize_and_reconcile."""
    def __init__(self):
        self.block_hashes: dict[int, str] = {}

    async def call(self, method, params, **kw):
        if method == "eth_getBlockByNumber":
            bn = int(params[0], 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": hex(bn), "hash": h}
        raise AssertionError(f"unexpected RPC {method}")


async def _intent(iid):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()


async def _settlement(tx_hash):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        return (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == tx_hash.lower())
        )).scalar_one_or_none()


async def _add_settlement_row(iid, *, status, tx_hash=None):
    """Direct ORM settlement row tied to an intent (for writer-guard tests
    that don't need the full ingest path)."""
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    tx = (tx_hash or ("0x" + secrets.token_hex(32))).lower()
    async with async_session() as db:
        db.add(PaymentSettlement(
            invoice_id="0x" + secrets.token_hex(32),
            merchant=MERCHANT.lower(),
            payer=PAYER.lower(),
            token=USDC_ADDR.lower(),
            amount=AMT,
            fee=600000,
            chain_id=CHAIN,
            tx_hash=tx,
            log_index=0,
            block_number=100,
            block_hash="0x" + secrets.token_hex(32),
            status=status,
            intent_id=iid,
        ))
        await db.commit()
    return tx


# ═══════════════════════════════════════════════════════════════
#  Rescue: a late-finalizing settlement un-expires the intent
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_late_final_settlement_rescues_expired_intent(webhook_calls):
    """Expiry flipped the intent before finality landed. The finalize pass must
    rescue it: expired → paid + the suppressed payment.completed, exactly once."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "31" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "d1" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "d1" * 32, block_number=100, block_hash=H)

    # Payment observed on-chain (pending settlement, intent untouched)...
    assert await _record_settlement(CHAIN, ev) == "new"
    assert (await _intent(iid)).status == IntentStatus.pending

    # ...then the expiry sweep wins the race before finality.
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        row = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()
        row.status = IntentStatus.expired
        await db.commit()

    # Finality arrives: the settlement finalizes and MUST rescue the intent.
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 1
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.final
    intent = await _intent(iid)
    assert intent.status == IntentStatus.paid
    assert intent.matched_tx_hash == ev["tx_hash"]
    assert intent.completed_at is not None
    assert webhook_calls == ["payment.completed"]

    # Idempotency: re-running finalize neither re-fires nor un-pays.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # Idempotency: the sweep never touches the rescued (paid) intent.
    await _expire_pending_intents_async()
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_finalize_still_ignores_cancelled_and_paid(webhook_calls):
    """The rescue must widen the gate to expired ONLY — cancelled stays cancelled."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "32" * 32
    iid = await _make_intent(invoice_id=inv, status=IntentStatus.cancelled)
    H = "0x" + "d2" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "d2" * 32, block_number=100, block_hash=H)
    await _record_settlement(CHAIN, ev)

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    # Settlement is recorded final (money moved), but a cancelled intent is not revived.
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.cancelled
    assert webhook_calls == []


# ═══════════════════════════════════════════════════════════════
#  Expiry sweep: settlements hold the timer
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_sweep_does_not_expire_intent_with_pending_settlement(webhook_calls):
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "33" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5)
    ev = _ev(invoice_id=inv, tx_hash="0x" + "d3" * 32, block_number=100,
             block_hash="0x" + "d3" * 32)
    await _record_settlement(CHAIN, ev)  # observed on-chain, not yet final

    result = await _expire_pending_intents_async()
    assert (await _intent(iid)).status == IntentStatus.pending  # held, not expired
    assert result["expired"] == 0
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_sweep_does_not_expire_intent_with_final_settlement(webhook_calls):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "34" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5)
    await _add_settlement_row(iid, status=SettlementStatus.final)

    result = await _expire_pending_intents_async()
    assert (await _intent(iid)).status == IntentStatus.pending
    assert result["expired"] == 0
    assert webhook_calls == []


@pytest.mark.parametrize("blocking", [False, "reorged", "rejected"])
@pytest.mark.asyncio
async def test_sweep_still_expires_genuinely_unpaid_intents(webhook_calls, blocking):
    """Real expiry keeps working: no settlement, or only a rolled-back/mismatched
    one, does NOT hold the timer."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "35" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5)
    if blocking:
        await _add_settlement_row(iid, status=SettlementStatus(blocking))

    result = await _expire_pending_intents_async()
    assert (await _intent(iid)).status == IntentStatus.expired
    assert result["expired"] == 1
    assert webhook_calls == ["payment.expired"]

    # Idempotency: a second sweep is a no-op.
    result = await _expire_pending_intents_async()
    assert result["expired"] == 0
    assert webhook_calls == ["payment.expired"]


@pytest.mark.asyncio
async def test_service_expire_stale_intents_also_holds(webhook_calls, monkeypatch):
    """The service-layer sweep (webhook_service.expire_stale_intents) enforces
    the same hold — it's one wiring away from being live."""
    from unittest.mock import AsyncMock
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.services.webhook_service import expire_stale_intents

    mock_dispatch = AsyncMock()
    monkeypatch.setattr("app.services.webhook_service._dispatch_event", mock_dispatch)

    inv = "0x" + "36" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5)
    ev = _ev(invoice_id=inv, tx_hash="0x" + "d6" * 32, block_number=100,
             block_hash="0x" + "d6" * 32)
    await _record_settlement(CHAIN, ev)

    async with async_session() as db:
        async with db.begin():
            count = await expire_stale_intents(db)
    assert count == 0
    assert (await _intent(iid)).status == IntentStatus.pending
    mock_dispatch.assert_not_called()


# ═══════════════════════════════════════════════════════════════
#  Merchant GET auto-expire: same hold
# ═══════════════════════════════════════════════════════════════
OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"


def _req(environment="test", *, owner=OWNER):
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


@pytest.mark.asyncio
async def test_merchant_get_does_not_expire_intent_with_settlement(webhook_calls):
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus
    from app.api.merchant_routes import get_payment_intent

    inv = "0x" + "37" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5,
                             merchant_id=OWNER, environment="test")
    await _add_settlement_row(iid, status=SettlementStatus.pending)

    async with async_session() as db:
        resp = await get_payment_intent(iid, _req(), db=db)
    assert resp.status == IntentStatus.pending.value  # not flipped by the read
    assert (await _intent(iid)).status == IntentStatus.pending


@pytest.mark.asyncio
async def test_merchant_get_still_expires_unpaid_intent(webhook_calls):
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.api.merchant_routes import get_payment_intent

    inv = "0x" + "38" * 32
    iid = await _make_intent(invoice_id=inv, expires_delta_minutes=-5,
                             merchant_id=OWNER, environment="test")

    async with async_session() as db:
        resp = await get_payment_intent(iid, _req(), db=db)
    assert resp.status == IntentStatus.expired.value
    assert (await _intent(iid)).status == IntentStatus.expired
