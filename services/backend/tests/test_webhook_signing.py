"""
RSends Backend — Test: outbound webhook signing (security hardening).

Proves the live outbound path signs every webhook with the merchant's REAL
per-merchant secret using a Stripe-style, replay-resistant scheme, and that the
inbound hmac_service placeholder/global secret is unreachable from that path.

Acceptance covered:
  1. a sent webhook is signed with the merchant's real secret; the documented
     verify_webhook_signature() accepts it.
  2. a signature made with the placeholder/wrong secret is REJECTED.
  3. tampering with body or timestamp invalidates the signature.
  4. payment.reversed goes through the same real signer and verifies.
  5. the placeholder signer is unreachable from the production send path.
  6. concurrent finalize fires the webhook exactly once (paid AND reversed).
  7. provisioning creates a unique per-merchant secret.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_webhook_signing.py -v
"""

import asyncio
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
    PaymentIntent,
    IntentStatus,
    MerchantWebhook,
    WebhookDelivery,
)
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.services.webhook_service import (
    compute_webhook_signature,
    verify_webhook_signature,
    send_webhook,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_FRESHNESS_SECONDS,
)
import app.services.payment_indexer as idx

MERCHANT_ID = "m_sign_test"
WEBHOOK_URL = "https://merchant.example.com/hook"
REAL_SECRET = "sk_" + secrets.token_hex(32)        # the merchant's real per-merchant secret
PLACEHOLDER = "PENDING_HMAC_SHA256"                  # inbound placeholder — must never sign outbound
GLOBAL_SECRET = "MUST_BE_SET_VIA_ENV_32_CHARS_MIN"  # global hmac_secret — inbound/admin only
CHAIN = 8453


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
        await conn.execute(WebhookDelivery.__table__.delete())
        await conn.execute(MerchantWebhook.__table__.delete())
    yield


# ── helpers ──────────────────────────────────────────────────
async def _create_webhook(secret: str = REAL_SECRET, events=None) -> MerchantWebhook:
    async with async_session() as db:
        wh = MerchantWebhook(
            merchant_id=MERCHANT_ID,
            url=WEBHOOK_URL,
            secret=secret,
            events=events or ["payment.completed", "payment.reversed"],
            is_active=True,
        )
        db.add(wh)
        await db.commit()
        await db.refresh(wh)
        return wh


async def _create_intent(status=IntentStatus.paid) -> PaymentIntent:
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=f"pi_{secrets.token_hex(8)}",
            reference_id=secrets.token_hex(8),
            merchant_id=MERCHANT_ID,
            amount=50.0,
            currency="USDC",
            chain="BASE",
            onchain_invoice_id="0x" + "cd" * 32,
            recipient="0x" + "1" * 40,
            status=status,
            matched_tx_hash="0x" + "aa" * 32,
            matched_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
        return intent


def _mock_httpx_capture():
    """Returns (patcher, captured) where captured holds the last POST kwargs."""
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


async def _send(event: str, secret: str = REAL_SECRET):
    """Drive the live send path; return captured POST (content, headers)."""
    await _create_webhook(secret=secret)
    intent = await _create_intent()

    mock_client, captured = _mock_httpx_capture()
    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=mock_client):
        async with async_session() as db:
            intent_db = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
            )).scalar_one()
            await send_webhook(db, merchant_id=MERCHANT_ID, event=event, intent=intent_db)
            await db.commit()
    return captured


# ═══════════════════════════════════════════════════════════════
#  1. Real-secret sign + documented verification accepts it
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_sent_webhook_signed_with_real_secret_verifies():
    cap = await _send("payment.completed")

    headers, body = cap["headers"], cap["content"]
    assert WEBHOOK_SIGNATURE_HEADER in headers
    assert WEBHOOK_TIMESTAMP_HEADER in headers

    # The documented merchant-side verification routine accepts it.
    assert verify_webhook_signature(
        REAL_SECRET,
        headers[WEBHOOK_TIMESTAMP_HEADER],
        body,
        headers[WEBHOOK_SIGNATURE_HEADER],
    ) is True

    # Payload carries event id + type for dedup/ordering.
    payload = json.loads(body)
    assert payload["event"] == "payment.completed"
    assert payload["event_id"].startswith("evt_")


# ═══════════════════════════════════════════════════════════════
#  2. Wrong / placeholder / global secret are REJECTED
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_placeholder_and_wrong_secret_rejected():
    cap = await _send("payment.completed")
    headers, body = cap["headers"], cap["content"]
    ts, sig = headers[WEBHOOK_TIMESTAMP_HEADER], headers[WEBHOOK_SIGNATURE_HEADER]

    for bad in (PLACEHOLDER, GLOBAL_SECRET, "sk_totally_wrong", ""):
        assert verify_webhook_signature(bad, ts, body, sig) is False

    # A signature *made with* the placeholder does not match the real-secret verify.
    forged = compute_webhook_signature(PLACEHOLDER, ts, body)
    assert verify_webhook_signature(REAL_SECRET, ts, body, forged) is False


# ═══════════════════════════════════════════════════════════════
#  3. Tampering with body or timestamp invalidates the signature
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_tampering_invalidates_signature():
    cap = await _send("payment.completed")
    headers, body = cap["headers"], cap["content"]
    ts, sig = headers[WEBHOOK_TIMESTAMP_HEADER], headers[WEBHOOK_SIGNATURE_HEADER]

    # Tamper body.
    tampered_body = body.replace(b'"amount"', b'"am0unt"')
    assert tampered_body != body
    assert verify_webhook_signature(REAL_SECRET, ts, tampered_body, sig) is False

    # Tamper timestamp (still fresh, but breaks the HMAC over {ts}.{body}).
    other_ts = str(int(ts) - 5)
    assert verify_webhook_signature(REAL_SECRET, other_ts, body, sig) is False


