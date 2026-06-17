"""
FULL-settlement idempotency for the custodial PaymentIntent two-leg sweep.

Drives a complete intent through deposit_sweep_service._execute_sweep_inner and
asserts the merchant leg and the platform-fee leg are TWO DISTINCT broadcasts —
merchant→merchant at nonce N, fee→treasury at N+1 — each with its own TxIntent
row and its own tx hash.

This reproduces the regression where both legs shared the key
`deposit_sweep:{intent_id}`: the fee leg's claim hit the merchant row, skipped
its broadcast, and the merchant hash was recorded as the fee hash. The
`fee_tx_hash == fee leg hash (not merchant)` assertion FAILS against that code.

Run:
  cd fee-router-dapp/services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_full_settlement_idempotency.py -v
"""

import importlib
import pkgutil
import sys
import types
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
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
from app.models.merchant_models import PaymentIntent, IntentStatus
import app.services.deposit_sweep_service as dss
from app.services.deposit_address_service import sweep_deposit

INTENT = "pi_settle_1"
MERCHANT = "0x" + "a1" * 20
TREASURY = "0x" + "b2" * 20
DEPOSIT = "0x" + "33" * 20
BALANCE = 10 ** 18
MERCHANT_AMOUNT = 99 * 10 ** 16
FEE_AMOUNT = 10 ** 16
BASE_NONCE = 5


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TransactionNotFound(Exception):
    """Matches web3.exceptions.TransactionNotFound by class name."""


def _hash_for_nonce(n):
    return "0x" + f"{n:064x}"


class FakeEth:
    """Native-ETH chain, hash-aware. get_balance is high so gas-funding is
    skipped. Tx hash is carried in raw_transaction (signed-hash == broadcast-hash);
    a broadcast records the hash as mined unless flagged reverted/mempool."""

    def __init__(self, *, balance=BALANCE, base_nonce=BASE_NONCE):
        self._balance = balance
        self._count = base_nonce
        self.gas_price = 10 ** 9
        self.chain_id = 8453
        self.sends = []
        self.raise_after_send = False
        self.sent = set()
        self.reverted = set()
        self.mempool = set()

    def get_balance(self, addr):
        return self._balance

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


def _patch(eth, *, signed_txs):
    """Patch web3 + key derivation + orchestrator deps. `signed_txs` collects
    each (nonce, to) the deposit account signs, so legs can be inspected."""
    fake_w3 = FakeW3(eth)
    web3_mock = MagicMock()
    web3_mock.return_value = fake_w3
    web3_mock.HTTPProvider = MagicMock()
    web3_mock.to_checksum_address = lambda a: a
    fake_web3_mod = types.ModuleType("web3")
    fake_web3_mod.Web3 = web3_mock

    deposit_account = MagicMock()
    deposit_account.address = DEPOSIT

    def _sign(tx):
        signed_txs.append((tx.get("nonce"), tx.get("to")))
        h = _hash_for_nonce(tx.get("nonce"))
        return SimpleNamespace(hash=h, raw_transaction=h.encode())

    deposit_account.sign_transaction = MagicMock(side_effect=_sign)
    account_mock = MagicMock()
    account_mock.from_key.return_value = deposit_account

    fee = SimpleNamespace(
        enabled=True, fee_bps=100, fee_amount=FEE_AMOUNT, merchant_amount=MERCHANT_AMOUNT,
    )

    stack = ExitStack()
    enter = stack.enter_context
    enter(patch.dict(sys.modules, {"web3": fake_web3_mod}))
    enter(patch("app.services.deposit_address_service.Account", account_mock))
    enter(patch("app.services.deposit_address_service.get_private_key_for_intent",
                MagicMock(return_value="0x" + "11" * 32)))
    # Orchestrator deps (imported into deposit_sweep_service namespace):
    enter(patch("app.services.deposit_sweep_service.get_deposit_balance",
                AsyncMock(return_value=BALANCE)))
    enter(patch("app.services.deposit_sweep_service.calculate_fee",
                MagicMock(return_value=fee)))
    enter(patch("app.services.deposit_sweep_service.token_decimals",
                MagicMock(return_value=18)))
    enter(patch("app.services.deposit_sweep_service.get_settings",
                MagicMock(return_value=SimpleNamespace(platform_treasury_address=TREASURY))))
    enter(patch("app.services.deposit_sweep_service.log_event", AsyncMock()))
    # Base nonce fetched once; explicit sequencing does the rest.
    enter(patch("app.services.deposit_address_service.read_deposit_nonce",
                AsyncMock(return_value=BASE_NONCE)))
    return stack


async def _make_intent(status=IntentStatus.completed):
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=INTENT, reference_id="ref-settle-1", merchant_id="m1",
            amount=1.0, currency="ETH", recipient=MERCHANT, status=status,
            chain="BASE", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await db.commit()


# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_settlement_two_distinct_legs():
    """Merchant leg → merchant @N, fee leg → treasury @N+1: two distinct
    broadcasts, two TxIntent rows, fee_tx_hash = the FEE leg's hash."""
    await _make_intent()
    eth = FakeEth()
    signed = []

    with _patch(eth, signed_txs=signed):
        await dss._execute_sweep_inner(INTENT, "ETH", "BASE")

    # (1) + (5) two distinct broadcasts at consecutive nonces, distinct dests
    assert len(eth.sends) == 2
    assert signed == [(BASE_NONCE, MERCHANT), (BASE_NONCE + 1, TREASURY)]
    merchant_hash = _hash_for_nonce(BASE_NONCE)
    fee_hash = _hash_for_nonce(BASE_NONCE + 1)
    assert merchant_hash != fee_hash

    # (2) fee_tx_hash is the FEE leg's treasury-bound hash, NOT the merchant hash
    async with async_session() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == INTENT)
        )).scalar_one()
    assert intent.status == IntentStatus.settled
    assert intent.sweep_tx_hash == merchant_hash
    assert intent.fee_tx_hash == fee_hash
    assert intent.fee_tx_hash != intent.sweep_tx_hash      # the regression guard

    # (3) two DISTINCT TxIntent rows, one per leg
    async with async_session() as db:
        rows = (await db.execute(
            select(TxIntent).where(TxIntent.site == "deposit_sweep")
        )).scalars().all()
    by_key = {r.idempotency_key: r for r in rows}
    assert set(by_key) == {f"deposit_sweep:{INTENT}:merchant", f"deposit_sweep:{INTENT}:fee"}
    assert by_key[f"deposit_sweep:{INTENT}:merchant"].nonce == BASE_NONCE
    assert by_key[f"deposit_sweep:{INTENT}:fee"].nonce == BASE_NONCE + 1
    assert by_key[f"deposit_sweep:{INTENT}:merchant"].tx_hash == merchant_hash
    assert by_key[f"deposit_sweep:{INTENT}:fee"].tx_hash == fee_hash


@pytest.mark.asyncio
async def test_merchant_leg_crash_between_broadcast_and_commit_no_resend():
    """Merchant leg broadcasts then crashes; retry of the SAME leg reconciles
    against chain and does NOT re-broadcast. The fee leg is independent."""
    eth = FakeEth()
    signed = []
    with _patch(eth, signed_txs=signed):
        eth.raise_after_send = True
        with pytest.raises(RuntimeError):
            await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                                amount=MERCHANT_AMOUNT, leg="merchant", nonce=BASE_NONCE)
        assert len(eth.sends) == 1

        # Retry the merchant leg — must NOT broadcast again.
        eth.raise_after_send = False
        await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                            amount=MERCHANT_AMOUNT, leg="merchant", nonce=BASE_NONCE)
        assert len(eth.sends) == 1                          # no resend

        # The fee leg is a SEPARATE claim — it broadcasts independently at N+1.
        await sweep_deposit(INTENT, TREASURY, currency="ETH", chain="BASE",
                            amount=FEE_AMOUNT, leg="fee", nonce=BASE_NONCE + 1)
        assert len(eth.sends) == 2

    async with async_session() as db:
        rows = {r.idempotency_key: r for r in (await db.execute(
            select(TxIntent).where(TxIntent.site == "deposit_sweep")
        )).scalars().all()}
    # Hash-aware retry reconciled the crashed leg to its OWN tx via receipt of the
    # hash persisted on the claim (no resend) → real hash recovered, status confirmed.
    assert rows[f"deposit_sweep:{INTENT}:merchant"].status == "confirmed"
    assert rows[f"deposit_sweep:{INTENT}:merchant"].tx_hash == _hash_for_nonce(BASE_NONCE)
    assert rows[f"deposit_sweep:{INTENT}:merchant"].nonce == BASE_NONCE
    assert rows[f"deposit_sweep:{INTENT}:fee"].status == "confirmed"
    assert rows[f"deposit_sweep:{INTENT}:fee"].tx_hash == _hash_for_nonce(BASE_NONCE + 1)
    assert rows[f"deposit_sweep:{INTENT}:fee"].nonce == BASE_NONCE + 1


@pytest.mark.asyncio
async def test_fee_leg_crash_between_broadcast_and_commit_no_resend():
    """Fee leg broadcasts then crashes; retry of the fee leg reconciles, no
    resend; the merchant leg (already confirmed) is untouched."""
    eth = FakeEth()
    signed = []
    with _patch(eth, signed_txs=signed):
        # Merchant leg lands cleanly first.
        await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                            amount=MERCHANT_AMOUNT, leg="merchant", nonce=BASE_NONCE)
        assert len(eth.sends) == 1

        eth.raise_after_send = True
        with pytest.raises(RuntimeError):
            await sweep_deposit(INTENT, TREASURY, currency="ETH", chain="BASE",
                                amount=FEE_AMOUNT, leg="fee", nonce=BASE_NONCE + 1)
        assert len(eth.sends) == 2

        # Retry fee leg — reconciles, no resend.
        eth.raise_after_send = False
        await sweep_deposit(INTENT, TREASURY, currency="ETH", chain="BASE",
                            amount=FEE_AMOUNT, leg="fee", nonce=BASE_NONCE + 1)
        assert len(eth.sends) == 2                          # no resend

    async with async_session() as db:
        rows = {r.idempotency_key: r for r in (await db.execute(
            select(TxIntent).where(TxIntent.site == "deposit_sweep")
        )).scalars().all()}
    # Merchant leg landed cleanly and is untouched by the fee-leg retry.
    assert rows[f"deposit_sweep:{INTENT}:merchant"].status == "confirmed"
    assert rows[f"deposit_sweep:{INTENT}:merchant"].tx_hash == _hash_for_nonce(BASE_NONCE)
    assert rows[f"deposit_sweep:{INTENT}:merchant"].nonce == BASE_NONCE
    # Fee leg reconciled to its own tx on retry via receipt (no resend); real hash recovered.
    assert rows[f"deposit_sweep:{INTENT}:fee"].status == "confirmed"
    assert rows[f"deposit_sweep:{INTENT}:fee"].tx_hash == _hash_for_nonce(BASE_NONCE + 1)
    assert rows[f"deposit_sweep:{INTENT}:fee"].nonce == BASE_NONCE + 1
