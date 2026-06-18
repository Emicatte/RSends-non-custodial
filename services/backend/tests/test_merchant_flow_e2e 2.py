"""
RPagos Backend — Merchant Flow E2E Tests.

Testa l'intero flusso merchant end-to-end contro il server locale.
Richiede il backend in esecuzione su localhost:8000 con RSEND_DEV_AUTH_BYPASS=1.

Run:
    pytest tests/test_merchant_flow_e2e.py -v -m "not slow"

Pre-requisiti:
    1. Backend avviato: cd rpagos-backend && RSEND_DEV_AUTH_BYPASS=1 ENVIRONMENT=development python3 -m app.main
    2. DEPOSIT_MASTER_SEED impostato in .env (serve per generare deposit address)
    3. Nessun Redis richiesto per i test (fail-open idempotency)

Il test legge HMAC_SECRET dal .env del backend per calcolare le firme.
"""

import asyncio
import hashlib
import hmac as hmac_mod
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

# ── Config ────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
API_KEY = f"rsend_live_{secrets.token_hex(24)}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _read_hmac_secret() -> str:
    """Legge HMAC_SECRET dal .env del backend."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("HMAC_SECRET=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("HMAC_SECRET", "change-me-in-production")


HMAC_SECRET = _read_hmac_secret()


def compute_tx_signature(
    fiscal_ref: str,
    tx_hash: str,
    gross_amount: str,
    currency: str,
    timestamp: str,
) -> str:
    """Calcola HMAC-SHA256 identico a quello del backend."""
    message = f"{fiscal_ref}|{tx_hash}|{gross_amount}|{currency}|{timestamp}"
    return hmac_mod.new(
        HMAC_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=15.0,
        follow_redirects=True,
    )


async def _health_or_skip():
    """Verifica backend raggiungibile, altrimenti skip."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5.0) as c:
        try:
            resp = await c.get("/health")
            assert resp.status_code == 200
        except (httpx.ConnectError, AssertionError):
            pytest.skip(
                "Backend non raggiungibile su localhost:8000. "
                "Avvia con: cd rpagos-backend && RSEND_DEV_AUTH_BYPASS=1 ENVIRONMENT=development python3 -m app.main"
            )


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

async def create_intent(client: httpx.AsyncClient, **kwargs) -> dict:
    """Crea un payment intent, ritorna la response dict."""
    defaults = {"amount": 100.0, "currency": "USDC", "chain": "BASE"}
    defaults.update(kwargs)
    resp = await client.post(
        "/api/v1/merchant/payment-intent",
        headers=AUTH_HEADERS,
        json=defaults,
    )
    assert resp.status_code == 200, f"Create intent failed: {resp.text}"
    return resp.json()


async def send_tx(client: httpx.AsyncClient, *, recipient, gross_amount, currency) -> httpx.Response:
    """Invia TX callback con HMAC valido."""
    tx_hash = "0x" + secrets.token_hex(32)
    fiscal_ref = f"E2E-{secrets.token_hex(4)}"
    timestamp = datetime.now(timezone.utc).isoformat()

    signature = compute_tx_signature(
        fiscal_ref=fiscal_ref,
        tx_hash=tx_hash,
        gross_amount=str(gross_amount),
        currency=currency,
        timestamp=timestamp,
    )

    resp = await client.post(
        "/api/v1/tx/callback",
        json={
            "fiscal_ref": fiscal_ref,
            "tx_hash": tx_hash,
            "gross_amount": gross_amount,
            "net_amount": gross_amount,
            "fee_amount": 0.0,
            "currency": currency,
            "network": "BASE_MAINNET",
            "recipient": recipient,
            "status": "completed",
            "timestamp": timestamp,
            "x_signature": signature,
        },
    )
    return resp


# ═══════════════════════════════════════════════════════════════════
#  TEST 1: Full Payment Flow (Happy Path)
# ═══════════════════════════════════════════════════════════════════

