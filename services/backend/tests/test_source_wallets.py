"""The /api/v1/user/org/source-wallets surface — RED-first pins (Pair A).

A source wallet is the merchant wallet RSendsAutoSplit empties: the row is
the org<->wallet linkage plus the keeper's watch scope (chain + token) — the
policy itself (recipients/bps/minAmount) lives ON CHAIN and is never
mirrored. Registration is SIWE challenge/verify (Pair A: only the wallet's
key-holder can register — the merchant necessarily holds it, having to sign
setPolicy/approve on chain anyway), which is what makes the uniqueness index
GLOBAL-active safe: `uq_source_wallets_active` UNIQUE (chain_id, address,
token_symbol) WHERE disabled_at IS NULL, cross-org.

Pins here: registration row shape (org_id tenant key, lowercase address,
checksummed display, environment stamped from chain), global-active
uniqueness with disable->re-register (fresh-row semantics), org isolation in
the SQL (cross-tenant disable -> 404, never 403), env scoping, the per-org
cap, require_org_approved wiring on every route (the GATED-list pattern from
test_approval_gate.py), and the ENDPOINT_LIMITS entries via _match_endpoint
(the test_rate_limit_matching discipline — first-startswith-wins, so the
subpath rows must sit ABOVE the bare GET).

Imports of the not-yet-built modules happen INSIDE fixtures/tests so each
test fails RED with its own ModuleNotFoundError; the wiring and rate-limit
pins import existing modules and fail RED on assertions. SIWE is stubbed on
the route module (suite idiom), never signed.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Membership, Organization

ADDR = "0x" + "a" * 40
ADDR_2 = "0x" + "b" * 40
ADDR_3 = "0x" + "c" * 40
# EIP-55 checksum of ADDR ("0xaaa...a" checksums to mixed case) is computed
# by the implementation; tests only assert lower/display consistency.
AUTOSPLIT_ADDR = "0x" + "5" * 40
CHAIN = "base_sepolia"
BASE_PREFIX = "/api/v1/user/org/source-wallets"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """create_all + FK-ordered ROW wipe — no drop_all (shared-PG gotcha)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in (
            Membership.__table__,
            Organization.__table__,
            User.__table__,
        ):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_org(session):
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
    await session.commit()
    return str(user.id), str(org.id)


@pytest.fixture
def stub_siwe(monkeypatch):
    import app.api.source_wallet_routes as swr

    async def _ok(**kwargs):
        return "siwe-message"

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(swr, "verify_challenge", _ok)
    monkeypatch.setattr(swr, "record_auth_event", _noop)


@pytest.fixture
def open_autosplit(monkeypatch):
    """Every row-creating test needs the fail-closed AutoSplit gate open."""
    import app.services.source_wallet_service as svc

    monkeypatch.setattr(svc, "auto_split_address_for", lambda chain: AUTOSPLIT_ADDR)


async def _verify(session, ctx, *, address=ADDR, chain=CHAIN, token_symbol="USDC"):
    from app.api.source_wallet_routes import post_verify
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    return await post_verify(
        payload=SourceWalletVerifyRequest(
            chain=chain,
            token_symbol=token_symbol,
            address=address,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        ),
        ctx=ctx,
        db=session,
    )


async def _list(session, ctx, *, environment="test"):
    from app.api.source_wallet_routes import list_source_wallets

    return await list_source_wallets(ctx=ctx, environment=environment, db=session)


async def _disable(session, ctx, source_wallet_id):
    from app.api.source_wallet_routes import post_disable

    return await post_disable(
        source_wallet_id=source_wallet_id, ctx=ctx, db=session
    )


async def _rows(session):
    from app.models.source_wallet_models import SourceWallet

    return (await session.execute(select(SourceWallet))).scalars().all()


# ── Registration row shape ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_creates_row_with_org_tenancy_and_env(
    session, stub_siwe, open_autosplit
):
    """Happy path: the row is org_id-keyed (NEVER owner_address — the org_id
    re-key lesson), address stored lowercase with a checksummed display twin,
    environment stamped server-side from the chain (base_sepolia -> test)."""
    user_id, org_id = await _make_org(session)
    checksummed = "0x" + "Aa" * 20  # mixed-case wire form of ADDR

    await _verify(session, (user_id, org_id, "admin"), address=checksummed)

    rows = await _rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert str(row.org_id) == org_id
    assert row.address == ADDR  # lowercased at rest
    assert row.display_address.lower() == ADDR  # checksum twin, same wallet
    assert row.display_address != ADDR  # and actually checksummed, not copied
    assert row.environment == "test"
    assert row.token_symbol == "USDC"
    assert row.chain_id == 84532
    assert row.disabled_at is None


# ── Global-active uniqueness (safe only because registration is SIWE) ─────


@pytest.mark.asyncio
async def test_second_org_same_tuple_409_then_free_after_disable(
    session, stub_siwe, open_autosplit
):
    """GLOBAL-active unique on (chain_id, address, token_symbol): a second
    org registering the same tuple gets 409 source_wallet_taken; after the
    holder disables, the tuple is registrable again (the partial
    `WHERE disabled_at IS NULL` predicate doing its job — fresh-row
    re-enable semantics, decision 4)."""
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)

    resp_a = await _verify(session, (user_a, org_a, "admin"))
    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_b, org_b, "admin"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "source_wallet_taken"

    await _disable(session, (user_a, org_a, "admin"), resp_a.id)
    await _verify(session, (user_b, org_b, "admin"))  # now succeeds

    rows = await _rows(session)
    active = [r for r in rows if r.disabled_at is None]
    assert len(active) == 1 and str(active[0].org_id) == org_b


