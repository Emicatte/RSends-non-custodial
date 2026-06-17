"""
RPagos Backend — Test: Enhanced Webhook Service.

Testa le nuove funzionalita' del webhook service:
  - send_webhook() delivery success immediata
  - send_webhook() retry su failure (backoff schedule)
  - Idempotenza: stessa TX non genera duplicati (DB + Redis)
  - Payload contiene chain, deposit_address, timestamp
  - X-RSend-Delivery header e' un UUID
  - expire_pending_intents scade intent e triggera webhook

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 \
    pytest tests/test_webhook_enhanced.py -v
"""

import json
import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from app.db.session import engine, async_session
from app.models.db_models import Base
from app.models.merchant_models import (
    PaymentIntent, IntentStatus,
    MerchantWebhook, WebhookDelivery, DeliveryStatus,
)
from app.services.webhook_service import (
    send_webhook, _build_merchant_payload,
    compute_webhook_signature, _check_redis_idempotency,
    process_pending_deliveries, expire_stale_intents,
    MAX_RETRIES, BASE_BACKOFF_SECONDS,
)


# ── Constants ────────────────────────────────────────────────

MERCHANT_ID = "test-merchant-wh-001"
WEBHOOK_URL = "https://merchant.example.com/webhook"
WEBHOOK_SECRET = "test-secret-hmac-key-256bit"
DEPOSIT_ADDR = "0x" + "cd" * 20


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_intent(
    *,
    status: IntentStatus = IntentStatus.completed,
    expires_in_minutes: int = 30,
    chain: str = "BASE",
    matched_tx_hash: str = None,
) -> PaymentIntent:
    """Helper: crea un PaymentIntent nel DB."""
    import secrets
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=f"pi_{secrets.token_hex(16)}",
            reference_id=secrets.token_hex(8),
            merchant_id=MERCHANT_ID,
            amount=50.0,
            currency="USDC",
            chain=chain,
            deposit_address=DEPOSIT_ADDR,
            status=status,
            matched_tx_hash=matched_tx_hash or ("0x" + "aa" * 32),
            matched_at=datetime.now(timezone.utc) if status == IntentStatus.completed else None,
            completed_at=datetime.now(timezone.utc) if status == IntentStatus.completed else None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
            metadata_={"order_id": "ORD-123", "customer": "alice"},
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
        return intent


async def _create_webhook(
    *,
    events: list = None,
    is_active: bool = True,
) -> MerchantWebhook:
    """Helper: registra un webhook per il merchant."""
    async with async_session() as db:
        wh = MerchantWebhook(
            merchant_id=MERCHANT_ID,
            url=WEBHOOK_URL,
            secret=WEBHOOK_SECRET,
            events=events or ["payment.completed", "payment.expired", "payment.failed"],
            is_active=is_active,
        )
        db.add(wh)
        await db.commit()
        await db.refresh(wh)
        return wh


# ═══════════════════════════════════════════════════════════════
#  Test: Payload Structure
# ═══════════════════════════════════════════════════════════════

class TestPayloadStructure:
    """Verifica che il payload contenga tutti i campi richiesti."""

    @pytest.mark.asyncio
    async def test_payload_contains_required_fields(self):
        intent = await _create_intent()
        payload = _build_merchant_payload("payment.completed", intent)

        assert payload["event"] == "payment.completed"
        assert payload["intent_id"] == intent.intent_id
        assert payload["amount"] == str(intent.amount)
        assert payload["currency"] == "USDC"
        assert payload["chain"] == "BASE"
        assert payload["tx_hash"] is not None
        assert payload["deposit_address"] == DEPOSIT_ADDR
        assert payload["metadata"] == {"order_id": "ORD-123", "customer": "alice"}
        assert "timestamp" in payload
        # Verifica che timestamp sia ISO 8601
        datetime.fromisoformat(payload["timestamp"])

    @pytest.mark.asyncio
    async def test_payload_extra_fields_merged(self):
        intent = await _create_intent()
        payload = _build_merchant_payload(
            "payment.completed", intent,
            extra={"custom_field": "value", "amount_received": "50.5"},
        )
        assert payload["custom_field"] == "value"
        assert payload["amount_received"] == "50.5"


