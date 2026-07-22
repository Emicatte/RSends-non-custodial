"""
Reorg-safety + validation tests for the non-custodial PaymentMade indexer.

All RPC is mocked (FakeChain) — no live chain. Covers:
  - valid event past finality      → paid, settlement final, webhook fired ONCE
  - non-router address             → ignored, not paid
  - wrong merchant/token/amount    → rejected, not paid, no webhook
  - duplicate log                  → idempotent (one settlement, one webhook)
  - below depth                    → pending; reaching depth → final
  - reorg of a pending settlement  → reorged, un-paid, no webhook
  - reorg after finalize           → reorged, reverted, payment.reversed signalled
  - restart/gap                    → resumes from last block, no miss/duplicate
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func

import app.services.payment_indexer as idx
from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PaymentWatcher,
    _record_settlement,
    _finalize_and_reconcile,
)
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
ROUTER = "0x" + "a" * 40
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
BASE_FEE = 600000
AMT = to_base_units(100.0, USDC_DEC)  # 100_000000


# ── DB + webhook fixtures ────────────────────────────────────
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
        # Isolate: clear the tables these tests touch so rows never leak across
        # tests/files (the engine + DB are shared process-wide).
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


@pytest.fixture
def webhook_calls(monkeypatch):
    """Capture every webhook dispatch (event name) and prove 'fire once'."""
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers ──────────────────────────────────────────────────
async def _make_intent(*, invoice_id, recipient=MERCHANT, amount=100.0, currency="USDC", chain="base"):
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_reorg_test",
            amount=amount,
            currency=currency,
            chain=chain,
            recipient=recipient,
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


def _ev(*, invoice_id, tx_hash, block_number, block_hash,
        merchant=MERCHANT, token=USDC_ADDR, amount=AMT, log_index=0, fee=BASE_FEE):
    return {
        "invoice_id": invoice_id.lower(),
        "merchant": merchant.lower(),
        "payer": PAYER.lower(),
        "token": token.lower(),
        "amount": amount,
        "fee": fee,
        "block_timestamp": 1_700_000_000,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "block_number": block_number,
        "block_hash": block_hash.lower(),
    }


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def _word(n: int) -> str:
    return f"{n:064x}"


def _make_log(*, invoice_id, tx_hash, block_number, block_hash, address=ROUTER,
              merchant=MERCHANT, token=USDC_ADDR, amount=AMT, fee=BASE_FEE, log_index=0):
    data = "0x" + _addr_word(token) + _word(amount) + _word(fee) + _word(1_700_000_000)
    return {
        "address": address,
        "topics": [PAYMENT_MADE_TOPIC, invoice_id, "0x" + _addr_word(merchant), "0x" + _addr_word(payer := PAYER)],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block_number),
        "blockHash": block_hash,
    }


class FakeChain:
    """Mock JSON-RPC: eth_blockNumber / eth_getBlockByNumber / eth_getLogs /
    eth_getTransactionReceipt.

    Note: eth_getLogs intentionally returns ALL logs in range regardless of the
    `address` filter, so the indexer's per-log source-authenticity guard is the
    thing under test (simulates a buggy/hostile RPC returning extra logs).
    `receipts` maps tx_hash → receipt blockHash; a missing/None entry means the
    tx has no receipt (gone) — the reorg-evidence corroboration reads this.
    """
    def __init__(self):
        self.latest = 0
        self.finalized = 0
        self.block_hashes: dict[int, str] = {}
        self.logs: list[dict] = []
        self.receipts: dict[str, str | None] = {}

    async def call(self, method, params, **kw):
        if method == "eth_blockNumber":
            return hex(self.latest)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag in ("finalized", "safe"):
                return {"number": hex(self.finalized),
                        "hash": self.block_hashes.get(self.finalized, "0x" + "00" * 32)}
            bn = int(tag, 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": hex(bn), "hash": h}
        if method == "eth_getLogs":
            f = int(params[0]["fromBlock"], 16)
            t = int(params[0]["toBlock"], 16)
            return [lg for lg in self.logs if f <= int(lg["blockNumber"], 16) <= t]
        if method == "eth_getTransactionReceipt":
            h = self.receipts.get(params[0].lower())
            return None if h is None else {"blockHash": h}
        raise AssertionError(f"unexpected RPC {method}")


async def _settlement_count(tx_hash=None):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        q = select(func.count()).select_from(PaymentSettlement)
        if tx_hash:
            q = q.where(PaymentSettlement.tx_hash == tx_hash.lower())
        return (await db.execute(q)).scalar_one()


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


# ═══════════════════════════════════════════════════════════════
#  Lifecycle
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_valid_event_finalizes_pays_and_fires_webhook_once(webhook_calls):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "11" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "a1" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "aa" * 32, block_number=100, block_hash=H)

    # INGEST → pending, NOT paid, no webhook
    assert await _record_settlement(CHAIN, ev) == "new"
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []

    # FINALIZE (block 100 well below final_head 200) → final + paid + webhook once
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 1
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.final and s.finalized_at is not None
    assert s.webhook_fired_at is not None
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # Re-running finalize must NOT fire a second webhook.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_below_depth_pending_then_final(webhook_calls):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "12" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "b2" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "bb" * 32, block_number=100, block_hash=H)
    await _record_settlement(CHAIN, ev)

    # final_head below the settlement block → still pending, not paid.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=50)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []

    # final_head now past it → final + paid.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_duplicate_log_is_idempotent(webhook_calls):
    inv = "0x" + "13" * 32
    await _make_intent(invoice_id=inv)
    H = "0x" + "c3" * 32
    rpc = FakeChain(); rpc.block_hashes[100] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "cc" * 32, block_number=100, block_hash=H, log_index=7)

    assert await _record_settlement(CHAIN, ev) == "new"
    assert await _record_settlement(CHAIN, ev) == "duplicate"
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert await _record_settlement(CHAIN, ev) == "duplicate"

    assert await _settlement_count(ev["tx_hash"]) == 1
    assert webhook_calls == ["payment.completed"]


@pytest.mark.parametrize("field,value,tag", [
    ("merchant", "0x" + "9" * 40, "41"),
    ("token", "0x" + "9" * 40, "42"),
    ("amount", AMT - 1, "43"),
])
@pytest.mark.asyncio
async def test_validation_mismatch_rejected_not_paid(webhook_calls, field, value, tag):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + tag * 32           # unique per param so cases never collide
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + tag * 32
    rpc = FakeChain(); rpc.block_hashes[100] = H
    kwargs = {"invoice_id": inv, "tx_hash": "0x" + tag * 32, "block_number": 100, "block_hash": H}
    kwargs[field] = value
    ev = _ev(**kwargs)

    assert await _record_settlement(CHAIN, ev) == "new"
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.rejected
    # F-4: rejected + alert only — the intent is untouched (public invoiceId,
    # a stranger's mismatch must not flip a pending intent to review).
    assert (await _intent(iid)).status == IntentStatus.pending
    assert (await _intent(iid)).matched_tx_hash is None

    # Rejected rows never finalize/pay.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert (await _intent(iid)).status != IntentStatus.paid
    assert webhook_calls == []


# ═══════════════════════════════════════════════════════════════
#  Reorg safety
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_reorg_of_pending_settlement_marked_reorged(webhook_calls):
    """B-2: a reorg of a PENDING settlement is honored only after
    REORG_EVIDENCE_TICKS consecutive ticks of (hash mismatch + tx receipt gone)
    — never on a single RPC answer."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "15" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    rpc.block_hashes[100] = "0x" + "e5" * 32  # observed hash
    ev = _ev(invoice_id=inv, tx_hash="0x" + "e5" * 32, block_number=100,
             block_hash="0x" + "e5" * 32)
    await _record_settlement(CHAIN, ev)

    # Reorg: block 100 now has a DIFFERENT canonical hash AND the tx is gone.
    rpc.block_hashes[100] = "0x" + "ff" * 32
    rpc.receipts[ev["tx_hash"]] = None

    # Evidence must persist: nothing reverses before the threshold tick.
    # (getattr default keeps this a behavior-FAIL, not an AttributeError,
    # against pre-B-2 code.)
    for _ in range(getattr(idx, "REORG_EVIDENCE_TICKS", 3) - 1):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert res["reorged"] == 0
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending

    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["reorged"] == 1
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.reorged
    assert (await _intent(iid)).status == IntentStatus.pending  # never paid
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_finalized_settlement_survives_reported_reorg(webhook_calls):
    """B-2: FINALIZED IS TERMINAL. A settlement past finality is never reverted
    by the reconciler, no matter what the RPC reports — no payment.reversed.
    (Replaces the pre-B-2 pin that reversed a finalized payment on one answer.)"""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "16" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "16" * 32
    rpc = FakeChain()
    rpc.block_hashes[180] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + "16" * 32, block_number=180, block_hash=H)

    await _record_settlement(CHAIN, ev)
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # RPC now claims block 180 has a different hash and the tx is gone —
    # persistently. The finalized payment must not move.
    rpc.block_hashes[180] = "0x" + "fe" * 32
    rpc.receipts[ev["tx_hash"]] = None
    for _ in range(getattr(idx, "REORG_EVIDENCE_TICKS", 3) + 2):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert res["reorged"] == 0

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


