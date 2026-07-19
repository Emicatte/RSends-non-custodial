"""F-1 + F-10: depth-mode finality is reorg-safe — final is reconcilable until
TRUE L1 finality, and a finality downgrade is loud, never silent.

Before this fix, depth mode (INDEXER_USE_FINALIZED_TAG=false, the demo config)
marked an intent paid and fired payment.completed at latest−15, then treated
`final` as terminal forever: the reconciler selected pending rows only, ingest
rescanned only the unfinalized tail, and the payment.reversed dispatch was
gated on webhook_fired_at — a flag only ever set together with status=final —
so it was provably dead code. A >15-block reorg before true finality left a
permanent false-paid. F-10 compounded it: in tag mode, any finalized-tag RPC
hiccup silently fell back to depth semantics with no log and no metric.

Invariants pinned here:
  - A `final` settlement ABOVE the true-finality boundary (terminal_head) is
    reconcilable: hash-mismatch + receipt-gone evidence held for
    FINAL_REORG_EVIDENCE_TICKS (6, stricter than pending's 3) consecutive
    ticks reverses it — payment.reversed fires (the merchant was told paid).
  - A settlement AT or BELOW terminal_head is terminal: no adversarial RPC
    sequence ever reverses it (tag-mode semantics preserved).
  - terminal_head=None (finalized tag unknown) keeps ALL final rows
    reconcilable — fail-safe, never fail-terminal.
  - Contrary evidence resets the final-row counter (no oscillation); a receipt
    alive elsewhere never reverses (money is on-chain).
  - F-10: tag mode with the tag unavailable REFUSES to finalize that tick and
    announces the degradation (gauge + transition WARNING + CRITICAL after
    FINALITY_DEGRADED_CRITICAL_TICKS + INFO on recovery). Depth mode keeps
    paying at depth (the paid gate never depends on the tag) but the terminal
    boundary freezes and the same degradation signals fire.
  - Re-finalization after a reversal (tx re-included later) re-pays the intent
    but cannot re-fire payment.completed (claim consumed; delivery-layer dedup
    would suppress it anyway) — it must CRITICAL-alert instead.

All RPC mocked. Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_terminal_reconcile.py
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.payment_indexer as idx
from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PaymentWatcher,
    _finalize_and_reconcile,
    _record_settlement,
)
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
ROUTER = "0x" + "a" * 40
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
AMT = to_base_units(100.0, USDC_DEC)
DEPTH = 15
TICKS_FINAL = 6  # expected FINAL_REORG_EVIDENCE_TICKS (pinned below)


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
    idx._REORG_SUSPECTS.clear()
    yield
    idx._REORG_SUSPECTS.clear()


@pytest.fixture
def depth_mode(monkeypatch):
    """Flip the CACHED settings object into depth mode, as the Render env
    flip would after restart."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "indexer_use_finalized_tag", False)
    monkeypatch.setattr(s, "indexer_confirmations", DEPTH)
    return s


