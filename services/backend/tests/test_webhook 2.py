"""
RPagos Backend — Test: Alchemy Webhook

Testa l'endpoint POST /api/v1/webhooks/alchemy:
  - Verifica firma HMAC-SHA256
  - Rifiuto firma mancante/invalida
  - Parsing payload Address Activity
  - Matching regole attive
  - Ignorare activity vuota
  - Payload malformato

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_webhook.py -v
"""

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.db.session import engine, async_session
from app.models.db_models import Base
from app.models.forwarding_models import ForwardingRule, SweepLog, SweepStatus

# ── Test addresses ────────────────────────────────────────

OWNER = "0x" + "aa" * 20
SOURCE = "0x" + "bb" * 20
DEST = "0x" + "cc" * 20
SENDER = "0x" + "11" * 20

WEBHOOK_SECRET = "test-webhook-secret-key"


# ── Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Client HTTP asincrono."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def rule_in_db():
    """Inserisce una regola attiva nel DB per il matching."""
    async with async_session() as db:
        rule = ForwardingRule(
            user_id=OWNER.lower(),
            source_wallet=SOURCE.lower(),
            destination_wallet=DEST.lower(),
            is_active=True,
            is_paused=False,
            min_threshold=0.001,
            chain_id=8453,
            token_symbol="ETH",
            cooldown_sec=0,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule


def _alchemy_payload(
    to_addr: str = SOURCE,
    from_addr: str = SENDER,
    value: float = 0.5,
    tx_hash: str = "0x" + "ab" * 32,
    asset: str = "ETH",
    category: str = "external",
    raw_contract: dict = None,
) -> dict:
    """Genera un payload Alchemy Address Activity."""
    activity_entry = {
        "fromAddress": from_addr,
        "toAddress": to_addr,
        "value": value,
        "hash": tx_hash,
        "asset": asset,
        "blockNum": "0x123456",
        "category": category,
    }
    if raw_contract:
        activity_entry["rawContract"] = raw_contract

    return {
        "webhookId": "wh_test123",
        "id": "evt_test456",
        "createdAt": "2026-03-30T12:00:00Z",
        "type": "ADDRESS_ACTIVITY",
        "event": {
            "network": "BASE_MAINNET",
            "activity": [activity_entry],
        },
    }


def _sign_payload(payload: dict, secret: str = WEBHOOK_SECRET) -> str:
    """Calcola la firma HMAC-SHA256 per il payload."""
    body = json.dumps(payload).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ═══════════════════════════════════════════════════════════
#  1. HMAC Signature Verification
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_webhook_valid_signature(client: AsyncClient, rule_in_db):
    """Firma HMAC valida → 200 accepted (via verify_webhook security chain)."""
    import asyncio as _asyncio
    payload = _alchemy_payload()

    # Mock verify_webhook to return parsed payload (security chain tested in test_cc06)
    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
            mock_celery.delay = lambda p: None

            r = await client.post(
                "/api/v1/webhooks/alchemy",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            await _asyncio.sleep(0.1)

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "accepted"
    assert data["activity_count"] == 1


@pytest.mark.asyncio
async def test_webhook_missing_signature(client: AsyncClient):
    """Firma mancante → 401 (raised by verify_webhook)."""
    from app.security.webhook_verifier import WebhookVerificationError

    payload = _alchemy_payload()

    with patch(
        "app.api.sweeper_routes.verify_webhook",
        new_callable=AsyncMock,
        side_effect=WebhookVerificationError("Missing X-Alchemy-Signature header", 401),
    ):
        r = await client.post(
            "/api/v1/webhooks/alchemy",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    assert r.status_code == 401
    assert "Missing" in r.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient):
    """Firma errata → 401 (raised by verify_webhook)."""
    from app.security.webhook_verifier import WebhookVerificationError

    payload = _alchemy_payload()

    with patch(
        "app.api.sweeper_routes.verify_webhook",
        new_callable=AsyncMock,
        side_effect=WebhookVerificationError("Invalid webhook signature", 401),
    ):
        r = await client.post(
            "/api/v1/webhooks/alchemy",
            content=json.dumps(payload),
            headers={
                "x-alchemy-signature": "bad_signature_here",
                "content-type": "application/json",
            },
        )

    assert r.status_code == 401
    assert "Invalid" in r.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_no_secret_configured(client: AsyncClient, rule_in_db):
    """verify_webhook passes → 200 accepted."""
    import asyncio as _asyncio
    payload = _alchemy_payload()

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
            mock_celery.delay = lambda p: None

            r = await client.post(
                "/api/v1/webhooks/alchemy",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            await _asyncio.sleep(0.1)

    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


# ═══════════════════════════════════════════════════════════
#  2. Payload Parsing
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_webhook_empty_activity(client: AsyncClient):
    """Activity vuota → ignored."""
    payload = {
        "webhookId": "wh_test",
        "event": {"network": "BASE_MAINNET", "activity": []},
    }

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        r = await client.post(
            "/api/v1/webhooks/alchemy",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    assert r.json()["reason"] == "no_activity"


@pytest.mark.asyncio
async def test_webhook_invalid_json(client: AsyncClient):
    """Payload non-JSON → 400 (raised by verify_webhook)."""
    from app.security.webhook_verifier import WebhookVerificationError

    with patch(
        "app.api.sweeper_routes.verify_webhook",
        new_callable=AsyncMock,
        side_effect=WebhookVerificationError("Invalid JSON body", 400),
    ):
        r = await client.post(
            "/api/v1/webhooks/alchemy",
            content=b"not json {{{",
            headers={"content-type": "application/json"},
        )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_multiple_activities(client: AsyncClient, rule_in_db):
    """Payload con multiple activity entries → tutte processate."""
    payload = {
        "webhookId": "wh_test",
        "event": {
            "network": "BASE_MAINNET",
            "activity": [
                {
                    "fromAddress": SENDER,
                    "toAddress": SOURCE,
                    "value": 1.0,
                    "hash": "0x" + "a1" * 32,
                    "asset": "ETH",
                    "blockNum": "0x100",
                    "category": "external",
                },
                {
                    "fromAddress": SENDER,
                    "toAddress": SOURCE,
                    "value": 2.0,
                    "hash": "0x" + "b2" * 32,
                    "asset": "ETH",
                    "blockNum": "0x101",
                    "category": "external",
                },
            ],
        },
    }

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
            mock_celery.delay = lambda p: None

            r = await client.post(
                "/api/v1/webhooks/alchemy",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            import asyncio
            await asyncio.sleep(0.1)

    assert r.status_code == 200
    assert r.json()["activity_count"] == 2


# ═══════════════════════════════════════════════════════════
#  3. ERC-20 Payload Parsing
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_webhook_erc20_activity(client: AsyncClient, rule_in_db):
    """Payload ERC-20 con rawContract → token info estratto."""
    payload = _alchemy_payload(
        asset="USDC",
        category="token",
        value=100.0,
        raw_contract={
            "address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "decimals": 6,
        },
    )

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
            mock_celery.delay = lambda p: None  # Celery stub

            r = await client.post(
                "/api/v1/webhooks/alchemy",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            import asyncio
            await asyncio.sleep(0.1)  # Let background task complete

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_webhook_zero_value_skipped(client: AsyncClient, rule_in_db):
    """TX con value=0 viene ignorata (approval, contract call)."""
    payload = _alchemy_payload(value=0)

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
            mock_delay = mock_celery.delay = AsyncMock()

            r = await client.post(
                "/api/v1/webhooks/alchemy",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            import asyncio
            await asyncio.sleep(0.1)

    assert r.status_code == 200
    # Celery .delay() should NOT have been called for zero-value
    mock_delay.assert_not_called()


# ═══════════════════════════════════════════════════════════
#  4. Rule Matching (integration)
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_process_incoming_tx_matches_rule(rule_in_db):
    """process_incoming_tx matcha la regola e crea sweep log."""
    from app.services.sweep_service import process_incoming_tx

    # Mock queue_sweep to avoid actual execution
    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr=SOURCE.lower(),
                value=0.5,
                tx_hash="0x" + "ab" * 32,
                asset="ETH",
            )

    assert count == 1
    mock_q.assert_called_once()

    # Verify sweep log created
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(SweepLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].amount_human == 0.5
        assert logs[0].trigger_tx_hash == "0x" + "ab" * 32


@pytest.mark.asyncio
async def test_process_incoming_tx_below_threshold(rule_in_db):
    """Amount sotto min_threshold → nessun sweep."""
    from app.services.sweep_service import process_incoming_tx

    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr=SOURCE.lower(),
                value=0.0001,  # Below 0.001 threshold
                tx_hash="0x" + "cd" * 32,
                asset="ETH",
            )

    assert count == 0
    mock_q.assert_not_called()


@pytest.mark.asyncio
async def test_process_incoming_tx_no_matching_rule():
    """Nessuna regola per l'indirizzo → 0 sweep."""
    from app.services.sweep_service import process_incoming_tx

    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr="0x" + "ff" * 20,  # No rule for this address
                value=1.0,
                tx_hash="0x" + "ef" * 32,
                asset="ETH",
            )

    assert count == 0


@pytest.mark.asyncio
async def test_process_incoming_tx_paused_rule():
    """Regola pausata → non matcha."""
    from app.services.sweep_service import process_incoming_tx

    async with async_session() as db:
        rule = ForwardingRule(
            user_id=OWNER.lower(),
            source_wallet=SOURCE.lower(),
            destination_wallet=DEST.lower(),
            is_active=True,
            is_paused=True,  # Paused!
            min_threshold=0.001,
            chain_id=8453,
            cooldown_sec=0,
        )
        db.add(rule)
        await db.commit()

    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr=SOURCE.lower(),
                value=1.0,
                tx_hash="0x" + "aa" * 32,
                asset="ETH",
            )

    assert count == 0


@pytest.mark.asyncio
async def test_process_incoming_tx_inactive_rule():
    """Regola inattiva → non matcha."""
    from app.services.sweep_service import process_incoming_tx

    async with async_session() as db:
        rule = ForwardingRule(
            user_id=OWNER.lower(),
            source_wallet=SOURCE.lower(),
            destination_wallet=DEST.lower(),
            is_active=False,  # Inactive!
            is_paused=False,
            min_threshold=0.001,
            chain_id=8453,
            cooldown_sec=0,
        )
        db.add(rule)
        await db.commit()

    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr=SOURCE.lower(),
                value=1.0,
                tx_hash="0x" + "bb" * 32,
                asset="ETH",
            )

    assert count == 0


@pytest.mark.asyncio
async def test_process_incoming_tx_token_mismatch(rule_in_db):
    """Regola con token_address specifico → mismatch non matcha."""
    # Update rule to target USDC specifically
    async with async_session() as db:
        from sqlalchemy import update
        await db.execute(
            update(ForwardingRule)
            .where(ForwardingRule.id == rule_in_db.id)
            .values(token_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
        )
        await db.commit()

    from app.services.sweep_service import process_incoming_tx

    with patch("app.services.sweep_service.queue_sweep", new_callable=AsyncMock) as mock_q:
        with patch("app.api.websocket_routes.feed_manager") as mock_feed:
            mock_feed.broadcast = AsyncMock()

            # Send ETH (no token_address) → should not match USDC-specific rule
            count = await process_incoming_tx(
                from_addr=SENDER.lower(),
                to_addr=SOURCE.lower(),
                value=1.0,
                tx_hash="0x" + "cc" * 32,
                asset="ETH",
                token_address=None,
            )

    assert count == 0


# ═══════════════════════════════════════════════════════════
#  7. Per-TX Dedup (tx_hash-based idempotency)
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_webhook_per_tx_dedup_skips_already_processed(client: AsyncClient, rule_in_db):
    """If tx_hash was already processed, activity is skipped even with a new webhook_id."""
    tx_hash = "0x" + "de" * 32
    payload = _alchemy_payload(tx_hash=tx_hash)

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.services.idempotency_service.is_tx_processed", new_callable=AsyncMock, return_value=True) as mock_check:
            with patch("app.services.sweep_service.process_incoming_tx", new_callable=AsyncMock) as mock_process:
                r = await client.post(
                    "/api/v1/webhooks/alchemy",
                    content=json.dumps(payload),
                    headers={"content-type": "application/json"},
                )
                import asyncio
                await asyncio.sleep(0.1)

    assert r.status_code == 200
    mock_check.assert_called_once_with(tx_hash)
    mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_per_tx_dedup_marks_after_processing(client: AsyncClient, rule_in_db):
    """After successful processing, tx_hash is marked as processed."""
    tx_hash = "0x" + "ef" * 32
    payload = _alchemy_payload(tx_hash=tx_hash)

    with patch("app.api.sweeper_routes.verify_webhook", new_callable=AsyncMock, return_value=payload):
        with patch("app.services.idempotency_service.is_tx_processed", new_callable=AsyncMock, return_value=False):
            with patch("app.services.idempotency_service.mark_tx_processed", new_callable=AsyncMock) as mock_mark:
                with patch("app.services.split_webhook_bridge.maybe_execute_split", new_callable=AsyncMock, return_value=None):
                    with patch("app.api.sweeper_routes.process_incoming_tx", new_callable=AsyncMock):
                        r = await client.post(
                            "/api/v1/webhooks/alchemy",
                            content=json.dumps(payload),
                            headers={"content-type": "application/json"},
                        )
                        import asyncio
                        await asyncio.sleep(0.2)

    assert r.status_code == 200
    mock_mark.assert_called_with(tx_hash)
