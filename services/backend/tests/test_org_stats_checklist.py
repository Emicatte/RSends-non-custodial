"""Get-started checklist facts on the session org-stats route.

Pins the contract that feeds the /app home "Get started" card:

  1. Three flat booleans on the stats response — `settlement_wallet_set`
     (org column non-empty), `has_api_key` (≥1 active rsusr_ key for the org,
     same predicate as the "N of 5 used" count), `has_paid_payment`
     (≥1 intent with status == paid, env-scoped like the KPIs).
  2. Fresh-merchant safety: an org with NO owner identity (no primary EVM
     wallet, no settlement_wallet) gets **200 with zeroed KPIs + the
     booleans**, NOT the resolver's 409 `no_primary_wallet` — that state is
     exactly the card's primary audience. `settlement_wallet_conflict`
     still propagates as 409 (contested identity stays loud).
  3. The response model is `OrgDashboardStats` — without the response_model
     swap FastAPI would silently strip the booleans from the wire while
     these direct-coroutine tests stay green.

Direct-handler tests, same pattern as test_org_stats_usd.py.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

import app.api.user_org_stats_routes as stats_mod
from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.user_api_keys_models import UserApiKey
from app.models.merchant_models import PaymentIntent, IntentStatus
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.api.user_org_stats_routes import get_org_stats

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40
SETTLE_WALLET = "0x" + "d" * 40
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


@pytest.fixture(autouse=True)
def _patch_price(monkeypatch):
    async def _fake_price(coingecko_id, currency="usd"):
        return {"usd-coin": 1.0, "ethereum": 2000.0}.get(coingecko_id)
    monkeypatch.setattr(stats_mod, "get_price", _fake_price)


async def _make_org(session, *, primary_wallet=None, settlement_wallet=None):
    """Org (+ owner user + admin membership). Unlike the usd file's helper the
    primary EVM wallet is OPTIONAL — the fresh-merchant tests need it absent."""
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
        settlement_wallet=settlement_wallet,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if primary_wallet is not None:
        session.add(UserWallet(
            user_id=user.id, org_id=org.id, address=primary_wallet,
            display_address=primary_wallet, verified_chain_id=84532,
            is_primary=True, chain_family="evm",
        ))
    await session.commit()
    return user, org


async def _seed_intent(session, *, owner, status, environment="test"):
    """A bare intent — the paid-payment boolean needs no settlement row."""
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(PaymentIntent(
        intent_id=intent_id, reference_id=secrets.token_hex(8),
        merchant_id=owner, environment=environment, amount=5.0, currency="USDC",
        chain="base_sepolia", status=status, recipient=SETTLE_WALLET,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    ))
    await session.commit()
    return intent_id


async def _seed_settled_intent(session, *, owner, recipient, status,
                               environment="test", amount_base=5_000_000):
    """Intent + FINAL settlement (the usd file's helper, with `status` a
    required param — its hardcoded legacy `completed` would never tick the
    paid boolean)."""
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(PaymentIntent(
        intent_id=intent_id, reference_id=secrets.token_hex(8),
        merchant_id=owner, environment=environment, amount=5.0, currency="USDC",
        chain="base_sepolia", status=status, recipient=recipient,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    ))
    session.add(PaymentSettlement(
        invoice_id="0x" + "1" * 64, merchant=recipient,
        payer="0x" + "e" * 40, token=USDC_SEPOLIA, amount=amount_base,
        chain_id=84532, tx_hash="0x" + secrets.token_hex(32), log_index=0,
        block_number=1, status=SettlementStatus.final, intent_id=intent_id,
    ))
    await session.commit()
    return intent_id


async def _seed_user_key(session, *, user, org, is_active=True, revoked_at=None):
    """Direct rsusr_ key row (skip bcrypt/create_key — the boolean only reads
    org_id + is_active + revoked_at, the "N of 5 used" predicate)."""
    session.add(UserApiKey(
        user_id=user.id, org_id=org.id, label="test key",
        key_prefix="rsusr_live_" + secrets.token_hex(4),
        display_prefix="rsusr_live_" + secrets.token_hex(4) + "...",
        key_hash=secrets.token_hex(32),
        scopes=[], is_active=is_active, revoked_at=revoked_at,
    ))
    await session.commit()


def _ctx(org, role="viewer"):
    return ("user-unused", str(org.id), role)


def _assert_zeroed_kpis(stats):
    assert stats.volume_24h == 0.0
    assert stats.volume_24h_delta_pct == 0.0
    assert stats.transactions_24h == 0
    assert stats.transactions_24h_delta == 0
    assert stats.total_balance == 0.0
    assert stats.total_balance_chains == 0
    assert stats.active_clients == 0
    assert stats.active_clients_this_week == 0
    assert stats.recent_transactions == []


@pytest.mark.asyncio
async def test_fresh_org_200_with_zeroed_kpis_not_409(session):
    """No primary wallet, no settlement wallet — the fresh-merchant state.
    The route must RETURN (zeroed KPIs + all-False booleans), not raise the
    resolver's 409 `no_primary_wallet`."""
    _user, org = await _make_org(session)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    _assert_zeroed_kpis(stats)
    assert stats.settlement_wallet_set is False
    assert stats.has_api_key is False
    assert stats.has_paid_payment is False


