"""
RPagos Backend — Test CC-07: Distribution CRUD & Rule CRUD Updates.

Tests:
  - Distribution CRUD (create, list, detail, update, delete, CSV import/export)
  - Rule CRUD V2 (auth, distribution_list_id, optimistic locking, batches, spending)
  - Validation: percent sum, max recipients, no dupes, source immutability
  - Error codes: 403, 404, 409, 422

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_cc07_api_routes.py -v
"""

import io
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock

from app.main import app
from app.db.session import engine, async_session
from app.models.db_models import Base
from app.models.forwarding_models import ForwardingRule, AuditLog
from app.models.command_models import DistributionList, DistributionRecipient


# ── Test addresses ────────────────────────────────────────

OWNER = "0x" + "aa" * 20
SOURCE = "0x" + "bb" * 20
DEST = "0x" + "cc" * 20
OTHER_OWNER = "0x" + "dd" * 20
RECIPIENT_1 = "0x" + "11" * 20
RECIPIENT_2 = "0x" + "22" * 20
RECIPIENT_3 = "0x" + "33" * 20


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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers()) as ac:
        yield ac


@pytest_asyncio.fixture
async def dist_list_in_db():
    """Insert a distribution list with 2 recipients."""
    async with async_session() as db:
        dl = DistributionList(
            owner_address=OWNER.lower(),
            label="Test List",
            chain_id=8453,
        )
        db.add(dl)
        await db.flush()

        r1 = DistributionRecipient(
            list_id=dl.id,
            address=RECIPIENT_1.lower(),
            percent_bps=6000,
            label="Primary",
        )
        r2 = DistributionRecipient(
            list_id=dl.id,
            address=RECIPIENT_2.lower(),
            percent_bps=4000,
            label="Secondary",
        )
        db.add(r1)
        db.add(r2)
        await db.commit()
        await db.refresh(dl)
        return dl


@pytest_asyncio.fixture
async def rule_in_db():
    """Insert a forwarding rule owned by OWNER."""
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
            version=1,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule


# ═══════════════════════════════════════════════════════════
#  Distribution CRUD Tests
# ═══════════════════════════════════════════════════════════

