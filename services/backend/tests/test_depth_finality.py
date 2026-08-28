"""Fix A: confirmation-depth finality (Paid in ~35s instead of ~13 min).

The mode itself is an env flip (INDEXER_USE_FINALIZED_TAG=false +
INDEXER_CONFIRMATIONS=15 on Render; rollback = flip the first back to true).
These tests pin the depth-mode code path end to end — it had ZERO coverage
before this file, and tomorrow's demo runs on it:

  - _finalized_head: tag mode, depth mode (latest − N), tag-failure fallback;
  - a full _tick in depth mode pays an intent as soon as its block is N deep
    (and not before), without consulting the finalized tag at all;
  - a shallow reorg under depth never finalizes and is handled by B-2's
    evidence path;
  - the config default for INDEXER_CONFIRMATIONS is 15 (footgun removal), and
    the watcher start log names the active finality mode unambiguously.

All RPC mocked. Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_depth_finality.py
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.payment_indexer as idx
from app.config import get_settings
from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PaymentWatcher,
    _finalized_head,
)
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
ROUTER = "0x" + "a" * 40
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
AMT = to_base_units(100.0, USDC_DEC)
DEPTH = 15


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
    s = get_settings()
    monkeypatch.setattr(s, "indexer_use_finalized_tag", False)
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


# ── helpers (house pattern from test_payment_indexer_reorg) ──
async def _make_intent(*, invoice_id):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_depth_test",
            amount=100.0,
            currency="USDC",
            chain="base",
            recipient=MERCHANT,
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


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
    def __init__(self):
        self.latest = 0
        self.finalized = 0
        self.tag_raises = False
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


# ═══════════════════════════════════════════════════════════════
#  Config default + mode visibility (RED before the code change)
# ═══════════════════════════════════════════════════════════════
def test_indexer_confirmations_config_default_is_15():
    """Footgun removal: flipping the tag off without setting a depth must not
    land on a 2-block depth."""
    from app.config import Settings

    assert Settings.model_fields["indexer_confirmations"].default == DEPTH
    assert idx.DEFAULT_CONFIRMATIONS == DEPTH


@pytest.fixture(autouse=True)
def _chain_identity_proven(monkeypatch):
    """PaymentWatcher.start() proves the chain via eth_chainId before scheduling
    the loop (F1). These tests are about finality-mode announcements, not about
    the network, so the proof is stubbed AT THE TEST BOUNDARY — patching the
    module-level function, not a config flag: the guard deliberately has no off
    switch (test_chain_identity_guard::test_no_configuration_surface_can_disable_chain_identity).
    """
    async def _proven(chain_id, timeout=None):
        return None

    monkeypatch.setattr(
        "app.services.rpc_manager.assert_chain_identity", _proven
    )


@pytest.mark.asyncio
async def test_watcher_start_logs_depth_mode_warning(depth_mode, monkeypatch, caplog):
    """In depth mode the watcher must announce it LOUDLY at start — the demo
    log stream has to show which finality mode is live."""
    async def _noop(self):
        return None

    monkeypatch.setattr(PaymentWatcher, "_loop", _noop)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with caplog.at_level(logging.INFO, logger="payment_indexer"):
        await w.start()
        await w.stop()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("finality" in r.message and str(DEPTH) in r.message for r in warnings), \
        [r.message for r in caplog.records]


@pytest.mark.asyncio
async def test_watcher_start_logs_tag_mode_info(monkeypatch, caplog):
    """Tag mode announces itself at INFO — and no depth-mode warning fires."""
    async def _noop(self):
        return None

    monkeypatch.setattr(PaymentWatcher, "_loop", _noop)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with caplog.at_level(logging.INFO, logger="payment_indexer"):
        await w.start()
        await w.stop()

    assert any("finality" in r.message and "finalized" in r.message
               for r in caplog.records if r.levelno == logging.INFO)
    assert not any("finality" in r.message
                   for r in caplog.records if r.levelno == logging.WARNING)


# ═══════════════════════════════════════════════════════════════
#  _finalized_head — both modes + fallback
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_finalized_head_tag_mode_uses_tag():
    rpc = FakeChain()
    rpc.finalized = 120
    s = SimpleNamespace(indexer_use_finalized_tag=True,
                        indexer_finalized_tag="finalized",
                        indexer_confirmations=DEPTH)
    assert await _finalized_head(rpc, s, latest=200) == 120
    assert rpc.tag_calls == 1


@pytest.mark.asyncio
async def test_finalized_head_depth_mode_is_latest_minus_n():
    rpc = FakeChain()
    rpc.finalized = 0  # stale on purpose: depth mode must not consult the tag
    s = SimpleNamespace(indexer_use_finalized_tag=False,
                        indexer_finalized_tag="finalized",
                        indexer_confirmations=DEPTH)
    assert await _finalized_head(rpc, s, latest=200) == 200 - DEPTH
    assert rpc.tag_calls == 0


@pytest.mark.asyncio
async def test_finalized_head_tag_mode_unavailable_returns_none():
    """F-10: tag mode with the tag unavailable must NOT silently degrade to
    depth semantics — it returns None and the caller refuses to finalize.
    (Replaces the pre-F-10 pin that asserted the silent latest−N fallback.)"""
    rpc = FakeChain()
    rpc.tag_raises = True
    s = SimpleNamespace(indexer_use_finalized_tag=True,
                        indexer_finalized_tag="finalized",
                        indexer_confirmations=DEPTH)
    assert await _finalized_head(rpc, s, latest=200) is None


# ═══════════════════════════════════════════════════════════════
#  Full _tick in depth mode — the path the demo runs on
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_tick_depth_mode_pays_once_n_deep_not_before(
    depth_mode, monkeypatch, webhook_calls
):
    """latest=200, N=15 → final head 185. A payment at block 185 is Paid on
    the FIRST tick; one at 190 stays pending until the chain advances. The
    paid gate never DEPENDS on the finalized tag (it raises here — the
    terminal-boundary fetch may consult it, but paying must not wait for it)."""
    from app.models.merchant_models import IntentStatus

    inv_a, inv_b = "0x" + "71" * 32, "0x" + "72" * 32
    iid_a = await _make_intent(invoice_id=inv_a)
    iid_b = await _make_intent(invoice_id=inv_b)

    rpc = FakeChain()
    rpc.latest = 200
    rpc.tag_raises = True  # paid-at-depth must survive a dead finalized tag
    ha, hb = "0x" + "71" * 32, "0x" + "72" * 32
    rpc.block_hashes[185] = ha
    rpc.block_hashes[190] = hb
    rpc.logs = [
        _make_log(invoice_id=inv_a, tx_hash="0x" + "71" * 32, block_number=185, block_hash=ha),
        _make_log(invoice_id=inv_b, tx_hash="0x" + "72" * 32, block_number=190, block_hash=hb),
    ]

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    await w._tick()
    assert (await _intent(iid_a)).status == IntentStatus.paid      # 15 deep → paid now
    assert (await _intent(iid_b)).status == IntentStatus.pending   # only 10 deep
    assert webhook_calls == ["payment.completed"]

    # Chain advances past depth for B → paid on the next tick.
    rpc.latest = 210
    await w._tick()
    assert (await _intent(iid_b)).status == IntentStatus.paid
    assert sorted(webhook_calls) == ["payment.completed", "payment.completed"]


@pytest.mark.asyncio
async def test_tick_depth_mode_shallow_reorg_never_finalizes(
    depth_mode, monkeypatch, webhook_calls
):
    """A block that reorged before reaching depth N must never pay: the hash
    mismatch blocks finalization, and B-2's evidence path (3 ticks of mismatch
    + receipt gone) marks it reorged."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "73" * 32
    iid = await _make_intent(invoice_id=inv)

    rpc = FakeChain()
    rpc.latest = 200
    H = "0x" + "73" * 32
    # The log claims block 185/H, but the canonical chain disagrees and the
    # tx has no receipt — a real shallow reorg observed from tick 1.
    rpc.block_hashes[185] = "0x" + "ff" * 32
    rpc.logs = [_make_log(invoice_id=inv, tx_hash="0x" + "73" * 32,
                          block_number=185, block_hash=H)]

    cursor = {CHAIN: 180}
    _wire(monkeypatch, rpc, cursor)
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    for tick in (1, 2):
        await w._tick()
        s = await _settlement("0x" + "73" * 32)
        assert s.status == SettlementStatus.pending, f"tick {tick}"
        assert (await _intent(iid)).status == IntentStatus.pending

    await w._tick()  # third consecutive evidence tick → reversed, never paid
    assert (await _settlement("0x" + "73" * 32)).status == SettlementStatus.reorged
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []
