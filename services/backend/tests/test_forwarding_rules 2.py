"""
RPagos Backend — Test: Forwarding Rules CRUD

Testa il ciclo completo delle regole di auto-forwarding:
  - Creazione con validazione address/split/chain
  - Lettura singola e lista con stats
  - Update con audit log, diff, e optimistic locking
  - Delete (soft e hard)
  - Pause / Resume
  - Emergency stop
  - Limite 20 regole per owner

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_forwarding_rules.py -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.db.session import engine, async_session
from app.models.db_models import Base

# ── Test addresses ────────────────────────────────────────

OWNER = "0x" + "aa" * 20       # 0xaaaa...aa
SOURCE = "0x" + "bb" * 20      # 0xbbbb...bb
DEST = "0x" + "cc" * 20        # 0xcccc...cc
SPLIT_DEST = "0x" + "dd" * 20  # 0xdddd...dd
OTHER = "0x" + "ee" * 20       # 0xeeee...ee


# ── Auth helpers ──────────────────────────────────────────

def auth_headers(address: str = OWNER) -> dict:
    """Debug auth headers for testnet bypass."""
    return {
        "X-Wallet-Address": address,
        "X-Wallet-Signature": "0x" + "ab" * 65,
        "X-Timestamp": "2026-01-01T00:00:00Z",
        "X-Chain-Id": "84532",
    }


# ── Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    from app.middleware.rate_limit import _memory_limiter
    _memory_limiter._buckets.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Client HTTP asincrono."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers()) as ac:
        yield ac


def _rule_payload(**overrides) -> dict:
    """Payload base per creare una regola."""
    base = {
        "source_wallet": SOURCE,
        "destination_wallet": DEST,
        "label": "Test Rule",
        "min_threshold": 0.01,
        "gas_strategy": "normal",
        "max_gas_percent": 10.0,
        "gas_limit_gwei": 50,
        "cooldown_sec": 60,
        "chain_id": 8453,
    }
    base.update(overrides)
    return base


async def _create_rule(client: AsyncClient, **overrides) -> dict:
    """Helper: crea una regola e restituisce il response JSON."""
    with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
        mock_wm.add_address_to_webhook = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/rules",
            json=_rule_payload(**overrides),
            headers=auth_headers(),
        )
    assert r.status_code == 200, f"Create rule failed: {r.text}"
    return r.json()


# ═══════════════════════════════════════════════════════════
#  1. Creazione con validazione
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_rule_success(client: AsyncClient):
    """Crea una regola valida."""
    data = await _create_rule(client)
    assert data["status"] == "created"
    rule = data["rule"]
    assert rule["source_wallet"] == SOURCE.lower()
    assert rule["destination_wallet"] == DEST.lower()
    assert rule["is_active"] is True
    assert rule["is_paused"] is False
    assert rule["chain_id"] == 8453
    assert rule["gas_strategy"] == "normal"
    assert rule["id"] is not None
    assert rule["version"] == 1


@pytest.mark.asyncio
async def test_create_rule_invalid_address(client: AsyncClient):
    """Indirizzo non valido rifiutato con 422."""
    payload = _rule_payload(source_wallet="not-an-address")
    r = await client.post(
        "/api/v1/forwarding/rules", json=payload, headers=auth_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_invalid_gas_strategy(client: AsyncClient):
    """Gas strategy non valida rifiutata."""
    payload = _rule_payload(gas_strategy="turbo")
    r = await client.post(
        "/api/v1/forwarding/rules", json=payload, headers=auth_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_with_split(client: AsyncClient):
    """Crea regola con split routing valido."""
    data = await _create_rule(
        client,
        split_enabled=True,
        split_percent=70,
        split_destination=SPLIT_DEST,
    )
    rule = data["rule"]
    assert rule["split_enabled"] is True
    assert rule["split_percent"] == 70
    assert rule["split_destination"] == SPLIT_DEST.lower()


@pytest.mark.asyncio
async def test_create_rule_split_without_destination(client: AsyncClient):
    """Split enabled senza destination → 422."""
    payload = _rule_payload(split_enabled=True, split_percent=70)
    with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
        mock_wm.add_address_to_webhook = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/rules", json=payload, headers=auth_headers(),
        )
    assert r.status_code == 422
    assert "split_destination" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_rule_split_100_percent(client: AsyncClient):
    """Split enabled con 100% → 422 (non ha senso)."""
    payload = _rule_payload(
        split_enabled=True, split_percent=100, split_destination=SPLIT_DEST,
    )
    with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
        mock_wm.add_address_to_webhook = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/rules", json=payload, headers=auth_headers(),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_with_token_filter(client: AsyncClient):
    """Crea regola con token filter."""
    data = await _create_rule(
        client,
        token_filter=["USDC", "ETH"],
        token_symbol="USDC",
        token_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    )
    rule = data["rule"]
    assert rule["token_filter"] == ["USDC", "ETH"]
    assert rule["token_symbol"] == "USDC"


@pytest.mark.asyncio
async def test_create_rule_with_schedule(client: AsyncClient):
    """Crea regola con scheduling."""
    schedule = {
        "days": [0, 1, 2, 3, 4],
        "hours_start": 9,
        "hours_end": 18,
        "timezone": "Europe/Rome",
    }
    data = await _create_rule(client, schedule_json=schedule)
    rule = data["rule"]
    assert rule["schedule_json"]["timezone"] == "Europe/Rome"
    assert rule["schedule_json"]["hours_start"] == 9


# ═══════════════════════════════════════════════════════════
#  2. Lettura
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_rules(client: AsyncClient):
    """Lista regole per owner."""
    await _create_rule(client, label="Rule A")
    await _create_rule(
        client, label="Rule B",
        source_wallet="0x" + "11" * 20,
    )

    r = await client.get(
        "/api/v1/forwarding/rules",
        params={"owner_address": OWNER},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    labels = [rule["label"] for rule in data["rules"]]
    assert "Rule A" in labels
    assert "Rule B" in labels


@pytest.mark.asyncio
async def test_list_rules_empty(client: AsyncClient):
    """Nessuna regola per un owner sconosciuto."""
    r = await client.get(
        "/api/v1/forwarding/rules",
        params={"owner_address": OTHER},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_rule_detail(client: AsyncClient):
    """Dettaglio regola con statistiche."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.get(f"/api/v1/forwarding/rules/{rule_id}")
    assert r.status_code == 200
    data = r.json()["rule"]
    assert data["id"] == rule_id
    assert "stats" in data
    assert data["stats"]["total_sweeps"] == 0