@pytest.mark.asyncio
async def test_fresh_org_with_active_key_reports_has_api_key(session):
    """The key fact is org-scoped and computed BEFORE owner resolution — an
    identity-less org that already made a key must see the step complete."""
    user, org = await _make_org(session)
    await _seed_user_key(session, user=user, org=org)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.has_api_key is True
    assert stats.settlement_wallet_set is False
    assert stats.has_paid_payment is False


@pytest.mark.asyncio
async def test_settlement_wallet_set_true_via_fallback(session):
    """Settlement wallet set (unclaimed), no primary → owner resolves via the
    PR#20 fallback; the wallet step reads complete, KPIs still zero."""
    _user, org = await _make_org(session, settlement_wallet=SETTLE_WALLET)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.settlement_wallet_set is True
    assert stats.has_api_key is False
    assert stats.has_paid_payment is False
    _assert_zeroed_kpis(stats)


@pytest.mark.asyncio
async def test_settlement_wallet_set_false_with_primary_wallet_only(session):
    """The boolean is the org COLUMN, not "has an owner identity" — a
    SIWE-linked org without a settlement wallet still has the step open
    (the recipient gate needs the column to create intents)."""
    _user, org = await _make_org(session, primary_wallet=OWNER_A)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.settlement_wallet_set is False


@pytest.mark.asyncio
async def test_settlement_wallet_empty_string_reads_unset(session):
    """'' is unset everywhere (the resolver's `if not settlement:`); the
    boolean must agree — truthiness, not IS NOT NULL — or the card would show
    the wallet step complete while the route takes the identity-less path."""
    _user, org = await _make_org(session, settlement_wallet="")

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.settlement_wallet_set is False
    _assert_zeroed_kpis(stats)


