"""require_org_approved gate — behavior, wiring, and the inline
settlement-wallet / chain guards.

Three layers:
1. Dep behavior: pre-submit org -> 403 {"code": "company_profile_required"};
   submitted org -> passes the (user_id, org_id, role) ctx through unchanged.
2. Wiring introspection on the REAL app: every operational session route
   (payments, webhooks, stats, api-keys, wallets) resolves through the gated
   dependency; onboarding/org-management routes must NOT be gated (they are
   how a merchant gets THROUGH onboarding).
3. Inline gates: PATCH /organizations/{id} blocks only the settlement_wallet
   write pre-submit (rename stays allowed); the session intent-create handler
   consults the central chain guard (mainnet chain -> 403 even for a
   submitted org, since activation_status never becomes 'active' in-app).
"""

import secrets
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


async def _make_org(session, *, onboarding_status, role="admin", with_wallet=False):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
        email_verified=True,
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
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role=role))
    if with_wallet:
        from app.models.user_wallets_models import UserWallet

        address = "0x" + secrets.token_hex(20)
        org.settlement_wallet = address
        session.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=address,
                display_address=address,
                verified_chain_id=84532,
                is_primary=True,
                chain_family="evm",
            )
        )
    await session.commit()
    return user, org


# ── 1. Dep behavior ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["created", "email_verified"])
async def test_gate_denies_before_submission(session, status):
    from app.api.deps.require_org_approved import require_org_approved

    _user, org = await _make_org(session, onboarding_status=status)
    dep = require_org_approved("viewer")

    with pytest.raises(HTTPException) as exc:
        await dep(ctx=("u", str(org.id), "viewer"), db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "company_profile_required"


@pytest.mark.asyncio
async def test_gate_passes_ctx_through_after_submission(session):
    from app.api.deps.require_org_approved import require_org_approved

    _user, org = await _make_org(session, onboarding_status="company_submitted")
    dep = require_org_approved("operator")

    ctx = ("u", str(org.id), "operator")
    assert await dep(ctx=ctx, db=session) == ctx


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
def test_operational_routes_are_gated(method, path):
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert any("require_org_approved" in n for n in names), (
        f"{method} {path} is NOT gated by require_org_approved: {names}"
    )


@pytest.mark.parametrize("method,path", OPEN)
def test_onboarding_and_org_management_routes_stay_open(method, path):
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert not any("require_org_approved" in n for n in names), (
        f"{method} {path} must stay reachable during onboarding"
    )


# ── 3a. Inline settlement-wallet gate on PATCH /organizations/{id} ─

@pytest.mark.asyncio
async def test_settlement_wallet_write_blocked_pre_submit(session):
    from app.api.organizations_routes import update_org
    from app.models.org_schemas import OrganizationPatchRequest

    user, org = await _make_org(session, onboarding_status="email_verified")

    with pytest.raises(HTTPException) as exc:
        await update_org(
            org_id=org.id,
            payload=OrganizationPatchRequest(
                settlement_wallet="0x" + "1" * 40
            ),
            user_id=str(user.id),
            db=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "company_profile_required"

    # Rename stays allowed during onboarding.
    renamed = await update_org(
        org_id=org.id,
        payload=OrganizationPatchRequest(name="New Name"),
        user_id=str(user.id),
        db=session,
    )
    assert renamed.name == "New Name"


@pytest.mark.asyncio
async def test_settlement_wallet_write_allowed_post_submit(session):
    from app.api.organizations_routes import update_org
    from app.models.org_schemas import OrganizationPatchRequest

    user, org = await _make_org(session, onboarding_status="company_submitted")
    updated = await update_org(
        org_id=org.id,
        payload=OrganizationPatchRequest(settlement_wallet="0x" + "1" * 40),
        user_id=str(user.id),
        db=session,
    )
    assert updated.settlement_wallet == "0x" + "1" * 40


# ── 3b. Chain guard wiring in session intent-create ───────────────

@pytest.mark.asyncio
async def test_intent_create_denies_mainnet_chain_without_activation(session):
    from app.api.user_org_payments_routes import create_org_payment_intent
    from app.models.merchant_models import CreatePaymentIntentRequest

    _user, org = await _make_org(
        session, onboarding_status="company_submitted", with_wallet=True
    )

    with pytest.raises(HTTPException) as exc:
        await create_org_payment_intent(
            payload=CreatePaymentIntentRequest(
                amount=10.0, currency="USDC", chain="base"
            ),
            ctx=("u", str(org.id), "operator"),
            environment="test",
            db=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mainnet_activation_required"


@pytest.mark.asyncio
async def test_intent_create_allows_testnet_chain_when_submitted(session):
    from app.api.user_org_payments_routes import create_org_payment_intent
    from app.models.merchant_models import CreatePaymentIntentRequest

    _user, org = await _make_org(
        session, onboarding_status="company_submitted", with_wallet=True
    )

    resp = await create_org_payment_intent(
        payload=CreatePaymentIntentRequest(
            amount=10.0, currency="USDC", chain="base_sepolia"
        ),
        ctx=("u", str(org.id), "operator"),
        environment="test",
        db=session,
    )
    assert resp.intent_id.startswith("pi_")