@pytest.mark.asyncio
async def test_get_rule_not_found(client: AsyncClient):
    """Regola inesistente → 404."""
    r = await client.get("/api/v1/forwarding/rules/99999")
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════
#  3. Update con audit log e optimistic locking
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_rule(client: AsyncClient):
    """Aggiorna campi di una regola."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
        mock_fm.broadcast = AsyncMock()
        r = await client.put(
            f"/api/v1/forwarding/rules/{rule_id}",
            json={
                "version": 1,
                "label": "Updated Label",
                "min_threshold": 0.05,
                "gas_limit_gwei": 80,
            },
            headers=auth_headers(),
        )
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["label"] == "Updated Label"
    assert rule["min_threshold"] == 0.05
    assert rule["gas_limit_gwei"] == 80
    assert rule["version"] == 2


@pytest.mark.asyncio
async def test_update_rule_wrong_owner(client: AsyncClient):
    """Update da non-owner → 403."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.put(
        f"/api/v1/forwarding/rules/{rule_id}",
        json={"version": 1, "label": "Hacked"},
        headers=auth_headers(OTHER),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_rule_no_fields(client: AsyncClient):
    """Update senza campi → 422."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.put(
        f"/api/v1/forwarding/rules/{rule_id}",
        json={"version": 1},
        headers=auth_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_split_validation(client: AsyncClient):
    """Enable split senza destination → 422."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.put(
        f"/api/v1/forwarding/rules/{rule_id}",
        json={
            "version": 1,
            "split_enabled": True,
            "split_percent": 60,
        },
        headers=auth_headers(),
    )
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════
#  4. Delete
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_rule_soft_with_logs(client: AsyncClient):
    """Delete con sweep logs → soft delete (is_active=False, is_paused=True)."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    # Aggiungi un sweep log per forzare il soft delete path
    from app.models.forwarding_models import SweepLog, SweepStatus
    async with async_session() as db:
        log = SweepLog(
            rule_id=rule_id,
            source_wallet=SOURCE.lower(),
            destination_wallet=DEST.lower(),
            amount_wei="1000000000000000000",
            amount_human=1.0,
            status=SweepStatus.completed,
        )
        db.add(log)
        await db.commit()

    with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
        mock_wm.remove_address_from_webhook = AsyncMock()
        r = await client.request(
            "DELETE",
            f"/api/v1/forwarding/rules/{rule_id}",
            headers=auth_headers(),
        )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "soft"

    # Verify it's still in DB but inactive and paused
    r2 = await client.get(f"/api/v1/forwarding/rules/{rule_id}")
    assert r2.status_code == 200
    rule = r2.json()["rule"]
    assert rule["is_active"] is False
    assert rule["is_paused"] is True


@pytest.mark.asyncio
async def test_delete_rule_wrong_owner(client: AsyncClient):
    """Delete da non-owner → 403."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.request(
        "DELETE",
        f"/api/v1/forwarding/rules/{rule_id}",
        headers=auth_headers(OTHER),
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
#  5. Pause / Resume
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pause_resume(client: AsyncClient):
    """Pause e Resume di una regola."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
        mock_fm.broadcast = AsyncMock()

        # Pause
        r = await client.post(
            f"/api/v1/forwarding/rules/{rule_id}/pause",
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "paused"

        # Double pause → 409
        r2 = await client.post(
            f"/api/v1/forwarding/rules/{rule_id}/pause",
            headers=auth_headers(),
        )
        assert r2.status_code == 409

        # Resume
        r3 = await client.post(
            f"/api/v1/forwarding/rules/{rule_id}/resume",
            headers=auth_headers(),
        )
        assert r3.status_code == 200
        assert r3.json()["status"] == "resumed"

        # Double resume → 409
        r4 = await client.post(
            f"/api/v1/forwarding/rules/{rule_id}/resume",
            headers=auth_headers(),
        )
        assert r4.status_code == 409


@pytest.mark.asyncio
async def test_pause_wrong_owner(client: AsyncClient):
    """Pause da non-owner → 403."""
    created = await _create_rule(client)
    rule_id = created["rule"]["id"]

    r = await client.post(
        f"/api/v1/forwarding/rules/{rule_id}/pause",
        headers=auth_headers(OTHER),
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
#  6. Emergency Stop
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_emergency_stop(client: AsyncClient):
    """Emergency stop pausa tutte le regole attive dell'owner."""
    # Crea 3 regole
    for i in range(3):
        await _create_rule(
            client,
            label=f"Rule {i}",
            source_wallet=f"0x{i:02d}" + "bb" * 19,
        )

    with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
        mock_fm.broadcast = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/emergency-stop",
            headers=auth_headers(),
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "emergency_stop"
    assert data["paused_count"] == 3

    # Verify all are paused
    r2 = await client.get(
        "/api/v1/forwarding/rules",
        params={"owner_address": OWNER},
    )
    for rule in r2.json()["rules"]:
        assert rule["is_paused"] is True


