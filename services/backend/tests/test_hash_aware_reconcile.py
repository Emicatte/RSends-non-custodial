"""
Hash-aware reconcile + fee-recovery tests (the three-state contract).

Covers:
  (1) merchant crash → receipt-recovers real hash → orchestrator SETTLES cleanly
  (2) merchant tx reverted on-chain (receipt status=0) → HOLD for review, no settle
  (3)/(7) fee-leg crash post-settled → fee-recovery job completes it via the :fee
          leg with the amount READ FROM THE RECORD; running twice → no double-collect
  (4) tx pending in mempool (receipt None, getTransactionByHash found) → back off
  (5)/(6) reclaim persists the CURRENT re-signed hash (RBF), not the stale one;
          durable across the crash → reconcile resolves completed, not needs_review

Run:
  cd fee-router-dapp/services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_hash_aware_reconcile.py -v
"""

import importlib
import pkgutil
import sys
import types
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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

INTENT = "pi_hash_1"
MERCHANT = "0x" + "a1" * 20
TREASURY = "0x" + "b2" * 20
DEPOSIT = "0x" + "33" * 20
BALANCE = 10 ** 18
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
    pass


def _h(n):
    return "0x" + f"{n:064x}"


class FakeEth:
    def __init__(self, *, balance=BALANCE, base_nonce=BASE_NONCE):
        self._balance = balance
        self._count = base_nonce
        self.gas_price = 10 ** 9
        self.chain_id = 8453
        self.sends = []
        self.raise_after_send = False
        self.raise_before_send = False
        self.sent = set()
        self.reverted = set()
        self.mempool = set()

    def get_balance(self, addr):
        return self._balance

    def get_transaction_count(self, addr, block="latest"):
        return self._count

    def send_raw_transaction(self, raw):
        if self.raise_before_send:
            raise RuntimeError("crash before send")  # tx hash never broadcast
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


def _web3_account_patches(eth, *, hash_fn=None, signed=None):
    """Common web3 + Account + key-derivation patches. ``hash_fn(tx)`` chooses the
    signed-tx hash (default: keyed on nonce); ``signed`` collects (nonce,to,hash)."""
    if hash_fn is None:
        hash_fn = lambda tx: _h(tx["nonce"])
    fake_w3 = FakeW3(eth)
    web3_mock = MagicMock()
    web3_mock.return_value = fake_w3
    web3_mock.HTTPProvider = MagicMock()
    web3_mock.to_checksum_address = lambda a: a
    mod = types.ModuleType("web3")
    mod.Web3 = web3_mock

    acct = MagicMock()
    acct.address = DEPOSIT

    def _sign(tx):
        h = hash_fn(tx)
        if signed is not None:
            signed.append((tx.get("nonce"), tx.get("to"), h))
        return SimpleNamespace(hash=h, raw_transaction=h.encode())

    acct.sign_transaction = MagicMock(side_effect=_sign)
    account_mock = MagicMock()
    account_mock.from_key.return_value = acct

    patches = [
        patch.dict(sys.modules, {"web3": mod}),
        patch("app.services.deposit_address_service.Account", account_mock),
        patch("app.services.deposit_address_service.get_private_key_for_intent",
              MagicMock(return_value="0x" + "11" * 32)),
    ]
    return patches


def _orchestrator_patches(eth, *, signed=None):
    fee = SimpleNamespace(enabled=True, fee_bps=100,
                          fee_amount=10 ** 16, merchant_amount=99 * 10 ** 16)
    stack = ExitStack()
    for p in _web3_account_patches(eth, signed=signed):
        stack.enter_context(p)
    stack.enter_context(patch("app.services.deposit_sweep_service.get_deposit_balance",
                              AsyncMock(return_value=BALANCE)))
    stack.enter_context(patch("app.services.deposit_sweep_service.calculate_fee",
                              MagicMock(return_value=fee)))
    stack.enter_context(patch("app.services.deposit_sweep_service.token_decimals",
                              MagicMock(return_value=18)))
    stack.enter_context(patch("app.services.deposit_sweep_service.get_settings",
                              MagicMock(return_value=SimpleNamespace(platform_treasury_address=TREASURY))))
    stack.enter_context(patch("app.services.deposit_sweep_service.log_event", AsyncMock()))
    stack.enter_context(patch("app.services.deposit_address_service.read_deposit_nonce",
                              AsyncMock(return_value=BASE_NONCE)))
    stack.enter_context(patch("app.services.alert_service.critical_alert", AsyncMock()))
    return stack


