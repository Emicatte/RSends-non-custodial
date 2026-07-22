"""Indexer cursor hardening — Postgres-authoritative checkpoint (migration 0012).

The cursor previously lived only in Redis: a flush/restart re-initialized the
indexer at the current chain head, permanently skipping the gap — silent
payment loss (no settlement row, no webhook; the intent expired while the
money sat in the merchant's wallet). Pinned here:

  • eth_getLogs is never called with a span wider than the configured max;
  • catch-up from a cursor far behind head walks the WHOLE gap in contiguous
    chunked windows across ticks — a backfill, never a skip;
  • cold start with a persisted Postgres cursor resumes from it, NOT head;
  • a legacy Redis-only cursor is ADOPTED into Postgres (deploy safety);
  • true first run (no cursor anywhere) initializes at head ONCE, persisted;
  • a cursor write that reaches neither Postgres nor Redis raises — the tick
    fails loudly instead of freezing silently;
  • stall detection escalates to one CRITICAL after STALL_TICKS consecutive
    failures and flips the /health snapshot + gauge.

All RPC is faked (RecordingChain). Same direct-tick style as
tests/test_payment_indexer_reorg.py.
"""

import logging

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.services.payment_indexer as idx
from app.services.payment_indexer import (
    PaymentWatcher,
    STALL_TICKS,
    _get_last_block,
    _pg_get_cursor,
    _pg_set_cursor,
    _set_last_block,
    indexer_status,
)

ROUTER = "0x" + "a" * 40
CHAIN = 84532
REDIS_KEY = idx.REDIS_LAST_BLOCK_KEY.format(chain_id=CHAIN)


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.indexer_models  # noqa: F401 — register indexer_cursors
    import app.models.merchant_models  # noqa: F401
    import app.models.settlement_models  # noqa: F401
    from app.models.indexer_models import IndexerCursor

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(IndexerCursor.__table__.delete())
    # Reset the /health snapshot between tests.
    idx._status.clear()
    yield
    idx._status.clear()


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = str(value)