@pytest.mark.asyncio
async def test_emergency_stop_no_active(client: AsyncClient):
    """Emergency stop senza regole attive."""
    with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
        mock_fm.broadcast = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/emergency-stop",
            headers=auth_headers(OTHER),
        )
    assert r.status_code == 200
    assert r.json()["paused_count"] == 0


@pytest.mark.asyncio
async def test_emergency_stop_skips_already_paused(client: AsyncClient):
    """Emergency stop non conta le regole già pausate."""
    await _create_rule(client, label="Active")
    created2 = await _create_rule(
        client, label="Pre-paused",
        source_wallet="0x" + "11" * 20,
    )

    with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
        mock_fm.broadcast = AsyncMock()
        # Pause the second one first
        await client.post(
            f"/api/v1/forwarding/rules/{created2['rule']['id']}/pause",
            headers=auth_headers(),
        )

        r = await client.post(
            "/api/v1/forwarding/emergency-stop",
            headers=auth_headers(),
        )
    assert r.status_code == 200
    assert r.json()["paused_count"] == 1  # Only the active one


# ═══════════════════════════════════════════════════════════
#  7. Limite 20 regole per owner
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_max_rules_per_owner(client: AsyncClient):
    """Limite di 20 regole attive per owner."""
    # Crea 20 regole con source_wallet diversi
    for i in range(20):
        await _create_rule(
            client,
            label=f"Rule {i}",
            source_wallet=f"0x{i:02d}" + "bb" * 19,
        )

    # La 21esima deve fallire con 409
    payload = _rule_payload(
        label="Rule 21",
        source_wallet="0x" + "ff" * 20,
    )
    with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
        mock_wm.add_address_to_webhook = AsyncMock()
        r = await client.post(
            "/api/v1/forwarding/rules", json=payload, headers=auth_headers(),
        )
    assert r.status_code == 409
    assert "20" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════
#  8. Stats e Logs (endpoints vuoti)
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stats_empty(client: AsyncClient):
    """Stats con zero sweep logs."""
    await _create_rule(client)

    r = await client.get(
        "/api/v1/forwarding/stats",
        params={"owner_address": OWNER},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total_sweeps"] == 0
    assert data["success_rate"] == 0


@pytest.mark.asyncio
async def test_logs_empty(client: AsyncClient):
    """Logs con zero sweep logs."""
    await _create_rule(client)

    r = await client.get(
        "/api/v1/forwarding/logs",
        params={"owner_address": OWNER},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["logs"] == []
    assert data["pagination"]["total"] == 0


@pytest.mark.asyncio
async def test_daily_stats_empty(client: AsyncClient):
    """Daily stats vuoti."""
    r = await client.get(
        "/api/v1/forwarding/stats/daily",
        params={"owner_address": OWNER, "days": 7},
    )
    assert r.status_code == 200
    assert r.json()["data"] == []