# ═══════════════════════════════════════════════════════════════
#  Source authenticity + restart/gap (full _tick path)
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_non_router_address_log_is_ignored(monkeypatch, webhook_calls):
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "17" * 32
    iid = await _make_intent(invoice_id=inv)

    rpc = FakeChain()
    rpc.latest = 300
    rpc.finalized = 200
    rpc.block_hashes[100] = "0x" + "17" * 32
    # Same-signature PaymentMade, but emitted by a FOREIGN contract address.
    rpc.logs = [_make_log(invoice_id=inv, tx_hash="0x" + "17" * 32, block_number=100,
                          block_hash="0x" + "17" * 32, address="0x" + "9" * 40)]

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    cursor = {CHAIN: 50}
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    await w._tick()

    assert await _settlement_count() == 0           # foreign log dropped
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_restart_resumes_from_last_block_no_miss_no_duplicate(monkeypatch, webhook_calls):
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "18" * 32
    iid = await _make_intent(invoice_id=inv)

    H = "0x" + "18" * 32
    rpc = FakeChain()
    # +margin: the scan window tops out at latest − HEAD_SAFETY_MARGIN (=110).
    rpc.latest = 110 + idx.HEAD_SAFETY_MARGIN
    rpc.finalized = 108
    rpc.block_hashes[105] = H
    rpc.logs = [_make_log(invoice_id=inv, tx_hash="0x" + "18" * 32, block_number=105,
                          block_hash=H, address=ROUTER)]

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    cursor = {CHAIN: 100}  # we restarted having processed up to block 100
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    await w._tick()  # scans 101..110, log at 105 caught, finalized (105 <= 108)

    assert (await _intent(iid)).status == IntentStatus.paid
    assert await _settlement_count() == 1
    assert cursor[CHAIN] == 110                      # cursor advanced
    assert webhook_calls == ["payment.completed"]

    # Tick again — no missed/duplicated work, no second webhook.
    await w._tick()
    assert await _settlement_count() == 1
    assert webhook_calls == ["payment.completed"]


