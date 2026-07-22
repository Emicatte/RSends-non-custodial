"""Environment isolation for merchant webhooks.

Audit follow-up (CLAUDE.md): `MerchantWebhook` had no environment dimension, so
a `rsend_test_` key could register/test the same owner's LIVE webhooks and —
worse — outbound dispatch fanned out by merchant_id alone, delivering live
events to test endpoints and vice versa. These tests pin the fix: register
stamps the key's environment onto the webhook, webhook lookups are scoped to
the key's environment, and dispatch only selects webhooks whose environment
matches the intent's.

Direct-handler tests (no live server), same style as
tests/test_merchant_env_isolation.py: fake `request.state.client`, real SQLite
session.
"""

import secrets
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    IntentStatus,
    MerchantWebhook,
    PaymentIntent,
    RegisterWebhookRequest,
    WebhookDelivery,
)
# NB: aliased — pytest would otherwise try to collect the Test-prefixed
# pydantic model as a test class and emit a PytestCollectionWarning.
from app.models.merchant_models import TestWebhookRequest as WebhookTestPayload
# NB: aliased — pytest would otherwise collect the `test_webhook` route
# handler itself as a test function.
from app.api.merchant_routes import register_webhook
from app.api.merchant_routes import test_webhook as webhook_test_route

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


def _webhook(environment: str, *, owner: str = OWNER) -> MerchantWebhook:
    return MerchantWebhook(
        merchant_id=owner,
        environment=environment,
        url="https://merchant.example/hooks",
        secret=secrets.token_hex(32),
        events=["payment.completed"],
        is_active=True,
    )


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


# ── register stamps the key's environment ────────────────────

@pytest.mark.asyncio
async def test_register_stamps_key_environment(session, monkeypatch):
    """A webhook registered by a test key is persisted with environment='test'."""
    import app.api.merchant_routes as mr

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)

    payload = RegisterWebhookRequest(url="https://merchant.example/hooks")
    resp = await register_webhook(payload, _req("test"), db=session)

    row = (await session.execute(
        select(MerchantWebhook).where(MerchantWebhook.id == resp.webhook_id)
    )).scalar_one()
    assert row.environment == "test"


# ── webhook/test blocked across environments ─────────────────

@pytest.mark.asyncio
async def test_webhook_test_blocked_across_environment(session):
    """A test key hitting the same owner's live webhook must get 404."""
    live_wh = _webhook("live")
    session.add(live_wh)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await webhook_test_route(
            WebhookTestPayload(webhook_id=live_wh.id), _req("test"), db=session,
        )
    assert exc.value.status_code == 404


# ── outbound dispatch scoped to the intent's environment ─────

@pytest.mark.asyncio
async def test_dispatch_event_scoped_to_intent_environment(session):
    """_dispatch_event for a live intent must not enqueue to test webhooks."""
    from app.services import webhook_service as ws

    live_wh = _webhook("live")
    test_wh = _webhook("test")
    session.add_all([live_wh, test_wh])
    live_intent = _intent("live")
    session.add(live_intent)
    await session.commit()

    await ws._dispatch_event(
        session,
        merchant_id=OWNER,
        event_type="payment.completed",
        intent=live_intent,
    )
    await session.commit()

    deliveries = (await session.execute(select(WebhookDelivery))).scalars().all()
    assert [d.webhook_id for d in deliveries] == [live_wh.id]


@pytest.mark.asyncio
async def test_send_webhook_scoped_to_intent_environment(session, monkeypatch):
    """send_webhook for a test intent must not deliver to live webhooks."""
    from app.services import webhook_service as ws

    async def _delivered(delivery, wh):
        return True

    monkeypatch.setattr(ws, "_attempt_delivery", _delivered)

    live_wh = _webhook("live")
    test_wh = _webhook("test")
    session.add_all([live_wh, test_wh])
    test_intent = _intent("test")
    session.add(test_intent)
    await session.commit()

    created = await ws.send_webhook(
        session,
        merchant_id=OWNER,
        event="payment.completed",
        intent=test_intent,
    )
    await session.commit()

    assert created == 1
    deliveries = (await session.execute(select(WebhookDelivery))).scalars().all()
    assert [d.webhook_id for d in deliveries] == [test_wh.id]