class TestCreateDistribution:
    """POST /api/v1/distributions"""

    @pytest.mark.asyncio
    async def test_create_success(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "My List",
                "chain_id": 8453,
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 7000, "label": "Main"},
                    {"address": RECIPIENT_2, "percent_bps": 3000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["distribution"]["label"] == "My List"
        assert data["distribution"]["recipient_count"] == 2

    @pytest.mark.asyncio
    async def test_create_invalid_percent_sum(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "Bad List",
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 5000},
                    {"address": RECIPIENT_2, "percent_bps": 4000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_duplicate_addresses(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "Dupe List",
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 5000},
                    {"address": RECIPIENT_1, "percent_bps": 5000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_empty_recipients(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={"label": "Empty", "recipients": []},
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invalid_address(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "Bad addr",
                "recipients": [
                    {"address": "not-an-address", "percent_bps": 10000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_no_auth_fails(self, client):
        """No auth headers → 401."""
        with patch("app.security.auth.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(debug=False)
            resp = await client.post(
                "/api/v1/distributions",
                json={
                    "label": "Fail",
                    "recipients": [
                        {"address": RECIPIENT_1, "percent_bps": 10000},
                    ],
                },
            )
            assert resp.status_code == 401


class TestListDistributions:
    """GET /api/v1/distributions"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get(
            "/api/v1/distributions",
            params={"owner_address": OWNER},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_data(self, client, dist_list_in_db):
        resp = await client.get(
            "/api/v1/distributions",
            params={"owner_address": OWNER},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["distributions"][0]["label"] == "Test List"

    @pytest.mark.asyncio
    async def test_list_filter_chain(self, client, dist_list_in_db):
        resp = await client.get(
            "/api/v1/distributions",
            params={"owner_address": OWNER, "chain_id": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetDistribution:
    """GET /api/v1/distributions/{id}"""

    @pytest.mark.asyncio
    async def test_get_detail(self, client, dist_list_in_db):
        resp = await client.get(
            f"/api/v1/distributions/{dist_list_in_db.id}",
        )
        assert resp.status_code == 200
        data = resp.json()["distribution"]
        assert data["label"] == "Test List"
        assert len(data["recipients"]) == 2
        assert data["used_by_rules"] == []

    @pytest.mark.asyncio
    async def test_get_not_found(self, client):
        fake_id = uuid.uuid4()
        resp = await client.get(f"/api/v1/distributions/{fake_id}")
        assert resp.status_code == 404


class TestUpdateDistribution:
    """PUT /api/v1/distributions/{id}"""

    @pytest.mark.asyncio
    async def test_update_label(self, client, dist_list_in_db):
        with patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/distributions/{dist_list_in_db.id}",
                json={"label": "Updated Label"},
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["distribution"]["label"] == "Updated Label"

    @pytest.mark.asyncio
    async def test_update_recipients(self, client, dist_list_in_db):
        with patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/distributions/{dist_list_in_db.id}",
                json={
                    "recipients": [
                        {"address": RECIPIENT_3, "percent_bps": 10000},
                    ],
                },
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["distribution"]["recipient_count"] == 1

    @pytest.mark.asyncio
    async def test_update_wrong_owner(self, client, dist_list_in_db):
        resp = await client.put(
            f"/api/v1/distributions/{dist_list_in_db.id}",
            json={"label": "Hack"},
            headers=auth_headers(OTHER_OWNER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_warns_if_active_rules(self, client, dist_list_in_db, rule_in_db):
        """If a rule uses this list, response includes warnings."""
        # Link rule to distribution list
        async with async_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(ForwardingRule)
                .where(ForwardingRule.id == rule_in_db.id)
                .values(distribution_list_id=dist_list_in_db.id)
            )
            await db.commit()

        with patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/distributions/{dist_list_in_db.id}",
                json={"label": "Updated"},
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert "warnings" in resp.json()
        assert len(resp.json()["warnings"]) > 0


class TestDeleteDistribution:
    """DELETE /api/v1/distributions/{id}"""

    @pytest.mark.asyncio
    async def test_delete_success(self, client, dist_list_in_db):
        resp = await client.delete(
            f"/api/v1/distributions/{dist_list_in_db.id}",
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_wrong_owner(self, client, dist_list_in_db):
        resp = await client.delete(
            f"/api/v1/distributions/{dist_list_in_db.id}",
            headers=auth_headers(OTHER_OWNER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_409_if_active_rules(self, client, dist_list_in_db, rule_in_db):
        """409 if distribution list is used by active rules."""
        async with async_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(ForwardingRule)
                .where(ForwardingRule.id == rule_in_db.id)
                .values(distribution_list_id=dist_list_in_db.id)
            )
            await db.commit()

        resp = await client.delete(
            f"/api/v1/distributions/{dist_list_in_db.id}",
            headers=auth_headers(),
        )
        assert resp.status_code == 409
        assert "DISTRIBUTION_IN_USE" in str(resp.json())


class TestCSVImportExport:
    """POST /distributions/{id}/import-csv and GET /distributions/{id}/export-csv"""

    @pytest.mark.asyncio
    async def test_export_csv(self, client, dist_list_in_db):
        resp = await client.get(
            f"/api/v1/distributions/{dist_list_in_db.id}/export-csv",
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
        assert lines[0] == "address,percent_bps,label"
        assert len(lines) == 3  # header + 2 recipients

    @pytest.mark.asyncio
    async def test_import_csv_success(self, client, dist_list_in_db):
        csv_content = (
            "address,percent_bps,label\n"
            f"{RECIPIENT_3},10000,All\n"
        )
        resp = await client.post(
            f"/api/v1/distributions/{dist_list_in_db.id}/import-csv",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "imported"
        assert resp.json()["recipient_count"] == 1

    @pytest.mark.asyncio
    async def test_import_csv_bad_sum(self, client, dist_list_in_db):
        csv_content = (
            "address,percent_bps,label\n"
            f"{RECIPIENT_1},5000,Half\n"
        )
        resp = await client.post(
            f"/api/v1/distributions/{dist_list_in_db.id}/import-csv",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_import_csv_missing_columns(self, client, dist_list_in_db):
        csv_content = "name,amount\nAlice,100\n"
        resp = await client.post(
            f"/api/v1/distributions/{dist_list_in_db.id}/import-csv",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_import_csv_duplicate_addresses(self, client, dist_list_in_db):
        csv_content = (
            "address,percent_bps,label\n"
            f"{RECIPIENT_1},5000,A\n"
            f"{RECIPIENT_1},5000,B\n"
        )
        resp = await client.post(
            f"/api/v1/distributions/{dist_list_in_db.id}/import-csv",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers(),
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
#  Rule CRUD V2 Tests
# ═══════════════════════════════════════════════════════════

class TestCreateRuleV2:
    """POST /forwarding/rules with @require_wallet_auth and V2 fields."""

    @pytest.mark.asyncio
    async def test_create_with_destination(self, client):
        with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
            mock_wm.add_address_to_webhook = AsyncMock()
            resp = await client.post(
                "/api/v1/forwarding/rules",
                json={
                    "source_wallet": SOURCE,
                    "destination_wallet": DEST,
                },
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["rule"]["version"] == 1
        assert data["rule"]["user_id"] == OWNER.lower()

    @pytest.mark.asyncio
    async def test_create_with_distribution_list(self, client, dist_list_in_db):
        with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
            mock_wm.add_address_to_webhook = AsyncMock()
            resp = await client.post(
                "/api/v1/forwarding/rules",
                json={
                    "source_wallet": SOURCE,
                    "distribution_list_id": str(dist_list_in_db.id),
                },
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"]["distribution_list_id"] == str(dist_list_in_db.id)

    @pytest.mark.asyncio
    async def test_create_no_dest_no_distlist(self, client):
        resp = await client.post(
            "/api/v1/forwarding/rules",
            json={"source_wallet": SOURCE},
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_max_rules_per_owner(self, client):
        """Max 20 rules per owner."""
        with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
            mock_wm.add_address_to_webhook = AsyncMock()
            # Create 20 rules
            for i in range(20):
                resp = await client.post(
                    "/api/v1/forwarding/rules",
                    json={
                        "source_wallet": f"0x{'%02x' % i}" + "bb" * 19,
                        "destination_wallet": DEST,
                    },
                    headers=auth_headers(),
                )
                assert resp.status_code == 200, f"Rule {i+1} failed"

            # 21st should fail
            resp = await client.post(
                "/api/v1/forwarding/rules",
                json={
                    "source_wallet": "0x" + "ff" * 20,
                    "destination_wallet": DEST,
                },
                headers=auth_headers(),
            )
            assert resp.status_code == 409
            assert "20" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_request_id_in_response(self, client):
        with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
            mock_wm.add_address_to_webhook = AsyncMock()
            resp = await client.post(
                "/api/v1/forwarding/rules",
                json={
                    "source_wallet": SOURCE,
                    "destination_wallet": DEST,
                },
                headers={**auth_headers(), "X-Request-ID": "12345678-1234-1234-1234-123456789abc"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "request_id" in data


class TestUpdateRuleV2:
    """PUT /forwarding/rules/{id} with optimistic locking."""

    @pytest.mark.asyncio
    async def test_update_with_version(self, client, rule_in_db):
        with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
            mock_fm.broadcast = AsyncMock()
            resp = await client.put(
                f"/api/v1/forwarding/rules/{rule_in_db.id}",
                json={"version": 1, "label": "New Label"},
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"]["label"] == "New Label"
        assert data["rule"]["version"] == 2  # incremented

    @pytest.mark.asyncio
    async def test_update_version_conflict(self, client, rule_in_db):
        resp = await client.put(
            f"/api/v1/forwarding/rules/{rule_in_db.id}",
            json={"version": 99, "label": "Conflict"},
            headers=auth_headers(),
        )
        assert resp.status_code == 409
        assert "VERSION_CONFLICT" in str(resp.json())

    @pytest.mark.asyncio
    async def test_update_source_wallet_immutable(self, client, rule_in_db):
        """source_wallet is not in UpdateRulePayload — extra fields are ignored by Pydantic.
        Sending only source_wallet results in 'No fields to update' (422)."""
        resp = await client.put(
            f"/api/v1/forwarding/rules/{rule_in_db.id}",
            json={"version": 1, "source_wallet": "0x" + "ff" * 20},
            headers=auth_headers(),
        )
        # source_wallet cannot be updated: it's not a valid field
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_wrong_owner(self, client, rule_in_db):
        resp = await client.put(
            f"/api/v1/forwarding/rules/{rule_in_db.id}",
            json={"version": 1, "label": "Hack"},
            headers=auth_headers(OTHER_OWNER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_with_distribution_list(self, client, rule_in_db, dist_list_in_db):
        with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
            mock_fm.broadcast = AsyncMock()
            resp = await client.put(
                f"/api/v1/forwarding/rules/{rule_in_db.id}",
                json={
                    "version": 1,
                    "distribution_list_id": str(dist_list_in_db.id),
                },
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["rule"]["distribution_list_id"] == str(dist_list_in_db.id)


class TestDeleteRuleV2:
    """DELETE /forwarding/rules/{id} with @require_wallet_auth."""

    @pytest.mark.asyncio
    async def test_delete_hard(self, client, rule_in_db):
        with patch("app.api.sweeper_routes.alchemy_webhook_manager") as mock_wm:
            mock_wm.remove_address_from_webhook = AsyncMock()
            resp = await client.delete(
                f"/api/v1/forwarding/rules/{rule_in_db.id}",
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "hard"

    @pytest.mark.asyncio
    async def test_delete_wrong_owner(self, client, rule_in_db):
        resp = await client.delete(
            f"/api/v1/forwarding/rules/{rule_in_db.id}",
            headers=auth_headers(OTHER_OWNER),
        )
        assert resp.status_code == 403


class TestPauseResumeV2:
    """Pause/Resume/EmergencyStop with @require_wallet_auth."""

    @pytest.mark.asyncio
    async def test_pause(self, client, rule_in_db):
        with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
            mock_fm.broadcast = AsyncMock()
            resp = await client.post(
                f"/api/v1/forwarding/rules/{rule_in_db.id}/pause",
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    @pytest.mark.asyncio
    async def test_resume(self, client, rule_in_db):
        # First pause
        with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
            mock_fm.broadcast = AsyncMock()
            await client.post(
                f"/api/v1/forwarding/rules/{rule_in_db.id}/pause",
                headers=auth_headers(),
            )
            # Then resume
            resp = await client.post(
                f"/api/v1/forwarding/rules/{rule_in_db.id}/resume",
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"

    @pytest.mark.asyncio
    async def test_emergency_stop(self, client, rule_in_db):
        with patch("app.api.sweeper_routes.feed_manager") as mock_fm:
            mock_fm.broadcast = AsyncMock()
            resp = await client.post(
                "/api/v1/forwarding/emergency-stop",
                headers=auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["paused_count"] >= 1

    @pytest.mark.asyncio
    async def test_pause_wrong_owner(self, client, rule_in_db):
        resp = await client.post(
            f"/api/v1/forwarding/rules/{rule_in_db.id}/pause",
            headers=auth_headers(OTHER_OWNER),
        )
        assert resp.status_code == 403


class TestBatchesEndpoint:
    """GET /forwarding/rules/{id}/batches"""

    @pytest.mark.asyncio
    async def test_batches_empty(self, client, rule_in_db):
        resp = await client.get(
            f"/api/v1/forwarding/rules/{rule_in_db.id}/batches",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["batches"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_batches_invalid_status(self, client, rule_in_db):
        resp = await client.get(
            f"/api/v1/forwarding/rules/{rule_in_db.id}/batches",
            params={"status": "INVALID"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batches_rule_not_found(self, client):
        resp = await client.get("/api/v1/forwarding/rules/99999/batches")
        assert resp.status_code == 404


class TestSpendingLimitsEndpoint:
    """GET /forwarding/spending-limits"""

    @pytest.mark.asyncio
    async def test_spending_limits_success(self, client):
        mock_status = MagicMock()
        mock_status.source = SOURCE.lower()
        mock_status.chain_id = 8453
        mock_status.per_hour_spent_wei = "0"
        mock_status.per_hour_limit_wei = "25000000000000000000"
        mock_status.per_day_spent_wei = "0"
        mock_status.per_day_limit_wei = "50000000000000000000"
        mock_status.global_daily_spent_wei = "0"
        mock_status.global_daily_limit_wei = "500000000000000000000"
        mock_status.sweeps_this_hour = 0
        mock_status.max_sweeps_per_hour = 10

        with patch("app.services.spending_policy.SpendingPolicy") as MockPolicy:
            instance = MockPolicy.return_value
            instance.get_status = AsyncMock(return_value=mock_status)
            resp = await client.get(
                "/api/v1/forwarding/spending-limits",
                params={"source_address": SOURCE},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "limits" in data
        assert data["limits"]["velocity"]["max_sweeps_per_hour"] == 10

    @pytest.mark.asyncio
    async def test_spending_limits_invalid_address(self, client):
        resp = await client.get(
            "/api/v1/forwarding/spending-limits",
            params={"source_address": "bad"},
        )
        assert resp.status_code == 422


class TestResponseRequestId:
    """All responses should include request_id when available."""

    @pytest.mark.asyncio
    async def test_list_rules_has_request_id(self, client):
        resp = await client.get(
            "/api/v1/forwarding/rules",
            params={"owner_address": OWNER},
            headers={"X-Request-ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        )
        assert resp.status_code == 200
        assert "request_id" in resp.json()

    @pytest.mark.asyncio
    async def test_stats_has_request_id(self, client):
        resp = await client.get(
            "/api/v1/forwarding/stats",
            params={"owner_address": OWNER},
            headers={"X-Request-ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        )
        assert resp.status_code == 200
        assert "request_id" in resp.json()


class TestDistributionValidation:
    """Edge cases for distribution validation."""

    @pytest.mark.asyncio
    async def test_bps_out_of_range(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "Bad BPS",
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 0},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_label_too_long(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "x" * 200,
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 10000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_single_recipient_100_percent(self, client):
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "label": "Solo",
                "recipients": [
                    {"address": RECIPIENT_1, "percent_bps": 10000},
                ],
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["distribution"]["recipient_count"] == 1
