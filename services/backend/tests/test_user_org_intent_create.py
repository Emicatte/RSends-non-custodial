"""Phase D — session-authed org invoice (payment-intent) CREATE.

The `/app` create flow POSTs to a session endpoint that must go through the SAME
single construction site + Phase B recipient gate as the API-key path (extracted
into `intent_service.create_intent`), authed by org session instead of an API key.
The load-bearing properties: (1) the recipient gate applies on the session path
(no settlement wallet + no override → 422, fail-closed), and (2) org isolation on
create — the created intent's merchant_id is the session org's owner, so it lands
in that org's read scope and no other's.

Direct-handler tests (no live server), same pattern as test_recipient_gate.py /
test_user_org_payments.py: seed User+Organization+Membership+UserWallet against a
real SQLite session and call the route coroutine with the (user_id, org_id, role)
ctx that require_org_role would produce.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    CreatePaymentIntentRequest,
    IntentStatus,
    PaymentIntent,
)
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.user_org_payments_routes import create_org_payment_intent
from app.api.merchant_routes import create_payment_intent
from app.api.deps.require_org_role import require_org_role
from app.services.intent_service import list_org_intents

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE = "0x1111111111111111111111111111111111111111"
OVERRIDE = "0x2222222222222222222222222222222222222222"


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


async def _make_org(session, *, owner_address, settlement=None):
    """Org (+ owner user + admin membership + primary EVM wallet). `settlement`
    sets the org's settlement_wallet (the recipient-gate default)."""
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
        settlement_wallet=settlement,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if owner_address is not None:
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


def _ctx(org, role="operator"):
    return ("user-unused", str(org.id), role)


def _payload(**kw):
    d = dict(amount=10.0, currency="USDC", chain="base_sepolia")
    d.update(kw)
    return CreatePaymentIntentRequest(**d)


def _req(owner, environment="test"):
    """Fake Request as the API-key middleware leaves it (for the shared-gate test)."""
    return SimpleNamespace(
        state=SimpleNamespace(client={"client_id": owner, "environment": environment})
    )


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    """Neutralise external effects so tests exercise the gate + isolation only.
    Post-Phase-D the create body lives in intent_service; the onchain quote is
    still built in merchant_routes._intent_to_response."""
    import app.services.intent_service as isvc
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(isvc, "token_is_enabled", lambda chain, cur: True)
    monkeypatch.setattr(isvc, "log_event", _no_log)
    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)


async def _created_row(session, resp):
    return (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()


# ── RED-first: the gate blocks on the session path (fail-closed) ──

@pytest.mark.asyncio
async def test_session_create_blocked_without_default_422(session):
    """Org has a primary wallet but NO settlement_wallet, and no override →
    422 SETTLEMENT_WALLET_MISSING. The gate raises before any side effect."""
    org = await _make_org(session, owner_address=OWNER, settlement=None)
    with pytest.raises(HTTPException) as exc:
        await create_org_payment_intent(
            payload=_payload(), ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "SETTLEMENT_WALLET_MISSING"


# ── The gate resolves + org isolation on create ──────────────────

@pytest.mark.asyncio
async def test_session_create_uses_org_default(session):
    """No override → the org's settlement_wallet is stamped as recipient; the
    intent's merchant_id is the org's owner (so it lands in the org's read scope)."""
    org = await _make_org(session, owner_address=OWNER, settlement=SETTLE)
    resp = await create_org_payment_intent(
        payload=_payload(), ctx=_ctx(org), environment="test", db=session,
    )
    row = await _created_row(session, resp)
    assert row.recipient == SETTLE
    assert row.merchant_id == OWNER
    assert row.status is IntentStatus.pending
    assert row.environment == "test"


@pytest.mark.asyncio
async def test_session_create_override_recipient(session):
    """An explicit per-intent recipient override beats the org default."""
    org = await _make_org(session, owner_address=OWNER, settlement=SETTLE)
    resp = await create_org_payment_intent(
        payload=_payload(recipient=OVERRIDE), ctx=_ctx(org), environment="test", db=session,
    )
    row = await _created_row(session, resp)
    assert row.recipient == OVERRIDE


@pytest.mark.asyncio
async def test_session_create_isolation(session):
    """The created intent belongs to the session org's owner — org B never sees it."""
    owner_b = "0x" + "b" * 40
    org_a = await _make_org(session, owner_address=OWNER, settlement=SETTLE)
    await _make_org(session, owner_address=owner_b, settlement=OVERRIDE)

    resp = await create_org_payment_intent(
        payload=_payload(), ctx=_ctx(org_a), environment="test", db=session,
    )
    row = await _created_row(session, resp)
    assert row.merchant_id == OWNER  # org A's owner, not org B's

    a_ids = {r.intent_id for r in (await list_org_intents(session, OWNER, "test")).records}
    b_ids = {r.intent_id for r in (await list_org_intents(session, owner_b, "test")).records}
    assert resp.intent_id in a_ids
    assert resp.intent_id not in b_ids


@pytest.mark.asyncio
async def test_both_paths_share_gate(session):
    """API-key and session create both hit the SAME gate (create_intent) →
    both fail-closed 422 when no recipient resolves."""
    # Session path: org with no settlement wallet.
    org = await _make_org(session, owner_address=OWNER, settlement=None)
    with pytest.raises(HTTPException) as e_sess:
        await create_org_payment_intent(
            payload=_payload(), ctx=_ctx(org), environment="test", db=session,
        )
    assert e_sess.value.status_code == 422
    assert e_sess.value.detail["error"] == "SETTLEMENT_WALLET_MISSING"

    # API-key path: owner linked to no org → same gate, same verdict.
    unlinked = "0x" + "9" * 40
    with pytest.raises(HTTPException) as e_key:
        await create_payment_intent(_payload(), _req(unlinked), db=session)
    assert e_key.value.status_code == 422
    assert e_key.value.detail["error"] == "SETTLEMENT_WALLET_MISSING"


# ── RBAC + fail-closed edges ─────────────────────────────────────

@pytest.mark.asyncio
async def test_session_create_viewer_403(session, monkeypatch):
    """The create route wires require_org_role('operator'); a viewer is rejected."""
    import app.api.deps.require_org_role as rreq

    org = await _make_org(session, owner_address=OWNER, settlement=SETTLE)
    viewer = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
        active_org_id=org.id,
    )
    session.add(viewer)
    await session.flush()
    session.add(Membership(user_id=viewer.id, org_id=org.id, role="viewer"))
    await session.commit()

    async def _fake_verify(token):
        return {"sub": viewer.id}

    monkeypatch.setattr(rreq, "verify_access_token", _fake_verify)

    dep = require_org_role("operator")
    req = SimpleNamespace(headers={"Authorization": "Bearer x"})
    with pytest.raises(HTTPException) as exc:
        await dep(request=req, db=session)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_session_create_no_primary_wallet_409(session):
    """An org with no primary EVM wallet cannot resolve an owner → 409."""
    org = await _make_org(session, owner_address=None, settlement=SETTLE)
    with pytest.raises(HTTPException) as exc:
        await create_org_payment_intent(
            payload=_payload(), ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "no_primary_wallet"