async def _make_intent(status=IntentStatus.completed, **extra):
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=INTENT, reference_id="ref-hash-1", merchant_id="m1",
            amount=1.0, currency="ETH", recipient=MERCHANT, status=status,
            chain="BASE", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            **extra,
        ))
        await db.commit()


# ── (1) merchant crash → receipt-recover → orchestrator settles ─────────────

@pytest.mark.asyncio
async def test_merchant_crash_recovers_and_settles():
    await _make_intent()
    eth = FakeEth()

    with _orchestrator_patches(eth):
        eth.raise_after_send = True
        await dss._execute_sweep_inner(INTENT, "ETH", "BASE")  # crashes, reverts
    async with async_session() as db:
        intent = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == INTENT))).scalar_one()
    assert intent.status == IntentStatus.completed       # reverted for retry
    assert len(eth.sends) == 1

    with _orchestrator_patches(eth):
        await dss._execute_sweep_inner(INTENT, "ETH", "BASE")  # retry → recover
    async with async_session() as db:
        intent = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == INTENT))).scalar_one()
    assert intent.status == IntentStatus.settled
    assert intent.sweep_tx_hash == _h(BASE_NONCE)        # recovered real hash
    assert len(eth.sends) == 2                           # merchant (recovered, no resend) + fee


# ── (2) merchant reverted on-chain → hold for review, no settle ─────────────