# ═══════════════════════════════════════════════════════════════
#  Test: HMAC Signature
# ═══════════════════════════════════════════════════════════════

class TestHMACSignature:
    """Verifica firma HMAC-SHA256."""

    def test_signature_deterministic(self):
        payload = b'{"event":"payment.completed","intent_id":"pi_test"}'
        sig1 = compute_webhook_signature(WEBHOOK_SECRET, payload)
        sig2 = compute_webhook_signature(WEBHOOK_SECRET, payload)
        assert sig1 == sig2

    def test_signature_changes_with_different_secret(self):
        payload = b'{"event":"payment.completed"}'
        sig1 = compute_webhook_signature("secret-a", payload)
        sig2 = compute_webhook_signature("secret-b", payload)
        assert sig1 != sig2

    def test_signature_changes_with_different_payload(self):
        sig1 = compute_webhook_signature(WEBHOOK_SECRET, b'payload-a')
        sig2 = compute_webhook_signature(WEBHOOK_SECRET, b'payload-b')
        assert sig1 != sig2


# ═══════════════════════════════════════════════════════════════
#  Test: send_webhook Delivery Success
# ═══════════════════════════════════════════════════════════════

class TestSendWebhookSuccess:
    """Verifica delivery immediata con risposta 2xx."""

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    @patch("app.services.webhook_service.httpx.AsyncClient")
    async def test_immediate_delivery_success(self, mock_client_cls, mock_redis):
        # Setup mock HTTP response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        intent = await _create_intent()
        wh = await _create_webhook()

        async with async_session() as db:
            async with db.begin():
                # Re-fetch intent within this session
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()

                created = await send_webhook(
                    db,
                    merchant_id=MERCHANT_ID,
                    event="payment.completed",
                    intent=intent_db,
                )

        assert created == 1

        # Verifica che il POST sia stato chiamato
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

        # Verifica headers
        assert "X-RSend-Signature" in headers
        assert headers["X-RSend-Event"] == "payment.completed"
        assert "X-RSend-Delivery" in headers
        # X-RSend-Delivery deve essere un UUID valido
        uuid.UUID(headers["X-RSend-Delivery"])

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    @patch("app.services.webhook_service.httpx.AsyncClient")
    async def test_delivery_creates_record(self, mock_client_cls, mock_redis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        intent = await _create_intent()
        wh = await _create_webhook()

        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        # Verifica WebhookDelivery creata e delivered
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(WebhookDelivery))
            delivery = result.scalar_one()
            assert delivery.status == DeliveryStatus.delivered
            assert delivery.response_code == 200
            assert delivery.event_type == "payment.completed"


# ═══════════════════════════════════════════════════════════════
#  Test: Retry on Failure
# ═══════════════════════════════════════════════════════════════

class TestRetryOnFailure:
    """Verifica che una delivery fallita scheduli un retry con backoff."""

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    @patch("app.services.webhook_service.httpx.AsyncClient")
    async def test_failure_schedules_retry(self, mock_client_cls, mock_redis):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        intent = await _create_intent()
        wh = await _create_webhook()

        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        # Verifica che la delivery sia still pending con retry schedulato
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(WebhookDelivery))
            delivery = result.scalar_one()
            assert delivery.status == DeliveryStatus.pending
            assert delivery.retries == 1
            assert delivery.response_code == 500
            assert delivery.response_body == "Internal Server Error"
            assert delivery.next_retry_at is not None
            # SQLite perde timezone — normalize per confronto
            retry_at = delivery.next_retry_at
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            assert retry_at > datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════
#  Test: Idempotency (No Duplicates)
# ═══════════════════════════════════════════════════════════════

