"""The keeper's work-list endpoint, and the secret that is its only auth.

`/api/internal/keeper/source-wallets` is a deliberately CROSS-TENANT read: the
keeper serves every org, so there is no org to scope by and the shared secret is
the entire security story. Three things therefore get pinned here rather than
left to review:

  1. the gate lives on the ROUTER, not on one handler, so a second endpoint
     added under this prefix later cannot be added ungated;
  2. the path is exempt from API-KEY auth — which is not the same as
     unauthenticated. `api_auth.py` consults `is_exempt` before anything else
     and is deny-by-default on every method, so a NON-exempt path 401s in the
     middleware and the route dependency never runs at all. `/admin/approvals`
     is the existing precedent: exempt, gated by `require_admin` on its router;
  3. the two dead sibling prefixes (`/api/internal/signing`, `/oracle`) are
     gone. `is_exempt` is a bare `startswith` over an unordered set with no
     boundary check, so an exempt prefix with no route behind it is a loaded
     gun: mount anything under it and it is unauthenticated.

Handlers are called directly (the suite's idiom — no TestClient), so the gate
is NOT exercised by the data tests. That is exactly why the wiring is pinned
statically by walking `app.routes[].dependant`.
"""

import os
import secrets
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Membership, Organization

# Registers source_wallets in Base.metadata BEFORE the autouse create_all —
# same ordering hazard as test_source_wallets.py. Side effect only.
import app.models.source_wallet_models  # noqa: F401,E402
from app.models.source_wallet_models import SourceWallet

