"""
Crash-between-broadcast-and-commit SOAK for the PAYOUT (distribution) path.

This path is ALREADY crash-tolerant (C1b): per-item nonce is persisted with
status SIGNING BEFORE broadcast, and the retry reuses the SAME nonce. This test
documents that guarantee under a multi-item crash — it does NOT change the path.

Scenario: a batch crashed mid-flight. Items @100 and @101 were already broadcast
(the chain now rejects them as 'nonce too low'); item @102 never went out. On
retry the persisted nonces are reused (no fresh reserve_range), the already-sent
items are marked SUBMITTED WITHOUT a second real broadcast, and only @102 is sent.

Run:
  cd fee-router-dapp/services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_distribution_crash_soak.py -v
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


async def _make_batch(status, items):
    """items: list of (recipient_suffix, nonce_or_None, item_status)."""
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
            db.add(SweepBatchItem(
                batch_id=batch.id,
                recipient_address="0x" + suffix * 20,
                amount_wei="300000000000000000",
                percent_bps=3333,
                status=item_status,
                nonce=nonce,
            ))
        await db.commit()
        return str(batch.id)


def _patch_deps(transfer_side_effect, reserve_range):
    policy = MagicMock()
    policy.check_and_reserve = AsyncMock(
        return_value=SimpleNamespace(allowed=True, reason=None, tier=None))
    policy.release = AsyncMock()
    wm = MagicMock()
    wm.estimate_sweep_gas = AsyncMock(return_value=21000)
    wm.check_hot_sufficient = AsyncMock(return_value=True)
    rpc = MagicMock()
    rpc.call = AsyncMock(return_value=hex(10 ** 9))
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
    enter(patch("app.services.sweep_service._replacement_mode_active", AsyncMock(return_value=False)))
    enter(patch.object(st, "_execute_single_transfer", AsyncMock(side_effect=transfer_side_effect)))
    enter(patch.object(st, "_notify_websocket", AsyncMock()))
    enter(patch.object(st, "_notify_telegram", AsyncMock()))
    enter(patch.object(st, "confirm_batch", MagicMock()))
    enter(patch.object(st, "retry_failed_items", MagicMock()))
    return stack, nm


@pytest.mark.asyncio
async def test_multi_item_crash_retry_no_double_broadcast():
    """A batch crashed mid-flight: @100 and @101 already broadcast, @102 not.
    The retry reuses persisted nonces, never reserves fresh ones, never re-sends
    the already-broadcast nonces, and sends only the un-sent item."""
    batch_id = await _make_batch("PROCESSING", [
        ("a0", 100, "SIGNING"),
        ("b1", 101, "SIGNING"),
        ("c2", 102, "SIGNING"),
    ])

    calls: list[int] = []
    real_sends: list[int] = []

    def transfer(*_a, **k):
        n = k["nonce"]
        calls.append(n)
        if n in (100, 101):
            # Already mined in the crashed run — chain rejects a re-broadcast.
            raise RuntimeError("nonce too low")
        real_sends.append(n)
        return "0x" + f"{n:064x}"

    # reserve_range must NOT be called; if it were, this would hand out new nonces.
    stack, nm = _patch_deps(transfer, AsyncMock(return_value=(900, 902)))
    with stack:
        await st._execute_distribution_async(MagicMock(), batch_id)

    assert nm.reserve_range.call_count == 0           # nonces reused, none reserved
    assert sorted(calls) == [100, 101, 102]           # each persisted nonce attempted
    assert real_sends == [102]                         # ONLY the un-sent item went out

    async with async_session() as db:
        rows = (await db.execute(select(SweepBatchItem))).scalars().all()
    by_nonce = {r.nonce: r.status for r in rows}
    assert by_nonce == {100: "SUBMITTED", 101: "SUBMITTED", 102: "SUBMITTED"}