@pytest.fixture
def tag_mode(monkeypatch):
    """Pin the cached settings to finalized-tag mode explicitly."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "indexer_use_finalized_tag", True)
    monkeypatch.setattr(s, "indexer_finalized_tag", "finalized")
    monkeypatch.setattr(s, "indexer_confirmations", DEPTH)
    return s


@pytest.fixture
def webhook_calls(monkeypatch):
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers (house pattern) ──────────────────────────────────
async def _make_intent(*, invoice_id, expires_delta_minutes=30):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_terminal_test",
            amount=100.0,
            currency="USDC",
            chain="base",
            recipient=MERCHANT,
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
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


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def _word(n: int) -> str:
    return f"{n:064x}"


def _make_log(*, invoice_id, tx_hash, block_number, block_hash):
    data = "0x" + _addr_word(USDC_ADDR) + _word(AMT) + _word(600000) + _word(1_700_000_000)
    return {
        "address": ROUTER,
        "topics": [PAYMENT_MADE_TOPIC, invoice_id,
                   "0x" + _addr_word(MERCHANT), "0x" + _addr_word(PAYER)],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(0),
        "blockNumber": hex(block_number),
        "blockHash": block_hash,
    }


class FakeChain:
    """Full mock RPC: latest head, finalized tag (can raise / return None),
    numeric block hashes, getLogs, receipts."""

    def __init__(self):
        self.latest = 0
        self.finalized = 0
        self.tag_raises = False
        self.tag_returns_none = False
        self.tag_calls = 0
        self.block_hashes: dict[int, str] = {}
        self.logs: list[dict] = []
        self.receipts: dict[str, str | None] = {}

    async def call(self, method, params, **kw):
        if method == "eth_blockNumber":
            return hex(self.latest)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag in ("finalized", "safe"):
                self.tag_calls += 1
                if self.tag_raises:
                    raise RuntimeError("finalized tag unsupported")
                if self.tag_returns_none:
                    return None
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


async def _async_return(v):
    return v


async def _async_set(d, c, b):
    d[c] = b


def _wire(monkeypatch, rpc, cursor):
    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))


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


async def _seed_final_paid(tag: str, *, block=180, expires_delta_minutes=30):
    """intent + settlement ingested and FINALIZED (paid, completed fired)
    → (iid, ev, rpc). Seed uses the default terminal semantics (== final_head),
    i.e. exactly what tag mode does today."""
    inv = "0x" + tag * 32
    iid = await _make_intent(invoice_id=inv,
                             expires_delta_minutes=expires_delta_minutes)
    H = "0x" + tag * 32
    rpc = FakeChain()
    rpc.block_hashes[block] = H
    ev = _ev(invoice_id=inv, tx_hash="0x" + tag * 32, block_number=block, block_hash=H)
    rpc.receipts[ev["tx_hash"]] = H
    assert await _record_settlement(CHAIN, ev) == "new"
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    return iid, ev, rpc


def _go_bad(rpc, ev, block=180):
    """Adversarial chain state: canonical hash differs AND the receipt is gone."""
    rpc.block_hashes[block] = "0x" + "ff" * 32
    rpc.receipts[ev["tx_hash"]] = None


# ═══════════════════════════════════════════════════════════════
#  Constants + alert types (the new knobs, pinned)
# ═══════════════════════════════════════════════════════════════
def test_final_evidence_ticks_constant():
    """Final rows need MORE evidence than pending ones — reversing an
    already-announced payment is the costlier mistake."""
    assert idx.REORG_EVIDENCE_TICKS == 3          # unchanged (B-2)
    assert idx.FINAL_REORG_EVIDENCE_TICKS == TICKS_FINAL
    assert idx.FINALITY_DEGRADED_CRITICAL_TICKS == 3


def test_finality_alert_types_exist():
    from app.services.alert_service import AlertSeverity, AlertType, SEVERITY_MAP

    assert SEVERITY_MAP[AlertType.FINALITY_DEGRADED] is AlertSeverity.CRITICAL
    assert SEVERITY_MAP[AlertType.FINALITY_RESTORED] is AlertSeverity.INFO


# ═══════════════════════════════════════════════════════════════
#  Final rows above terminal_head are reconcilable (core F-1)
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_depth_final_row_reverses_on_held_evidence(webhook_calls):
    """A final (paid, completed-fired) settlement whose block reorgs out BEFORE
    true finality is reversed after FINAL_REORG_EVIDENCE_TICKS consecutive
    evidence ticks — and payment.reversed fires (the dead dispatch, revived)."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("81")
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    _go_bad(rpc, ev)

    # Ticks 1..5: suspicion only — an announced payment needs the FULL window.
    for tick in range(1, TICKS_FINAL):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                            terminal_head=170)
        assert res["reorged"] == 0, f"reversed too early (tick {tick})"
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
        assert (await _intent(iid)).status == IntentStatus.paid

    # Tick 6: evidence held → reversed exactly once, merchant notified.
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                        terminal_head=170)
    assert res["reorged"] == 1
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.reorged
    assert s.finalized_at is None
    assert (await _intent(iid)).status == IntentStatus.pending  # un-paid
    assert webhook_calls == ["payment.completed", "payment.reversed"]

    # Later ticks: idempotent — reorged rows are never re-selected.
    for _ in range(3):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                            terminal_head=170)
        assert res["reorged"] == 0
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.reorged
    assert webhook_calls == ["payment.completed", "payment.reversed"]