@pytest.fixture
def no_redis(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(idx, "get_redis", _none)


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()

    async def _get():
        return r

    monkeypatch.setattr(idx, "get_redis", _get)
    return r


class RecordingChain:
    """Fake JSON-RPC that records every eth_getLogs range."""

    def __init__(self, latest: int, finalized: int | None = None):
        self.latest = latest
        self.finalized = latest if finalized is None else finalized
        self.ranges: list[tuple[int, int]] = []

    async def call(self, method, params, **kw):
        if method == "eth_blockNumber":
            return hex(self.latest)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag in ("finalized", "safe"):
                return {"number": hex(self.finalized), "hash": "0x" + "00" * 32}
            return {"number": tag, "hash": "0x" + "00" * 32}
        if method == "eth_getLogs":
            f = int(params[0]["fromBlock"], 16)
            t = int(params[0]["toBlock"], 16)
            self.ranges.append((f, t))
            return []
        raise AssertionError(f"unexpected RPC {method}")


@pytest.fixture
def watcher(monkeypatch):
    def _make(chain: RecordingChain) -> PaymentWatcher:
        monkeypatch.setattr(
            "app.services.rpc_manager.get_rpc_manager", lambda cid: chain
        )
        return PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    return _make


def _max_range() -> int:
    from app.config import get_settings

    return max(1, int(getattr(get_settings(), "indexer_getlogs_max_range", 10)))


def _assert_contiguous(ranges, start, end, max_range):
    """Every block in [start, end] scanned exactly once, no span > max_range."""
    expected = start
    for f, t in ranges:
        assert f == expected, f"gap or overlap: expected from={expected}, got {f}"
        assert t >= f
        assert t - f + 1 <= max_range, f"range {f}-{t} wider than {max_range}"
        expected = t + 1
    assert expected == end + 1, f"scan stopped at {expected - 1}, wanted {end}"


# ── getLogs bounds + catch-up coverage ───────────────────────

@pytest.mark.asyncio
async def test_getlogs_never_exceeds_max_range_and_covers_gap(no_redis, watcher):
    await _pg_set_cursor(CHAIN, 100)
    # +margin: the scan window tops out at latest − HEAD_SAFETY_MARGIN.
    chain = RecordingChain(latest=180 + idx.HEAD_SAFETY_MARGIN)
    w = watcher(chain)

    await w._tick()

    mr = _max_range()
    assert chain.ranges, "expected getLogs calls"
    _assert_contiguous(chain.ranges, 101, 180, mr)
    assert await _pg_get_cursor(CHAIN) == 180


@pytest.mark.asyncio
async def test_far_behind_cursor_backfills_across_ticks_no_skip(no_redis, watcher):
    """A cursor 1200 blocks behind head is a BACKFILL: successive ticks walk
    the whole gap in contiguous ≤max_range windows. Nothing is skipped."""
    head = 5_000
    await _pg_set_cursor(CHAIN, head - 1_200)
    chain = RecordingChain(latest=head + idx.HEAD_SAFETY_MARGIN)
    w = watcher(chain)

    for _ in range(10):  # 1200 blocks / 500 per tick → 3 ticks; margin for safety
        await w._tick()
        if await _pg_get_cursor(CHAIN) == head:
            break

    _assert_contiguous(chain.ranges, head - 1_200 + 1, head, _max_range())
    assert await _pg_get_cursor(CHAIN) == head


# ── Cold start / adoption / first run ────────────────────────

@pytest.mark.asyncio
async def test_cold_start_resumes_from_postgres_not_head(no_redis, watcher):
    """Redis empty (flushed/restarted) + Postgres cursor present → resume
    from the persisted cursor. This is the silent-payment-loss fix."""
    await _pg_set_cursor(CHAIN, 100)
    chain = RecordingChain(latest=150 + idx.HEAD_SAFETY_MARGIN)
    w = watcher(chain)

    await w._tick()

    assert chain.ranges[0][0] == 101  # resumed, not re-initialized at 150
    assert await _pg_get_cursor(CHAIN) == 150


@pytest.mark.asyncio
async def test_legacy_redis_cursor_is_adopted_into_postgres(fake_redis, watcher):
    """Deploy safety: pre-0012 installs have the cursor only in Redis. The
    first read adopts it into Postgres instead of re-initializing at head."""
    fake_redis.store[REDIS_KEY] = "120"
    chain = RecordingChain(latest=150 + idx.HEAD_SAFETY_MARGIN)
    w = watcher(chain)

    await w._tick()

    assert chain.ranges[0][0] == 121  # resumed from the adopted value
    assert await _pg_get_cursor(CHAIN) == 150
    assert fake_redis.store[REDIS_KEY] == "150"  # cache kept warm


@pytest.mark.asyncio
async def test_true_first_run_initializes_at_head_once_persisted(no_redis, watcher):
    chain = RecordingChain(latest=150)
    w = watcher(chain)

    res = await w._tick()
    assert res == {"processed": 0}
    assert chain.ranges == []  # init tick scans nothing
    assert await _pg_get_cursor(CHAIN) == 150  # persisted: happens once, ever

    await w._tick()  # second tick: nothing new on-chain → still no scan
    assert chain.ranges == []
    assert await _pg_get_cursor(CHAIN) == 150


# ── Loud cursor writes ───────────────────────────────────────

@pytest.mark.asyncio
async def test_cursor_write_reaching_neither_store_raises(no_redis, monkeypatch):
    async def _pg_boom(chain_id, block):
        raise RuntimeError("pg down")

    monkeypatch.setattr(idx, "_pg_set_cursor", _pg_boom)
    with pytest.raises(RuntimeError, match="neither Postgres nor Redis"):
        await _set_last_block(CHAIN, 123)


@pytest.mark.asyncio
async def test_cursor_write_survives_pg_outage_via_redis_cache(fake_redis, monkeypatch):
    """PG down but Redis up: progress is cached (loudly logged + counted),
    the tick keeps going; PG resumes slightly behind → idempotent re-scan."""
    async def _pg_boom(chain_id, block):
        raise RuntimeError("pg down")

    monkeypatch.setattr(idx, "_pg_set_cursor", _pg_boom)
    await _set_last_block(CHAIN, 123)  # must NOT raise
    assert fake_redis.store[REDIS_KEY] == "123"


@pytest.mark.asyncio
async def test_redis_only_value_never_wins_over_postgres(fake_redis):
    """Postgres is authoritative: a stale/hot Redis value must not override
    a present PG row."""
    await _pg_set_cursor(CHAIN, 100)
    fake_redis.store[REDIS_KEY] = "999"
    assert await _get_last_block(CHAIN) == 100


# ── Stall detection (fail loud) ──────────────────────────────

def test_stall_escalates_to_single_critical_and_health_flag(caplog):
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.ERROR, logger="payment_indexer"):
        for n in range(1, STALL_TICKS + 2):
            w._note_failure(n, "permanent RPC rejection — fix the config")

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1  # once per stall episode, not per tick
    assert "STALLED" in criticals[0].message
    assert indexer_status()[CHAIN]["stalled"] is True
    assert idx.INDEXER_STALLED.labels(chain_id=CHAIN)._value.get() == 1


@pytest.mark.asyncio
async def test_health_endpoint_surfaces_stalled_indexer(monkeypatch):
    """Direct-handler call, same style as the sibling suites. Redis healthy +
    a stalled watcher must still surface `degraded` — the stall is not
    allowed to hide behind a green Redis."""
    from app import main as app_main

    async def _redis_ok():
        return True

    monkeypatch.setattr("app.services.cache_service.is_redis_healthy", _redis_ok)
    idx._status[CHAIN] = {"last_block": 100, "lag": 5000, "stalled": True}

    body = await app_main.health()
    assert body["status"] == "degraded"
    assert body["indexer"][CHAIN]["stalled"] is True
