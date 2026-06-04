"""
RPagos Backend — Test: distribution re-broadcast idempotency (C1b fix).

Proves that a crash/retry of execute_distribution in the broadcast->commit
window CANNOT double-pay:

  - A fresh batch assigns + persists a per-item nonce (status SIGNING) BEFORE
    broadcasting, and the loop uses that persisted nonce.
  - On a retry of a batch left mid-flight (items in SIGNING with nonces), the
    SAME nonce is reused (no fresh reserve_range). If the chain reports the
    nonce already consumed ("nonce too low"), the item is marked SUBMITTED
    without re-broadcasting — never a second distinct transfer.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_distribution_idempotency.py -v
"""

import importlib
import pkgutil
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base

# Register ALL ORM models so create_all resolves every cross-model FK.
import app.models as _models_pkg

for _m in pkgutil.iter_modules(_models_pkg.__path__):
    if _m.name.endswith("_models"):
        importlib.import_module(f"app.models.{_m.name}")

from app.models.command_models import SweepBatch, SweepBatchItem
import app.tasks.sweep_tasks as st

HOT = "0x" + "99" * 20


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_batch(status: str, items: list[tuple[str, int | None, str]]) -> str:
    """items: list of (recipient_suffix, nonce_or_None, item_status). Returns batch_id str."""
    async with async_session() as db:
        batch = SweepBatch(
            incoming_tx_hash="0x" + uuid.uuid4().hex,
            source_address=HOT,
            chain_id=8453,
            total_amount_wei="1000000000000000000",
            token_symbol="ETH",
            status=status,
        )
        db.add(batch)
        await db.flush()
        for suffix, nonce, item_status in items:
            db.add(
                SweepBatchItem(
                    batch_id=batch.id,
                    recipient_address="0x" + suffix * 20,
                    amount_wei="500000000000000000",
                    percent_bps=5000,
                    status=item_status,
                    nonce=nonce,
                )
            )
        await db.commit()
        return str(batch.id)


def _patch_deps(transfer_side_effect, reserve_range: AsyncMock):
    """Patch every external dependency of _execute_distribution_async.

    Returns (ExitStack, nonce_manager_mock). Enter the stack as a context.
    """
    policy = MagicMock()
    policy.check_and_reserve = AsyncMock(
        return_value=SimpleNamespace(allowed=True, reason=None, tier=None)
    )
    policy.release = AsyncMock()
    wm = MagicMock()
    wm.estimate_sweep_gas = AsyncMock(return_value=21000)
    wm.check_hot_sufficient = AsyncMock(return_value=True)
    rpc = MagicMock()
    rpc.call = AsyncMock(return_value=hex(10**9))  # eth_gasPrice
    nm = MagicMock()
    nm.reserve_range = reserve_range
    signer = MagicMock()
    signer.get_address = AsyncMock(return_value=HOT)
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=0)
    redis.setex = AsyncMock()

    stack = ExitStack()
    enter = stack.enter_context
    enter(patch("app.services.circuit_breaker.get_circuit_breaker", MagicMock(return_value=None)))
    enter(patch("app.services.spending_policy.get_spending_policy", MagicMock(return_value=policy)))
    enter(patch("app.services.wallet_manager.get_wallet_manager", MagicMock(return_value=wm)))
    enter(patch("app.services.rpc_manager.get_rpc_manager", MagicMock(return_value=rpc)))
    enter(patch("app.services.nonce_manager.get_nonce_manager", MagicMock(return_value=nm)))
    enter(patch("app.services.key_manager.get_signer", MagicMock(return_value=signer)))
    enter(patch("app.services.audit_service.log_event", AsyncMock()))
    enter(patch("app.services.cache_service.get_redis", AsyncMock(return_value=redis)))
    enter(patch("app.services.sweep_service.get_bumped_gas_params", AsyncMock(return_value={})))
    enter(patch("app.services.sweep_service._replacement_mode_active", MagicMock(return_value=False)))
    enter(patch.object(st, "_execute_single_transfer", AsyncMock(side_effect=transfer_side_effect)))
    enter(patch.object(st, "_notify_websocket", AsyncMock()))
    enter(patch.object(st, "_notify_telegram", AsyncMock()))
    enter(patch.object(st, "confirm_batch", MagicMock()))
    enter(patch.object(st, "retry_failed_items", MagicMock()))
    return stack, nm


@pytest.mark.asyncio
async def test_fresh_batch_persists_nonce_and_sends_once():
    """Happy path: a fresh PENDING batch assigns nonces from reserve_range,
    persists them, and broadcasts each item exactly once."""
    batch_id = await _make_batch(
        "PENDING", [("a0", None, "PENDING"), ("b1", None, "PENDING")]
    )
    calls: list[int] = []

    def transfer(*_a, **k):
        calls.append(k["nonce"])
        return "0x" + f"{k['nonce']:064x}"  # unique per nonce (real TXes are unique)

    stack, nm = _patch_deps(transfer, AsyncMock(return_value=(100, 101)))
    with stack:
        await st._execute_distribution_async(MagicMock(), batch_id)

    assert nm.reserve_range.call_count == 1            # reserved once, for fresh items
    assert sorted(calls) == [100, 101]                 # each item sent once, at its nonce
    async with async_session() as db:
        rows = (await db.execute(select(SweepBatchItem))).scalars().all()
    assert all(r.status == "SUBMITTED" for r in rows)
    assert {r.nonce for r in rows} == {100, 101}


