"""Session-authed org volume time series — `GET /api/v1/user/org/stats/volume-series`.

Feeds the /app "Volume trend (7d)" card. Pins the properties that make a chart
trustworthy rather than merely plausible:

  * N days requested → N buckets returned, quiet days present as 0.0 and never
    omitted (a gap in the array is how a chart draws a misleading line);
  * bucket boundaries are UTC, asserted explicitly at 23:59:59Z / 00:00:00Z —
    the settlement `created_at` can come back naive from SQLite, and a naive
    `.astimezone()` would silently shift rows a bucket;
  * the SAME scope as the `volume_24h` tile beside it: settlements attributed
    through the intent join (owner + environment) with
    `PaymentSettlement.status == final`. If this diverged, the card and the
    tile would disagree about the same money.
  * no data is a normal state → 200 with zero buckets, never 404, never 500.
"""

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

import app.api.user_org_stats_routes as stats_mod
import app.api.user_org_volume_series_routes as series_mod
from app.api.user_org_volume_series_routes import get_org_volume_series
from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.org_models import Membership, Organization
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.models.user_wallets_models import UserWallet

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40
SETTLE_WALLET_A = "0x" + "d" * 40  # org A's settlement_wallet ≠ its primary wallet
USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # 6 decimals, pegged
NATIVE_ETH = "0x" + "0" * 40  # the indexer's native sentinel — ETH, no peg
ONE_USDC = 1_000_000  # base units → $1.00 at the 1:1 peg

# The suite runs at this instant, always. 00:04 UTC is deliberate: it is the
# condition under which this file used to fail in CI, once a day, for a one-hour
# window. Seeding further from midnight would only narrow that window — the fix
# is to stop reading the wall clock, so the same code takes the same path at
# every hour of every day.
FROZEN_NOW = datetime(2026, 3, 15, 0, 4, 0, tzinfo=timezone.utc)


