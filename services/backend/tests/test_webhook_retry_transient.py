"""A transient payment.completed dispatch failure must NOT lose the webhook.

The claim mechanism in _finalize_settlement releases webhook_fired_at back to
NULL when send_webhook raises, with a comment promising "the next reconcile
retries the dispatch". That promise was false: the reconcile loop only calls
_finalize_settlement for PENDING rows, and the row is already FINAL — in tag
mode it is TERMINAL (never selected again) the moment it pays. One flaky HTTP
call to the merchant and "paid, told nobody" became permanent.

Invariant pinned here: a FINAL settlement whose intent is paid-by-it and whose
completed webhook never fired is re-dispatched on every reconcile tick until
it succeeds — exactly once overall (same atomic claim), regardless of the
terminal boundary, and never for superseded or reversed settlements.

All RPC mocked (FakeChain, as in test_late_settlement_rescue). Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_webhook_retry_transient.py
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.payment_indexer import _record_settlement, _finalize_and_reconcile
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base_sepolia", "USDC")
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 84532
AMT = to_base_units(100.0, USDC_DEC)


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401
    import app.models.settlement_models  # noqa: F401
    from app.models.settlement_models import PaymentSettlement
    from app.models.merchant_models import PaymentIntent
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


class FlakyWebhook:
    """send_webhook double: raises for the first `fail_times` calls."""

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = []

    async def __call__(self, db, *, merchant_id, event, intent, extra_payload=None):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("transient dispatch failure")
        self.calls.append(event)
        return None


@pytest.fixture
def flaky(monkeypatch):
    def _install(fail_times):
        hook = FlakyWebhook(fail_times)
        monkeypatch.setattr("app.services.webhook_service.send_webhook", hook)
        return hook
    return _install


async def _make_intent(*, invoice_id, status=None):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_retry_test",
            environment="test",
            amount=100.0,
            currency="USDC",
            chain="base_sepolia",
            recipient=MERCHANT,
            onchain_invoice_id=invoice_id.lower(),
            status=status or IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


def _ev(*, invoice_id, tx_hash, block_number=100, block_hash=None, log_index=0):
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
        "block_hash": (block_hash or tx_hash).lower(),
    }


class FakeChain:
    def __init__(self):
        self.block_hashes: dict[int, str] = {}

    async def call(self, method, params, **kw):
        if method == "eth_getBlockByNumber":
            bn = int(params[0], 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": hex(bn), "hash": h}
        raise AssertionError(f"unexpected RPC {method}")


async def _settlement(tx_hash):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        return (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == tx_hash.lower())
        )).scalar_one_or_none()


async def _intent(iid):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()


async def _paid_with_unfired_webhook(flaky, *, tag, block=100):
    """Common setup: finalize with the dispatch failing once → intent paid,
    settlement final, webhook_fired_at NULL (the released claim)."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + tag * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + tag * 32
    rpc = FakeChain()
    rpc.block_hashes[block] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + tag * 32, block_number=block, block_hash=H)
    await _record_settlement(CHAIN, ev)

    hook = flaky(1)  # first dispatch raises, later ones succeed
    await _finalize_and_reconcile(CHAIN, rpc, final_head=block + 100)

    s = await _settlement(ev["tx_hash"])
    intent = await _intent(iid)
    assert s.status == SettlementStatus.final
    assert intent.status == IntentStatus.paid          # payment NOT blocked by dispatch
    assert s.webhook_fired_at is None                  # claim released
    assert hook.calls == []                            # nothing delivered yet
    return iid, ev, rpc, hook


@pytest.mark.asyncio
async def test_transient_dispatch_failure_is_retried_next_tick(flaky):
    """RED core: the released claim must actually be retried — next tick
    fires payment.completed exactly once and stamps webhook_fired_at."""
    iid, ev, rpc, hook = await _paid_with_unfired_webhook(flaky, tag="a1")

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)

    s = await _settlement(ev["tx_hash"])
    assert hook.calls == ["payment.completed"]
    assert s.webhook_fired_at is not None

    # Idempotency: further ticks never double-fire.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert hook.calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_retry_works_even_below_terminal(flaky):
    """Tag mode makes a row TERMINAL the moment it pays (terminal == final
    head), so the retry must not depend on the row being reconcilable —
    an unfired completed webhook is re-dispatched even for terminal rows."""
    iid, ev, rpc, hook = await _paid_with_unfired_webhook(flaky, tag="a2")

    # terminal_head explicitly past the block: the row is terminal.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=200)

    assert hook.calls == ["payment.completed"]
    assert (await _settlement(ev["tx_hash"])).webhook_fired_at is not None


@pytest.mark.asyncio
async def test_retry_keeps_failing_then_succeeds(flaky):
    """A multi-tick outage: every tick retries, none is lost, still exactly
    one delivery when the merchant endpoint recovers."""
    from app.models.settlement_models import SettlementStatus

    inv = "0x" + "a3" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "a3" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "a3" * 32, block_hash=H)
    await _record_settlement(CHAIN, ev)

    hook = flaky(3)  # finalize + two retry ticks fail, third retry succeeds
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # pays, dispatch fails
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # retry 1: fails
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # retry 2: fails
    assert hook.calls == []
    assert (await _settlement(ev["tx_hash"])).webhook_fired_at is None

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # retry 3: succeeds
    assert hook.calls == ["payment.completed"]

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert hook.calls == ["payment.completed"]  # never doubles


@pytest.mark.asyncio
async def test_no_retry_for_superseded_settlement(flaky):
    """Guard: a final row whose intent was since paid by a DIFFERENT
    settlement (matched_tx_hash ≠ this tx) must not fire completed for the
    stale row."""
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    iid, ev, rpc, hook = await _paid_with_unfired_webhook(flaky, tag="a4")

    # Simulate the intent having been re-matched to another tx meanwhile.
    async with async_session() as db:
        row = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()
        row.matched_tx_hash = "0x" + "ff" * 32
        await db.commit()

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert hook.calls == []
    assert (await _settlement(ev["tx_hash"])).webhook_fired_at is None


@pytest.mark.asyncio
async def test_no_retry_for_orphan_or_unpaid(flaky):
    """Guard: orphan finals (no intent) and terminal no-ops (intent not paid,
    e.g. cancelled before finality) never enter the retry path."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    # Orphan: no matching intent at all (wrong-chain-style orphan).
    rpc = FakeChain()
    H = "0x" + "a5" * 32
    rpc.block_hashes[100] = H
    orphan_ev = _ev(invoice_id="0x" + "a5" * 32, tx_hash="0x" + "a5" * 32, block_hash=H)
    await _record_settlement(CHAIN, orphan_ev)

    # Cancelled intent with a valid settlement (terminal no-op stamp).
    inv = "0x" + "a6" * 32
    await _make_intent(invoice_id=inv, status=IntentStatus.cancelled)
    rpc.block_hashes[101] = "0x" + "a6" * 32
    cancelled_ev = _ev(invoice_id=inv, tx_hash="0x" + "a6" * 32, block_number=101,
                       block_hash="0x" + "a6" * 32)
    await _record_settlement(CHAIN, cancelled_ev)

    hook = flaky(0)
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # both go final
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)   # retry tick
    assert hook.calls == []
    assert (await _settlement(orphan_ev["tx_hash"])).status == SettlementStatus.final
    assert (await _settlement(cancelled_ev["tx_hash"])).status == SettlementStatus.final
