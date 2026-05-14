"""
RPagos Backend Core — Test Suite.

Testa tutti gli endpoint e i servizi usando SQLite in-memory.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from app.main import app
from app.db.session import engine, async_session, init_db
from app.models.db_models import Base
from app.services.hmac_service import compute_signature


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    global _payload_counter
    _payload_counter = 0
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
    """Client HTTP asincrono per testare l'API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_payload_counter = 0

def make_payload(
    fiscal_ref: str = "RP-2025-TEST-001",
    tx_hash: str = "0x" + "a1b2c3d4" * 8,
    gross: float = 100.0,
    **overrides,
) -> dict:
    """Genera un payload di test valido con compliance_id unico."""
    global _payload_counter
    _payload_counter += 1
    ts = datetime.now(timezone.utc).isoformat()
    base = {
        "fiscal_ref": fiscal_ref,
        "payment_ref": "PAY-TEST-001",
        "tx_hash": tx_hash,
        "gross_amount": gross,
        "net_amount": gross * 0.995,
        "fee_amount": gross * 0.005,
        "currency": "USDC",
        "eur_value": gross * 0.92,
        "network": "BASE_MAINNET",
        "is_testnet": False,
        "recipient": "0x" + "1234567890abcdef" * 2 + "12345678",
        "status": "completed",
        "timestamp": ts,
        "x_signature": "PENDING_HMAC_SHA256",  # Accepted in debug mode
        "compliance_record": {
            "compliance_id": f"CMP-{fiscal_ref}-{_payload_counter:06d}",
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
#  Test: Health Check
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


# ═══════════════════════════════════════════════════════════════
#  Test: POST /api/v1/tx/callback
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_callback_success(client: AsyncClient):
    """Una transazione valida viene salvata correttamente."""
    payload = make_payload()
    r = await client.post("/api/v1/tx/callback", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["compliance_logged"] is True


@pytest.mark.asyncio
async def test_callback_duplicate_rejected(client: AsyncClient):
    """Una TX duplicata viene rifiutata con 409."""
    payload = make_payload()
    r1 = await client.post("/api/v1/tx/callback", json=payload)
    assert r1.status_code == 200

    r2 = await client.post("/api/v1/tx/callback", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_callback_invalid_tx_hash(client: AsyncClient):
    """Un tx_hash non valido viene rifiutato dalla validazione Pydantic."""
    payload = make_payload(tx_hash="not-a-valid-hash")
    r = await client.post("/api/v1/tx/callback", json=payload)
    assert r.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_callback_without_compliance(client: AsyncClient):
    """TX senza compliance record — comunque accettata."""
    payload = make_payload(
        fiscal_ref="RP-2025-NO-COMP",
        tx_hash="0x" + "ff" * 32,
    )
    payload.pop("compliance_record")
    r = await client.post("/api/v1/tx/callback", json=payload)
    assert r.status_code == 200
    assert r.json()["compliance_logged"] is False


# ═══════════════════════════════════════════════════════════════
#  Test: GET /api/v1/tx/{fiscal_ref}
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_transaction(client: AsyncClient):
    """Recupera una TX appena inserita."""
    payload = make_payload()
    await client.post("/api/v1/tx/callback", json=payload)

    r = await client.get(f"/api/v1/tx/{payload['fiscal_ref']}")
    assert r.status_code == 200
    assert r.json()["tx_hash"] == payload["tx_hash"].lower()


@pytest.mark.asyncio
async def test_get_transaction_not_found(client: AsyncClient):
    r = await client.get("/api/v1/tx/NON-ESISTE")
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Test: GET /api/v1/anomalies
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_anomaly_empty_db(client: AsyncClient):
    """Con poche TX, nessuna anomalia."""
    r = await client.get("/api/v1/anomalies?window_hours=24")
    assert r.status_code == 200
    data = r.json()
    assert data["anomalies_found"] == 0


@pytest.mark.asyncio
async def test_anomaly_with_data(client: AsyncClient):
    """Inserisce TX direttamente in DB e verifica che l'analisi funzioni."""
    from app.db.session import async_session as _session
    from app.models.db_models import TransactionLog, TxStatus

    async with _session() as session:
        for i in range(15):
            tx = TransactionLog(
                fiscal_ref=f"RP-ANOM-{i:03d}",
                tx_hash=f"0x{i:064x}",
                gross_amount=100.0 + (i * 2),
                net_amount=(100.0 + (i * 2)) * 0.995,
                fee_amount=(100.0 + (i * 2)) * 0.005,
                currency="USDC",
                network="BASE_MAINNET",
                status=TxStatus.completed,
                x_signature="test",
                signature_valid=True,
                tx_timestamp=datetime.now(timezone.utc),
            )
            session.add(tx)
        await session.commit()

    r = await client.get("/api/v1/anomalies?window_hours=1")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  Test: HMAC Service
# ═══════════════════════════════════════════════════════════════

def test_hmac_compute():
    """La firma HMAC è deterministica."""
    sig1 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01")
    sig2 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01")
    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 hex digest


def test_hmac_different_inputs():
    """Input diversi → firme diverse."""
    sig1 = compute_signature("REF1", "0xabc", "100.0", "USDC", "2025-01-01")
    sig2 = compute_signature("REF2", "0xabc", "100.0", "USDC", "2025-01-01")
    assert sig1 != sig2