@pytest.mark.asyncio
async def test_truly_final_row_survives_adversarial_rpc(webhook_calls):
    """AT or BELOW terminal_head the row is terminal: no adversarial sequence
    reverses it — tag-mode ('finalized cannot reorg') semantics preserved."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("82")
    _go_bad(rpc, ev)

    for _ in range(TICKS_FINAL + 2):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                            terminal_head=185)  # 180 <= 185
        assert res["reorged"] == 0

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_terminal_unknown_keeps_final_reconcilable(webhook_calls):
    """terminal_head=None (finalized tag unknown) must fail SAFE: every final
    row stays reconcilable — never silently terminal."""
    from app.models.settlement_models import SettlementStatus

    iid, ev, rpc = await _seed_final_paid("83")
    _go_bad(rpc, ev)

    for _ in range(TICKS_FINAL - 1):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=None)
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=None)

    assert res["reorged"] == 1
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.reorged
    assert webhook_calls == ["payment.completed", "payment.reversed"]


@pytest.mark.asyncio
async def test_final_row_evidence_flap_resets_no_oscillation(webhook_calls):
    """Contrary evidence resets the final-row counter: 5 bad ticks + 1 good
    tick + 5 bad ticks never reverse; only a FULL consecutive window does."""
    from app.models.settlement_models import SettlementStatus

    iid, ev, rpc = await _seed_final_paid("84")
    good = ev["block_hash"]

    _go_bad(rpc, ev)
    for _ in range(TICKS_FINAL - 1):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=170)

    # Canonical again for one tick — the provider was forked/lagging.
    rpc.block_hashes[180] = good
    rpc.receipts[ev["tx_hash"]] = good
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=170)

    # 5 more bad ticks: counter restarted, still nothing.
    _go_bad(rpc, ev)
    for tick in range(1, TICKS_FINAL):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                            terminal_head=170)
        assert res["reorged"] == 0, f"counter did not reset (tick {tick})"
        assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final

    # The 6th consecutive completes the fresh window → exactly one reversal.
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=170)
    assert res["reorged"] == 1
    assert webhook_calls == ["payment.completed", "payment.reversed"]


@pytest.mark.asyncio
async def test_final_row_receipt_alive_elsewhere_never_reversed(webhook_calls):
    """Hash mismatch but the tx is alive in another block: the money is
    on-chain — 'paid' stays TRUE. Never reverse on a moved tx."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("85")
    rpc.block_hashes[180] = "0x" + "fe" * 32
    rpc.receipts[ev["tx_hash"]] = "0x" + "fd" * 32  # alive, different block

    for _ in range(TICKS_FINAL + 2):
        res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200,
                                            terminal_head=170)
        assert res["reorged"] == 0

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


# ═══════════════════════════════════════════════════════════════
#  Full _tick, depth mode — the config the demo runs on
# ═══════════════════════════════════════════════════════════════
def _paid_setup(rpc, *, invoice, block=185, latest=200, finalized=100):
    """Chain state for a canonical payment at `block`, depth-payable at
    `latest`, with true finality lagging at `finalized`."""
    H = invoice  # reuse the 32-byte pattern as block hash
    rpc.latest = latest
    rpc.finalized = finalized
    rpc.block_hashes[block] = H
    tx = invoice
    rpc.logs = [_make_log(invoice_id=invoice, tx_hash=tx,
                          block_number=block, block_hash=H)]
    rpc.receipts[tx.lower()] = H
    return tx


