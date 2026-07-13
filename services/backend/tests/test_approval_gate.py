"""Org approval gate — fail-closed on every merchant-scoped surface.

Three layers, mirroring test_company_submitted_gate.py:
1. Dep behavior (`require_org_approved`): pending -> 403 approval_pending,
   declined -> 403 approval_declined (+reason), approved -> ctx passthrough,
   anything unknown -> deny. The company-submitted gate stays chained FIRST
   (a pre-KYB org gets company_profile_required, not approval_pending).
2. Wiring introspection on the REAL app: every operational session route is
   gated; onboarding/org-management routes are NOT (a pending merchant must
   be able to reach and complete KYB).
3. Merchant API-key surface (`require_approved_merchant`, router-level dep):
   the key's owner address is resolved to its org (primary user_wallet, else
   settlement_wallet) and that org must be approved; unresolvable -> deny
   (fail closed; every real org was backfilled 'approved' by 0010).
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


# ── 1. Session dep behavior ───────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_org_gets_approval_pending(session):
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(session, approval_status="pending_approval")
    dep = require_org_approved("viewer")

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
async def test_company_gate_fires_before_approval_gate(session):
    """A pre-KYB org is told to finish the profile, not that it's pending."""
    from app.api.deps.require_org_approved import require_org_approved

    _u, org = await _make_org(
        session, approval_status="pending_approval", onboarding_status="created"
    )
    dep = require_org_approved("viewer")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.detail["code"] == "company_profile_required"


# ── 2. Wiring on the real app ─────────────────────────────────────

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


# ── 3. Merchant API-key surface ───────────────────────────────────

OWNER = "0x" + "d" * 40


def _fake_request(owner: str = OWNER):
    return SimpleNamespace(
        state=SimpleNamespace(client={"client_id": owner, "environment": "test"})
    )


@pytest.mark.asyncio
async def test_api_key_of_pending_org_denied(session):
    from app.api.deps.require_approved_merchant import require_approved_merchant

    await _make_org(session, approval_status="pending_approval", wallet=OWNER)

    with pytest.raises(HTTPException) as exc:
        await require_approved_merchant(request=_fake_request(), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"


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