@pytest.mark.asyncio
async def test_same_wallet_different_token_is_a_separate_registration(
    session, stub_siwe, open_autosplit
):
    """The uniqueness key mirrors the contract's (merchant, token) policy
    key: same wallet + different token is a distinct, legal row."""
    user_id, org_id = await _make_org(session)
    await _verify(session, (user_id, org_id, "admin"), token_symbol="USDC")
    await _verify(session, (user_id, org_id, "admin"), token_symbol="ETH")
    assert len(await _rows(session)) == 2


# ── Org isolation + environment scoping (in the SQL, 404 not 403) ─────────


@pytest.mark.asyncio
async def test_list_is_org_isolated_and_env_scoped(session, stub_siwe, open_autosplit):
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    await _verify(session, (user_a, org_a, "admin"))

    listed_b = await _list(session, (user_b, org_b, "viewer"))
    assert listed_b.source_wallets == []

    listed_a_live = await _list(session, (user_a, org_a, "viewer"), environment="live")
    assert listed_a_live.source_wallets == []

    listed_a = await _list(session, (user_a, org_a, "viewer"))
    assert len(listed_a.source_wallets) == 1
    assert listed_a.source_wallets[0].address == ADDR


@pytest.mark.asyncio
async def test_disable_cross_tenant_404_and_idempotent(
    session, stub_siwe, open_autosplit
):
    """Tenant scope (id, org_id) IN the query: another org disabling my row
    gets 404 (existence never leaks as 403). Repeat disable by the owner is
    idempotent, and the row count never changes."""
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    resp = await _verify(session, (user_a, org_a, "admin"))

    with pytest.raises(HTTPException) as exc:
        await _disable(session, (user_b, org_b, "admin"), resp.id)
    assert exc.value.status_code == 404

    await _disable(session, (user_a, org_a, "admin"), resp.id)
    await _disable(session, (user_a, org_a, "admin"), resp.id)  # idempotent

    rows = await _rows(session)
    assert len(rows) == 1
    assert rows[0].disabled_at is not None


# ── Per-org cap (bounds keeper gas exposure) ──────────────────────────────


@pytest.mark.asyncio
async def test_cap_reached_409(session, stub_siwe, open_autosplit, monkeypatch):
    """MAX_SOURCE_WALLETS_PER_ORG counts ACTIVE rows only. Pinned via a
    monkeypatched cap of 2 on the route module (the MAX_WALLETS_PER_ORG
    import style of user_wallets_routes)."""
    import app.api.source_wallet_routes as swr

    monkeypatch.setattr(swr, "MAX_SOURCE_WALLETS_PER_ORG", 2)
    user_id, org_id = await _make_org(session)
    await _verify(session, (user_id, org_id, "admin"), address=ADDR)
    await _verify(session, (user_id, org_id, "admin"), address=ADDR_2)

    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_id, org_id, "admin"), address=ADDR_3)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "max_source_wallets_reached"
    assert len(await _rows(session)) == 2


# ── Route wiring: every route gated by require_org_approved ───────────────

SOURCE_WALLET_ROUTES = [
    ("GET", BASE_PREFIX),
    ("POST", BASE_PREFIX + "/challenge"),
    ("POST", BASE_PREFIX + "/verify"),
    ("POST", BASE_PREFIX + "/{source_wallet_id}/disable"),
    ("GET", BASE_PREFIX + "/{source_wallet_id}/onchain"),
]


def _route_dep_names(app, method: str, path: str) -> set[str]:
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            names = set()

            def _walk(dependant):
                for sub in dependant.dependencies:
                    if sub.call is not None:
                        names.add(getattr(sub.call, "__qualname__", ""))
                    _walk(sub)

            _walk(route.dependant)
            return names
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.parametrize("method,path", SOURCE_WALLET_ROUTES)
def test_source_wallet_routes_wired_and_approval_gated(method, path):
    """The five routes exist under the JWT-exempt /api/v1/user/ prefix and
    every one carries require_org_approved (the operational-route dep) —
    the GATED-list discipline of test_approval_gate.py."""
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert any("require_org_approved" in n for n in names), (
        f"{method} {path} is NOT gated by require_org_approved: {names}"
    )


# ── Rate limits: behavioral pins through _match_endpoint ──────────────────


def test_rate_limit_subpath_writes_matched():
    """POST subpath rule (10/60 ip) covers challenge/verify/disable and must
    sit ABOVE the bare GET row — _match_endpoint is first-startswith-wins,
    so misordering silently turns the stricter rule into dead code."""
    from app.middleware.rate_limit import _match_endpoint

    assert _match_endpoint("POST", BASE_PREFIX + "/challenge") == (10, 60, "ip")
    assert _match_endpoint("POST", BASE_PREFIX + "/verify") == (10, 60, "ip")
    assert _match_endpoint("POST", BASE_PREFIX + "/some-id/disable") == (10, 60, "ip")


def test_rate_limit_bare_get_matched():
    from app.middleware.rate_limit import _match_endpoint

    assert _match_endpoint("GET", BASE_PREFIX) == (120, 60, "ip")
