"""
RSendsRouterV2 backend wiring — the fee-less, ownerless mainnet router.

The v2 PaymentMade event drops the fee word (6 args, 3 data words). These
tests pin the decode, the settlement ingest (fee stored as 0 — the
SplitPaymentMade precedent), and — in later slices in this same file — the
dual-topic watcher filter and the v2 `build_onchain_payment` branch.

Same conventions as test_fee_model.py: self-contained, DB-backed cases use
the app's async_session against the configured Postgres.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PAYMENT_MADE_V2_TOPIC,
    _decode_payment_made,
    _decode_payment_made_v2,
    _record_settlement,
)
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import PaymentIntent, PaymentIntentRecipient
    from app.models.settlement_models import PaymentSettlement
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FK-ordered wipe: recipients reference intents — children first.
        await conn.execute(PaymentIntentRecipient.__table__.delete())
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


# ── log builders (v2 layout: 3 data words — token, amount, blockTimestamp) ──
def _word(n: int) -> str:
    return f"{n:064x}"


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def make_v2_log(*, invoice_id, merchant, payer, token, amount, ts,
                tx_hash="0x" + "ab" * 32, log_index=0, block=100,
                block_hash="0x" + "a5" * 32):
    data = "0x" + _addr_word(token) + _word(amount) + _word(ts)
    return {
        "topics": [PAYMENT_MADE_V2_TOPIC, invoice_id,
                   "0x" + _addr_word(merchant), "0x" + _addr_word(payer)],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block),
        "blockHash": block_hash,
    }


# ═══════════════════════════════════════════════════════════════
#  Decode — 3 data words, NO fee word; fee normalized to 0
# ═══════════════════════════════════════════════════════════════
class TestDecodePaymentMadeV2:
    def test_decodes_three_words_fee_is_zero(self):
        inv = "0x" + "cd" * 32
        log = make_v2_log(
            invoice_id=inv, merchant=MERCHANT, payer=PAYER, token=USDC_ADDR,
            amount=100_000000, ts=1_700_000_000, log_index=3, block=4242,
        )
        ev = _decode_payment_made_v2(log)
        assert ev is not None
        assert ev["invoice_id"] == inv
        assert ev["merchant"] == MERCHANT.lower()
        assert ev["payer"] == PAYER.lower()
        assert ev["token"] == USDC_ADDR.lower()
        assert ev["amount"] == 100_000000
        assert ev["fee"] == 0                      # no fee word exists — normalized 0
        assert ev["block_timestamp"] == 1_700_000_000   # word 2, NOT word 3
        assert ev["log_index"] == 3
        assert ev["block_number"] == 4242

    def test_rejects_short_data(self):
        # Only 2 words → must be rejected, not mis-parsed.
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        log["data"] = log["data"][: 2 + 64 * 2]
        assert _decode_payment_made_v2(log) is None

    def test_rejects_v1_topic(self):
        """A v1 log fed to the v2 decoder must return None — the dispatch keys
        on topic0 and each decoder re-checks it (defence-in-depth)."""
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        log["topics"][0] = PAYMENT_MADE_TOPIC
        assert _decode_payment_made_v2(log) is None

    def test_v1_decoder_rejects_v2_log(self):
        """The reverse direction: a v2 log (v2 topic, 3 words) must not be
        accepted by the v1 decoder — neither by topic nor by data length."""
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        assert _decode_payment_made(log) is None


# ═══════════════════════════════════════════════════════════════
#  Settlement ingest — v2 event stores fee == 0 (nullable column untouched)
# ═══════════════════════════════════════════════════════════════
async def _make_intent(*, invoice_id, recipient=MERCHANT, amount=100.0,
                       currency="USDC", chain="base"):
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_router_v2_test",
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


# ═══════════════════════════════════════════════════════════════
#  Watcher filter + dispatch — both topics, source-authenticity pairing
# ═══════════════════════════════════════════════════════════════
ROUTER_V1 = ("0x" + "a1" * 20).lower()
ROUTER_V2 = ("0x" + "a2" * 20).lower()
SPLIT_ROUTER = ("0x" + "a3" * 20).lower()
CHAIN = 8453


class CapturingChain:
    """FakeChain twin that also CAPTURES every eth_getLogs filter object, so
    the tests can assert the exact address/topics shape sent to the RPC."""

    def __init__(self):
        self.latest = 0
        self.finalized = 0
        self.block_hashes: dict[int, str] = {}
        self.logs: list[dict] = []
        self.receipts: dict[str, str | None] = {}
        self.captured_filters: list[dict] = []

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
            self.captured_filters.append(params[0])
            f = int(params[0]["fromBlock"], 16)
            t = int(params[0]["toBlock"], 16)
            # Intentionally ignores the address filter (hostile-RPC simulation):
            # the per-log (address, topic) pairing guard is the thing under test.
            return [lg for lg in self.logs if f <= int(lg["blockNumber"], 16) <= t]
        if method == "eth_getTransactionReceipt":
            h = self.receipts.get(params[0].lower())
            return None if h is None else {"blockHash": h}
        raise AssertionError(f"unexpected RPC {method}")


def _async_return(v):
    async def _c():
        return v
    return _c()


def _async_set(store, c, b):
    async def _c():
        store[c] = b
    return _c()


def _wire(monkeypatch, rpc, cursor):
    import app.services.payment_indexer as idx
    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))


class TestWatcherDualTopicFilter:
    @pytest.mark.asyncio
    async def test_v1_only_filter_shape_unchanged(self, monkeypatch):
        """Today's single-router deployments must produce the byte-identical
        scalar filter (no list wrapping) — zero behavioural drift."""
        from app.services.payment_indexer import PaymentWatcher

        rpc = CapturingChain()
        rpc.latest = 300
        rpc.finalized = 200
        _wire(monkeypatch, rpc, {CHAIN: 100})

        w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER_V1)
        await w._tick()

        assert rpc.captured_filters, "tick issued no getLogs"
        f = rpc.captured_filters[0]
        assert f["address"] == ROUTER_V1
        assert f["topics"] == [PAYMENT_MADE_TOPIC]

    @pytest.mark.asyncio
    async def test_filter_covers_all_three_contracts(self, monkeypatch):
        from app.services.payment_indexer import (
            PaymentWatcher, SPLIT_PAYMENT_MADE_TOPIC,
        )

        rpc = CapturingChain()
        rpc.latest = 300
        rpc.finalized = 200
        _wire(monkeypatch, rpc, {CHAIN: 100})

        w = PaymentWatcher(
            chain_id=CHAIN, router_address=ROUTER_V1,
            router_v2_address=ROUTER_V2, split_router_address=SPLIT_ROUTER,
        )
        await w._tick()

        f = rpc.captured_filters[0]
        assert f["address"] == [ROUTER_V1, ROUTER_V2, SPLIT_ROUTER]
        assert f["topics"] == [[PAYMENT_MADE_TOPIC, PAYMENT_MADE_V2_TOPIC,
                                SPLIT_PAYMENT_MADE_TOPIC]]

    @pytest.mark.asyncio
    async def test_v2_only_watcher_ingests_v2_log(self, monkeypatch):
        """A v2-only chain (mainnet cutover) must construct a working watcher
        with NO v1 router configured, and ingest via the v2 topic."""
        from app.db.session import async_session
        from app.models.settlement_models import PaymentSettlement
        from app.services.payment_indexer import PaymentWatcher

        inv = "0x" + "e3" * 32
        await _make_intent(invoice_id=inv)
        bhash = "0x" + "e4" * 32

        rpc = CapturingChain()
        rpc.latest = 300
        rpc.finalized = 200
        rpc.block_hashes[150] = bhash
        log = make_v2_log(invoice_id=inv, merchant=MERCHANT, payer=PAYER,
                          token=USDC_ADDR, amount=to_base_units(100.0, USDC_DEC),
                          ts=1_700_000_000, tx_hash="0x" + "e5" * 32,
                          block=150, block_hash=bhash)
        log["address"] = ROUTER_V2
        rpc.logs = [log]
        _wire(monkeypatch, rpc, {CHAIN: 100})

        w = PaymentWatcher(chain_id=CHAIN, router_v2_address=ROUTER_V2)
        await w._tick()

        f = rpc.captured_filters[0]
        assert f["address"] == ROUTER_V2
        assert f["topics"] == [PAYMENT_MADE_V2_TOPIC]
        async with async_session() as db:
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == log["transactionHash"])
            )).scalar_one()
            assert stl.fee == Decimal(0)

    @pytest.mark.asyncio
    async def test_v2_log_from_v1_address_dropped(self, monkeypatch):
        """Source authenticity: a v2-topic log claiming to come from the v1
        router address is a wrong (address, topic) pairing — dropped."""
        from app.services.payment_indexer import PaymentWatcher

        inv = "0x" + "e6" * 32
        await _make_intent(invoice_id=inv)

        rpc = CapturingChain()
        rpc.latest = 300
        rpc.finalized = 200
        log = make_v2_log(invoice_id=inv, merchant=MERCHANT, payer=PAYER,
                          token=USDC_ADDR, amount=to_base_units(100.0, USDC_DEC),
                          ts=1_700_000_000, tx_hash="0x" + "e7" * 32, block=150)
        log["address"] = ROUTER_V1                 # wrong source for a v2 topic
        rpc.logs = [log]
        _wire(monkeypatch, rpc, {CHAIN: 100})

        w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER_V1,
                           router_v2_address=ROUTER_V2)
        await w._tick()

        from app.db.session import async_session
        from app.models.settlement_models import PaymentSettlement
        async with async_session() as db:
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == log["transactionHash"])
            )).scalar_one_or_none()
            assert stl is None

    def test_watcher_requires_at_least_one_router(self):
        from app.services.payment_indexer import PaymentWatcher

        with pytest.raises(ValueError):
            PaymentWatcher(chain_id=CHAIN)


class TestStartIndexerUnion:
    @pytest.mark.asyncio
    async def test_v2_only_settings_still_start_a_watcher(self, monkeypatch):
        """The watcher-chains set is the UNION of the v1 and v2 address maps —
        a v2-only mainnet must get a watcher (and the split rule is unchanged)."""
        from types import SimpleNamespace
        import app.services.payment_indexer as idx

        monkeypatch.setattr(idx, "_watchers", [])
        monkeypatch.setattr(idx, "get_settings", lambda: SimpleNamespace(
            rsends_router_addresses={},
            rsends_router_v2_addresses={"8453": ROUTER_V2},
            split_router_addresses={},
            indexer_use_finalized_tag=True,
            indexer_finalized_tag="finalized",
        ))

        watchers = await idx.start_indexer_if_needed()
        try:
            assert len(watchers) == 1
            assert watchers[0].chain_id == 8453
            assert watchers[0].router_address is None
            assert watchers[0].router_v2_address == ROUTER_V2
        finally:
            for w in watchers:
                await w.stop()
            idx._watchers = []


class TestRecordSettlementV2:
    @pytest.mark.asyncio
    async def test_v2_event_ingests_with_zero_fee(self):
        from app.db.session import async_session
        from app.models.settlement_models import PaymentSettlement, SettlementStatus

        inv = "0x" + "e1" * 32
        await _make_intent(invoice_id=inv)

        log = make_v2_log(
            invoice_id=inv, merchant=MERCHANT, payer=PAYER, token=USDC_ADDR,
            amount=to_base_units(100.0, USDC_DEC), ts=1_700_000_000,
            tx_hash="0x" + "e2" * 32, block=500,
        )
        ev = _decode_payment_made_v2(log)
        assert ev is not None

        assert await _record_settlement(8453, ev) == "new"
        async with async_session() as db:
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
            )).scalar_one()
            assert stl.status == SettlementStatus.pending
            assert stl.fee == Decimal(0)
            assert stl.amount == Decimal(ev["amount"])