ADDR = "0x" + "a" * 40
ADDR_2 = "0x" + "b" * 40
AUTOSPLIT_ADDR = "0x" + "5" * 40
USDC_ADDR = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # base_sepolia registry
CHAIN = "base_sepolia"
KEEPER_PATH = "/api/internal/keeper/source-wallets"
SECRET = "k" * 48


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """create_all + FK-ordered ROW wipe — no drop_all (shared-PG gotcha)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in (
            SourceWallet.__table__,
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


async def _add_wallet(
    session,
    org_id,
    *,
    address=ADDR,
    chain=CHAIN,
    token_symbol="USDC",
    environment="test",
    disabled=False,
):
    row = SourceWallet(
        org_id=org_id,
        chain=chain,
        environment=environment,
        address=address,
        display_address=address,
        token_symbol=token_symbol,
        label="",
        disabled_at=datetime.now(timezone.utc) if disabled else None,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
def open_autosplit(monkeypatch):
    """The AutoSplit gate is fail-closed; open it so rows resolve."""
    import app.api.internal_keeper_routes as ikr

    monkeypatch.setattr(ikr, "auto_split_address_for", lambda chain: AUTOSPLIT_ADDR)


async def _list(session, *, environment="test"):
    from app.api.internal_keeper_routes import list_keeper_source_wallets

    return await list_keeper_source_wallets(environment=environment, db=session)


# ═══════════════════════════════════════════════════════════════
#  The secret gate
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_wrong_secret_is_403():
    from app.api.deps.require_internal_secret import require_internal_secret

    with patch.dict(os.environ, {"INTERNAL_PROXY_SECRET": SECRET}, clear=False):
        from app.config import get_settings

        get_settings.cache_clear()
        with pytest.raises(HTTPException) as exc:
            await require_internal_secret("not-the-secret")
        assert exc.value.status_code == 403
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_correct_secret_passes():
    from app.api.deps.require_internal_secret import require_internal_secret

    with patch.dict(os.environ, {"INTERNAL_PROXY_SECRET": SECRET}, clear=False):
        from app.config import get_settings

        get_settings.cache_clear()
        assert await require_internal_secret(SECRET) is None
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unconfigured_secret_denies_and_an_empty_header_cannot_match_it():
    """An empty configured secret must not be matchable by an empty presented
    one — `compare_digest("", "")` is True, so the emptiness check has to come
    FIRST. The deleted `internal_auth.py` also had a `settings.debug` early
    return; it does not come back, so this denies in every posture."""
    from app.api.deps.require_internal_secret import require_internal_secret

    with patch.dict(os.environ, {"INTERNAL_PROXY_SECRET": ""}, clear=False):
        from app.config import get_settings

        get_settings.cache_clear()
        for presented in ("", "anything"):
            with pytest.raises(HTTPException) as exc:
                await require_internal_secret(presented)
            assert exc.value.status_code == 503
        get_settings.cache_clear()


# ═══════════════════════════════════════════════════════════════
#  The work list
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_disabled_wallets_are_absent(session, open_autosplit):
    """`disabled_at` is the merchant's pause switch — a paused wallet must not
    reach the keeper at all. Note the SESSION list route deliberately returns
    disabled rows (the UI shows them); this one must not."""
    _u, org = await _make_org(session)
    await _add_wallet(session, org, address=ADDR)
    await _add_wallet(session, org, address=ADDR_2, disabled=True)

    resp = await _list(session)

    assert [w.address for w in resp.wallets] == [ADDR]


@pytest.mark.asyncio
async def test_environment_scoped(session, open_autosplit):
    _u, org = await _make_org(session)
    await _add_wallet(session, org, address=ADDR, environment="test")
    await _add_wallet(session, org, address=ADDR_2, environment="live")

    assert [w.address for w in (await _list(session, environment="test")).wallets] == [ADDR]
    assert [w.address for w in (await _list(session, environment="live")).wallets] == [ADDR_2]


@pytest.mark.asyncio
async def test_cross_tenant_by_design(session, open_autosplit):
    """The keeper serves every org — this read is deliberately NOT org-scoped,
    which is why the shared secret is the whole security story."""
    _u1, org1 = await _make_org(session)
    _u2, org2 = await _make_org(session)
    await _add_wallet(session, org1, address=ADDR)
    await _add_wallet(session, org2, address=ADDR_2)

    resp = await _list(session)

    assert {w.address for w in resp.wallets} == {ADDR, ADDR_2}
    assert {w.org_id for w in resp.wallets} == {org1, org2}


@pytest.mark.asyncio
async def test_resolves_everything_the_keeper_cannot_derive(session, open_autosplit):
    """The row carries neither the token address nor the AutoSplit address —
    both are re-resolved server-side at each use site. If the keeper had to
    resolve them it would need the registry and the config, i.e. it would need
    to be the backend."""
    _u, org = await _make_org(session)
    await _add_wallet(session, org, address=ADDR)

    w = (await _list(session)).wallets[0]

    assert w.chain == CHAIN
    assert w.chain_id == 84532
    assert w.token_symbol == "USDC"
    assert w.token_address.lower() == USDC_ADDR.lower()
    assert w.token_decimals == 6
    assert w.auto_split == AUTOSPLIT_ADDR


@pytest.mark.asyncio
async def test_unresolvable_autosplit_is_omitted_not_nulled(session, monkeypatch):
    """`auto_split_address_for` is fail-closed and returns None five different
    ways. A wallet the keeper cannot act on is left OUT of the work list — a
    row with a null contract address is an invitation to send to nowhere."""
    import app.api.internal_keeper_routes as ikr

    monkeypatch.setattr(ikr, "auto_split_address_for", lambda chain: None)
    _u, org = await _make_org(session)
    await _add_wallet(session, org, address=ADDR)

    assert (await _list(session)).wallets == []


@pytest.mark.asyncio
async def test_response_is_an_allowlist_not_the_orm_row(session, open_autosplit):
    """A future column must not leak into an unauthenticated-by-API-key surface
    just by existing."""
    _u, org = await _make_org(session)
    await _add_wallet(session, org, address=ADDR)

    w = (await _list(session)).wallets[0]

    assert set(w.model_dump().keys()) == {
        "id",
        "org_id",
        "chain",
        "chain_id",
        "address",
        "token_symbol",
        "token_address",
        "token_decimals",
        "auto_split",
    }


# ═══════════════════════════════════════════════════════════════
#  Wiring — the part the direct-call tests above cannot reach
# ═══════════════════════════════════════════════════════════════


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


def test_the_keeper_route_carries_the_secret_gate():
    """On the ROUTER, so a second endpoint under this prefix inherits it."""
    from app.main import app

    names = _route_dep_names(app, "GET", KEEPER_PATH)
    assert any("require_internal_secret" in n for n in names), (
        f"{KEEPER_PATH} is NOT gated by require_internal_secret: {names}"
    )


def test_keeper_path_is_exempt_from_api_key_auth():
    """Exempt from API-KEY auth, NOT unauthenticated — the router dependency
    above is the real gate. Without this the middleware 401s first and that
    dependency never runs."""
    from app.security.api_keys import is_exempt

    assert is_exempt(KEEPER_PATH) is True


def test_the_dead_internal_prefixes_are_gone():
    """Both routes were deleted; the exempt prefixes outlived them. `is_exempt`
    is a bare startswith, so anything ever mounted under either would have been
    exempt from API-key auth with nothing behind it."""
    from app.security.api_keys import EXEMPT_PATHS, is_exempt

    assert "/api/internal/signing" not in EXEMPT_PATHS
    assert "/api/internal/oracle" not in EXEMPT_PATHS
    assert is_exempt("/api/internal/signing/anything") is False
    assert is_exempt("/api/internal/oracle") is False


def test_keeper_endpoint_has_its_own_rate_limit_rule():
    """CLAUDE.md: every new endpoint gets an ENDPOINT_LIMITS entry. Per-IP
    deliberately — no rsend_ key exists, so "api_key" would silently degrade to
    the IP bucket anyway (`api_key_id or client_ip`)."""
    from app.middleware.rate_limit import _match_endpoint

    rule = _match_endpoint("GET", KEEPER_PATH)
    assert rule is not None, "no ENDPOINT_LIMITS entry — falls back to DEFAULT_GET_LIMIT"
    _max_req, _window, key_type = rule
    assert key_type == "ip"