def _at(day, hour=12, minute=0):
    """An instant inside `day`'s UTC bucket, named by the bucket it targets."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


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
    """Rebound from the removed `price_service.get_price` — same seam, new
    source. Patch the name bound IN THE ROUTE MODULE, not the registry's.

    USDC pegs at exactly 1.00; anything else returns None, and None means
    EXCLUDE — counted and named, never added as 0.0.
    """

    def _fake_peg(chain_id, address):
        if (address or "").lower() == USDC_SEPOLIA.lower():
            return Decimal("1")
        return None

    monkeypatch.setattr(series_mod, "get_usd_peg", _fake_peg)
    # The cross-check test calls the stats route, which binds its OWN copy
    # (user_org_stats_routes imports the name directly). Leaving it unpatched
    # would let the card and the tile resolve pegs from different sources and
    # disagree by construction. Same reason as above: patch the name bound in
    # EACH route module.
    monkeypatch.setattr(stats_mod, "get_usd_peg", _fake_peg)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch):
    """Pin the clock BOTH route modules read.

    Patched on the names bound in the route modules, same idiom as
    `_patch_price` above. `user_org_stats_routes` is included because the
    cross-check test compares this card against that route's rolling 24h
    window — freezing only one would make them disagree by construction.
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)

    monkeypatch.setattr(series_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(stats_mod, "datetime", _FrozenDatetime)


async def _make_org(session, *, owner_address):
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
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(
        UserWallet(
            user_id=user.id,
            org_id=org.id,
            address=owner_address,
            display_address=owner_address,
            verified_chain_id=84532,
            is_primary=True,
            chain_family="evm",
        )
    )
    await session.commit()
    return org


async def _seed(
    session,
    *,
    owner,
    created_at,
    recipient=SETTLE_WALLET_A,
    environment="test",
    amount_base=ONE_USDC,
    status=SettlementStatus.final,
    token=USDC_SEPOLIA,
    chain_id=84532,
):
    """One completed intent for `owner` + its settlement stamped `created_at`.

    Unlike the stats-suite helper this sets `created_at` explicitly — bucket
    placement is the whole point here, so it can never rely on `now()`.
    """
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(
        PaymentIntent(
            intent_id=intent_id,
            reference_id=secrets.token_hex(8),
            merchant_id=owner,
            environment=environment,
            amount=1.0,
            currency="USDC",
            chain="base_sepolia",
            status=IntentStatus.completed,
            recipient=recipient,
            expires_at=FROZEN_NOW + timedelta(minutes=30),
        )
    )
    session.add(
        PaymentSettlement(
            invoice_id="0x" + "1" * 64,
            merchant=recipient,
            payer="0x" + "e" * 40,
            token=token,
            amount=amount_base,
            chain_id=chain_id,
            tx_hash="0x" + secrets.token_hex(32),
            log_index=0,
            block_number=1,
            status=status,
            intent_id=intent_id,
            created_at=created_at,
        )
    )
    await session.commit()
    return intent_id


def _ctx(org, role="viewer"):
    return ("user-unused", str(org.id), role)


def _today():
    return FROZEN_NOW.date()


# ── 1. shape: N requested → N returned, quiet days are zeros ────────────────


@pytest.mark.asyncio
async def test_seven_buckets_with_zero_filled_quiet_days(session):
    org = await _make_org(session, owner_address=OWNER_A)
    # Volume on today and on D-3 only; the other five days stay quiet.
    # Named by the bucket each one targets, not offset from a moving "now":
    # `now - 1h` is only "today" when the suite runs after 01:00 UTC, which is
    # what used to fail here.
    await _seed(session, owner=OWNER_A, created_at=_at(_today()))
    await _seed(session, owner=OWNER_A, created_at=_at(_today() - timedelta(days=3)))

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert res.days == 7
    assert len(res.buckets) == 7, "seven days requested means seven buckets back"
    # Chronological, contiguous, no gaps.
    dates = [b.date for b in res.buckets]
    assert dates == sorted(dates)
    assert dates[-1] == _today()
    assert dates[0] == _today() - timedelta(days=6)
    for earlier, later in zip(dates, dates[1:]):
        assert (later - earlier).days == 1

    by_date = {b.date: b.volume_usd for b in res.buckets}
    assert by_date[_today()] == 1.0
    assert by_date[_today() - timedelta(days=3)] == 1.0
    # Every quiet day is present AND zero — not absent.
    quiet = [d for d in dates if d not in (_today(), _today() - timedelta(days=3))]
    assert len(quiet) == 5
    assert all(by_date[d] == 0.0 for d in quiet)


@pytest.mark.asyncio
async def test_empty_org_returns_zero_buckets_not_an_error(session):
    """No data is a normal state for this product, not a 404."""
    org = await _make_org(session, owner_address=OWNER_A)

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert res.days == 7
    assert len(res.buckets) == 7
    assert [b.volume_usd for b in res.buckets] == [0.0] * 7


# ── 2. UTC bucket boundaries, asserted rather than assumed ─────────────────


@pytest.mark.asyncio
async def test_utc_boundary_midnight_splits_buckets(session):
    """23:59:59Z belongs to its own day; 00:00:00Z to the next.

    Guards the naive-datetime trap: SQLite can hand back a tz-naive
    `created_at`, and treating that as local time would move a near-midnight
    settlement into the neighbouring bucket.
    """
    org = await _make_org(session, owner_address=OWNER_A)
    day = _today() - timedelta(days=2)

    await _seed(
        session,
        owner=OWNER_A,
        created_at=datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc),
    )
    nxt = day + timedelta(days=1)
    await _seed(
        session,
        owner=OWNER_A,
        created_at=datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0, tzinfo=timezone.utc),
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )
    by_date = {b.date: b.volume_usd for b in res.buckets}

    assert by_date[day] == 1.0, "23:59:59Z must stay in its own UTC day"
    assert by_date[nxt] == 1.0, "00:00:00Z must open the next UTC day"


# ── 3. environment isolation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_environment_never_shows_live_volume(session):
    org = await _make_org(session, owner_address=OWNER_A)
    now = FROZEN_NOW
    await _seed(session, owner=OWNER_A, created_at=now, environment="live")

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert sum(b.volume_usd for b in res.buckets) == 0.0


@pytest.mark.asyncio
async def test_live_environment_never_shows_test_volume(session):
    org = await _make_org(session, owner_address=OWNER_A)
    now = FROZEN_NOW
    await _seed(session, owner=OWNER_A, created_at=now, environment="test")

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="live", db=session
    )

    assert sum(b.volume_usd for b in res.buckets) == 0.0