@pytest.mark.asyncio
async def test_tick_depth_mode_deep_reorg_fires_payment_reversed(
    depth_mode, monkeypatch, webhook_calls
):
    """END TO END (the F-1 scenario): paid at depth-15, then a >15-block reorg
    drops the block before true finality → the settlement reverses and
    payment.reversed reaches the merchant."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "86" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    tx = _paid_setup(rpc, invoice=inv)

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    await w._tick()  # block 185 is 15 deep at latest=200 → paid, fast path
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]

    # Deep reorg: block 185 drops out entirely, the tx is gone.
    rpc.block_hashes[185] = "0x" + "ff" * 32
    rpc.receipts[tx.lower()] = None

    for tick in range(1, TICKS_FINAL):
        await w._tick()
        s = await _settlement(tx)
        assert s.status == SettlementStatus.final, f"reversed too early (tick {tick})"

    await w._tick()  # 6th consecutive evidence tick
    assert (await _settlement(tx)).status == SettlementStatus.reorged
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == ["payment.completed", "payment.reversed"]


@pytest.mark.asyncio
async def test_tick_depth_mode_truly_final_never_reversed(
    depth_mode, monkeypatch, webhook_calls
):
    """Once the finalized tag passes the block, depth mode is exactly as
    terminal as tag mode — adversarial RPC changes nothing. (Guard pin: green
    before and after the fix; it bounds the reconcilable window.)"""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "87" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    tx = _paid_setup(rpc, invoice=inv)

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    await w._tick()
    assert (await _intent(iid)).status == IntentStatus.paid

    rpc.finalized = 190          # true finality passes block 185
    await w._tick()              # healthy tick observes it

    rpc.block_hashes[185] = "0x" + "ff" * 32
    rpc.receipts[tx.lower()] = None
    for _ in range(TICKS_FINAL + 2):
        await w._tick()

    assert (await _settlement(tx)).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_tick_terminal_ratchet_never_regresses(
    depth_mode, monkeypatch, webhook_calls
):
    """The terminal boundary is a rise-only ratchet: a failover provider
    reporting an OLDER finalized tag (healthy fetch, lower value) must not
    lower it — a row already terminal can never be re-opened for reversal,
    no matter what evidence the lagging provider serves afterwards."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "8d" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    tx = _paid_setup(rpc, invoice=inv, finalized=190)

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    await w._tick()  # paid at depth AND immediately terminal (185 <= 190)
    assert (await _intent(iid)).status == IntentStatus.paid
    assert w._terminal_ratchet == 190

    # Failover to a lagging provider: the tag REGRESSES below the settled
    # block, and the same provider serves full reversal evidence.
    rpc.finalized = 100
    rpc.block_hashes[185] = "0x" + "ff" * 32
    rpc.receipts[tx.lower()] = None
    for _ in range(TICKS_FINAL + 2):
        await w._tick()

    assert w._terminal_ratchet == 190  # never went backwards
    assert (await _settlement(tx)).status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]  # no payment.reversed