@pytest.mark.asyncio
async def test_merchant_reverted_holds_for_review():
    await _make_intent()
    eth = FakeEth()

    with _orchestrator_patches(eth):
        eth.raise_after_send = True
        await dss._execute_sweep_inner(INTENT, "ETH", "BASE")  # broadcast, crash
    eth.reverted.add(_h(BASE_NONCE))                     # the merchant tx reverts on-chain

    with _orchestrator_patches(eth):
        await dss._execute_sweep_inner(INTENT, "ETH", "BASE")  # retry → reverted

    assert len(eth.sends) == 1                           # never resent
    async with async_session() as db:
        intent = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == INTENT))).scalar_one()
        row = (await db.execute(select(TxIntent).where(
            TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:merchant"))).scalar_one()
    assert intent.status == IntentStatus.review          # held, NOT settled
    assert intent.sweep_tx_hash is None
    assert row.status == "failed"


# ── (4) pending in mempool → back off, no resend/complete ───────────────────

@pytest.mark.asyncio
async def test_pending_in_mempool_backs_off():
    eth = FakeEth()
    with ExitStack() as stack:
        for p in _web3_account_patches(eth):
            stack.enter_context(p)
        # First broadcast lands in mempool but the call crashes pre-commit.
        eth.raise_after_send = True
        with pytest.raises(RuntimeError):
            await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                                amount=99 * 10 ** 16, leg="merchant", nonce=BASE_NONCE)
        # Model it as still pending (not mined): move from sent → mempool.
        eth.sent.discard(_h(BASE_NONCE))
        eth.mempool.add(_h(BASE_NONCE))

        eth.raise_after_send = False
        result = await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                                     amount=99 * 10 ** 16, leg="merchant", nonce=BASE_NONCE)
    assert result is None                                # pending → not completed
    assert len(eth.sends) == 1                           # no resend
    async with async_session() as db:
        row = (await db.execute(select(TxIntent).where(
            TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:merchant"))).scalar_one()
    assert row.status == "broadcasting"                  # still in flight, held


# ── (5)/(6) reclaim persists the CURRENT re-signed hash, not the stale one ──

@pytest.mark.asyncio
async def test_reclaim_persists_current_hash_not_stale():
    eth = FakeEth()
    # RBF: each sign at the same nonce yields a DIFFERENT hash (gas changed).
    seq = {"i": 0}

    def rbf_hash(tx):
        seq["i"] += 1
        return _h(1000 + seq["i"])     # H1=...3e9, H2=...3ea, distinct per attempt

    with ExitStack() as stack:
        for p in _web3_account_patches(eth, hash_fn=rbf_hash):
            stack.enter_context(p)
        # Attempt 1: claim persists H1, then CRASH BEFORE the send (H1 never broadcast).
        eth.raise_before_send = True
        with pytest.raises(RuntimeError):
            await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                                amount=99 * 10 ** 16, leg="merchant", nonce=BASE_NONCE)
        h1 = _h(1001)
        async with async_session() as db:
            row = (await db.execute(select(TxIntent).where(
                TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:merchant"))).scalar_one()
        assert row.tx_hash == h1 and row.status == "broadcasting"
        assert len(eth.sends) == 0                       # nothing broadcast yet

        # Attempt 2 after the staleness window: re-sign (H2) and actually broadcast.
        eth.raise_before_send = False
        with patch("app.services.tx_intent_guard.RECLAIM_STALE_AFTER_S", 0):
            out = await sweep_deposit(INTENT, MERCHANT, currency="ETH", chain="BASE",
                                      amount=99 * 10 ** 16, leg="merchant", nonce=BASE_NONCE)
        h2 = _h(1002)
        assert out == h2                                 # broadcast the fresh tx
        assert eth.sends == [h2]                         # H2 sent, never H1
        async with async_session() as db:
            row = (await db.execute(select(TxIntent).where(
                TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:merchant"))).scalar_one()
        assert row.tx_hash == h2                          # reclaim re-INSERT used CURRENT hash
        assert row.status == "confirmed"

        # A further reconcile resolves completed (not needs_review): hash is fresh.
        from app.services.tx_intent_guard import reconcile_via_web3
        verdict = await reconcile_via_web3(FakeW3(eth), DEPOSIT, row)
        assert verdict["status"] == "completed"


# ── (3)/(7) fee-recovery job: amount from record, idempotent (run twice) ────

@pytest.mark.asyncio
async def test_fee_recovery_job_collects_then_idempotent():
    # Settled intent that owes a fee (fee_amount stored human; treasury unset).
    await _make_intent(
        status=IntentStatus.settled, fee_bps=100, fee_amount="0.01",
        merchant_sweep_amount="0.99", sweep_tx_hash=_h(BASE_NONCE),
    )
    # The merchant leg already confirmed at nonce N → fee sequences to N+1.
    async with async_session() as db:
        db.add(TxIntent(
            idempotency_key=f"deposit_sweep:{INTENT}:merchant", site="deposit_sweep",
            chain_id=8453, from_address=DEPOSIT, nonce=BASE_NONCE,
            status="confirmed", tx_hash=_h(BASE_NONCE),
        ))
        await db.commit()

    eth = FakeEth()
    settings = SimpleNamespace(platform_treasury_address=TREASURY, alchemy_api_key="x")

    import app.tasks.fee_recovery_tasks as frt
    with ExitStack() as stack:
        for p in _web3_account_patches(eth):
            stack.enter_context(p)
        stack.enter_context(patch("app.config.get_settings",
                                  MagicMock(return_value=settings)))
        stack.enter_context(patch("app.services.deposit_address_service.get_settings",
                                  MagicMock(return_value=settings)))

        r1 = await frt._recover_pending_fees_async()
        r2 = await frt._recover_pending_fees_async()   # run twice → no double-collect

    assert r1["recovered"] == 1
    assert r2["recovered"] == 0 and r2["scanned"] == 0   # already collected → out of target set
    assert len(eth.sends) == 1                           # exactly one fee broadcast, ever

    async with async_session() as db:
        intent = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == INTENT))).scalar_one()
        fee_row = (await db.execute(select(TxIntent).where(
            TxIntent.idempotency_key == f"deposit_sweep:{INTENT}:fee"))).scalar_one()
    # Fee collected to treasury at N+1, recorded with the fee leg's OWN hash.
    assert intent.fee_tx_hash == _h(BASE_NONCE + 1)
    assert intent.fee_tx_hash != intent.sweep_tx_hash
    assert fee_row.nonce == BASE_NONCE + 1 and fee_row.status == "confirmed"