# ── 4. org isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_isolation_no_leak(session):
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    now = FROZEN_NOW
    await _seed(session, owner=OWNER_A, created_at=now)
    await _seed(session, owner=OWNER_B, created_at=now, recipient="0x" + "f" * 40)
    await _seed(session, owner=OWNER_B, created_at=now, recipient="0x" + "f" * 40)

    a = await get_org_volume_series(
        ctx=_ctx(org_a), days=7, environment="test", db=session
    )
    b = await get_org_volume_series(
        ctx=_ctx(org_b), days=7, environment="test", db=session
    )

    assert sum(x.volume_usd for x in a.buckets) == 1.0
    assert sum(x.volume_usd for x in b.buckets) == 2.0


@pytest.mark.asyncio
async def test_scoped_via_intent_join_not_settlement_merchant(session):
    """The settlement lands on SETTLE_WALLET_A (≠ OWNER_A's primary wallet).

    A `settlement.merchant == owner` filter — the legacy dashboard bug — would
    read zero here. Mirrors test_org_stats_usd.py's equivalent guard.
    """
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(
        session,
        owner=OWNER_A,
        created_at=FROZEN_NOW,
        recipient=SETTLE_WALLET_A,
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert sum(b.volume_usd for b in res.buckets) == 1.0


# ── 5. status rule — matches the volume_24h tile exactly ───────────────────


@pytest.mark.asyncio
async def test_only_final_settlements_count(session):
    """`pending` / `reorged` / `rejected` are money that did not (or no longer)
    settled. Same rule as the volume_24h tile: only `final`."""
    org = await _make_org(session, owner_address=OWNER_A)
    now = FROZEN_NOW
    for st in (
        SettlementStatus.pending,
        SettlementStatus.reorged,
        SettlementStatus.rejected,
    ):
        await _seed(session, owner=OWNER_A, created_at=now, status=st)

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )
    assert sum(b.volume_usd for b in res.buckets) == 0.0

    await _seed(session, owner=OWNER_A, created_at=now, status=SettlementStatus.final)
    res2 = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )
    assert sum(b.volume_usd for b in res2.buckets) == 1.0


