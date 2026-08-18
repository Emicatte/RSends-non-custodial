"""Mainnet activation gate on the API-key payment path.

`check_org_chain_access` (app/services/chain_access.py) is the single definition
of "may this org transact on this chain": mainnet requires the org's business
verification to be complete (activation_status == 'active'). Until now its only
caller was the session route (user_org_payments_routes), so a merchant API key
could create a mainnet intent for an org that was never activated — the gate
existed and the money path walked around it.

Enforced now at the shared construction site (intent_service.create_intent), so
both entry paths are covered by one call. Scoped to mainnet chains: the same
function also enforces the testnet `company_profile_required` rule, which is a
session-onboarding concept the API-key path has never had, so the session route
keeps its own call and testnet behaviour is unchanged.

Direct-handler tests, same pattern as test_merchant_chain_gate.py.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.merchant_routes import create_payment_intent
from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.org_models import Organization
from app.security.api_keys import generate_api_key

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
RECIPIENT = "0x1111111111111111111111111111111111111111"


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentIntent.__table__.delete())
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _req(environment: str, *, key_id=None, owner: str = OWNER):
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


def _payload(chain: str) -> CreatePaymentIntentRequest:
    return CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain=chain, recipient=RECIPIENT,
    )


async def _intent_count(session) -> int:
    return (
        await session.execute(select(func.count(PaymentIntent.intent_id)))
    ).scalar_one()


async def _make_org(session, activation_status: str) -> Organization:
    """Org (+ owner user) with an explicit activation_status."""
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
        activation_status=activation_status,
    )
    session.add(org)
    await session.flush()
    return org


async def _org_with_key(session, activation_status: str) -> ApiKey:
    org = await _make_org(session, activation_status)
    _plaintext, fields = generate_api_key(environment="live")
    key = ApiKey(
        owner_address=OWNER,
        org_id=str(org.id),
        **fields,
        label="activation-gate",
        scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


def _stub_side_effects(monkeypatch):
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)


# ── Refusal ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_key_of_unactivated_org_refused_on_mainnet(session):
    """The gate the API-key path used to walk around."""
    key = await _org_with_key(session, "not_started")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("base"), _req("live", key_id=key.id), db=session
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mainnet_activation_required"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_kyb_pending_org_still_refused_on_mainnet(session):
    """Verification in flight is not verification complete."""
    key = await _org_with_key(session, "kyb_pending")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("base"), _req("live", key_id=key.id), db=session
        )

    assert exc.value.detail["code"] == "mainnet_activation_required"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_unresolvable_org_fails_closed_on_mainnet(session):
    """No key_id, no org → activation cannot be verified → deny, never assume."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("base"), _req("live"), db=session)

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mainnet_activation_required"
    assert await _intent_count(session) == 0


# ── Admission ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_org_not_refused_on_mainnet(session, monkeypatch):
    """An activated org transacts on mainnet exactly as before."""
    _stub_side_effects(monkeypatch)
    key = await _org_with_key(session, "active")

    resp = await create_payment_intent(
        _payload("base"), _req("live", key_id=key.id), db=session
    )

    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert row.chain == "base"
    assert row.environment == "live"


@pytest.mark.asyncio
async def test_testnet_path_unaffected(session, monkeypatch):
    """Testnet creation must not acquire a new precondition."""
    _stub_side_effects(monkeypatch)

    resp = await create_payment_intent(
        _payload("base_sepolia"), _req("test"), db=session
    )

    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert row.chain == "base_sepolia"
    assert row.environment == "test"


@pytest.mark.asyncio
async def test_session_path_also_gated_on_mainnet(session):
    """The shared site covers the session path too (which keeps its own call)."""
    from app.services.intent_service import create_intent

    org = await _make_org(session, "not_started")
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_intent(
            session, OWNER, "live", _payload("base"),
            org_id=str(org.id), key_id=None,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mainnet_activation_required"
    assert await _intent_count(session) == 0
