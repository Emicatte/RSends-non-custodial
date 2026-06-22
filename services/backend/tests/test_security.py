"""
RPagos Backend — Security Test Suite.

Tests per:
  - HMAC verification (real + anti-replay)
  - Rate limiting (Redis fallback → in-memory)
  - Input sanitization (payload size, validators)
  - Currency/chain_id whitelist
"""

import time
import pytest
import pytest_asyncio
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.session import engine
from app.models.db_models import Base
from app.services.hmac_service import (
    compute_signature,
    verify_signature,
    _check_timestamp_freshness,
    REPLAY_WINDOW_SECONDS,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test. Reset rate limiter."""
    # Reset in-memory rate limiter tra i test
    from app.middleware.rate_limit import _memory_limiter
    _memory_limiter._buckets.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_counter = 0


def make_valid_payload(**overrides) -> dict:
    """Genera un payload valido con HMAC reale."""
    global _counter
    _counter += 1
    ts = datetime.now(timezone.utc).isoformat()
    fiscal_ref = f"RP-SEC-{_counter:06d}"
    tx_hash = "0x" + f"{_counter:064x}"
    gross = 100.0

    sig = compute_signature(
        fiscal_ref=fiscal_ref,
        tx_hash=tx_hash,
        amount=str(gross),
        currency="USDC",
        timestamp=ts,
    )

    base = {
        "fiscal_ref": fiscal_ref,
        "payment_ref": "PAY-SEC-001",
        "tx_hash": tx_hash,
        "gross_amount": gross,
        "net_amount": gross * 0.995,
        "fee_amount": gross * 0.005,
        "currency": "USDC",
        "eur_value": gross * 0.92,
        "network": "BASE_MAINNET",
        "is_testnet": False,
        "recipient": "0x" + "ab" * 20,
        "status": "completed",
        "timestamp": ts,
        "x_signature": sig,
        "compliance_record": {
            "compliance_id": f"CMP-SEC-{_counter:06d}",
            "block_timestamp": ts,
            "fiat_rate": 0.92,
            "asset": "USDC",
            "fiat_gross": gross * 0.92,
            "ip_jurisdiction": "IT",
            "mica_applicable": True,
            "fiscal_ref": fiscal_ref,
            "network": "BASE_MAINNET",
        },
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════
#  Test: HMAC Service — compute_signature
# ═══════════════════════════════════════════════════════════════

class TestHmacCompute:

    def test_compute_signature_deterministic(self):
        """La stessa input produce la stessa firma."""
        sig1 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01T00:00:00Z")
        sig2 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01T00:00:00Z")
        assert sig1 == sig2

    def test_compute_signature_is_hex(self):
        """La firma è un hex string di 64 caratteri (SHA-256)."""
        sig = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01T00:00:00Z")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_different_inputs_different_signatures(self):
        """Input diversi producono firme diverse."""
        sig1 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01T00:00:00Z")
        sig2 = compute_signature("REF2", "0xabc", "100.0", "USDC", "2025-01-01T00:00:00Z")
        assert sig1 != sig2


# ═══════════════════════════════════════════════════════════════
#  Test: HMAC Service — verify_signature
# ═══════════════════════════════════════════════════════════════

class TestHmacVerify:

    def test_valid_signature_passes(self):
        """Una firma valida viene accettata."""
        ts = datetime.now(timezone.utc).isoformat()
        sig = compute_signature("REF1", "0xabc", "100.0", "USDC", ts)
        assert verify_signature(sig, "REF1", "0xabc", "100.0", "USDC", ts) is True

    def test_invalid_signature_fails(self):
        """Una firma non valida viene rifiutata."""
        ts = datetime.now(timezone.utc).isoformat()
        assert verify_signature("bad_signature", "REF1", "0xabc", "100.0", "USDC", ts) is False

    @pytest.mark.skip(reason="Obsolete: the non-custodial fork hardened hmac_service to ALWAYS reject the PENDING_HMAC_SHA256 placeholder, even in debug (see hmac_service.py). This asserts the removed pre-fork behavior; test_production_rejects_placeholder covers the current contract. Pre-existing, unrelated to the fee model.")
    def test_debug_accepts_placeholder(self):
        """In debug mode, PENDING_HMAC_SHA256 è accettato."""
        with patch("app.services.hmac_service.get_settings") as mock:
            mock.return_value.debug = True
            mock.return_value.hmac_secret = "test"
            assert verify_signature(
                "PENDING_HMAC_SHA256", "REF1", "0xabc", "100.0", "USDC", "ts"
            ) is True

    def test_production_rejects_placeholder(self):
        """In produzione, PENDING_HMAC_SHA256 NON è accettato."""
        with patch("app.services.hmac_service.get_settings") as mock:
            mock.return_value.debug = False
            mock.return_value.hmac_secret = "test"
            assert verify_signature(
                "PENDING_HMAC_SHA256", "REF1", "0xabc", "100.0", "USDC",
                datetime.now(timezone.utc).isoformat(),
            ) is False

    def test_tampered_amount_fails(self):
        """Se l'importo viene alterato, la firma non corrisponde."""
        ts = datetime.now(timezone.utc).isoformat()
        sig = compute_signature("REF1", "0xabc", "100.0", "USDC", ts)
        # Verifica con amount diverso
        assert verify_signature(sig, "REF1", "0xabc", "200.0", "USDC", ts) is False


# ═══════════════════════════════════════════════════════════════
#  Test: Anti-replay
# ═══════════════════════════════════════════════════════════════

class TestAntiReplay:

    def test_fresh_timestamp_passes(self):
        """Un timestamp recente passa la verifica."""
        ts = datetime.now(timezone.utc).isoformat()
        assert _check_timestamp_freshness(ts) is True

    def test_old_timestamp_fails(self):
        """Un timestamp più vecchio di 5 minuti viene rifiutato."""
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        assert _check_timestamp_freshness(old.isoformat()) is False

    def test_just_within_window(self):
        """Un timestamp appena dentro la finestra di 5 minuti passa."""
        ts = datetime.now(timezone.utc) - timedelta(seconds=REPLAY_WINDOW_SECONDS - 10)
        assert _check_timestamp_freshness(ts.isoformat()) is True

    def test_invalid_format_fails(self):
        """Un timestamp non parsabile viene rifiutato."""
        assert _check_timestamp_freshness("not-a-date") is False

    def test_z_suffix_handled(self):
        """Il suffisso Z viene gestito correttamente."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _check_timestamp_freshness(ts) is True

    def test_production_rejects_old_hmac(self):
        """In produzione, HMAC con timestamp vecchio viene rifiutato anche se la firma è corretta."""
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        sig = compute_signature("REF1", "0xabc", "100.0", "USDC", old_ts)

        with patch("app.services.hmac_service.get_settings") as mock:
            mock.return_value.debug = False
            mock.return_value.hmac_secret = "change-me-in-production"
            assert verify_signature(sig, "REF1", "0xabc", "100.0", "USDC", old_ts) is False


# ═══════════════════════════════════════════════════════════════
#  Test: Rate Limiting — In-memory fallback
# ═══════════════════════════════════════════════════════════════

class TestRateLimitInMemory:

    def test_inmemory_allows_within_limit(self):
        """Richieste entro il limite vengono ammesse."""
        from app.middleware.rate_limit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter()
        for _ in range(5):
            allowed, remaining, _ = limiter.check("test:key", 10, 60)
            assert allowed is True
            assert remaining >= 0

    def test_inmemory_blocks_over_limit(self):
        """Richieste oltre il limite vengono bloccate."""
        from app.middleware.rate_limit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter()
        for _ in range(10):
            limiter.check("test:key2", 10, 60)

        allowed, remaining, _ = limiter.check("test:key2", 10, 60)
        assert allowed is False
        assert remaining == 0

    def test_inmemory_different_keys_independent(self):
        """Chiavi diverse hanno limiti indipendenti."""
        from app.middleware.rate_limit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter()
        for _ in range(10):
            limiter.check("test:a", 10, 60)

        allowed, _, _ = limiter.check("test:b", 10, 60)
        assert allowed is True


# ═══════════════════════════════════════════════════════════════
#  Test: Rate Limiting — via API
# ═══════════════════════════════════════════════════════════════

class TestRateLimitAPI:

    @pytest.mark.asyncio
    async def test_health_not_rate_limited(self, client: AsyncClient):
        """/health non ha rate limit."""
        for _ in range(100):
            r = await client.get("/health")
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self, client: AsyncClient):
        """Le risposte includono i rate limit headers."""
        payload = make_valid_payload()
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert "X-RateLimit-Limit" in r.headers
        assert "X-RateLimit-Remaining" in r.headers
        assert "X-RateLimit-Reset" in r.headers


# ═══════════════════════════════════════════════════════════════
#  Test: Input Sanitization — Payload size
# ═══════════════════════════════════════════════════════════════

class TestInputSanitization:

    @pytest.mark.asyncio
    async def test_oversized_payload_rejected(self, client: AsyncClient):
        """Un payload > 1MB viene rifiutato con 413."""
        huge = {"data": "x" * (1024 * 1024 + 1)}
        r = await client.post(
            "/api/v1/tx/callback",
            json=huge,
            headers={"content-length": str(2 * 1024 * 1024)},
        )
        assert r.status_code == 413
        assert r.json()["error"] == "PAYLOAD_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_normal_payload_passes(self, client: AsyncClient):
        """Un payload normale passa la sanitization."""
        payload = make_valid_payload()
        r = await client.post("/api/v1/tx/callback", json=payload)
        # Non deve essere 413
        assert r.status_code != 413


# ═══════════════════════════════════════════════════════════════
#  Test: Pydantic Validators — Currency whitelist
# ═══════════════════════════════════════════════════════════════

class TestCurrencyWhitelist:

    @pytest.mark.asyncio
    async def test_valid_currency_accepted(self, client: AsyncClient):
        """Una currency nella whitelist viene accettata."""
        payload = make_valid_payload(currency="USDC")
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code != 422  # Non errore di validazione

    @pytest.mark.asyncio
    async def test_invalid_currency_rejected(self, client: AsyncClient):
        """Una currency non nella whitelist viene rifiutata con 422."""
        payload = make_valid_payload(currency="SHIB")
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_all_allowed_currencies(self, client: AsyncClient):
        """Tutte le valute nella whitelist sono accettate."""
        for currency in ["ETH", "USDC", "USDT", "DAI", "cbBTC", "DEGEN"]:
            payload = make_valid_payload(currency=currency)
            r = await client.post("/api/v1/tx/callback", json=payload)
            assert r.status_code != 422, f"Currency {currency} was rejected"


# ═══════════════════════════════════════════════════════════════
#  Test: Pydantic Validators — tx_hash, recipient
# ═══════════════════════════════════════════════════════════════

class TestAddressValidation:

    @pytest.mark.asyncio
    async def test_invalid_tx_hash_rejected(self, client: AsyncClient):
        """Un tx_hash non valido viene rifiutato."""
        payload = make_valid_payload(tx_hash="not_a_hash")
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_recipient_rejected(self, client: AsyncClient):
        """Un recipient non valido viene rifiutato."""
        payload = make_valid_payload(recipient="not_an_address")
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_short_tx_hash_rejected(self, client: AsyncClient):
        """Un tx_hash troppo corto viene rifiutato."""
        payload = make_valid_payload(tx_hash="0xabc")
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════
#  Test: Full API flow with real HMAC
# ═══════════════════════════════════════════════════════════════

class TestFullHmacFlow:

    @pytest.mark.asyncio
    async def test_real_hmac_accepted(self, client: AsyncClient):
        """Un payload con HMAC reale viene accettato."""
        payload = make_valid_payload()
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    @pytest.mark.asyncio
    async def test_wrong_hmac_rejected(self, client: AsyncClient):
        """Un payload con HMAC sbagliato viene rifiutato con 401."""
        payload = make_valid_payload()
        payload["x_signature"] = "a" * 64  # Wrong HMAC
        r = await client.post("/api/v1/tx/callback", json=payload)
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "INVALID_SIGNATURE"
