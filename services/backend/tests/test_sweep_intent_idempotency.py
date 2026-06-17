"""
Broadcast-idempotency tests for execute_single_sweep (standalone sweeps).

Proves the tx_intents guard makes a double broadcast impossible across the
crash-after-broadcast-before-commit window:

  (a) concurrent entry            -> exactly one broadcast (Redis lock + guard)
  (b) crash between broadcast and -> retry reconciles against chain and does
      DB commit                      NOT re-broadcast
  (c) idempotent replay           -> a confirmed intent short-circuits, 0 sends

Run:
  cd fee-router-dapp/services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_sweep_intent_idempotency.py -v
"""

import asyncio
import importlib
import pkgutil
from contextlib import ExitStack
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

from app.models.command_models import TxIntent
import app.services.sweep_service as ss

SRC = "0x" + "11" * 20
DST = "0x" + "22" * 20


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class FakeRpc:
    """In-memory chain. The reserved nonce is consumed on every send attempt
    (even one that raises afterwards — modelling a lost RPC response), so a
    later reconcile sees pending_count > nonce and concludes 'already sent'."""

    def __init__(self, start_nonce: int = 5):
        self.count = start_nonce
        self.sends: list[str] = []
        self.raise_after_send = False

    async def consensus_call(self, method, params):
        # eth_getTransactionCount(addr, 'latest'|'pending')
        return hex(self.count)

    async def send_raw_transaction(self, raw_hex: str) -> str:
        self.sends.append(raw_hex)
        self.count += 1  # the nonce is now occupied on-chain
        if self.raise_after_send:
            raise RuntimeError("connection reset after broadcast")
        return "0x" + f"{len(self.sends):064x}"


def _patch_sweep(rpc: FakeRpc, *, lock=None):
    """Patch every external dep of execute_single_sweep. Returns the ExitStack."""
    signer = MagicMock()
    signer.get_address = AsyncMock(return_value=SRC)
    signer.sign_transaction = AsyncMock(return_value=b"\xab" * 32)

    stack = ExitStack()
    enter = stack.enter_context
    enter(patch("app.services.key_manager.get_signer", MagicMock(return_value=signer)))
    enter(patch("app.services.sweep_service.get_rpc_manager", MagicMock(return_value=rpc)))
    enter(patch("app.services.sweep_service.estimate_gas_cost",
                AsyncMock(return_value=(21000, 1.0, 0.0001, {}))))
    enter(patch("app.services.sweep_service._resolve_owner", AsyncMock(return_value=None)))
    if lock is None:
        enter(patch("app.services.sweep_service._acquire_lock", AsyncMock(return_value=True)))
        enter(patch("app.services.sweep_service._release_lock", AsyncMock()))
    else:
        acq, rel = lock
        enter(patch("app.services.sweep_service._acquire_lock", new=acq))
        enter(patch("app.services.sweep_service._release_lock", new=rel))
    return stack


async def _run(sweep_id=1, amount_wei=10 ** 18):
    return await ss.execute_single_sweep(
        sweep_id=sweep_id,
        source=SRC,
        destination=DST,
        amount_wei=amount_wei,
        chain_id=8453,
    )


# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_entry_single_broadcast():
    """Two concurrent sweeps for the SAME sweep_id: only one acquires the lock
    and broadcasts. Exactly one send, never two."""
    rpc = FakeRpc()
    held: set[str] = set()

    async def fake_acquire(key, ttl=300):
        if key in held:
            return False
        held.add(key)
        return True

    async def fake_release(key):
        held.discard(key)

    with _patch_sweep(rpc, lock=(fake_acquire, fake_release)):
        results = await asyncio.gather(_run(1), _run(1))

    assert len(rpc.sends) == 1  # broadcast exactly once, never twice
    statuses = [r.get("status") for r in results]
    assert statuses.count("completed") == 1
    assert statuses.count("failed") == 1  # the lock loser

    async with async_session() as db:
        intents = (await db.execute(select(TxIntent))).scalars().all()
    assert len(intents) == 1
    assert intents[0].status == "confirmed"


@pytest.mark.asyncio
async def test_crash_between_broadcast_and_commit_no_resend():
    """First attempt broadcasts then crashes BEFORE committing (response lost).
    The intent row is left 'broadcasting'. On retry, reconciliation sees the
    nonce already consumed and returns completed WITHOUT a second broadcast."""
    rpc = FakeRpc(start_nonce=5)
    rpc.raise_after_send = True

    # ── First attempt: broadcast lands, then the call raises (crash) ──
    with _patch_sweep(rpc):
        first = await _run(1)
    assert first["status"] == "failed"          # crashed before commit
    assert len(rpc.sends) == 1                   # but it DID broadcast once

    async with async_session() as db:
        row = (await db.execute(select(TxIntent))).scalars().one()
    assert row.status == "broadcasting"          # claim survives the crash
    assert row.nonce == 5

    # ── Retry: must NOT broadcast again ──
    rpc.raise_after_send = False
    with _patch_sweep(rpc):
        second = await _run(1)

    assert second["status"] == "completed"
    assert len(rpc.sends) == 1                   # STILL one — no double broadcast

    async with async_session() as db:
        row = (await db.execute(select(TxIntent))).scalars().one()
    assert row.status == "confirmed"


@pytest.mark.asyncio
async def test_idempotent_replay_confirmed_intent():
    """A confirmed intent for the same sweep_id short-circuits: zero broadcasts,
    the persisted tx_hash is returned."""
    known_hash = "0x" + "cd" * 32
    async with async_session() as db:
        db.add(TxIntent(
            idempotency_key="standalone_sweep:7",
            site="standalone_sweep",
            chain_id=8453,
            from_address=SRC,
            nonce=5,
            status="confirmed",
            tx_hash=known_hash,
        ))
        await db.commit()

    rpc = FakeRpc()
    with _patch_sweep(rpc):
        result = await _run(7)

    assert len(rpc.sends) == 0                    # never re-broadcast
    assert result["status"] == "completed"
    assert result["tx_hash"] == known_hash