@pytest.mark.asyncio
async def test_retry_reuses_nonce_and_does_not_double_send():
    """Crash recovery: a batch left mid-flight (items SIGNING with nonces).
    item @100 already mined (chain says 'nonce too low'); item @101 never sent.
    The retry must reuse the SAME nonces (no fresh reserve), mark the consumed
    one SUBMITTED WITHOUT re-broadcasting, and send only the un-sent one."""
    batch_id = await _make_batch(
        "PROCESSING", [("a0", 100, "SIGNING"), ("b1", 101, "SIGNING")]
    )
    calls: list[int] = []
    real_sends: list[int] = []

    def transfer(*_a, **k):
        n = k["nonce"]
        calls.append(n)
        if n == 100:
            raise RuntimeError("nonce too low")  # already mined in the crashed run
        real_sends.append(n)
        return "0x" + f"{n:064x}"  # unique per nonce

    stack, nm = _patch_deps(transfer, AsyncMock(return_value=(999, 999)))
    with stack:
        await st._execute_distribution_async(MagicMock(), batch_id)

    # No fresh nonce reserved (items already had nonces); only the persisted
    # nonces were attempted; the only REAL new send was item @101.
    assert nm.reserve_range.call_count == 0
    assert sorted(calls) == [100, 101]
    assert real_sends == [101]                         # @100 was NOT re-sent

    async with async_session() as db:
        rows = (await db.execute(select(SweepBatchItem))).scalars().all()
    by_nonce = {r.nonce: r.status for r in rows}
    assert by_nonce[100] == "SUBMITTED"                # idempotent: already-sent
    assert by_nonce[101] == "SUBMITTED"                # real send


# ──────────────────────────────────────────────────────────────────────────
#  C1 concurrency guard (_execute_distribution_locked): the fail-closed Redis
#  lock prevents TWO concurrent runs of the same batch from both broadcasting
#  (which C1b's per-task nonce-reuse does NOT cover — concurrent runs reserve
#  DISJOINT nonce ranges and pay every recipient twice).
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_execution_single_broadcast():
    """Two concurrent execute_distribution runs for the SAME batch: only one
    acquires the lock and broadcasts; the other is locked out. Each item is
    broadcast exactly once (never twice)."""
    import asyncio

    batch_id = await _make_batch(
        "PENDING", [("a0", None, "PENDING"), ("b1", None, "PENDING")]
    )
    calls: list[int] = []

    def transfer(*_a, **k):
        calls.append(k["nonce"])
        return "0x" + f"{k['nonce']:064x}"

    # Stateful in-memory SETNX: first acquire of a key wins, the rest get False
    # until released. fake_acquire has no await before mutating `held`, so under
    # asyncio.gather the first-scheduled run wins deterministically.
    held: set[str] = set()

    async def fake_acquire(key, ttl=300):
        if key in held:
            return False
        held.add(key)
        return True

    async def fake_release(key):
        held.discard(key)

    stack, nm = _patch_deps(transfer, AsyncMock(return_value=(100, 101)))
    with stack, \
            patch("app.services.sweep_service.acquire_sweep_lock", new=fake_acquire), \
            patch("app.services.sweep_service.release_sweep_lock", new=fake_release), \
            patch("app.services.sweep_service.start_sweep_heartbeat",
                  MagicMock(return_value=MagicMock())) as hb_start, \
            patch("app.services.sweep_service.stop_sweep_heartbeat", AsyncMock()) as hb_stop:
        results = await asyncio.gather(
            st._execute_distribution_locked(MagicMock(), batch_id),
            st._execute_distribution_locked(MagicMock(), batch_id),
        )

    # Each item broadcast exactly once — 2 sends total, NOT 4.
    assert sorted(calls) == [100, 101]
    assert nm.reserve_range.call_count == 1                 # only the winner reserved
    skipped = [r for r in results if r.get("status") == "skipped"]
    assert len(skipped) == 1 and skipped[0]["reason"] == "locked"
    # Only the winner ran under a heartbeat, and it was stopped on exit.
    assert hb_start.call_count == 1
    assert hb_stop.await_count == 1

    async with async_session() as db:
        rows = (await db.execute(select(SweepBatchItem))).scalars().all()
    assert all(r.status == "SUBMITTED" for r in rows)       # no duplicate/extra items


@pytest.mark.asyncio
async def test_lock_unavailable_fail_closed():
    """Fail-closed: when the Redis lock cannot be acquired (e.g. Redis down,
    acquire_sweep_lock returns False), execution is skipped and NOTHING is
    broadcast — better to delay than to risk a double-spend."""
    batch_id = await _make_batch("PENDING", [("a0", None, "PENDING")])
    calls: list[int] = []

    def transfer(*_a, **k):
        calls.append(k["nonce"])
        return "0x" + f"{k['nonce']:064x}"

    async def deny(key, ttl=300):
        return False  # Redis unavailable / already locked → fail-closed

    stack, nm = _patch_deps(transfer, AsyncMock(return_value=(100, 100)))
    with stack, \
            patch("app.services.sweep_service.acquire_sweep_lock", new=deny), \
            patch("app.services.sweep_service.release_sweep_lock", new=AsyncMock()), \
            patch("app.services.sweep_service.start_sweep_heartbeat",
                  MagicMock(return_value=MagicMock())) as hb_start, \
            patch("app.services.sweep_service.stop_sweep_heartbeat", AsyncMock()):
        result = await st._execute_distribution_locked(MagicMock(), batch_id)

    assert result == {"status": "skipped", "reason": "locked"}
    assert calls == []                                       # nothing broadcast
    assert nm.reserve_range.call_count == 0
    assert hb_start.call_count == 0                          # fail-closed: no heartbeat started