class TestIdempotency:
    """Verifica che la stessa TX non generi webhook duplicati."""

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    @patch("app.services.webhook_service.httpx.AsyncClient")
    async def test_db_idempotency_no_duplicate(self, mock_client_cls, mock_redis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        intent = await _create_intent()
        wh = await _create_webhook()

        # Prima chiamata: crea delivery
        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                created1 = await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        # Seconda chiamata: duplicato, skip
        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                created2 = await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        assert created1 == 1
        assert created2 == 0  # Duplicato skippato

        # Solo una delivery nel DB
        async with async_session() as db:
            from sqlalchemy import select, func
            result = await db.execute(select(func.count(WebhookDelivery.id)))
            count = result.scalar()
            assert count == 1

    @pytest.mark.asyncio
    async def test_redis_idempotency_hit(self):
        """Simula Redis che ritorna hit (duplicato)."""
        mock_redis_instance = AsyncMock()
        mock_redis_instance.set = AsyncMock(return_value=False)  # Key gia' presente

        mock_get_redis = AsyncMock(return_value=mock_redis_instance)
        with patch("app.services.cache_service.get_redis", mock_get_redis):
            is_dup = await _check_redis_idempotency("pi_test:payment.completed:1")
            assert is_dup is True

    @pytest.mark.asyncio
    async def test_redis_unavailable_proceeds(self):
        """Se Redis non e' disponibile, procede comunque (fail-open)."""
        mock_get_redis = AsyncMock(return_value=None)
        with patch("app.services.cache_service.get_redis", mock_get_redis):
            is_dup = await _check_redis_idempotency("pi_test:payment.completed:1")
            assert is_dup is False


# ═══════════════════════════════════════════════════════════════
#  Test: Inactive Webhook Skipped
# ═══════════════════════════════════════════════════════════════

class TestInactiveWebhook:

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    async def test_inactive_webhook_not_triggered(self, mock_redis):
        intent = await _create_intent()
        wh = await _create_webhook(is_active=False)

        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                created = await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        assert created == 0

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._check_redis_idempotency", new_callable=AsyncMock, return_value=False)
    async def test_event_filter_respected(self, mock_redis):
        """Webhook che ascolta solo payment.expired non riceve payment.completed."""
        intent = await _create_intent()
        wh = await _create_webhook(events=["payment.expired"])

        async with async_session() as db:
            async with db.begin():
                from sqlalchemy import select
                result = await db.execute(
                    select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
                )
                intent_db = result.scalar_one()
                created = await send_webhook(
                    db, merchant_id=MERCHANT_ID,
                    event="payment.completed", intent=intent_db,
                )

        assert created == 0


# ═══════════════════════════════════════════════════════════════
#  Test: Expire Stale Intents
# ═══════════════════════════════════════════════════════════════

class TestExpireStaleIntents:
    """Verifica che expire_stale_intents scada intent pendenti."""

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._dispatch_event", new_callable=AsyncMock)
    async def test_expire_pending_intent(self, mock_dispatch):
        # Crea intent gia' scaduto
        intent = await _create_intent(
            status=IntentStatus.pending,
            expires_in_minutes=-5,  # Scaduto 5 min fa
        )

        async with async_session() as db:
            async with db.begin():
                count = await expire_stale_intents(db)

        assert count == 1

        # Verifica status aggiornato
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
            )
            updated = result.scalar_one()
            assert updated.status == IntentStatus.expired

        # Verifica webhook dispatch chiamato
        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs["event_type"] == "payment.expired"

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._dispatch_event", new_callable=AsyncMock)
    async def test_non_expired_intent_untouched(self, mock_dispatch):
        # Intent non ancora scaduto
        intent = await _create_intent(
            status=IntentStatus.pending,
            expires_in_minutes=30,  # Scade tra 30 min
        )

        async with async_session() as db:
            async with db.begin():
                count = await expire_stale_intents(db)

        assert count == 0
        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.webhook_service._dispatch_event", new_callable=AsyncMock)
    async def test_already_completed_not_expired(self, mock_dispatch):
        """Intent completed non viene toccato anche se 'scaduto'."""
        intent = await _create_intent(
            status=IntentStatus.completed,
            expires_in_minutes=-5,
        )

        async with async_session() as db:
            async with db.begin():
                count = await expire_stale_intents(db)

        assert count == 0
        mock_dispatch.assert_not_called()
