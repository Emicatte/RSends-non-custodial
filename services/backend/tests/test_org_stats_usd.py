"""Phase E — session-authed org stats with USD conversion.

Pins the two properties that make this endpoint the correct replacement for the
scope-broken legacy `dashboard/stats`:
  1. USD conversion: a seeded settlement + patched price → expected USD volume.
  2. Scoping via the INTENT join (owner + env), NOT `settlement.merchant == owner`
     — so a settlement landing on the org's settlement_wallet (≠ primary wallet)
     is still counted. Plus org isolation.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.merchant_models import PaymentIntent, IntentStatus
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.api.user_org_stats_routes import get_org_stats

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40
SETTLE_WALLET_A = "0x" + "d" * 40  # org A's settlement_wallet ≠ its primary wallet
USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # 6 decimals, usd-coin


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_org(session, *, owner_address):
    user = User(id=str(uuid4()), email=f"{secrets.token_hex(6)}@example.com", account_type="individual")
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3), slug=secrets.token_hex(8),
        owner_user_id=user.id, is_personal=False, plan="free",
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=owner_address,
        display_address=owner_address, verified_chain_id=84532,
        is_primary=True, chain_family="evm",
    ))
    await session.commit()
    return org


async def _seed_settled_intent(session, *, owner, recipient, environment="test",
                               token=USDC_SEPOLIA, amount_base=5_000_000,
                               chain_id=84532, payer=None):
    """A completed intent for `owner` plus its FINAL on-chain settlement landing
    on `recipient` (the org's settlement wallet)."""
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(PaymentIntent(
        intent_id=intent_id, reference_id=secrets.token_hex(8),
        merchant_id=owner, environment=environment, amount=5.0, currency="USDC",
        chain="base_sepolia", status=IntentStatus.completed, recipient=recipient,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    ))
    session.add(PaymentSettlement(
        invoice_id="0x" + "1" * 64, merchant=recipient,
        payer=payer or ("0x" + "e" * 40), token=token, amount=amount_base,
        chain_id=chain_id, tx_hash="0x" + secrets.token_hex(32), log_index=0,
        block_number=1, status=SettlementStatus.final, intent_id=intent_id,
    ))
    await session.commit()
    return intent_id


def _ctx(org, role="viewer"):
    return ("user-unused", str(org.id), role)


@pytest.mark.asyncio
async def test_usd_volume_from_seeded_settlement(session):
    """5 USDC settled + price 1.0 → volume_24h == 5.0, count == 1."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.transactions_24h == 1
    assert stats.volume_24h == 5.0
    assert stats.recent_transactions[0].amount_usd == 5.0
    assert stats.recent_transactions[0].currency == "USDC"


@pytest.mark.asyncio
async def test_stats_scoped_by_settlement_wallet_not_primary(session):
    """The settlement lands on SETTLE_WALLET_A (≠ OWNER_A primary). The legacy
    `settlement.merchant == owner` filter would read ZERO; the intent-join scope
    counts it."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    # Proves scoping is via intent.merchant_id==owner, not settlement.merchant.
    assert stats.transactions_24h == 1
    assert stats.volume_24h == 5.0


@pytest.mark.asyncio
async def test_stats_org_isolation_no_leak(session):
    """Org A's stats never include org B's settlements."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)
    await _seed_settled_intent(session, owner=OWNER_B, recipient=("0x" + "f" * 40))
    await _seed_settled_intent(session, owner=OWNER_B, recipient=("0x" + "f" * 40))

    a = await get_org_stats(ctx=_ctx(org_a), environment="test", db=session)
    b = await get_org_stats(ctx=_ctx(org_b), environment="test", db=session)
    assert a.transactions_24h == 1
    assert b.transactions_24h == 2


@pytest.mark.asyncio
async def test_stats_env_scoped(session):
    """`environment` scopes via the intent join (settlements have no env column)."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A, environment="test")
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A, environment="live")

    test_view = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    live_view = await get_org_stats(ctx=_ctx(org), environment="live", db=session)
    assert test_view.transactions_24h == 1
    assert live_view.transactions_24h == 1


@pytest.mark.asyncio
async def test_unmatched_settlement_excluded(session):
    """A settlement with no intent_id can't be attributed to an org/env → excluded."""
    org = await _make_org(session, owner_address=OWNER_A)
    session.add(PaymentSettlement(
        invoice_id="0x" + "2" * 64, merchant=SETTLE_WALLET_A,
        payer="0x" + "e" * 40, token=USDC_SEPOLIA, amount=9_000_000,
        chain_id=84532, tx_hash="0x" + secrets.token_hex(32), log_index=0,
        block_number=1, status=SettlementStatus.final, intent_id=None,
    ))
    await session.commit()

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    assert stats.transactions_24h == 0
    assert stats.volume_24h == 0.0


# ═════════════════════════════════════════════════════════════════
#  Stablecoin peg (price_service removed 2026-07-14)
# ═════════════════════════════════════════════════════════════════

NATIVE_ETH = "0x" + "0" * 40


@pytest.mark.asyncio
async def test_eth_settlement_counts_but_contributes_zero_volume(session):
    """RSends moves stablecoins only: a non-stablecoin settlement (native ETH,
    no peg) is counted in transactions_24h but adds 0 to the USD volume KPI."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)
    await _seed_settled_intent(
        session, owner=OWNER_A, recipient=SETTLE_WALLET_A,
        token=NATIVE_ETH, amount_base=10**18,  # 1 ETH
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.transactions_24h == 2          # both counted
    assert stats.volume_24h == 5.0              # only the USDC contributes


def test_registry_pegs_stablecoins_only():
    """peg_usd = 1.0 exactly on the USD stablecoins, None on everything else —
    the dashboard volume figure must never invent a price."""
    from app.tokens.registry import TOKEN_REGISTRY

    for token in TOKEN_REGISTRY.values():
        if token.symbol in ("USDC", "USDT", "DAI"):
            assert token.peg_usd == 1.0, token
        else:
            assert token.peg_usd is None, token