# ── tiny async shims for monkeypatched redis-cursor helpers ──
async def _async_return(v):
    return v


async def _async_set(d, c, b):
    d[c] = b


# ═════════════════════════════════════════════════════════════════
#  eth_getLogs chunking (Alchemy free tier caps the range at 10)
# ═════════════════════════════════════════════════════════════════

ALCHEMY_RANGE_ERROR = (
    "RPC eth_getLogs error: {'code': -32600, 'message': 'Under the Free tier "
    "plan, you can make eth_getLogs requests with up to a 10 block range.'}"
)


class RangeLimitedChain(FakeChain):
    """FakeChain that rejects eth_getLogs spans wider than `max_range` (the
    Alchemy free-tier behavior) and records every requested span."""

    def __init__(self, max_range: int = 10):
        super().__init__()
        self.max_range = max_range
        self.getlogs_spans: list[tuple[int, int]] = []
        self.fail_at_call: int | None = None  # 1-based getLogs call to fail

    async def call(self, method, params, **kw):
        if method == "eth_getLogs":
            f = int(params[0]["fromBlock"], 16)
            t = int(params[0]["toBlock"], 16)
            self.getlogs_spans.append((f, t))
            if self.fail_at_call is not None and len(self.getlogs_spans) == self.fail_at_call:
                raise RuntimeError("transient RPC blip")
            if t - f + 1 > self.max_range:
                raise RuntimeError(ALCHEMY_RANGE_ERROR)
        return await super().call(method, params, **kw)


