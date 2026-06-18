"""
Soak harness for the C1 distribution lock (`_execute_distribution_locked`).

Runs the EXACT worker code path (`asyncio.run(_execute_distribution_locked(...))`)
against REAL Redis, with the chain STUBBED (a slow `await asyncio.sleep` no-op for
`_execute_single_transfer`) — no funds, no RPC, no testnet. Only Redis is real, so
the lock + heartbeat + TTL behavior is exercised for real.

Usage (Redis must be up at REDIS_URL):
  DATABASE_URL="sqlite+aiosqlite:////tmp/soak_distrib.db" REDIS_URL="redis://localhost:6379/0" DEBUG=1 \
    ./venv/bin/python scripts/soak_distribution_lock.py seed --items 2
  ...                                                        run <batch_id> --slow 8

Real Redis key held = "sweep_lock:distrib_batch:{batch_id}" (acquire_sweep_lock
prefixes "sweep_lock:"); the heartbeat log shows the unprefixed key.
"""
import argparse
import asyncio
import importlib
import logging
import os
import pkgutil
import sys
import time
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# repo root on sys.path (this file lives in scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402,F401
from app.db.session import async_session, engine  # noqa: E402
from app.models.db_models import Base  # noqa: E402

# register ALL ORM models so create_all resolves cross-model FKs
import app.models as _models_pkg  # noqa: E402
for _m in pkgutil.iter_modules(_models_pkg.__path__):
    if _m.name.endswith("_models"):
        importlib.import_module(f"app.models.{_m.name}")

from app.models.command_models import SweepBatch, SweepBatchItem  # noqa: E402
import app.tasks.sweep_tasks as st  # noqa: E402

HOT = "0x" + "99" * 20
log = logging.getLogger("soak")


def _setup_logging():
    """Force root DEBUG + stdout handler AFTER imports (so nothing overrides it).
    The heartbeat line is logger.debug in app.services.sweep_service."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stderr)  # logs -> stderr; results (batch_id, RESULT) -> stdout
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers[:] = [h]
    logging.getLogger("app.services.sweep_service").setLevel(logging.DEBUG)
    # Kill SQLAlchemy echo (DEBUG=1 sets echo=True at engine creation) + other noise:
    # remove their own handlers (echo attaches a stdout handler) and stop propagation.
    for noisy in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
                  "sqlalchemy.pool", "sqlalchemy.dialects", "aiosqlite", "asyncio"):
        lg = logging.getLogger(noisy)
        lg.handlers[:] = []
        lg.setLevel(logging.WARNING)
        lg.propagate = False


async def _seed(n_items: int) -> str:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        batch = SweepBatch(
            incoming_tx_hash="0x" + uuid.uuid4().hex,
            source_address=HOT,
            chain_id=8453,
            total_amount_wei="1000000000000000000",
            token_symbol="ETH",
            status="PENDING",
        )
        db.add(batch)
        await db.flush()
        share = 10000 // n_items
        for i in range(n_items):
            db.add(SweepBatchItem(
                batch_id=batch.id,
                recipient_address="0x" + f"{i + 1:02x}" * 20,
                amount_wei="500000000000000000",
                percent_bps=share,
                status="PENDING",
                nonce=None,
            ))
        await db.commit()
        return str(batch.id)


def _patch_chain(slow: float) -> ExitStack:
    """Stub every CHAIN dependency. Redis + acquire_sweep_lock + start_sweep_heartbeat
    are deliberately NOT patched -> real Redis lock + real heartbeat."""
    policy = MagicMock()
    policy.check_and_reserve = AsyncMock(return_value=SimpleNamespace(allowed=True, reason=None, tier=None))
    policy.release = AsyncMock()
    wm = MagicMock()
    wm.estimate_sweep_gas = AsyncMock(return_value=21000)
    wm.check_hot_sufficient = AsyncMock(return_value=True)
    rpc = MagicMock()
    rpc.call = AsyncMock(return_value=hex(10 ** 9))  # eth_gasPrice
    nm = MagicMock()
    nm.reserve_range = AsyncMock(return_value=(100, 100))
    signer = MagicMock()
    signer.get_address = AsyncMock(return_value=HOT)

    async def slow_transfer(*_a, **k):
        # async sleep -> event loop yields -> heartbeat task can run
        await asyncio.sleep(slow)
        return "0x" + f"{k.get('nonce', 0):064x}"

    stack = ExitStack()
    e = stack.enter_context
    e(patch("app.services.circuit_breaker.get_circuit_breaker", MagicMock(return_value=None)))
    e(patch("app.services.spending_policy.get_spending_policy", MagicMock(return_value=policy)))
    e(patch("app.services.wallet_manager.get_wallet_manager", MagicMock(return_value=wm)))
    e(patch("app.services.rpc_manager.get_rpc_manager", MagicMock(return_value=rpc)))
    e(patch("app.services.nonce_manager.get_nonce_manager", MagicMock(return_value=nm)))
    e(patch("app.services.key_manager.get_signer", MagicMock(return_value=signer)))
    e(patch("app.services.audit_service.log_event", AsyncMock()))
    e(patch("app.services.sweep_service.get_bumped_gas_params", AsyncMock(return_value={})))
    e(patch("app.services.sweep_service._replacement_mode_active", MagicMock(return_value=False)))
    e(patch.object(st, "_execute_single_transfer", AsyncMock(side_effect=slow_transfer)))
    e(patch.object(st, "_notify_websocket", AsyncMock()))
    e(patch.object(st, "_notify_telegram", AsyncMock()))
    e(patch.object(st, "confirm_batch", MagicMock()))
    e(patch.object(st, "retry_failed_items", MagicMock()))
    return stack


async def _run(batch_id: str, slow: float):
    with _patch_chain(slow):
        t0 = time.monotonic()
        res = await st._execute_distribution_locked(MagicMock(), batch_id)
        dt = time.monotonic() - t0
        print(f"RESULT pid={os.getpid()} elapsed={dt:.1f}s {res}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("seed")
    sp.add_argument("--items", type=int, default=1)
    rp = sub.add_parser("run")
    rp.add_argument("batch_id")
    rp.add_argument("--slow", type=float, default=5.0)
    args = ap.parse_args()

    _setup_logging()
    if args.cmd == "seed":
        print(asyncio.run(_seed(args.items)), flush=True)
    else:
        asyncio.run(_run(args.batch_id, args.slow))


if __name__ == "__main__":
    main()