@pytest.mark.asyncio
async def test_has_api_key_false_when_inactive_or_revoked(session):
    """Both prongs of the active predicate: is_active=False and revoked_at set
    each disqualify a key — matches count_active_keys_for_org / "N of 5"."""
    user, org = await _make_org(session, primary_wallet=OWNER_A)
    await _seed_user_key(session, user=user, org=org, is_active=False)
    await _seed_user_key(
        session, user=user, org=org, revoked_at=datetime.now(timezone.utc)
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.has_api_key is False


@pytest.mark.asyncio
async def test_has_paid_payment_true_on_paid_intent(session):
    _user, org = await _make_org(session, primary_wallet=OWNER_A)
    await _seed_intent(session, owner=OWNER_A, status=IntentStatus.paid)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.has_paid_payment is True


@pytest.mark.asyncio
async def test_has_paid_payment_false_for_pending_and_legacy_completed(session):
    """Only `paid` ticks the box (spec-final). Legacy `completed` counts as
    settled elsewhere (invoice_service) but NOT here — the step's point is a
    payment the indexer actually finalized, and fresh non-custodial orgs only
    ever produce `paid`."""
    _user, org = await _make_org(session, primary_wallet=OWNER_A)
    await _seed_intent(session, owner=OWNER_A, status=IntentStatus.pending)
    await _seed_intent(session, owner=OWNER_A, status=IntentStatus.completed)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.has_paid_payment is False


@pytest.mark.asyncio
async def test_has_paid_payment_env_scoped(session):
    """A live paid intent must not tick the test-env checklist (the /app UI is
    hard-locked to test) — and vice versa."""
    _user, org = await _make_org(session, primary_wallet=OWNER_A)
    await _seed_intent(
        session, owner=OWNER_A, status=IntentStatus.paid, environment="live"
    )

    test_view = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    live_view = await get_org_stats(ctx=_ctx(org), environment="live", db=session)

    assert test_view.has_paid_payment is False
    assert live_view.has_paid_payment is True


@pytest.mark.asyncio
async def test_checklist_cross_org_isolation(session):
    """Org A completed everything; org B must read all-False — none of A's
    wallet/key/intent facts leak into B's checklist. B has its OWN primary
    wallet (OWNER_B) so it reaches the paid-intent probe — an identity-less B
    would early-return with a hardcoded False and leave the probe's
    merchant_id filter unexercised. The fresh-org (identity-less) case is
    test_fresh_org_200_with_zeroed_kpis_not_409."""
    user_a, org_a = await _make_org(
        session, primary_wallet=OWNER_A, settlement_wallet=SETTLE_WALLET
    )
    await _seed_user_key(session, user=user_a, org=org_a)
    await _seed_intent(session, owner=OWNER_A, status=IntentStatus.paid)
    _user_b, org_b = await _make_org(session, primary_wallet=OWNER_B)

    a = await get_org_stats(ctx=_ctx(org_a), environment="test", db=session)
    b = await get_org_stats(ctx=_ctx(org_b), environment="test", db=session)

    assert a.settlement_wallet_set is True
    assert a.has_api_key is True
    assert a.has_paid_payment is True
    assert b.settlement_wallet_set is False
    assert b.has_api_key is False
    assert b.has_paid_payment is False


@pytest.mark.asyncio
async def test_settlement_wallet_conflict_still_409(session):
    """Only `no_primary_wallet` is caught. A contested settlement wallet (here:
    already SIWE-claimed by org A) keeps failing loud with 409
    `settlement_wallet_conflict` — never a silent zeroed payload."""
    await _make_org(session, primary_wallet=OWNER_A)
    _user_b, org_b = await _make_org(session, settlement_wallet=OWNER_A)

    with pytest.raises(HTTPException) as exc:
        await get_org_stats(ctx=_ctx(org_b), environment="test", db=session)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "settlement_wallet_conflict"


@pytest.mark.asyncio
async def test_success_path_kpis_with_booleans(session):
    """Full seed (paid intent + FINAL settlement): the booleans ride along
    WITHOUT disturbing the KPI math the usd file pins."""
    user, org = await _make_org(
        session, primary_wallet=OWNER_A, settlement_wallet=SETTLE_WALLET
    )
    await _seed_user_key(session, user=user, org=org)
    await _seed_settled_intent(
        session, owner=OWNER_A, recipient=SETTLE_WALLET, status=IntentStatus.paid
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.transactions_24h == 1
    assert stats.volume_24h == 5.0
    assert stats.settlement_wallet_set is True
    assert stats.has_api_key is True
    assert stats.has_paid_payment is True


def test_route_response_model_is_org_dashboard_stats():
    """Guard against the response_model filtering trap: every other test here
    calls the coroutine directly and would stay green even if FastAPI stripped
    the booleans from the wire. Pin the APIRoute's response_model."""
    from fastapi.routing import APIRoute
    from app.main import app
    from app.models.dashboard_schemas import OrgDashboardStats

    route = next(
        r for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == "/api/v1/user/org/stats"
        and "GET" in r.methods
    )
    assert route.response_model is OrgDashboardStats