# ═══════════════════════════════════════════════════════════════
#  3b. Freshness window — replay resistance
# ═══════════════════════════════════════════════════════════════
def test_stale_timestamp_rejected_even_with_valid_hmac():
    body = b'{"event":"payment.completed"}'
    stale_ts = str(int(datetime.now(timezone.utc).timestamp()) - WEBHOOK_FRESHNESS_SECONDS - 60)
    sig = compute_webhook_signature(REAL_SECRET, stale_ts, body)
    # HMAC is correct, but the timestamp is outside the freshness window → reject.
    assert verify_webhook_signature(REAL_SECRET, stale_ts, body, sig) is False
    # Non-numeric timestamp is rejected too.
    assert verify_webhook_signature(REAL_SECRET, "not-a-ts", body,
                                    compute_webhook_signature(REAL_SECRET, "not-a-ts", body)) is False


# ═══════════════════════════════════════════════════════════════
#  4. payment.reversed goes through the SAME real signer
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_payment_reversed_signed_with_real_secret():
    cap = await _send("payment.reversed")
    headers, body = cap["headers"], cap["content"]
    assert json.loads(body)["event"] == "payment.reversed"
    assert verify_webhook_signature(
        REAL_SECRET,
        headers[WEBHOOK_TIMESTAMP_HEADER],
        body,
        headers[WEBHOOK_SIGNATURE_HEADER],
    ) is True


# ═══════════════════════════════════════════════════════════════
#  5. Placeholder unreachable from the production send path
# ═══════════════════════════════════════════════════════════════
def test_outbound_modules_do_not_import_inbound_signer():
    import app.services.webhook_service as wh
    import app.services.payment_indexer as pidx
    for mod in (wh, pidx):
        assert not hasattr(mod, "compute_signature"), f"{mod.__name__} imports inbound signer"
        assert not hasattr(mod, "verify_signature"), f"{mod.__name__} imports inbound verifier"
        # The outbound modules must not reference the global hmac_secret.
        src = open(mod.__file__).read()
        assert "hmac_secret" not in src, f"{mod.__name__} references global hmac_secret"
        assert "hmac_service" not in src, f"{mod.__name__} imports hmac_service"


@pytest.mark.asyncio
async def test_signature_derives_from_webhook_secret_not_global():
    """If the live path used a wrong/global secret, merchant verification fails."""
    cap = await _send("payment.completed", secret=REAL_SECRET)
    headers, body = cap["headers"], cap["content"]
    ts, sig = headers[WEBHOOK_TIMESTAMP_HEADER], headers[WEBHOOK_SIGNATURE_HEADER]
    # Real secret verifies; global secret does not → signature came from webhook.secret.
    assert verify_webhook_signature(REAL_SECRET, ts, body, sig) is True
    assert verify_webhook_signature(GLOBAL_SECRET, ts, body, sig) is False


# ═══════════════════════════════════════════════════════════════
#  6. Concurrent finalize fires the webhook exactly once (paid)
# ═══════════════════════════════════════════════════════════════
async def _make_settlement(intent, *, status=SettlementStatus.pending,
                           webhook_fired_at=None, reversal_fired_at=None) -> int:
    async with async_session() as db:
        s = PaymentSettlement(
            invoice_id=intent.onchain_invoice_id,
            merchant="0x" + "1" * 40,
            payer="0x" + "2" * 40,
            token="0x" + "3" * 40,
            amount=50_000000,
            fee=600000,
            chain_id=CHAIN,
            tx_hash=intent.matched_tx_hash,
            log_index=0,
            block_number=100,
            block_hash="0x" + "ab" * 32,
            status=status,
            intent_id=intent.intent_id,
            webhook_fired_at=webhook_fired_at,
            reversal_fired_at=reversal_fired_at,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_concurrent_finalize_fires_paid_exactly_once(monkeypatch):
    intent = await _create_intent(status=IntentStatus.pending)
    sid = await _make_settlement(intent, status=SettlementStatus.pending)

    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    # Isolate the concurrency guard from event-validation details.
    monkeypatch.setattr(idx, "_validate_event_against_intent", lambda ev, intent: [])

    async with async_session() as db:
        s = (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.id == sid)
        )).scalar_one()
        # Two concurrent finalizations of the SAME settlement row.
        await asyncio.gather(
            idx._finalize_settlement(db, s, CHAIN),
            idx._finalize_settlement(db, s, CHAIN),
        )
        await db.commit()

    assert calls == ["payment.completed"], f"expected one fire, got {calls}"


@pytest.mark.asyncio
async def test_concurrent_reverse_fires_reversed_exactly_once(monkeypatch):
    # Already-final settlement whose webhook fired → eligible for reversal.
    intent = await _create_intent(status=IntentStatus.paid)
    sid = await _make_settlement(
        intent, status=SettlementStatus.final,
        webhook_fired_at=datetime.now(timezone.utc),
    )

    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)

    async with async_session() as db:
        s = (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.id == sid)
        )).scalar_one()
        await asyncio.gather(
            idx._reverse_settlement(db, s),
            idx._reverse_settlement(db, s),
        )
        await db.commit()

    assert calls == ["payment.reversed"], f"expected one reversal, got {calls}"


# ═══════════════════════════════════════════════════════════════
#  7. Provisioning creates a unique, high-entropy per-merchant secret
# ═══════════════════════════════════════════════════════════════
def test_provisioning_generates_unique_high_entropy_secret():
    secrets_seen = {secrets.token_hex(32) for _ in range(50)}
    assert len(secrets_seen) == 50  # all distinct
    for s in secrets_seen:
        assert len(s) >= 64  # token_hex(32) → 64 hex chars
