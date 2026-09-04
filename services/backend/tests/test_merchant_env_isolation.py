"""Tenant isolation across environments for the merchant REST surface.

Audit finding #1 (env binding on reads): `merchant_id` is derived from the API
key's owner address, which is IDENTICAL for a given owner's test and live keys.
Without an environment dimension, a `rsend_test_` key can read that owner's LIVE
transactions and intent details. These tests pin the fix: every read/list is
scoped to the authenticated key's environment, and create stamps that
environment onto the intent.

Direct-handler tests (no live server): we call the route coroutines with a fake
`request.state.client` carrying the environment, against a real SQLite session.
"""

import secrets
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    IntentStatus,
    PaymentIntent,
    CreatePaymentIntentRequest,
)
from app.api.merchant_routes import (
    list_merchant_transactions,
    get_payment_intent,
    create_payment_intent,
)

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"


# ── Fixtures ─────────────────────────────────────────────────

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


def _req(environment: str, *, owner: str = OWNER):
    """Fake Request as APIKeyMiddleware would leave it for an authenticated key."""
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


def _intent(environment: str, *, owner: str = OWNER) -> PaymentIntent:
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=owner,
        environment=environment,
        amount=100.0,
        currency="USDC",
        chain="base" if environment == "live" else "base_sepolia",
        status=IntentStatus.pending,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


# ── list /transactions ───────────────────────────────────────

@pytest.mark.asyncio
async def test_list_transactions_scoped_to_environment(session):
    """A test key must NOT see the same owner's live intents, and vice-versa."""
    live = _intent("live")
    test = _intent("test")
    session.add_all([live, test])
    await session.commit()

    test_view = await list_merchant_transactions(
        _req("test"), status=None, currency=None, page=1, per_page=20, db=session,
    )
    assert test_view.total == 1
    assert [r.intent_id for r in test_view.records] == [test.intent_id]

    live_view = await list_merchant_transactions(
        _req("live"), status=None, currency=None, page=1, per_page=20, db=session,
    )
    assert live_view.total == 1
    assert [r.intent_id for r in live_view.records] == [live.intent_id]


# ── get /payment-intent/{id} ─────────────────────────────────

@pytest.mark.asyncio
async def test_get_intent_blocked_across_environment(session):
    """A test key fetching a live intent by id must get 404, not the live row."""
    live = _intent("live")
    session.add(live)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_payment_intent(live.intent_id, _req("test"), db=session)
    assert exc.value.status_code == 404


# ── create stamps the key's environment ──────────────────────

@pytest.mark.asyncio
async def test_create_stamps_key_environment(session, monkeypatch):
    """An intent created by a test key is persisted with environment='test'."""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)

    # Explicit recipient satisfies the Phase B recipient gate — this test pins
    # environment stamping, not the gate.
    payload = CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain="base_sepolia",
        recipient="0x1111111111111111111111111111111111111111",
    )
    resp = await create_payment_intent(payload, _req("test"), db=session)

    from sqlalchemy import select
    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert row.environment == "test"
