"""
Broadcast-idempotency tests for sweep_deposit (deposit-address sweeps).

sweep_deposit emits TWO broadcasts per intent (gas-funding + main sweep), uses a
raw web3 client, and has NO internal lock (its caller holds one). The tx_intents
guard must make each broadcast crash-safe and concurrency-safe:

  - main-sweep crash between broadcast and commit -> retry does NOT re-broadcast
  - gas-fund already confirmed                    -> gas broadcast skipped
  - concurrent entry                              -> exactly one main broadcast

Run:
  cd fee-router-dapp/services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_deposit_sweep_idempotency.py -v
"""

import asyncio
import importlib
import pkgutil
import sys
import types
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

from app.models.command_models import TxIntent
import app.services.deposit_address_service as das

INTENT = "intent-abc"
DEPOSIT = "0x" + "33" * 20
HOT = "0x" + "99" * 20
DST = "0x" + "22" * 20


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TransactionNotFound(Exception):
    """Matches web3.exceptions.TransactionNotFound by class name (reconcile_via_web3
    detects it by name, so it works without a real web3 install)."""


def _hash_for_nonce(n: int) -> str:
    return "0x" + f"{n:064x}"


class FakeEth:
    """Sync web3.eth supporting hash-aware reconcile. The tx hash is carried in
    raw_transaction (set by the fake account) so signed-hash == broadcast-hash.
    Broadcasting records the hash as mined (status 1) unless flagged reverted/
    mempool. The nonce is consumed on every send attempt (even one that raises)."""

    def __init__(self, *, balances, nonce=5, gas_price=10 ** 9, chain_id=8453):
        self._balances = list(balances)
        self._bal_i = 0
        self._count = nonce
        self.gas_price = gas_price
        self.chain_id = chain_id
        self.sends: list = []
        self.raise_after_send = False
        self.sent: set = set()       # broadcast → mined OK (status 1)
        self.reverted: set = set()   # mined with status 0
        self.mempool: set = set()    # broadcast but not yet mined (pending)

    def get_balance(self, addr):
        v = self._balances[min(self._bal_i, len(self._balances) - 1)]
        self._bal_i += 1
        return v

    def get_transaction_count(self, addr, block="latest"):
        return self._count

    def send_raw_transaction(self, raw):
        h = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        self.sends.append(h)
        self.sent.add(h)
        self._count += 1
        if self.raise_after_send:
            raise RuntimeError("connection reset after broadcast")
        return h

    def get_transaction_receipt(self, h):
        if h in self.reverted:
            return {"status": 0}
        if h in self.sent:
            return {"status": 1}
        raise TransactionNotFound(h)

    def get_transaction(self, h):
        if h in self.mempool:
            return {"hash": h}
        raise TransactionNotFound(h)

    def wait_for_transaction_receipt(self, h, timeout=120):
        return {"status": 1}


class FakeW3:
    def __init__(self, eth):
        self.eth = eth


def _patch_deposit(eth: FakeEth):
    """Patch web3 + key derivation + signer + nonce manager around sweep_deposit."""
    fake_w3 = FakeW3(eth)
    web3_mock = MagicMock()
    web3_mock.return_value = fake_w3
    web3_mock.HTTPProvider = MagicMock()
    web3_mock.to_checksum_address = lambda a: a

    # web3 is imported lazily inside sweep_deposit and is not installed in this
    # venv — inject a fake module so `from web3 import Web3` resolves to our mock.
    fake_web3_mod = types.ModuleType("web3")
    fake_web3_mod.Web3 = web3_mock

    deposit_account = MagicMock()
    deposit_account.address = DEPOSIT

    def _sign(tx):
        # hash deterministic per nonce, carried in raw_transaction so the fake
        # chain's send returns the SAME hash (signed-hash == broadcast-hash).
        h = _hash_for_nonce(tx["nonce"])
        return SimpleNamespace(hash=h, raw_transaction=h.encode())

    deposit_account.sign_transaction = MagicMock(side_effect=_sign)
    account_mock = MagicMock()
    account_mock.from_key.return_value = deposit_account

    km_signer = MagicMock()
    km_signer.get_address = AsyncMock(return_value=HOT)
    km_signer.sign_transaction = AsyncMock(return_value=b"\x01" * 8)

    nm = MagicMock()
    nm.get_next = AsyncMock(return_value=11)
    nm.sync_from_chain = AsyncMock()
    nm.initialize = AsyncMock()

    stack = ExitStack()
    enter = stack.enter_context
    enter(patch.dict(sys.modules, {"web3": fake_web3_mod}))
    enter(patch("app.services.deposit_address_service.Account", account_mock))
    enter(patch("app.services.deposit_address_service.get_private_key_for_intent",
                MagicMock(return_value="0x" + "11" * 32)))
    enter(patch("app.services.key_manager.get_signer", MagicMock(return_value=km_signer)))
    enter(patch("app.services.nonce_manager.get_nonce_manager", MagicMock(return_value=nm)))
    return stack


