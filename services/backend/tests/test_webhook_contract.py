"""Webhook payload CONTRACT — the v1 unified shape (2026-07-18).

This is the data contract merchants build against. ONE builder
(`_build_payload`) serves EVERY event — lifecycle (`_dispatch_event`),
settlement (`send_webhook`), and the test-fire button — so shapes cannot
drift apart again (the root cause of the old divergence was two independent
builders plus an inline test payload).

Pins:
  1. The exact key set of every event's payload (golden set + per-event
     extras) — a new or removed key fails here first, deliberately.
  2. Deprecated/removed fields stay removed: `fee` (subscription model;
     on-chain fee stays readable via tx_hash), `network` (chain + chain_id
     are the one way to identify the network), `merchant_id` (identity echo,
     changes at the org_id re-key).
  3. Types: `amount` is a STRING; `chain` is the canonical lowercase
     registry name; `chain_id` is the numeric id.
  4. HMAC signature (unchanged scheme) verifies over the new body.
  5. The test-fire payload has the SAME key set as production events.
  6. The v2 matcher maps status `review` → event `payment.needs_review`
     (was `payment.review`, which no allowlist/filter matched — merchants
     silently never received it) and `payment.reversed` is subscribable.

Run:
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_webhook_contract.py -v
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    VALID_EVENTS,
    DeliveryStatus,
    IntentStatus,
    MerchantWebhook,
    PaymentIntent,
    WebhookDelivery,
)
from app.models.settlement_models import PaymentSettlement, SettlementStatus
import app.services.payment_indexer as idx
import app.services.webhook_service as ws
from app.services.webhook_service import (
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    _build_payload,
    _build_test_event_payload,
    _dispatch_event,
    _finalize_event_type,
    send_webhook,
    verify_webhook_signature,
)

MERCHANT_ID = "m_contract_test"
WEBHOOK_URL = "https://merchant.example.com/hook"
SECRET = "sk_" + secrets.token_hex(32)
CHAIN_ID = 8453

# ── THE CONTRACT ─────────────────────────────────────────────
# Every webhook body carries exactly these keys (plus documented per-event
# extras). Changing this set is a breaking contract change: docs
# (apps/web/app/docs/webhooks/page.tsx) must move in the same PR.

CONTRACT_KEYS = frozenset({
    "event_id",
    "event",
    "intent_id",
    "reference_id",
    "onchain_invoice_id",
    "amount",
    "amount_received",
    "overpaid_amount",
    "underpaid_amount",
    "currency",
    "chain",
    "chain_id",
    "recipient",
    "tx_hash",
    "status",
    "completed_late",
    "late_minutes",
    "metadata",
    "timestamp",
    "created_at",
    "completed_at",
})

REMOVED_KEYS = ("fee", "network", "merchant_id")

# Per-event extras exactly as the call sites merge them.
EVENT_EXTRAS = {
    "payment.completed": {"tx_hash": "0x" + "aa" * 32, "settlement": "onchain"},
    "payment.reversed": {
        "tx_hash": "0x" + "aa" * 32, "reason": "reorg", "settlement": "onchain",
    },
    "payment.completed_late": {},
    "payment.expired": {},
    "payment.expired_rejected": {"tx_hash": "0x" + "aa" * 32, "late_minutes": 7},
    "payment.needs_review": {},
    "payment.partial": {
        "expected_amount": "50.0", "received_amount": "30.0",
        "overpaid_amount": None, "underpaid_amount": "20.0",
    },
    "payment.overpaid": {
        "expected_amount": "50.0", "received_amount": "60.0",
        "overpaid_amount": "10.0", "underpaid_amount": None,
    },
    # Watch-only (TRON): one transfer, several pending invoices it could be
    # paying. The matcher refuses to choose, so the subject intent here is
    # REPRESENTATIVE — the real candidate list rides in the extras and no
    # intent was touched. See app/services/tron_matcher.py.
    "payment.ambiguous": {
        "tx_hash": "e" * 64, "settlement": "onchain",
        "candidate_intent_ids": ["pi_aaaa", "pi_bbbb"],
    },
}


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(WebhookDelivery.__table__.delete())
        await conn.execute(MerchantWebhook.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


async def _create_intent(
    *, status=IntentStatus.completed, chain="BASE_SEPOLIA",
) -> PaymentIntent:
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=f"pi_{secrets.token_hex(16)}",
            reference_id=secrets.token_hex(8),
            merchant_id=MERCHANT_ID,
            amount=50.0,
            currency="USDC",
            chain=chain,
            onchain_invoice_id="0x" + "cd" * 32,
            recipient="0x" + "1" * 40,
            status=status,
            matched_tx_hash="0x" + "aa" * 32,
            matched_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            metadata_={"order_id": "ORD-1"},
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
        return intent


async def _create_webhook(events=None) -> MerchantWebhook:
    async with async_session() as db:
        wh = MerchantWebhook(
            merchant_id=MERCHANT_ID,
            url=WEBHOOK_URL,
            secret=SECRET,
            events=events,  # None ⇒ receives every event
            is_active=True,
        )
        db.add(wh)
        await db.commit()
        await db.refresh(wh)
        return wh


def _mock_httpx_capture():
    captured = {}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "OK"

    async def _post(url, *, content=None, headers=None, **kw):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        return mock_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=_post)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, captured


# ═══════════════════════════════════════════════════════════════
#  1+2. Golden key set per event; removed fields stay removed
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", sorted(EVENT_EXTRAS))
async def test_every_event_emits_the_contract_shape(event_type):
    intent = await _create_intent()
    extras = EVENT_EXTRAS[event_type]
    payload = _build_payload(event_type, intent, extra=extras or None)

    assert set(payload.keys()) == CONTRACT_KEYS | set(extras.keys())
    for gone in REMOVED_KEYS:
        assert gone not in payload, f"{gone} must not reappear in {event_type}"
    assert payload["event"] == event_type
    assert payload["event_id"].startswith("evt_")


@pytest.mark.asyncio
async def test_contract_types_and_canonical_chain():
    intent = await _create_intent(chain="BASE_SEPOLIA")
    payload = _build_payload("payment.completed", intent)

    assert payload["amount"] == "50.0" and isinstance(payload["amount"], str)
    assert payload["chain"] == "base_sepolia"       # canonical lowercase
    assert payload["chain_id"] == 84532             # derived, numeric
    assert payload["recipient"] == "0x" + "1" * 40
    assert payload["reference_id"] == intent.reference_id
    assert payload["status"] == "completed"
    datetime.fromisoformat(payload["timestamp"])


def test_exactly_one_builder_exists():
    """The 2024-era divergence came from two independent builders — pin that
    they are gone and `_build_payload` is the only body constructor left."""
    assert not hasattr(ws, "_build_event_payload")
    assert not hasattr(ws, "_build_merchant_payload")


# ═══════════════════════════════════════════════════════════════
#  3. Both dispatch paths produce the same shape
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_wire_body_shape_and_signature_settlement_path():
    """send_webhook (indexer/settlement path): exact wire bytes carry the
    contract shape and verify under the unchanged HMAC scheme."""
    await _create_webhook()
    intent = await _create_intent()

    mock_client, captured = _mock_httpx_capture()
    with patch("app.services.webhook_service.httpx.AsyncClient",
               return_value=mock_client):
        async with async_session() as db:
            intent_db = (await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent.intent_id)
            )).scalar_one()
            await send_webhook(
                db, merchant_id=MERCHANT_ID, event="payment.completed",
                intent=intent_db,
                extra_payload=EVENT_EXTRAS["payment.completed"],
            )
            await db.commit()

    body, headers = captured["content"], captured["headers"]
    payload = json.loads(body)
    assert set(payload.keys()) == CONTRACT_KEYS | {"settlement"}
    for gone in REMOVED_KEYS:
        assert gone not in payload
    assert verify_webhook_signature(
        SECRET, headers[WEBHOOK_TIMESTAMP_HEADER], body,
        headers[WEBHOOK_SIGNATURE_HEADER],
    ) is True


@pytest.mark.asyncio
async def test_dispatch_event_lifecycle_path_same_shape():
    """_dispatch_event (lifecycle path): the persisted delivery payload is the
    same contract shape — no second shape can ship."""
    wh = await _create_webhook()
    intent = await _create_intent(status=IntentStatus.expired)

    async with async_session() as db:
        intent_db = (await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.intent_id == intent.intent_id)
        )).scalar_one()
        await _dispatch_event(
            db, merchant_id=MERCHANT_ID, event_type="payment.expired",
            intent=intent_db,
        )
        await db.commit()

        delivery = (await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.webhook_id == wh.id)
        )).scalar_one()
    assert set(delivery.payload.keys()) == CONTRACT_KEYS
    for gone in REMOVED_KEYS:
        assert gone not in delivery.payload


# ═══════════════════════════════════════════════════════════════
#  4. Indexer extras: no fee, no duplicate chain_id
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_indexer_finalize_extras_carry_no_fee_or_chain_id(monkeypatch):
    intent = await _create_intent(status=IntentStatus.pending)
    async with async_session() as db:
        s = PaymentSettlement(
            invoice_id=intent.onchain_invoice_id,
            merchant="0x" + "1" * 40,
            payer="0x" + "2" * 40,
            token="0x" + "3" * 40,
            amount=50_000000,
            fee=600000,
            chain_id=CHAIN_ID,
            tx_hash=intent.matched_tx_hash,
            log_index=0,
            block_number=100,
            block_hash="0x" + "ab" * 32,
            status=SettlementStatus.pending,
            intent_id=intent.intent_id,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sid = s.id

    seen = {}

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        seen["event"] = event
        seen["extra"] = extra_payload
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    monkeypatch.setattr(idx, "_validate_event_against_intent", lambda ev, intent: [])

    async with async_session() as db:
        s = (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.id == sid)
        )).scalar_one()
        await idx._finalize_settlement(db, s, CHAIN_ID)
        await db.commit()

    assert seen["event"] == "payment.completed"
    assert "fee" not in seen["extra"]        # deprecated: removed from the contract
    assert "chain_id" not in seen["extra"]   # now in the base payload, not an extra
    assert set(seen["extra"]).issubset({"tx_hash", "settlement", "split"})


# ═══════════════════════════════════════════════════════════════
#  5. Test-fire payload == production shape
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_test_fire_payload_matches_production_shape():
    wh = await _create_webhook()
    payload = _build_test_event_payload(wh)

    assert set(payload.keys()) == CONTRACT_KEYS
    for gone in REMOVED_KEYS:
        assert gone not in payload
    assert payload["event"] == "test"
    assert isinstance(payload["amount"], str)
    assert isinstance(payload["chain_id"], int)
    assert payload["event_id"].startswith("evt_")


# ═══════════════════════════════════════════════════════════════
#  6. Event-name contract: needs_review reachable, reversed subscribable
# ═══════════════════════════════════════════════════════════════

def test_finalize_event_type_maps_review_to_needs_review():
    class _Fake:
        completed_late = False

        def __init__(self, status):
            self.status = status

    assert _finalize_event_type(_Fake(IntentStatus.review)) == "payment.needs_review"
    assert _finalize_event_type(_Fake(IntentStatus.partial)) == "payment.partial"
    assert _finalize_event_type(_Fake(IntentStatus.overpaid)) == "payment.overpaid"
    assert _finalize_event_type(_Fake(IntentStatus.completed)) == "payment.completed"
    late = _Fake(IntentStatus.completed)
    late.completed_late = True
    assert _finalize_event_type(late) == "payment.completed_late"


def test_every_emitted_event_is_subscribable():
    """Every event the backend can emit must be registrable/filterable —
    payment.reversed used to fire without being in VALID_EVENTS."""
    emitted = {
        "payment.completed", "payment.completed_late", "payment.expired",
        "payment.expired_rejected", "payment.needs_review", "payment.partial",
        "payment.overpaid", "payment.reversed",
        # Reserved since the contract was written; first emitted by the TRON
        # watch-only matcher (slice 3) — payment.partial too, which until then
        # came only from the dead matcher.
        "payment.ambiguous",
    }
    assert emitted.issubset(VALID_EVENTS)
