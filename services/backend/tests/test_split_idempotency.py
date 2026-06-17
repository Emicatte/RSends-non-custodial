"""
RPagos Backend — Test: Split execution idempotency (C1a fix).

Verifies that a duplicate webhook delivery for the same
(contract_id, source_tx_hash) CANNOT cause a double split payout:

  - The DB unique constraint `uq_split_exec_contract_srctx` rejects the 2nd
    INSERT (IntegrityError) BEFORE any on-chain transfer is sent.
  - SplitExecutor.execute() turns that into DuplicateSplitExecution.
  - The duplicate path sends ZERO transactions.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_split_idempotency.py -v

NB: sequential by design — the in-memory SQLite test engine has no StaticPool,
so concurrent sessions could land on separate DBs. Sequential deliveries reuse
the pooled connection and deterministically exercise the constraint, which is
exactly what protects production (the constraint is atomic on Postgres too).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import engine, async_session
from app.models.db_models import Base

# Register ALL ORM models so Base.metadata.create_all can resolve every
# cross-model FK (e.g. users.active_org_id -> organizations). The running app
# registers these transitively via its routers; a test must do it explicitly,
# otherwise create_all raises NoReferencedTableError on an unimported target.
import importlib
import pkgutil
import app.models as _models_pkg

for _m in pkgutil.iter_modules(_models_pkg.__path__):
    if _m.name.endswith("_models"):
        importlib.import_module(f"app.models.{_m.name}")

from app.models.split_models import SplitContract, SplitExecution
from app.services.split_engine import SplitOutput, SplitPlan
from app.services.split_executor import DuplicateSplitExecution, SplitExecutor

SOURCE_TX = "0x" + "ab" * 32
W_A = "0x" + "22" * 20
W_B = "0x" + "33" * 20


class _CountingSigner:
    """Mock signer that counts how many on-chain transfers it was asked to do."""

    def __init__(self):
        self.sends = 0

    async def send_native(self, to, value):
        self.sends += 1
        return "0x" + "11" * 32

    async def send_erc20(self, token_address, to, amount):
        self.sends += 1
        return "0x" + "cd" * 32


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create and drop all tables per test (mirrors test_sweep_service)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    # Dispose pooled aiosqlite connections so the process exits cleanly
    # (lingering connection threads otherwise keep pytest alive at the end).
    await engine.dispose()


async def _make_contract() -> int:
    async with async_session() as db:
        contract = SplitContract(
            client_id="client-test",
            master_wallet="0x" + "44" * 20,
            owner_address="0x" + "44" * 20,
            chain_id=8453,
            rsend_fee_bps=50,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


def _make_plan(contract_id: int) -> SplitPlan:
    return SplitPlan(
        contract_id=contract_id,
        client_id="client-test",
        input_amount=1_000_000,
        rsend_fee=5_000,
        distributable=995_000,
        outputs=[
            SplitOutput(
                wallet=W_A, label="A", role="primary",
                share_bps=6000, amount=597_000, position=0,
            ),
            SplitOutput(
                wallet=W_B, label="B", role="recipient",
                share_bps=4000, amount=398_000, position=1,
            ),
        ],
        remainder=0,
        token="USDC",
        decimals=6,
        total_check=995_000,
    )


async def _deliver(contract_id: int, signer) -> SplitExecution:
    """Run one split delivery with AML/kill-switch stubbed out (we test
    idempotency here, not AML)."""
    plan = _make_plan(contract_id)
    async with async_session() as db:
        executor = SplitExecutor(signer=signer, rpc_client=None, db_session=db)
        executor._aml_gate = AsyncMock(return_value=None)  # isolate from AML
        with patch("app.services.split_executor.kill_switch") as ks, patch(
            "app.services.split_executor.auto_stop", MagicMock()
        ):
            ks.can_execute = AsyncMock(return_value=(True, ""))
            return await executor.execute(plan, source_tx_hash=SOURCE_TX)


@pytest.mark.asyncio
async def test_unique_constraint_rejects_second_execution():
    """Two SplitExecution rows with the same (contract_id, source_tx_hash)
    cannot coexist — the DB constraint is the atomic gate."""
    contract_id = await _make_contract()
    async with async_session() as db:
        db.add(
            SplitExecution(
                contract_id=contract_id,
                source_tx_hash=SOURCE_TX,
                input_amount="1000000",
                input_token="USDC",
                input_decimals=6,
                status="completed",
            )
        )
        await db.flush()
        db.add(
            SplitExecution(
                contract_id=contract_id,
                source_tx_hash=SOURCE_TX,
                input_amount="1000000",
                input_token="USDC",
                input_decimals=6,
                status="executing",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()


@pytest.mark.asyncio
async def test_duplicate_delivery_sends_nothing():
    """1st delivery executes and sends; a 2nd delivery for the same TX raises
    DuplicateSplitExecution and sends ZERO transactions (no double payout)."""
    contract_id = await _make_contract()

    # ── Delivery 1: succeeds, sends 2 transfers ──
    signer1 = _CountingSigner()
    execution = await _deliver(contract_id, signer1)
    assert execution.status == "completed"
    assert signer1.sends == 2  # one per output

    # ── Delivery 2: same (contract, tx) → duplicate, ZERO sends ──
    signer2 = _CountingSigner()
    with pytest.raises(DuplicateSplitExecution):
        await _deliver(contract_id, signer2)
    assert signer2.sends == 0  # idempotency gate fired BEFORE any send

    # ── Exactly one execution committed for this (contract, tx) ──
    async with async_session() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(SplitExecution)
                .where(
                    SplitExecution.contract_id == contract_id,
                    SplitExecution.source_tx_hash == SOURCE_TX,
                )
            )
        ).scalar_one()
    assert count == 1
