"""Phase E — session-authed org stats with USD conversion.

Pins the three properties that make this endpoint the correct replacement for the
scope-broken legacy `dashboard/stats`:
  1. USD conversion: a seeded settlement + its token's peg → expected USD volume.
  2. A token with NO peg is EXCLUDED from the aggregate and REPORTED, never
     summed as zero — so "paid in a token we cannot value" is distinguishable
     from "not paid at all".
  3. Scoping via the INTENT join (owner + env), NOT `settlement.merchant == owner`
     — so a settlement landing on the org's settlement_wallet (≠ primary wallet)
     is still counted. Plus org isolation.
"""

import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

import app.api.user_org_stats_routes as stats_mod
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
USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # 6 decimals, pegged
NATIVE_ETH = "0x" + "0" * 40  # the indexer's native sentinel — ETH, no peg

# The suite runs at this instant, always. Same reasoning as
# test_org_volume_series.py: a KPI route that reads the wall clock makes the
# result depend on when you happen to run the suite. Every fixture below is
# seeded relative to this constant, never to `now`.
FROZEN_NOW = datetime(2026, 3, 15, 0, 4, 0, tzinfo=timezone.utc)


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


@pytest.fixture(autouse=True)
def _patch_peg(monkeypatch):
    """Rebound from the removed `price_service.get_price` — same seam (the name
    bound IN THE ROUTE MODULE, not the one in `app.tokens.registry`), new source.

    USDC pegs at exactly 1.00. ETH returns None, and None means EXCLUDE: the
    route must count it and name it, never add 0.0 to the volume. Pinning the
    seam here rather than reading the real registry keeps these tests
    independent of which tokens the registry happens to carry.
    """

    def _fake_peg(chain_id, address):
        if (address or "").lower() == USDC_SEPOLIA.lower():
            return Decimal("1")
        return None

    monkeypatch.setattr(stats_mod, "get_usd_peg", _fake_peg)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch):
    """Pin the clock the route reads, so the 24h/48h windows are fixed."""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)

    monkeypatch.setattr(stats_mod, "datetime", _FrozenDatetime)


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
                               chain_id=84532, payer=None, created_at=None):
    """A completed intent for `owner` plus its FINAL on-chain settlement landing
    on `recipient` (the org's settlement wallet).

    `created_at` defaults to an instant inside the frozen 24h window; it is set
    explicitly rather than left to the column default so bucket/window placement
    never depends on when the suite runs.
    """
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(PaymentIntent(
        intent_id=intent_id, reference_id=secrets.token_hex(8),
        merchant_id=owner, environment=environment, amount=5.0, currency="USDC",
        chain="base_sepolia", status=IntentStatus.completed, recipient=recipient,
        expires_at=FROZEN_NOW + timedelta(minutes=30),
    ))
    session.add(PaymentSettlement(
        invoice_id="0x" + "1" * 64, merchant=recipient,
        payer=payer or ("0x" + "e" * 40), token=token, amount=amount_base,
        chain_id=chain_id, tx_hash="0x" + secrets.token_hex(32), log_index=0,
        block_number=1, status=SettlementStatus.final, intent_id=intent_id,
        created_at=created_at or (FROZEN_NOW - timedelta(hours=1)),
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
        created_at=FROZEN_NOW - timedelta(hours=1),
    ))
    await session.commit()

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    assert stats.transactions_24h == 0
    assert stats.volume_24h == 0.0
    # Unattributable, not unpriced — it never entered this org's scope at all.
    assert stats.volume_24h_unpriced_count == 0


# ── The peg: excluded, never zero ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_unpriced_is_distinguishable_from_no_payments(session):
    """THE regression this branch exists for.

    An org paid only in an unpeggable token reports volume 0.00 — the same
    number an org with no payments at all reports. If that is all the response
    says, the merchant cannot tell "we received nothing" from "we received
    money we could not value", and the second reads as the first. The exclusion
    count is what separates them.
    """
    paid_in_eth = await _make_org(session, owner_address=OWNER_A)
    paid_nothing = await _make_org(session, owner_address=OWNER_B)
    await _seed_settled_intent(
        session, owner=OWNER_A, recipient=SETTLE_WALLET_A,
        token=NATIVE_ETH, amount_base=2 * 10**18,  # 2 ETH, real money
    )

    eth = await get_org_stats(ctx=_ctx(paid_in_eth), environment="test", db=session)
    none = await get_org_stats(ctx=_ctx(paid_nothing), environment="test", db=session)

    # The settlement is real and counted...
    assert eth.transactions_24h == 1
    # ...contributes NOTHING to the aggregate (not 0.0 — nothing)...
    assert eth.volume_24h == 0.0
    # ...and says so, by count and by name.
    assert eth.volume_24h_unpriced_count == 1
    assert eth.volume_24h_unpriced_symbols == ["ETH"]

    # The genuinely-empty org reports the same volume and nothing else.
    assert none.transactions_24h == 0
    assert none.volume_24h == 0.0
    assert none.volume_24h_unpriced_count == 0
    assert none.volume_24h_unpriced_symbols == []

    # The whole point: identical volume, different responses.
    assert eth.volume_24h == none.volume_24h
    assert (eth.volume_24h_unpriced_count, eth.transactions_24h) != (
        none.volume_24h_unpriced_count, none.transactions_24h
    )


@pytest.mark.asyncio
async def test_pegged_only_org_reports_no_exclusion(session):
    """Every token valued → the aggregate is complete and claims to be."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.transactions_24h == 2
    assert stats.volume_24h == 10.0
    assert stats.volume_24h_unpriced_count == 0
    assert stats.volume_24h_unpriced_symbols == []


@pytest.mark.asyncio
async def test_mixed_org_reports_pegged_total_and_excluded_count(session):
    """A mix must report the pegged sum AND how much it left out — an aggregate
    that silently drops rows is a wrong number, not a partial one."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)
    await _seed_settled_intent(
        session, owner=OWNER_A, recipient=SETTLE_WALLET_A,
        token=NATIVE_ETH, amount_base=10**18,
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.transactions_24h == 2
    assert stats.volume_24h == 5.0            # the USDC leg only
    assert stats.volume_24h_unpriced_count == 1
    assert stats.volume_24h_unpriced_symbols == ["ETH"]


@pytest.mark.asyncio
async def test_unpriced_recent_row_is_not_reported_as_zero_dollars(session):
    """The recent-transactions list has the same failure mode as the tile: an
    ETH payment rendered as `$0` is a lie about a real payment."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(
        session, owner=OWNER_A, recipient=SETTLE_WALLET_A,
        token=NATIVE_ETH, amount_base=10**18,
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    row = stats.recent_transactions[0]
    assert row.currency == "ETH"
    assert row.amount_usd_known is False


@pytest.mark.asyncio
async def test_pegged_recent_row_is_marked_known(session):
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed_settled_intent(session, owner=OWNER_A, recipient=SETTLE_WALLET_A)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    row = stats.recent_transactions[0]
    assert row.amount_usd == 5.0
    assert row.amount_usd_known is True