async def test_full_payment_flow():
    """
    Flusso completo in un unico test:
    1. Registra webhook
    2. Crea intent → deposit_address unico
    3. TX callback su deposit_address → match + webhook fired
    4. Verifica intent completed
    5. Stessa TX di nuovo → idempotenza (no double match)
    """
    await _health_or_skip()

    async with await _make_client() as client:
        # ── 1. Registra webhook ──────────────────────────────
        resp = await client.post(
            "/api/v1/merchant/webhook/register",
            headers=AUTH_HEADERS,
            json={
                "url": "https://httpbin.org/post",
                "events": ["payment.completed", "payment.expired"],
            },
        )
        assert resp.status_code == 200, f"Register failed: {resp.text}"
        wh = resp.json()
        assert "webhook_id" in wh
        assert "secret" in wh
        assert wh["is_active"] is True

        # ── 2. Crea intent ───────────────────────────────────
        data = await create_intent(
            client,
            amount=25.50,
            currency="USDC",
            expires_in_minutes=30,
            metadata={"order_id": "ORD-E2E-001"},
        )
        assert data["status"] == "pending"
        assert data["intent_id"].startswith("pi_")
        assert data["metadata"] == {"order_id": "ORD-E2E-001"}

        deposit_addr = data.get("deposit_address")
        if not deposit_addr:
            pytest.skip("deposit_address null — DEPOSIT_MASTER_SEED non impostato in .env")

        intent_id = data["intent_id"]
        assert deposit_addr.startswith("0x")

        # Unicità deposit_address
        data2 = await create_intent(client, amount=10.0, currency="USDC")
        assert data2.get("deposit_address") != deposit_addr

        # ── 3. TX callback → match ──────────────────────────
        tx_hash = "0x" + secrets.token_hex(32)
        fiscal_ref = f"E2E-{secrets.token_hex(4)}"
        timestamp = datetime.now(timezone.utc).isoformat()

        signature = compute_tx_signature(
            fiscal_ref=fiscal_ref,
            tx_hash=tx_hash,
            gross_amount="25.5",
            currency="USDC",
            timestamp=timestamp,
        )

        resp = await client.post(
            "/api/v1/tx/callback",
            json={
                "fiscal_ref": fiscal_ref,
                "tx_hash": tx_hash,
                "gross_amount": 25.5,
                "net_amount": 25.5,
                "fee_amount": 0.0,
                "currency": "USDC",
                "network": "BASE_MAINNET",
                "recipient": deposit_addr,
                "status": "completed",
                "timestamp": timestamp,
                "x_signature": signature,
            },
        )
        assert resp.status_code == 200, f"TX callback failed: {resp.text}"
        tx_data = resp.json()
        assert tx_data["status"] == "success"
        assert tx_data["matched_intent_id"] == intent_id
        assert tx_data["webhook_triggered"] is True

        # ── 4. Verifica completed ────────────────────────────
        resp = await client.get(
            f"/api/v1/merchant/payment-intent/{intent_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        intent = resp.json()
        assert intent["status"] == "completed"
        assert intent["matched_tx_hash"] == tx_hash.lower()
        assert intent["amount_received"] == "25.5"
        assert intent["completed_at"] is not None

        # ── 5. Idempotenza: stessa TX ────────────────────────
        fiscal_ref2 = f"E2E-DUP-{secrets.token_hex(4)}"
        timestamp2 = datetime.now(timezone.utc).isoformat()
        sig2 = compute_tx_signature(
            fiscal_ref=fiscal_ref2,
            tx_hash=tx_hash,
            gross_amount="25.5",
            currency="USDC",
            timestamp=timestamp2,
        )

        resp = await client.post(
            "/api/v1/tx/callback",
            json={
                "fiscal_ref": fiscal_ref2,
                "tx_hash": tx_hash,
                "gross_amount": 25.5,
                "net_amount": 25.5,
                "fee_amount": 0.0,
                "currency": "USDC",
                "network": "BASE_MAINNET",
                "recipient": deposit_addr,
                "status": "completed",
                "timestamp": timestamp2,
                "x_signature": sig2,
            },
        )
        if resp.status_code == 409:
            assert "DUPLICATE_TX" in resp.text
        elif resp.status_code == 200:
            d = resp.json()
            assert d.get("webhook_triggered") is False or d.get("matched_intent_id") is None


# ═══════════════════════════════════════════════════════════════════
#  TEST 2: Cancelled intent rejects late TX
# ═══════════════════════════════════════════════════════════════════

async def test_cancelled_intent_rejects_tx():
    """Cancella un intent pending, poi invia TX → no match."""
    await _health_or_skip()

    async with await _make_client() as client:
        data = await create_intent(client, amount=10.0, currency="ETH")
        intent_id = data["intent_id"]
        deposit_addr = data.get("deposit_address")

        if not deposit_addr:
            pytest.skip("deposit_address null — DEPOSIT_MASTER_SEED non impostato")

        # Verifica pending
        resp = await client.get(
            f"/api/v1/merchant/payment-intent/{intent_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

        # Cancella
        resp = await client.post(
            f"/api/v1/merchant/payment-intent/{intent_id}/cancel",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # TX tardiva → no match
        resp = await send_tx(client, recipient=deposit_addr, gross_amount=10.0, currency="ETH")
        assert resp.status_code == 200
        d = resp.json()
        assert d["matched_intent_id"] is None
        assert d["webhook_triggered"] is False


# ═══════════════════════════════════════════════════════════════════
#  TEST 3: Real expiration (5 min wait)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.slow
async def test_expired_intent_rejects_late_tx():
    """Crea intent con 5 min expiry, aspetta, verifica expired, TX → no match."""
    await _health_or_skip()

    async with await _make_client() as client:
        data = await create_intent(client, amount=5.0, currency="USDC", expires_in_minutes=5)
        intent_id = data["intent_id"]
        deposit_addr = data.get("deposit_address")

        if not deposit_addr:
            pytest.skip("deposit_address null")

        # Aspetta scadenza
        await asyncio.sleep(310)

        # GET → auto-expire
        resp = await client.get(
            f"/api/v1/merchant/payment-intent/{intent_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

        # TX tardiva
        resp = await send_tx(client, recipient=deposit_addr, gross_amount=5.0, currency="USDC")
        assert resp.status_code == 200
        assert resp.json()["matched_intent_id"] is None
        assert resp.json()["webhook_triggered"] is False


# ═══════════════════════════════════════════════════════════════════
#  TEST 4: Edge Cases
# ═══════════════════════════════════════════════════════════════════

async def test_currency_mismatch():
    """Intent in USDC, TX in ETH → no match."""
    await _health_or_skip()

    async with await _make_client() as client:
        data = await create_intent(client, amount=100.0, currency="USDC")
        deposit_addr = data.get("deposit_address")
        if not deposit_addr:
            pytest.skip("deposit_address null")

        resp = await send_tx(client, recipient=deposit_addr, gross_amount=100.0, currency="ETH")
        assert resp.status_code == 200
        assert resp.json()["matched_intent_id"] is None


async def test_underpayment():
    """50% underpayment → no match."""
    await _health_or_skip()

    async with await _make_client() as client:
        data = await create_intent(client, amount=100.0, currency="USDC")
        deposit_addr = data.get("deposit_address")
        if not deposit_addr:
            pytest.skip("deposit_address null")

        resp = await send_tx(client, recipient=deposit_addr, gross_amount=50.0, currency="USDC")
        assert resp.status_code == 200
        assert resp.json()["matched_intent_id"] is None


async def test_invalid_hmac():
    """HMAC invalido → 401."""
    await _health_or_skip()

    async with await _make_client() as client:
        tx_hash = "0x" + secrets.token_hex(32)
        fiscal_ref = f"E2E-HMAC-{secrets.token_hex(4)}"
        timestamp = datetime.now(timezone.utc).isoformat()

        resp = await client.post(
            "/api/v1/tx/callback",
            json={
                "fiscal_ref": fiscal_ref,
                "tx_hash": tx_hash,
                "gross_amount": 10.0,
                "net_amount": 10.0,
                "fee_amount": 0.0,
                "currency": "USDC",
                "network": "BASE_MAINNET",
                "recipient": "0x" + "0" * 40,
                "status": "completed",
                "timestamp": timestamp,
                "x_signature": "invalid_signature_here",
            },
        )
        assert resp.status_code == 401
        assert "INVALID_SIGNATURE" in resp.text


async def test_overpayment():
    """150% overpayment → match con overpaid_amount."""
    await _health_or_skip()

    async with await _make_client() as client:
        data = await create_intent(client, amount=50.0, currency="USDC", allow_overpayment=True)
        intent_id = data["intent_id"]
        deposit_addr = data.get("deposit_address")
        if not deposit_addr:
            pytest.skip("deposit_address null")

        resp = await send_tx(client, recipient=deposit_addr, gross_amount=75.0, currency="USDC")
        assert resp.status_code == 200
        assert resp.json()["matched_intent_id"] == intent_id

        # Verifica overpaid_amount
        resp = await client.get(
            f"/api/v1/merchant/payment-intent/{intent_id}",
            headers=AUTH_HEADERS,
        )
        d = resp.json()
        assert d["status"] == "completed"
        assert d["overpaid_amount"] == "25.0"
        assert d["amount_received"] == "75.0"
