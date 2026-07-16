"""B-2: a single unverified RPC response must never reverse a confirmed payment.

The reorg reconciler used to flip settlements off `final` (un-paying the intent
and firing payment.reversed) on ONE differing eth_getBlockByNumber answer — a
lagging/forked provider was enough to revert a confirmed payment, and a falsely
reversed FINAL row could never recover (its block is outside the ingest re-scan
tail), permanently re-stranding an intent B-1 just rescued.

Invariants pinned here:
  - FINALIZED IS TERMINAL: a `final` settlement (finalized_at set) is never
    reverted by the reconciler nor by the ingest re-inclusion path — the latter
    logs CRITICAL and mutates nothing.
  - PENDING rows reverse only on real evidence: REORG_EVIDENCE_TICKS (3)
    consecutive ticks where the canonical block hash differs AND
    eth_getTransactionReceipt reports the tx gone. Contrary or missing evidence
    resets the counter. A receipt alive in a different block blocks reversal
    (re-inclusion is INGEST's job). block_hash=None rows are unverifiable.

All RPC mocked. Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_reorg_evidence.py
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.payment_indexer as idx
from app.services.payment_indexer import _record_settlement, _finalize_and_reconcile
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
AMT = to_base_units(100.0, USDC_DEC)


# ── fixtures (house pattern) ─────────────────────────────────
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


@pytest_asyncio.fixture(autouse=True)
async def _clear_suspects():
    suspects = getattr(idx, "_REORG_SUSPECTS", None)
    if suspects is not None:
        suspects.clear()
    yield
    if suspects is not None:
        suspects.clear()


@pytest.fixture
def webhook_calls(monkeypatch):
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers ──────────────────────────────────────────────────
async def _make_intent(*, invoice_id, status=None, expires_delta_minutes=30):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_evidence_test",
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


class EvidenceChain:
    """Mock RPC: block hashes at heights + tx receipts.

    receipts: tx_hash → block_hash of the receipt, None for "no receipt"
    (tx gone). A tx_hash missing from the dict also means no receipt.
    """

    def __init__(self):
        self.block_hashes: dict[int, str] = {}
        self.receipts: dict[str, str | None] = {}
        self.receipt_calls = 0

    async def call(self, method, params, **kw):
        if method == "eth_getBlockByNumber":
            bn = int(params[0], 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": hex(bn), "hash": h}
        if method == "eth_getTransactionReceipt":
            self.receipt_calls += 1
            h = self.receipts.get(params[0].lower())
            return None if h is None else {"blockHash": h}
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


async def _seed_final_paid(tag: str, block=180):
    """intent + settlement ingested and finalized → (iid, ev, rpc).

    block=180 sits INSIDE the pre-B-2 re-verify window (final_head 200 − depth
    64) — the regression these tests pin only fired there."""
    inv = "0x" + tag * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + tag * 32
    rpc = EvidenceChain()
    rpc.block_hashes[block] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + tag * 32, block_number=block, block_hash=H)
    rpc.receipts[ev["tx_hash"]] = H
    assert await _record_settlement(CHAIN, ev) == "new"
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    return iid, ev, rpc


# ═══════════════════════════════════════════════════════════════
#  Finalized is terminal
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_single_bad_rpc_answer_does_not_revert_final(webhook_calls):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("51")
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # One lagging/forked provider answer: different hash, receipt gone too.
    rpc.block_hashes[180] = "0x" + "ff" * 32
    rpc.receipts[ev["tx_hash"]] = None
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)

    assert res["reorged"] == 0
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.final
    assert s.finalized_at is not None
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]  # no payment.reversed


@pytest.mark.asyncio
async def test_finalized_survives_persistent_bad_rpc(webhook_calls):
    """Even *persistent* wrong answers never revert a finalized payment."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("52")
    rpc.block_hashes[180] = "0x" + "fe" * 32
    rpc.receipts[ev["tx_hash"]] = None

    for _ in range(6):  # well past any evidence threshold
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200)

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_ingest_reinclusion_over_final_row_is_conflict_not_reversal(
    webhook_calls, caplog
):
    """The same log re-observed in a different block over a FINAL row must not
    auto-reverse: CRITICAL alert, no mutation."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("53")

    moved = dict(ev, block_number=181, block_hash="0x" + "fd" * 32)
    with caplog.at_level(logging.CRITICAL, logger="payment_indexer"):
        action = await _record_settlement(CHAIN, moved)

    assert action == "conflict"
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.final
    assert s.finalized_at is not None
    assert s.block_number == 180                      # untouched
    assert s.block_hash == ev["block_hash"]
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]     # no payment.reversed
    assert any("finalized" in r.message and "manual" in r.message
               for r in caplog.records if r.levelno == logging.CRITICAL)


@pytest.mark.asyncio
async def test_rescued_intent_is_not_restranded(webhook_calls):
    """B-1 interplay: an intent rescued expired→paid must survive adversarial
    RPC afterwards — the reconciler never re-strands it."""
    from app.db.session import async_session
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import PaymentIntent, IntentStatus

    inv = "0x" + "54" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "54" * 32
    rpc = EvidenceChain()
    rpc.block_hashes[180] = H  # inside the pre-B-2 re-verify window
    ev = _ev(invoice_id=inv, tx_hash="0x" + "54" * 32, block_number=180, block_hash=H)
    await _record_settlement(CHAIN, ev)

    # Expiry wins the race...
    async with async_session() as db:
        row = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()
        row.status = IntentStatus.expired
        await db.commit()

    # ...B-1 rescues at finality...
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # ...and adversarial RPC afterwards changes nothing.
    rpc.block_hashes[180] = "0x" + "fc" * 32
    rpc.receipts[ev["tx_hash"]] = None
    for _ in range(6):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200)

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


# ═══════════════════════════════════════════════════════════════
#  Pending rows: reversal needs evidence
# ═══════════════════════════════════════════════════════════════
async def _seed_pending(tag: str, block=250):
    """Pending settlement ABOVE final_head=200 (so it never finalizes here)."""
    inv = "0x" + tag * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + tag * 32
    rpc = EvidenceChain()
    rpc.block_hashes[block] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + tag * 32, block_number=block, block_hash=H)
    rpc.receipts[ev["tx_hash"]] = H
    assert await _record_settlement(CHAIN, ev) == "new"
    return iid, ev, rpc


@pytest.mark.asyncio
async def test_real_reorg_needs_three_consecutive_evidence_ticks(webhook_calls):
    """Wrong hash + tx gone must persist for REORG_EVIDENCE_TICKS ticks before
    the reversal happens — and then exactly once."""
    from app.models.settlement_models import SettlementStatus

    iid, ev, rpc = await _seed_pending("61")

    # Genuine reorg: canonical hash differs AND the tx has no receipt.
    rpc.block_hashes[250] = "0x" + "ee" * 32
    rpc.receipts[ev["tx_hash"]] = None

    # Ticks 1 and 2: suspicion only — nothing reversed yet.
    for tick in (1, 2):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert res["reorged"] == 0, f"reversed too early (tick {tick})"
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending

    # Tick 3: evidence complete → reversed exactly once.
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["reorged"] == 1
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.reorged
    assert webhook_calls == []  # pending row: no completed, no reversed webhook

    # Later ticks: idempotent, no oscillation.
    for _ in range(3):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert res["reorged"] == 0
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.reorged


@pytest.mark.asyncio
async def test_transient_mismatch_resets_evidence_no_oscillation(webhook_calls):
    """Alternating wrong/right answers (flaky provider) must never reverse."""
    from app.models.settlement_models import SettlementStatus

    iid, ev, rpc = await _seed_pending("62")
    good, bad = rpc.block_hashes[250], "0x" + "ed" * 32

    for i in range(8):
        rpc.block_hashes[250] = bad if i % 2 == 0 else good
        rpc.receipts[ev["tx_hash"]] = None if i % 2 == 0 else good
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending

    assert webhook_calls == []


@pytest.mark.asyncio
async def test_receipt_alive_elsewhere_blocks_reversal(webhook_calls):
    """Hash mismatch but the tx is alive in another block → the log moved;
    re-inclusion is INGEST's job. Never reverse on this."""
    from app.models.settlement_models import SettlementStatus

    iid, ev, rpc = await _seed_pending("63")
    rpc.block_hashes[250] = "0x" + "ec" * 32
    rpc.receipts[ev["tx_hash"]] = "0x" + "eb" * 32  # alive, different block

    for _ in range(5):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending

    assert webhook_calls == []


@pytest.mark.asyncio
async def test_missing_block_hash_row_is_never_reversed(webhook_calls):
    """A row without a stored block_hash is unverifiable — skip, don't reverse."""
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement, SettlementStatus

    iid, ev, rpc = await _seed_pending("64")
    async with async_session() as db:
        row = (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
        )).scalar_one()
        row.block_hash = None
        await db.commit()

    rpc.receipts[ev["tx_hash"]] = None
    for _ in range(5):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.pending

    assert webhook_calls == []
