"""Phase D — session-authed org invoice CANCEL.

`POST /api/v1/user/org/payment-intents/{id}/cancel` (operator+) cancels a pending
intent for the active org. Scoping is IN the query (intent_id + owner + env) so a
cross-tenant cancel is a 404 (merchant-resource 404-not-403 rule), and only
`pending` intents cancel. Direct-handler tests, same pattern as the create tests.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.user_org_payments_routes import cancel_org_payment_intent

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40


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
def _patch_side_effects(monkeypatch):
    import app.api.user_org_payments_routes as rt
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(rt, "log_event", _no_log)
    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)


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


async def _mk_intent(session, merchant_id, *, status=IntentStatus.pending):
    intent = PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment="test",
        amount=100.0,
        currency="USDC",
        chain="base_sepolia",
        recipient="0x1111111111111111111111111111111111111111",
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(intent)
    await session.commit()
    return intent


def _ctx(org, role="operator"):
    return ("user-unused", str(org.id), role)


@pytest.mark.asyncio
async def test_cancel_pending_ok(session):
    org = await _make_org(session, owner_address=OWNER_A)
    intent = await _mk_intent(session, OWNER_A)

    resp = await cancel_org_payment_intent(
        intent_id=intent.intent_id, ctx=_ctx(org), environment="test", db=session,
    )
    assert resp.status == IntentStatus.cancelled.value

    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
        )
    ).scalar_one()
    assert row.status is IntentStatus.cancelled


@pytest.mark.asyncio
async def test_cancel_cross_tenant_404(session):
    """Org B cannot cancel org A's intent — scoped lookup misses → 404, not 403
    (no existence leak)."""
    await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    intent = await _mk_intent(session, OWNER_A)  # belongs to org A

    with pytest.raises(HTTPException) as exc:
        await cancel_org_payment_intent(
            intent_id=intent.intent_id, ctx=_ctx(org_b), environment="test", db=session,
        )
    assert exc.value.status_code == 404

    # And org A's intent is untouched (still pending).
    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
        )
    ).scalar_one()
    assert row.status is IntentStatus.pending


@pytest.mark.asyncio
async def test_cancel_non_pending_400(session):
    org = await _make_org(session, owner_address=OWNER_A)
    intent = await _mk_intent(session, OWNER_A, status=IntentStatus.paid)

    with pytest.raises(HTTPException) as exc:
        await cancel_org_payment_intent(
            intent_id=intent.intent_id, ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "INVALID_STATE"