async def _sweep():
    return await das.sweep_deposit(INTENT, DST, currency="ETH", chain="BASE")


# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_main_sweep_crash_between_broadcast_and_commit():
    """Main sweep broadcasts then the call crashes (response lost). The intent
    is left 'broadcasting'. A retry reconciles the nonce as consumed and does
    NOT re-broadcast."""
    # Gas sufficient on every read -> gas funding is skipped; only the sweep.
    eth = FakeEth(balances=[10 ** 18, 10 ** 18, 10 ** 18], nonce=5)
    eth.raise_after_send = True

    with _patch_deposit(eth):
        with pytest.raises(RuntimeError):
            await _sweep()
    assert len(eth.sends) == 1                       # broadcast happened once

    # Hash was persisted on the claim BEFORE the broadcast (durable).
    async with async_session() as db:
        row = (await db.execute(
            select(TxIntent).where(TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:primary")
        )).scalars().one()
    assert row.status == "broadcasting" and row.nonce == 5
    assert row.tx_hash == _hash_for_nonce(5)

    # Retry — reconcile by receipt of OUR hash recovers the real tx; no resend.
    eth.raise_after_send = False
    with _patch_deposit(eth):
        result = await _sweep()
    assert len(eth.sends) == 1                       # STILL one — no double sweep
    assert result == _hash_for_nonce(5)              # recovered the real hash

    async with async_session() as db:
        row = (await db.execute(
            select(TxIntent).where(TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:primary")
        )).scalars().one()
    assert row.status == "confirmed"
    assert row.tx_hash == _hash_for_nonce(5)


@pytest.mark.asyncio
async def test_gasfund_already_confirmed_skips_gas_broadcast():
    """A confirmed gas-fund intent means gas was already sent on a prior run.
    The retry skips the gas broadcast and only broadcasts the main sweep once."""
    async with async_session() as db:
        db.add(TxIntent(
            idempotency_key=f"deposit_gasfund:{INTENT}",
            site="deposit_gasfund",
            chain_id=8453,
            from_address=HOT,
            nonce=11,
            status="confirmed",
            tx_hash="0x" + "ab" * 32,
        ))
        await db.commit()

    # native_balance reads 0 on the 2nd get_balance -> enters gas-funding branch.
    eth = FakeEth(balances=[10 ** 18, 0, 10 ** 18], nonce=5)
    with _patch_deposit(eth):
        await _sweep()

    # Gas broadcast skipped (already confirmed); only the main sweep was sent.
    assert len(eth.sends) == 1

    async with async_session() as db:
        sweep_row = (await db.execute(
            select(TxIntent).where(TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:primary")
        )).scalars().one()
    assert sweep_row.status == "confirmed"


@pytest.mark.asyncio
async def test_concurrent_entry_single_main_broadcast(tmp_path):
    """Two concurrent sweep_deposit calls for the same intent (no internal lock):
    the UNIQUE intent claim + staleness back-off guarantee exactly one broadcast.

    Uses a shared FILE-backed sqlite DB so the UNIQUE constraint is enforced
    across connections under true concurrency (pure in-memory sqlite gives each
    connection a private DB, which can't model cross-connection UNIQUE — the
    same way Postgres would in production).
    """
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    db_file = tmp_path / "concur.db"
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(eng.sync_engine, "connect")
    def _pragma(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

    sm = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    eth = FakeEth(balances=[10 ** 18] * 6, nonce=5)
    with _patch_deposit(eth), \
            patch("app.services.tx_intent_guard.async_session", sm):
        await asyncio.gather(_sweep(), _sweep())

    assert len(eth.sends) == 1                       # never two

    async with sm() as db:
        rows = (await db.execute(
            select(TxIntent).where(TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:primary")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "confirmed"
    await eng.dispose()
