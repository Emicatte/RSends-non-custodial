"""A rollback must never orphan a webhook idempotency claim.

send_webhook claimed a Redis SETNX idempotency key (7-day TTL) BEFORE the
WebhookDelivery row was durable, and never released it: any rollback after
the claim (flush failure, or the CALLER rolling back the transaction that
send_webhook only flushed into) left a claim with no delivery row. Every
later legitimate retry of the same (intent, event, webhook) — including the
indexer's unfired-webhook sweep, which re-calls send_webhook with the same
idem_key — was silently suppressed for up to 7 days. payment.expired has no
re-driver at all, so there the event was simply lost.

Invariant pinned here: idempotency state must live and die with the DB
transaction that owns the delivery row. After a rollback, the event is
retriable; within one durable history, it stays exactly-once (the UNIQUE
constraint on WebhookDelivery.idempotency_key is the durable backstop).

The expire task's pending→expired flip is the upstream claim for
payment.expired: it must be an atomic UPDATE-WHERE (single winner across
concurrent expire workers — Celery beat and the asyncio fallback loop can
coexist), re-checked here sequentially; the cross-transaction race is pinned
in tests/test_concurrency_postgres.py.

Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_webhook_idem_rollback.py -v
"""

import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.webhook_service import send_webhook


class _FakeRedis:
    """Minimal Redis honoring SET ... NX semantics (as in test_webhook_dedup_atomic)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401
    from app.models.merchant_models import (
        MerchantWebhook,
        PaymentIntent,
        WebhookDelivery,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(WebhookDelivery.__table__.delete())
        await conn.execute(MerchantWebhook.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


MERCHANT = "0x" + "1" * 40


async def _seed(db, *, expires_delta_minutes=30):
    """One active webhook + one pending intent, committed."""
    from app.models.merchant_models import IntentStatus, MerchantWebhook, PaymentIntent

    wh = MerchantWebhook(
        merchant_id=MERCHANT,
        environment="test",
        url="https://merchant.example/hook",
        secret="whsec_" + secrets.token_hex(16),
        events=[],  # empty ⇒ all events
        is_active=True,
    )
    intent = PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=MERCHANT,
        environment="test",
        amount=100.0,
        currency="USDC",
        chain="base_sepolia",
        recipient=MERCHANT,
        status=IntentStatus.pending,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_delta_minutes),
    )
    db.add(wh)
    db.add(intent)
    await db.commit()
    return intent.intent_id


@pytest.mark.asyncio
async def test_rollback_after_send_leaves_event_retriable():
    """Claim state must not survive a rollback that discarded the delivery row."""
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, WebhookDelivery

    fake = _FakeRedis()
    with patch("app.services.cache_service.get_redis", AsyncMock(return_value=fake)), \
         patch("app.services.webhook_service._attempt_delivery",
               AsyncMock(return_value=True)):

        async with async_session() as db:
            intent_id = await _seed(db)

        # Attempt 1: delivery row flushed, then the OWNING transaction rolls
        # back (e.g. a later statement in the caller's tx failed).
        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )).scalar_one()
            created = await send_webhook(
                db, merchant_id=MERCHANT, event="payment.expired", intent=intent,
            )
            assert created == 1
            await db.rollback()

        # Attempt 2 (the re-drive): same (intent, event, webhook) in a fresh
        # transaction. The event must be deliverable — nothing durable exists.
        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )).scalar_one()
            created = await send_webhook(
                db, merchant_id=MERCHANT, event="payment.expired", intent=intent,
            )
            await db.commit()

        assert created == 1, (
            "retry after rollback was suppressed by an orphaned idempotency claim"
        )
        async with async_session() as db:
            rows = (await db.execute(select(WebhookDelivery))).scalars().all()
            assert len(rows) == 1
            assert rows[0].event_type == "payment.expired"


@pytest.mark.asyncio
async def test_committed_delivery_stays_exactly_once():
    """The durable dedup is untouched: a COMMITTED delivery is never doubled."""
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, WebhookDelivery

    with patch("app.services.webhook_service._attempt_delivery",
               AsyncMock(return_value=True)):
        async with async_session() as db:
            intent_id = await _seed(db)

        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )).scalar_one()
            assert await send_webhook(
                db, merchant_id=MERCHANT, event="payment.expired", intent=intent,
            ) == 1
            await db.commit()

        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
            )).scalar_one()
            assert await send_webhook(
                db, merchant_id=MERCHANT, event="payment.expired", intent=intent,
            ) == 0
            await db.commit()

        async with async_session() as db:
            rows = (await db.execute(select(WebhookDelivery))).scalars().all()
            assert len(rows) == 1


@pytest.mark.asyncio
async def test_expire_claim_is_single_winner_sequentially():
    """The pending→expired flip is an atomic claim: the second transaction
    re-evaluates against the committed row and must NOT win (and so must not
    send the webhook). Cross-transaction race: test_concurrency_postgres."""
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent
    from app.tasks.webhook_tasks import _claim_intent_expiry

    async with async_session() as db:
        intent_id = await _seed(db, expires_delta_minutes=-5)

    async with async_session() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        assert await _claim_intent_expiry(db, intent) is True
        await db.commit()

    async with async_session() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        assert await _claim_intent_expiry(db, intent) is False
        await db.commit()

    async with async_session() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
        assert intent.status == IntentStatus.expired