def _wire(monkeypatch, rpc, cursor):
    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))


def test_getlogs_max_range_config_default_is_10():
    from app.config import Settings

    assert Settings.model_fields["indexer_getlogs_max_range"].default == 10


@pytest.mark.asyncio
async def test_getlogs_chunked_within_provider_limit(monkeypatch, webhook_calls):
    """A 60-block window against a 10-block provider limit must be scanned in
    chunks the provider accepts — no request wider than the limit, no log
    missed, cursor at the end of the window."""
    from app.models.merchant_models import IntentStatus

    inv_a, inv_b = "0x" + "21" * 32, "0x" + "22" * 32
    iid_a = await _make_intent(invoice_id=inv_a)
    iid_b = await _make_intent(invoice_id=inv_b)

    rpc = RangeLimitedChain(max_range=10)
    rpc.latest = 160 + idx.HEAD_SAFETY_MARGIN  # window still ends at 160
    rpc.finalized = 158
    ha, hb = "0x" + "21" * 32, "0x" + "22" * 32
    rpc.block_hashes[105] = ha
    rpc.block_hashes[155] = hb
    rpc.logs = [
        _make_log(invoice_id=inv_a, tx_hash="0x" + "21" * 32, block_number=105,
                  block_hash=ha, address=ROUTER),
        _make_log(invoice_id=inv_b, tx_hash="0x" + "22" * 32, block_number=155,
                  block_hash=hb, address=ROUTER),
    ]

    cursor = {CHAIN: 100}
    _wire(monkeypatch, rpc, cursor)

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    await w._tick()

    assert all(t - f + 1 <= 10 for f, t in rpc.getlogs_spans), rpc.getlogs_spans
    assert len(rpc.getlogs_spans) >= 6                     # 101..160 in ≤10-block chunks
    assert (await _intent(iid_a)).status == IntentStatus.paid
    assert (await _intent(iid_b)).status == IntentStatus.paid
    assert await _settlement_count() == 2
    assert cursor[CHAIN] == 160


@pytest.mark.asyncio
async def test_chunk_failure_preserves_partial_progress(monkeypatch, webhook_calls):
    """A failure mid-window must not throw away completed chunks: the cursor
    stops at the last successful chunk and the next tick resumes exactly
    there — never the same oversized range forever."""
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "23" * 32
    iid = await _make_intent(invoice_id=inv)

    rpc = RangeLimitedChain(max_range=10)
    rpc.latest = 160 + idx.HEAD_SAFETY_MARGIN  # window still ends at 160
    rpc.finalized = 158
    h = "0x" + "23" * 32
    rpc.block_hashes[105] = h
    rpc.logs = [_make_log(invoice_id=inv, tx_hash="0x" + "23" * 32, block_number=105,
                          block_hash=h, address=ROUTER)]

    cursor = {CHAIN: 100}
    _wire(monkeypatch, rpc, cursor)
    rpc.fail_at_call = 3  # chunks 101-110 and 111-120 succeed, 121-130 blows up

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with pytest.raises(RuntimeError, match="transient RPC blip"):
        await w._tick()

    assert cursor[CHAIN] == 120                            # partial progress kept
    assert await _settlement_count() == 1                  # log at 105 ingested

    # Next tick resumes from the exact failure point and completes the window.
    rpc.fail_at_call = None
    await w._tick()
    assert rpc.getlogs_spans[-((160 - 121) // 10 + 1)][0] == 121   # resumed at 121
    assert cursor[CHAIN] == 160
    assert (await _intent(iid)).status == IntentStatus.paid
    assert await _settlement_count() == 1                  # no duplicates