@pytest.mark.asyncio
async def test_unpriced_token_is_excluded_and_reported_not_zeroed(session):
    """An unpeggable token must not raise, must not guess, and must not be
    summed as zero. It is left OUT of the total and counted — on the bucket it
    belongs to as well as on the window, because a single quiet-looking bucket
    is exactly where a dropped payment hides."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(
        session,
        owner=OWNER_A,
        created_at=FROZEN_NOW,
        token="0x" + "9" * 40,  # not in the token registry at all
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert len(res.buckets) == 7
    assert sum(b.volume_usd for b in res.buckets) == 0.0
    assert res.unpriced_count == 1
    assert res.buckets[-1].unpriced_count == 1
    assert sum(b.unpriced_count for b in res.buckets) == res.unpriced_count


@pytest.mark.asyncio
async def test_empty_window_is_distinguishable_from_an_unvaluable_one(session):
    """The series counterpart of the stats regression: two orgs, the same flat
    zero line, one of them actually got paid."""
    paid_in_eth = await _make_org(session, owner_address=OWNER_A)
    paid_nothing = await _make_org(session, owner_address=OWNER_B)
    await _seed(
        session,
        owner=OWNER_A,
        created_at=FROZEN_NOW,
        token=NATIVE_ETH,
        amount_base=2 * 10**18,
    )

    eth = await get_org_volume_series(
        ctx=_ctx(paid_in_eth), days=7, environment="test", db=session
    )
    none = await get_org_volume_series(
        ctx=_ctx(paid_nothing), days=7, environment="test", db=session
    )

    assert sum(b.volume_usd for b in eth.buckets) == 0.0
    assert sum(b.volume_usd for b in none.buckets) == 0.0
    assert eth.unpriced_count == 1
    assert none.unpriced_count == 0
    assert all(b.unpriced_count == 0 for b in none.buckets)


@pytest.mark.asyncio
async def test_mixed_window_totals_the_pegged_and_counts_the_rest(session):
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(session, owner=OWNER_A, created_at=FROZEN_NOW)
    await _seed(
        session,
        owner=OWNER_A,
        created_at=FROZEN_NOW,
        token=NATIVE_ETH,
        amount_base=10**18,
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert sum(b.volume_usd for b in res.buckets) == 1.0
    assert res.unpriced_count == 1


@pytest.mark.asyncio
async def test_unpriced_counts_land_in_their_own_bucket(session):
    """Two unvaluable payments on two different days must be attributed to those
    days, not lumped onto one."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(
        session, owner=OWNER_A, created_at=_at(_today()),
        token=NATIVE_ETH, amount_base=10**18,
    )
    await _seed(
        session, owner=OWNER_A, created_at=_at(_today() - timedelta(days=3)),
        token=NATIVE_ETH, amount_base=10**18,
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    by_day = {b.date: b.unpriced_count for b in res.buckets}
    assert by_day[_today()] == 1
    assert by_day[_today() - timedelta(days=3)] == 1
    assert res.unpriced_count == 2
    assert sum(by_day.values()) == 2


# ── 6. days parameter ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_days_parameter_controls_bucket_count(session):
    org = await _make_org(session, owner_address=OWNER_A)

    res = await get_org_volume_series(
        ctx=_ctx(org), days=30, environment="test", db=session
    )

    assert res.days == 30
    assert len(res.buckets) == 30
    assert res.buckets[-1].date == _today()
    assert res.buckets[0].date == _today() - timedelta(days=29)


@pytest.mark.asyncio
async def test_volume_outside_the_window_is_excluded(session):
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(
        session, owner=OWNER_A, created_at=FROZEN_NOW - timedelta(days=10)
    )

    res = await get_org_volume_series(
        ctx=_ctx(org), days=7, environment="test", db=session
    )

    assert sum(b.volume_usd for b in res.buckets) == 0.0


# ── 7. agreement with the tile beside it ───────────────────────────────────


@pytest.mark.asyncio
async def test_series_agrees_with_the_stats_tile(session):
    """The card and the `volume_24h` tile must never disagree about the same money.

    Rather than sharing code (which would mean editing the working stats
    route), this pins the two BEHAVIOURALLY: one settlement landing now is
    inside both the tile's rolling 24h window and today's calendar bucket, so
    any divergence in the join, the env filter, the owner resolution or the
    status rule shows up here as a mismatch.
    """
    from app.api.user_org_stats_routes import get_org_stats

    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(session, owner=OWNER_A, created_at=FROZEN_NOW)
    # An unvaluable payment in the same window: the two surfaces must agree on
    # what they LEFT OUT as well as on what they summed, or the dashboard shows
    # one exclusion notice next to a card that admits nothing.
    await _seed(
        session,
        owner=OWNER_A,
        created_at=FROZEN_NOW,
        token=NATIVE_ETH,
        amount_base=10**18,
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)
    series = await get_org_volume_series(
        ctx=_ctx(org), days=1, environment="test", db=session
    )

    assert stats.volume_24h == 1.0  # guard: the tile actually saw it
    assert series.buckets[-1].volume_usd == stats.volume_24h
    assert stats.volume_24h_unpriced_count == 1  # guard: it saw the ETH leg too
    assert series.unpriced_count == stats.volume_24h_unpriced_count
    assert series.buckets[-1].unpriced_count == stats.volume_24h_unpriced_count


# ── 8. wire shape ──────────────────────────────────────────────────────────


def test_route_is_registered_with_the_right_response_model():
    """Direct-coroutine tests cannot catch a wrong `response_model` — FastAPI
    would silently strip fields on the wire while every assertion above stayed
    green. Same trap flagged in test_org_stats_checklist.py.
    """
    from app.main import app
    from app.models.dashboard_schemas import VolumeSeriesResponse

    routes = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/api/v1/user/org/stats/volume-series"
    ]
    assert len(routes) == 1, "route missing or registered twice"
    assert "GET" in routes[0].methods
    assert routes[0].response_model is VolumeSeriesResponse


def test_openapi_exposes_days_buckets_and_the_exclusion_on_the_wire():
    from app.main import app

    schema = app.openapi()
    path = schema["paths"]["/api/v1/user/org/stats/volume-series"]["get"]
    ref = path["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    model = schema["components"]["schemas"][ref.split("/")[-1]]

    # `unpriced_count` is part of the contract at BOTH levels, not an internal
    # detail: without it on the wire a flat chart cannot say why it is flat,
    # and the client would be back to rendering a silent zero.
    assert set(model["properties"]) == {"days", "buckets", "unpriced_count"}
    bucket_ref = model["properties"]["buckets"]["items"]["$ref"]
    bucket = schema["components"]["schemas"][bucket_ref.split("/")[-1]]
    assert set(bucket["properties"]) == {"date", "volume_usd", "unpriced_count"}
    # A bare UTC calendar date, not a datetime — the client must not have to
    # guess an offset to place the point.
    assert bucket["properties"]["date"]["format"] == "date"
