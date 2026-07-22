"""Tip-race hardening for the getLogs window (observed Base Sepolia 2026-07).

`eth_blockNumber` and `eth_getLogs` are not pinned to one provider (RPCManager
re-selects per call), and even a single provider URL is a load-balanced fleet —
so the head used to compute toBlock can come from a node ahead of the node that
serves the getLogs, which then rejects with -32602 "block range extends beyond
current head block". The indexer must (a) keep toBlock a small safety margin
below the observed head, and (b) treat a residual tip race as a
WARNING-transient failed tick, never the ERROR "will not self-heal" path.

All RPC mocked. Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_indexer_head_clamp.py
"""

import logging

import pytest
import pytest_asyncio

import app.services.payment_indexer as idx
from app.services.payment_indexer import PaymentWatcher

ROUTER = "0x" + "a" * 40
CHAIN = 8453


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


class FakeChain:
    def __init__(self):
        self.latest = 0
        self.finalized = 0
        self.block_hashes: dict[int, str] = {}
        self.logs: list[dict] = []
        self.receipts: dict[str, str | None] = {}
        self.getlogs_spans: list[tuple[int, int]] = []

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
            self.getlogs_spans.append((f, t))
            return [lg for lg in self.logs if f <= int(lg["blockNumber"], 16) <= t]
        if method == "eth_getTransactionReceipt":
            h = self.receipts.get(params[0].lower())
            return None if h is None else {"blockHash": h}
        raise AssertionError(f"unexpected RPC {method}")


class HeadRaceChain(FakeChain):
    """The node serving getLogs lags the node that answered eth_blockNumber by
    one block — the exact production shape ("requested 44477130, head
    44477129"). Rejects like the transient stack surfaces it after failover."""

    def __init__(self, serving_head_lag: int = 1):
        super().__init__()
        self.serving_head_lag = serving_head_lag

    async def call(self, method, params, **kw):
        if method == "eth_getLogs":
            t = int(params[0]["toBlock"], 16)
            serving_head = self.latest - self.serving_head_lag
            if t > serving_head:
                raise RuntimeError(
                    f"All RPC providers failed for eth_getLogs on chain "
                    f"{CHAIN}: RPC eth_getLogs error: {{'code': -32602, "
                    f"'message': 'block range extends beyond current head "
                    f"block: requested {t}, head {serving_head}'}}"
                )
        return await super().call(method, params, **kw)


async def _async_return(v):
    return v


async def _async_set(d, c, b):
    d[c] = b


def _wire(monkeypatch, rpc, cursor):
    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))


# ═══════════════════════════════════════════════════════════════
#  toBlock clamp
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_getlogs_toblock_clamped_below_head(monkeypatch):
    """The getLogs upper bound must stay HEAD_SAFETY_MARGIN (2) blocks below
    the eth_blockNumber head, and the cursor must stop there too."""
    rpc = FakeChain()
    rpc.latest = 140
    rpc.finalized = 130
    cursor = {CHAIN: 100}
    _wire(monkeypatch, rpc, cursor)

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    await w._tick()

    assert rpc.getlogs_spans, "expected at least one getLogs call"
    max_to = max(t for _, t in rpc.getlogs_spans)
    assert max_to == 140 - 2, rpc.getlogs_spans  # HEAD_SAFETY_MARGIN
    assert cursor[CHAIN] == 140 - 2


@pytest.mark.asyncio
async def test_tip_race_head_divergence_tick_succeeds(monkeypatch):
    """With the serving node one block behind the head answer (the production
    tip race), the clamped window must make the tick succeed — no failed tick,
    cursor advances normally."""
    rpc = HeadRaceChain(serving_head_lag=1)
    rpc.latest = 140
    rpc.finalized = 130
    cursor = {CHAIN: 100}
    _wire(monkeypatch, rpc, cursor)

    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    await w._tick()  # must not raise

    assert cursor[CHAIN] == 140 - 2


# ═══════════════════════════════════════════════════════════════
#  Tip-race failed tick: WARNING-transient, not ERROR-permanent
# ═══════════════════════════════════════════════════════════════
TIP_RACE_ERROR = (
    "All RPC providers failed for eth_getLogs on chain 8453: RPC eth_getLogs "
    "error: {'code': -32602, 'message': 'block range extends beyond current "
    "head block: requested 44477130, head 44477129'}"
)


def _run_loop_with_failures(monkeypatch, w, exc: Exception, failures: int = 1):
    """Drive PaymentWatcher._loop through `failures` failing ticks, then one
    successful tick that stops the watcher."""
    calls = {"n": 0}

    async def _fake_tick():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc
        w._running = False
        return {"processed": 0}

    monkeypatch.setattr(w, "_tick", _fake_tick)
    monkeypatch.setattr(idx, "POLL_INTERVAL", 0)
    w._running = True
    return w._loop()


@pytest.mark.asyncio
async def test_tip_race_failed_tick_logs_warning_not_error(monkeypatch, caplog):
    """A residual tip race below the stall threshold is a benign, self-healing
    condition — it must log WARNING (transient, will retry), never the ERROR
    line that trips alerting."""
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with caplog.at_level(logging.WARNING, logger="payment_indexer"):
        await _run_loop_with_failures(
            monkeypatch, w, RuntimeError(TIP_RACE_ERROR), failures=1
        )

    tick_records = [r for r in caplog.records if "tick failed" in r.message]
    assert tick_records, [r.message for r in caplog.records]
    assert all(r.levelno == logging.WARNING for r in tick_records), \
        [(r.levelname, r.message) for r in tick_records]
    assert not any(r.levelno >= logging.ERROR for r in caplog.records), \
        [(r.levelname, r.message) for r in caplog.records]


@pytest.mark.asyncio
async def test_generic_transient_failure_still_logs_error(monkeypatch, caplog):
    """Pin: only the tip race is downgraded — any other transient failure
    keeps the ERROR line."""
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with caplog.at_level(logging.WARNING, logger="payment_indexer"):
        await _run_loop_with_failures(
            monkeypatch, w, RuntimeError("upstream timeout"), failures=1
        )

    tick_records = [r for r in caplog.records if "tick failed" in r.message]
    assert tick_records
    assert all(r.levelno == logging.ERROR for r in tick_records), \
        [(r.levelname, r.message) for r in tick_records]


@pytest.mark.asyncio
async def test_tip_race_persisting_still_stalls_critical(monkeypatch, caplog):
    """Pin: a tip race that somehow persists STALL_TICKS consecutive ticks
    still fires the CRITICAL STALLED signal — the downgrade never silences
    the stall detector."""
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)
    with caplog.at_level(logging.WARNING, logger="payment_indexer"):
        await _run_loop_with_failures(
            monkeypatch, w, RuntimeError(TIP_RACE_ERROR), failures=idx.STALL_TICKS
        )

    assert any(
        r.levelno == logging.CRITICAL and "STALLED" in r.message
        for r in caplog.records
    ), [(r.levelname, r.message) for r in caplog.records]
