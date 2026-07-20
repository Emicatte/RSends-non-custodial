"""F-5: a settled-but-not-finalized intent cannot be cancelled out from under
its settlement.

Both cancel endpoints (API-key `POST /merchant/payment-intent/{id}/cancel` and
session `POST /user/org/payment-intents/{id}/cancel`) gated only on
`status != pending`, omitting the `has_settlement_hold` guard every expiry
writer uses. A payer's observed-but-not-yet-final on-chain payment could be
cancelled: merchant paid, intent cancelled, settlement dropped at finalize,
no webhook.

Invariant: an intent with a settlement hold (`pending` or `final` settlement)
refuses cancel with 409 SETTLEMENT_IN_FLIGHT. `rejected`/`reorged` settlements
do NOT hold (same set as expiry — a griefer's 1-wei rejected payment must not
be able to block cancellation).

Direct-handler tests, same pattern as test_user_org_intent_cancel.py.
"""

import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.merchant_routes import cancel_payment_intent
from app.api.user_org_payments_routes import cancel_org_payment_intent

OWNER = "0x" + "a" * 40
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40


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
    monkeypatch.setattr(mr, "log_event", _no_log)
    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)


def _req(environment="test", *, owner=OWNER):
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _make_org(session, *, owner_address=OWNER):
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


async def _mk_intent(session, merchant_id=OWNER, *, status=IntentStatus.pending):
    intent = PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment="test",
        amount=100.0,
        currency="USDC",
        chain="base_sepolia",
        recipient=MERCHANT,
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(intent)
    await session.commit()
    return intent


async def _add_settlement(session, intent_id, *, status):
    session.add(PaymentSettlement(
        invoice_id="0x" + secrets.token_hex(32),
        merchant=MERCHANT.lower(),
        payer=PAYER.lower(),
        token="0x" + "c" * 40,
        amount=100_000_000,
        fee=600000,
        chain_id=84532,
        tx_hash="0x" + secrets.token_hex(32),
        log_index=0,
        block_number=100,
        block_hash="0x" + secrets.token_hex(32),
        status=status,
        intent_id=intent_id,
    ))
    await session.commit()


async def _status(session, intent_id):
    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )).scalar_one()
    await session.refresh(row)
    return row.status


def _ctx(org, role="operator"):
    return ("user-unused", str(org.id), role)


# ═══════════════════════════════════════════════════════════════
#  Merchant (API-key) cancel — refuses on hold
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hold", [SettlementStatus.pending, SettlementStatus.final])
@pytest.mark.asyncio
async def test_merchant_cancel_refused_on_settlement_hold(session, hold):
    """An observed (pending) or final settlement blocks cancel with 409 —
    the payment must win over the merchant's cancel, matching the expiry guard."""
    intent = await _mk_intent(session)
    await _add_settlement(session, intent.intent_id, status=hold)

    with pytest.raises(HTTPException) as exc:
        await cancel_payment_intent(intent.intent_id, _req(), db=session)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "SETTLEMENT_IN_FLIGHT"
    assert await _status(session, intent.intent_id) is IntentStatus.pending


@pytest.mark.parametrize("non_hold", [SettlementStatus.rejected, SettlementStatus.reorged])
@pytest.mark.asyncio
async def test_merchant_cancel_still_allowed_on_non_hold_settlement(session, non_hold):
    """Anti-grief pin: a rejected (mismatched stranger payment) or reorged
    settlement must NOT block cancellation."""
    intent = await _mk_intent(session)
    await _add_settlement(session, intent.intent_id, status=non_hold)

    resp = await cancel_payment_intent(intent.intent_id, _req(), db=session)
    assert resp.status == IntentStatus.cancelled.value
    assert await _status(session, intent.intent_id) is IntentStatus.cancelled


# ═══════════════════════════════════════════════════════════════
#  Session (JWT org) cancel — same guard
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hold", [SettlementStatus.pending, SettlementStatus.final])
@pytest.mark.asyncio
async def test_session_cancel_refused_on_settlement_hold(session, hold):
    org = await _make_org(session)
    intent = await _mk_intent(session)
    await _add_settlement(session, intent.intent_id, status=hold)

    with pytest.raises(HTTPException) as exc:
        await cancel_org_payment_intent(
            intent_id=intent.intent_id, ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "SETTLEMENT_IN_FLIGHT"
    assert await _status(session, intent.intent_id) is IntentStatus.pending


@pytest.mark.asyncio
async def test_session_cancel_still_allowed_on_rejected_settlement(session):
    org = await _make_org(session)
    intent = await _mk_intent(session)
    await _add_settlement(session, intent.intent_id, status=SettlementStatus.rejected)

    resp = await cancel_org_payment_intent(
        intent_id=intent.intent_id, ctx=_ctx(org), environment="test", db=session,
    )
    assert resp.status == IntentStatus.cancelled.value
    assert await _status(session, intent.intent_id) is IntentStatus.cancelled