@pytest.mark.asyncio
async def test_tick_depth_mode_tag_outage_loud_but_still_safe(
    depth_mode, monkeypatch, webhook_calls, caplog
):
    """Depth mode with the finalized tag unavailable: payments still complete
    at depth (the paid gate never depends on the tag), the degradation is
    announced ONCE (gauge + WARNING, CRITICAL after 3 consecutive), and final
    rows remain reconcilable — a deep reorg still reverses."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "88" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    tx = _paid_setup(rpc, invoice=inv)
    rpc.tag_raises = True  # terminal boundary unknowable from tick one

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.INFO, logger="payment_indexer"):
        await w._tick()
        assert (await _intent(iid)).status == IntentStatus.paid  # depth pays
        assert idx.INDEXER_FINALITY_DEGRADED.labels(chain_id=CHAIN)._value.get() == 1

        await w._tick()  # second degraded tick: no WARNING storm
        degraded_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "DEGRADED" in r.message
        ]
        assert len(degraded_warnings) == 1

        await w._tick()  # third consecutive → CRITICAL escalation
        assert any(
            r.levelno == logging.CRITICAL and "DEGRADED" in r.message
            for r in caplog.records
        )

        # Deep reorg DURING the outage: terminal unknown → still reversible.
        rpc.block_hashes[185] = "0x" + "ff" * 32
        rpc.receipts[tx.lower()] = None
        for _ in range(TICKS_FINAL):
            await w._tick()
        assert (await _settlement(tx)).status == SettlementStatus.reorged
        assert webhook_calls == ["payment.completed", "payment.reversed"]

        # Recovery: gauge drops, restoration announced.
        rpc.tag_raises = False
        rpc.finalized = 100
        await w._tick()
        assert idx.INDEXER_FINALITY_DEGRADED.labels(chain_id=CHAIN)._value.get() == 0
        assert any(
            r.levelno == logging.INFO and "RESTORED" in r.message
            for r in caplog.records
        )
    await asyncio.sleep(0)  # let fire-and-forget alert tasks run out


# ═══════════════════════════════════════════════════════════════
#  F-10: tag mode must refuse to finalize when the tag is unavailable
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_tick_tag_mode_outage_refuses_to_finalize_loudly(
    tag_mode, monkeypatch, webhook_calls, caplog
):
    """The operator chose 'paid = L1-final'. A tag outage must NOT silently pay
    at depth under that banner: nothing finalizes during the outage, the
    degradation is announced (gauge + WARNING once + CRITICAL at 3), and
    finalization resumes on recovery — exactly one payment.completed."""
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "89" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    _paid_setup(rpc, invoice=inv)  # block 185, latest 200: depth would pay NOW
    rpc.tag_raises = True

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.INFO, logger="payment_indexer"):
        await w._tick()
        # F-10 core: the silent fallback used to mark this paid right here.
        assert (await _intent(iid)).status == IntentStatus.pending
        assert webhook_calls == []
        assert idx.INDEXER_FINALITY_DEGRADED.labels(chain_id=CHAIN)._value.get() == 1

        await w._tick()
        assert (await _intent(iid)).status == IntentStatus.pending
        degraded_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "DEGRADED" in r.message
        ]
        assert len(degraded_warnings) == 1  # transition-only, no storm

        await w._tick()  # third consecutive → CRITICAL
        assert any(
            r.levelno == logging.CRITICAL and "DEGRADED" in r.message
            for r in caplog.records
        )

        # Tag recovers → the payment completes normally, exactly once.
        rpc.tag_raises = False
        rpc.finalized = 190
        await w._tick()
        assert (await _intent(iid)).status == IntentStatus.paid
        assert webhook_calls == ["payment.completed"]
        assert idx.INDEXER_FINALITY_DEGRADED.labels(chain_id=CHAIN)._value.get() == 0
        assert any(
            r.levelno == logging.INFO and "RESTORED" in r.message
            for r in caplog.records
        )
    await asyncio.sleep(0)  # let fire-and-forget alert tasks run out


# ═══════════════════════════════════════════════════════════════
#  After a reversal: coherent stream, no silent re-completion
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_tick_refinalize_after_reversal_alerts_no_second_completed(
    depth_mode, monkeypatch, webhook_calls, caplog
):
    """Reversed → tx re-included in a later block → the intent is re-paid, but
    payment.completed CANNOT fire again (claim consumed; the delivery layer
    would dedupe it anyway) — a CRITICAL alert flags the silent hop."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "8a" * 32
    iid = await _make_intent(invoice_id=inv)
    rpc = FakeChain()
    tx = _paid_setup(rpc, invoice=inv)

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    await w._tick()  # paid
    rpc.block_hashes[185] = "0x" + "ff" * 32
    rpc.receipts[tx.lower()] = None
    for _ in range(TICKS_FINAL):
        await w._tick()  # reversed
    assert (await _settlement(tx)).status == SettlementStatus.reorged
    assert webhook_calls == ["payment.completed", "payment.reversed"]

    # The network re-includes the tx at block 195 (inside the rescan tail).
    H2 = "0x" + "8b" * 32
    rpc.block_hashes[195] = H2
    rpc.logs = [_make_log(invoice_id=inv, tx_hash=tx, block_number=195, block_hash=H2)]
    rpc.receipts[tx.lower()] = H2

    await w._tick()  # ingest revives the row (pending @ 195)
    assert (await _settlement(tx)).status == SettlementStatus.pending

    rpc.latest = 210  # 195 reaches depth
    with caplog.at_level(logging.CRITICAL, logger="payment_indexer"):
        await w._tick()

    s = await _settlement(tx)
    assert s.status == SettlementStatus.final
    assert (await _intent(iid)).status == IntentStatus.paid          # re-paid
    assert webhook_calls == ["payment.completed", "payment.reversed"]  # no 3rd event
    assert any(
        "re-finalized" in r.message and "reversal" in r.message
        for r in caplog.records if r.levelno == logging.CRITICAL
    )


@pytest.mark.asyncio
async def test_reversed_intent_sweep_expires_coherently(webhook_calls):
    """Post-reversal stream is truthful end to end: completed → reversed →
    expired (a reorged settlement does not hold the expiry timer)."""
    from app.tasks.webhook_tasks import _expire_pending_intents_async
    from app.models.merchant_models import IntentStatus

    iid, ev, rpc = await _seed_final_paid("8c", expires_delta_minutes=-5)
    assert (await _intent(iid)).status == IntentStatus.paid

    _go_bad(rpc, ev)
    for _ in range(TICKS_FINAL):
        await _finalize_and_reconcile(CHAIN, rpc, final_head=200, terminal_head=170)
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == ["payment.completed", "payment.reversed"]

    await _expire_pending_intents_async()
    assert (await _intent(iid)).status == IntentStatus.expired
    assert webhook_calls == ["payment.completed", "payment.reversed", "payment.expired"]
