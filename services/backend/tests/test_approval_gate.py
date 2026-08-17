"""Org approval gate — environment-scoped, fail-closed where money is real.

Since 2026-08-08 the gate is KYB-self-service: a SUBMITTED COMPANY PROFILE
opens the sandbox, with no operator in the loop. Real approval is still
required for `live`. The policy is single-sourced in
`app/api/deps/approval_policy.py`; these tests pin it at every surface.

Four layers, mirroring test_company_submitted_gate.py:
1. The policy itself: what "approved enough" means per environment.
2. Dep behavior (`require_org_approved`): pending -> PASSES on the sandbox
   default, declined -> 403 approval_declined (+reason), approved -> ctx
   passthrough, anything unknown -> still denied. The company-submitted gate
   stays chained FIRST (a pre-KYB org gets company_profile_required).
3. Wiring introspection on the REAL app: every operational session route is
   gated; onboarding/org-management routes are NOT (a pre-KYB merchant must
   be able to reach and complete KYB).
4. Merchant API-key surface (`require_approved_merchant`, router-level dep):
   the key's owner address is resolved to its org (primary user_wallet, else
   settlement_wallet); a `test` key passes while pending, a `live` key does
   not. Unresolvable owner -> deny in BOTH environments (that is tenant
   safety, not approval, and it never relaxed).
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Membership, Organization


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


async def _make_org(
    session,
    *,
    approval_status: str,
    onboarding_status: str = "company_submitted",
    decline_reason: str | None = None,
    wallet: str | None = None,
    settlement_wallet: str | None = None,
):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=True,
        plan="free",
        onboarding_status=onboarding_status,
        approval_status=approval_status,
        decline_reason=decline_reason,
        settlement_wallet=settlement_wallet,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if wallet is not None:
        from app.models.user_wallets_models import UserWallet

        session.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=wallet,
                display_address=wallet,
                verified_chain_id=84532,
                is_primary=True,
                chain_family="evm",
            )
        )
    await session.commit()
    return user, org


# ── 1. The policy itself ──────────────────────────────────────────


def test_policy_sandbox_lets_pending_through_but_live_does_not():
    """The whole point of the 2026-08-08 change, in one assertion pair."""
    from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial

    assert approval_denial("pending_approval", environment=SANDBOX_ENVIRONMENT) is None
    denial = approval_denial("pending_approval", environment="live")
    assert denial is not None and denial.detail["code"] == "approval_pending"


def test_policy_declined_blocks_in_every_environment():
    from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial

    for env in (SANDBOX_ENVIRONMENT, "live"):
        denial = approval_denial("declined", environment=env, decline_reason="nope")
        assert denial is not None, f"declined must block on {env}"
        assert denial.detail["code"] == "approval_declined"
        assert denial.detail["reason"] == "nope"


def test_policy_unknown_status_fails_closed_even_on_the_sandbox():
    """Sandbox access is an allowlist. A future `suspended` must not sneak in."""
    from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial

    for env in (SANDBOX_ENVIRONMENT, "live"):
        for status in ("bogus_state", None, "suspended"):
            denial = approval_denial(status, environment=env)
            assert denial is not None, f"{status!r} must be denied on {env}"
            assert denial.detail["code"] == "approval_pending"


def test_policy_approved_passes_everywhere():
    from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial

    assert approval_denial("approved", environment=SANDBOX_ENVIRONMENT) is None
    assert approval_denial("approved", environment="live") is None


# ── 2. Session dep behavior ───────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_org_reaches_the_sandbox(session):
    """A submitted profile is enough: no operator has to act for testnet."""
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(session, approval_status="pending_approval")
    dep = require_org_approved("viewer")

    ctx = ("u", str(org.id), "viewer")
    assert await dep(ctx=ctx, db=session) == ctx


@pytest.mark.asyncio
async def test_pending_org_still_denied_on_a_live_surface(session):
    """The strict rule is one keyword away for the future /app env toggle."""
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(session, approval_status="pending_approval")
    dep = require_org_approved("viewer", environment="live")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"


@pytest.mark.asyncio
async def test_declined_org_gets_approval_declined_with_reason(session):
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(
        session, approval_status="declined", decline_reason="prohibited category"
    )
    dep = require_org_approved("viewer")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_declined"
    assert exc.value.detail["reason"] == "prohibited category"


@pytest.mark.asyncio
async def test_approved_org_passes_ctx_through(session):
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(session, approval_status="approved")
    dep = require_org_approved("operator")

    ctx = ("u", str(org.id), "operator")
    assert await dep(ctx=ctx, db=session) == ctx


@pytest.mark.asyncio
async def test_unknown_status_fails_closed(session):
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(session, approval_status="bogus_state")
    dep = require_org_approved("viewer")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"


@pytest.mark.asyncio
async def test_company_gate_still_blocks_a_pre_kyb_org(session):
    """The KYB gate did NOT relax: it is now the only thing between signup and
    the sandbox, so it had better still fire."""
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(
        session, approval_status="pending_approval", onboarding_status="created"
    )
    dep = require_org_approved("viewer")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "company_profile_required"


# ── 3. Wiring on the real app ─────────────────────────────────────

GATED = [
    ("GET", "/api/v1/user/org/payment-intents"),
    ("POST", "/api/v1/user/org/payment-intents"),
    ("POST", "/api/v1/user/org/payment-intents/{intent_id}/cancel"),
    ("GET", "/api/v1/user/org/webhooks"),
    ("GET", "/api/v1/user/org/webhooks/{webhook_id}/deliveries"),
    ("POST", "/api/v1/user/org/webhooks"),
    ("POST", "/api/v1/user/org/webhooks/{webhook_id}/test"),
    ("GET", "/api/v1/user/org/stats"),
    ("GET", "/api/v1/user/api-keys"),
    ("POST", "/api/v1/user/api-keys"),
    ("PATCH", "/api/v1/user/api-keys/{key_id}"),
    ("DELETE", "/api/v1/user/api-keys/{key_id}"),
    ("GET", "/api/v1/user/wallets"),
    ("POST", "/api/v1/user/wallets/challenge"),
    ("POST", "/api/v1/user/wallets/verify"),
]

OPEN = [
    ("GET", "/api/v1/user/onboarding"),
    ("POST", "/api/v1/user/consents"),
    ("GET", "/api/v1/user/org/company-profile"),
    ("PATCH", "/api/v1/user/org/company-profile"),
    ("POST", "/api/v1/user/org/company-profile/submit"),
    ("GET", "/api/v1/organizations"),
    ("POST", "/api/v1/organizations"),
    ("POST", "/api/v1/organizations/switch"),
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


@pytest.mark.parametrize("method,path", GATED)
def test_operational_routes_require_approval(method, path):
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert any("require_org_approved" in n for n in names), (
        f"{method} {path} is NOT gated by require_org_approved: {names}"
    )


@pytest.mark.parametrize("method,path", OPEN)
def test_onboarding_routes_stay_reachable_while_pending(method, path):
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert not any("require_org_approved" in n for n in names), (
        f"{method} {path} must stay reachable pre-approval"
    )


# ── 4. Merchant API-key surface ───────────────────────────────────

OWNER = "0x" + "d" * 40


def _fake_request(owner: str = OWNER, environment: str = "test"):
    return SimpleNamespace(
        state=SimpleNamespace(client={"client_id": owner, "environment": environment})
    )


@pytest.mark.asyncio
async def test_test_key_of_pending_org_passes(session):
    """The sandbox key a self-serve merchant just minted has to work."""
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="pending_approval", wallet=OWNER)
    await require_approved_merchant(request=_fake_request(), db=session)  # no raise


@pytest.mark.asyncio
async def test_live_key_of_pending_org_denied(session):
    """Real money still needs a real approval."""
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="pending_approval", wallet=OWNER)

    with pytest.raises(HTTPException) as exc:
        await require_approved_merchant(
            request=_fake_request(environment="live"), db=session
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"


@pytest.mark.asyncio
async def test_key_without_environment_gets_the_strict_rule(session):
    """An unstamped key must never fall into the sandbox carve-out."""
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="pending_approval", wallet=OWNER)
    request = SimpleNamespace(state=SimpleNamespace(client={"client_id": OWNER}))

    with pytest.raises(HTTPException) as exc:
        await require_approved_merchant(request=request, db=session)
    assert exc.value.detail["code"] == "approval_pending"


@pytest.mark.asyncio
async def test_declined_org_denied_on_test_and_live(session):
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(
        session, approval_status="declined", decline_reason="prohibited", wallet=OWNER
    )

    for env in ("test", "live"):
        with pytest.raises(HTTPException) as exc:
            await require_approved_merchant(
                request=_fake_request(environment=env), db=session
            )
        assert exc.value.detail["code"] == "approval_declined", env
        assert exc.value.detail["reason"] == "prohibited"


@pytest.mark.asyncio
async def test_api_key_of_approved_org_via_wallet_passes(session):
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="approved", wallet=OWNER)
    await require_approved_merchant(request=_fake_request(), db=session)  # no raise


@pytest.mark.asyncio
async def test_api_key_of_approved_org_via_settlement_wallet_passes(session):
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="approved", settlement_wallet=OWNER.lower())
    await require_approved_merchant(request=_fake_request(), db=session)  # no raise


@pytest.mark.asyncio
async def test_api_key_with_unresolvable_owner_fails_closed(session):
    from app.api.deps.require_approved_merchant import require_approved_merchant

    with pytest.raises(HTTPException) as exc:
        await require_approved_merchant(request=_fake_request("0x" + "e" * 40), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"


# ── 5. The mint route cannot leak a live key to an unapproved org ──


def test_sandbox_mint_pin_and_guard_agree():
    """The session mint is pinned to `test`, which is why `require_org_approved`'s
    sandbox rule is the correct gate for it. If someone lifts the pin, the
    handler's own guard (create_merchant_key) must re-assert real approval —
    this test exists so lifting the pin without that guard is a loud failure."""
    import inspect

    from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT
    from app.api import user_org_merchant_keys_routes as mod

    assert mod.ENVIRONMENT == SANDBOX_ENVIRONMENT, (
        "the mint route is no longer pinned to the sandbox environment — the "
        "guard in create_merchant_key is now load-bearing; verify it, then "
        "update this test"
    )
    source = inspect.getsource(mod.create_merchant_key)
    assert "approval_denial" in source and "SANDBOX_ENVIRONMENT" in source, (
        "create_merchant_key lost its non-sandbox approval guard"
    )


@pytest.mark.asyncio
async def test_pending_org_can_mint_a_sandbox_key(session):
    """End of the funnel: KYB submitted, no operator, working key."""
    from app.api.user_org_merchant_keys_routes import create_merchant_key
    from app.api.user_org_merchant_keys_routes import MerchantKeyCreateRequest

    _u, org = await _make_org(
        session, approval_status="pending_approval", settlement_wallet=OWNER.lower()
    )
    request = SimpleNamespace(client=None, headers={})

    resp = await create_merchant_key(
        payload=MerchantKeyCreateRequest(label="quickstart"),
        request=request,
        ctx=("u", str(org.id), "admin"),
        db=session,
    )
    assert resp.key.startswith("rsend_test_")
    assert resp.environment == "test"
    assert resp.scope == "write"


def test_every_merchant_route_carries_the_approval_dep():
    """Every route of the API-KEY merchant router is gated. (The JWT-authed
    /api/v1/merchant/profile + /invoices routers are a separate, pre-existing
    session surface — unreachable in prod without RSEND_DEV_AUTH_BYPASS,
    documented in CLAUDE.md — and are not part of this gate.)"""
    from app.api.merchant_routes import merchant_router
    from app.main import app
    from fastapi.routing import APIRoute

    key_router_paths = {
        r.path for r in merchant_router.routes if isinstance(r, APIRoute)
    }
    assert key_router_paths, "merchant router routes not found"
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in key_router_paths:
            names = _route_dep_names(app, next(iter(route.methods)), route.path)
            assert any("require_approved_merchant" in n for n in names), (
                f"{route.path} lacks require_approved_merchant"
            )
