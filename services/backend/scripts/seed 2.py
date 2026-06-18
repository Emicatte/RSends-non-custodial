"""
RSends Backend — Database Seed Script.

Seeds initial data required for the system to operate:
  - Ledger accounts (fee, escrow, treasury, gas_reserve)
  - Default circuit breaker states
  - Sample distribution list (testnet only)

Usage:
    cd rpagos-backend
    python -m scripts.seed                       # default: uses DATABASE_URL from .env
    DATABASE_URL=sqlite+aiosqlite:///./dev.db python -m scripts.seed
"""

import asyncio
import hashlib
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is on sys.path
sys.path.insert(0, ".")

from app.db.session import async_session, init_db
from app.models.ledger_models import Account, LedgerAuditLog
from app.models.command_models import CircuitBreakerState


# ═══════════════════════════════════════════════════════════════
#  Seed Data
# ═══════════════════════════════════════════════════════════════

SYSTEM_ACCOUNTS = [
    {
        "account_type": "FEE_COLLECTION",
        "currency": "ETH",
        "label": "Platform Fee Collection (ETH)",
        "metadata_": {"description": "Collects 0.5% platform fees on ETH sweeps"},
    },
    {
        "account_type": "FEE_COLLECTION",
        "currency": "USDC",
        "label": "Platform Fee Collection (USDC)",
        "metadata_": {"description": "Collects 0.5% platform fees on USDC sweeps"},
    },
    {
        "account_type": "ESCROW",
        "currency": "ETH",
        "label": "Sweep Escrow (ETH)",
        "metadata_": {"description": "Temporary hold during sweep processing"},
    },
    {
        "account_type": "ESCROW",
        "currency": "USDC",
        "label": "Sweep Escrow (USDC)",
        "metadata_": {"description": "Temporary hold during USDC sweep processing"},
    },
    {
        "account_type": "TREASURY",
        "currency": "ETH",
        "label": "Treasury (ETH)",
        "metadata_": {"description": "Main treasury account for ETH"},
    },
    {
        "account_type": "TREASURY",
        "currency": "USDC",
        "label": "Treasury (USDC)",
        "metadata_": {"description": "Main treasury account for USDC"},
    },
    {
        "account_type": "GAS_RESERVE",
        "currency": "ETH",
        "label": "Gas Reserve",
        "metadata_": {"description": "Hot wallet gas reserve for sweep transactions"},
    },
]

CIRCUIT_BREAKERS = [
    {"name": "redis", "state": "CLOSED"},
    {"name": "alchemy_rpc", "state": "CLOSED"},
    {"name": "base_rpc", "state": "CLOSED"},
    {"name": "ethereum_rpc", "state": "CLOSED"},
    {"name": "sweep_executor", "state": "CLOSED"},
    {"name": "telegram_alerts", "state": "CLOSED"},
]


# ═══════════════════════════════════════════════════════════════
#  Seed Functions
# ═══════════════════════════════════════════════════════════════

def _compute_chain_hash(
    previous_hash: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_id: str,
    created_at: str,
) -> str:
    """Compute SHA-256 chain hash for audit log entry."""
    payload = f"{previous_hash}|{event_type}|{entity_type}|{entity_id}|{actor_id}|{created_at}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def seed_accounts(session: AsyncSession) -> int:
    """Seed system ledger accounts. Skips if already exist."""
    created = 0
    for acct_data in SYSTEM_ACCOUNTS:
        # Check if account with this type+currency already exists
        result = await session.execute(
            select(Account).where(
                Account.account_type == acct_data["account_type"],
                Account.currency == acct_data["currency"],
                Account.label == acct_data["label"],
            )
        )
        if result.scalar_one_or_none() is not None:
            continue

        account = Account(
            id=uuid.uuid4(),
            account_type=acct_data["account_type"],
            currency=acct_data["currency"],
            label=acct_data["label"],
            is_active=True,
            metadata_=acct_data["metadata_"],
            created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        created += 1

    return created


async def seed_circuit_breakers(session: AsyncSession) -> int:
    """Seed initial circuit breaker states. Skips if already exist."""
    created = 0
    now = datetime.now(timezone.utc)

    for cb_data in CIRCUIT_BREAKERS:
        result = await session.execute(
            select(CircuitBreakerState).where(
                CircuitBreakerState.name == cb_data["name"]
            )
        )
        if result.scalar_one_or_none() is not None:
            continue

        cb = CircuitBreakerState(
            id=uuid.uuid4(),
            name=cb_data["name"],
            state=cb_data["state"],
            failure_count=0,
            success_count=0,
            metadata_={"seeded": True},
            updated_at=now,
            created_at=now,
        )
        session.add(cb)
        created += 1

    return created


async def seed_genesis_audit(session: AsyncSession) -> int:
    """Create genesis audit log entry (sequence 0) for chain hash anchor."""
    result = await session.execute(
        select(LedgerAuditLog).where(LedgerAuditLog.sequence_number == 0)
    )
    if result.scalar_one_or_none() is not None:
        return 0

    genesis_hash = "0" * 64
    now = datetime.now(timezone.utc)
    chain_hash = _compute_chain_hash(
        genesis_hash, "GENESIS", "system", "genesis", "seed_script", now.isoformat()
    )

    entry = LedgerAuditLog(
        sequence_number=0,
        event_type="GENESIS",
        entity_type="system",
        entity_id="genesis",
        actor_type="system",
        actor_id="seed_script",
        previous_hash=genesis_hash,
        chain_hash=chain_hash,
        created_at=now,
    )
    session.add(entry)
    return 1


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all seed functions."""
    print("RSends Database Seed Script")
    print("=" * 50)

    # Ensure tables exist
    await init_db()
    print("[OK] Tables created/verified")

    async with async_session() as session:
        async with session.begin():
            accounts_created = await seed_accounts(session)
            print(f"[OK] Accounts: {accounts_created} created")

            cb_created = await seed_circuit_breakers(session)
            print(f"[OK] Circuit breakers: {cb_created} created")

            audit_created = await seed_genesis_audit(session)
            print(f"[OK] Genesis audit entry: {audit_created} created")

    print("=" * 50)
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
