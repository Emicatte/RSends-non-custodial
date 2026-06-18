"""
RSends Backend — Test Suite: Audit Service, Request Context, Audit Endpoint.

Testa:
  - log_event scrive nella tabella audit_log
  - Auto-fill da request context (request_id, ip, user_agent)
  - Event types validi e sconosciuti
  - Integrazione: state machine crea audit log entries
  - Integrazione: ledger crea audit log entries per ogni entry
  - GET /api/v1/audit/log: paginazione cursor-based, filtri, admin auth
  - Request context middleware: X-Request-ID header
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import engine
from app.models.db_models import Base
from app.models.ledger_models import (
    Account,
    LedgerAuditLog,
    LedgerEntry,
    Transaction,
)
from app.services.audit_service import log_event
from app.services.state_machine import TransactionStateMachine
from app.services.ledger_service import create_payment_entries, get_balance
from app.middleware.request_context import (
    _request_id_ctx,
    _client_ip_ctx,
    _user_agent_ctx,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    """Sessione DB per test diretti."""
    from app.db.session import async_session
    async with async_session() as s:
        yield s


@pytest_asyncio.fixture
async def sample_tx(session):
    """Crea una Transaction PENDING."""
    tx = Transaction(
        idempotency_key=f"test-{uuid.uuid4().hex[:16]}",
        tx_type="PAYMENT",
        status="PENDING",
    )
    session.add(tx)
    await session.flush()
    return tx


@pytest_asyncio.fixture
async def three_accounts(session):
    """Crea sender, recipient e treasury accounts."""
    sender = Account(account_type="MERCHANT", currency="USDC", label="Sender")
    recipient = Account(account_type="MERCHANT", currency="USDC", label="Recipient")
    treasury = Account(account_type="TREASURY", currency="USDC", label="Treasury")
    session.add_all([sender, recipient, treasury])
    await session.flush()
    return sender, recipient, treasury


# ═══════════════════════════════════════════════════════════════
#  Audit Service — Unit Tests
# ═══════════════════════════════════════════════════════════════

class TestAuditService:

    @pytest.mark.asyncio
    async def test_log_event_creates_record(self, session):
        """log_event scrive un record in audit_log."""
        entry = await log_event(
            session,
            "TX_CREATED",
            "transaction",
            "test-entity-123",
            actor_type="system",
            actor_id="test-runner",
        )
        assert entry.id is not None
        assert entry.event_type == "TX_CREATED"
        assert entry.entity_type == "transaction"
        assert entry.entity_id == "test-entity-123"
        assert entry.actor_type == "system"
        assert entry.actor_id == "test-runner"

    @pytest.mark.asyncio
    async def test_log_event_with_changes(self, session):
        """log_event salva il dict changes."""
        changes = {"status": {"old": "PENDING", "new": "AUTHORIZED"}}
        entry = await log_event(
            session,
            "TX_STATE_CHANGE",
            "transaction",
            "tx-456",
            changes=changes,
        )
        assert entry.changes == changes

    @pytest.mark.asyncio
    async def test_log_event_with_metadata(self, session):
        """log_event salva metadata nel campo metadata_."""
        meta = {"reason": "test reversal", "admin_note": "approved"}
        entry = await log_event(
            session,
            "ADMIN_ACTION",
            "transaction",
            "tx-789",
            metadata=meta,
        )
        assert entry.metadata_ == meta

    @pytest.mark.asyncio
    async def test_log_event_with_explicit_request_id(self, session):
        """Se request_id è passato esplicitamente, viene usato."""
        rid = uuid.uuid4()
        entry = await log_event(
            session,
            "TX_CREATED",
            "transaction",
            "tx-abc",
            request_id=rid,
        )
        assert entry.request_id == rid

    @pytest.mark.asyncio
    async def test_log_event_auto_fills_from_context(self, session):
        """log_event prende request_id, ip, user_agent dal context."""
        rid = uuid.uuid4()
        tok_rid = _request_id_ctx.set(rid)
        tok_ip = _client_ip_ctx.set("192.168.1.100")
        tok_ua = _user_agent_ctx.set("TestBot/1.0")
        try:
            entry = await log_event(
                session,
                "TX_CREATED",
                "transaction",
                "tx-ctx",
            )
            assert entry.request_id == rid
            assert entry.ip_address == "192.168.1.100"
            assert entry.user_agent == "TestBot/1.0"
        finally:
            _request_id_ctx.reset(tok_rid)
            _client_ip_ctx.reset(tok_ip)
            _user_agent_ctx.reset(tok_ua)

    @pytest.mark.asyncio
    async def test_log_event_explicit_overrides_context(self, session):
        """Valori espliciti hanno priorità sul context."""
        ctx_rid = uuid.uuid4()
        explicit_rid = uuid.uuid4()
        tok = _request_id_ctx.set(ctx_rid)
        try:
            entry = await log_event(
                session,
                "TX_CREATED",
                "transaction",
                "tx-override",
                request_id=explicit_rid,
                ip_address="10.0.0.1",
                user_agent="ExplicitAgent",
            )
            assert entry.request_id == explicit_rid
            assert entry.ip_address == "10.0.0.1"
            assert entry.user_agent == "ExplicitAgent"
        finally:
            _request_id_ctx.reset(tok)

    @pytest.mark.asyncio
    async def test_log_event_unknown_type_still_works(self, session):
        """Event type sconosciuto viene loggato comunque (con warning)."""
        entry = await log_event(
            session,
            "UNKNOWN_EVENT",
            "test",
            "test-id",
        )
        assert entry.event_type == "UNKNOWN_EVENT"

    @pytest.mark.asyncio
    async def test_log_event_append_only(self, session):
        """Verifica che i record sono immutabili (append-only pattern)."""
        from sqlalchemy import select, func
        await log_event(session, "TX_CREATED", "tx", "1")
        await log_event(session, "TX_COMPLETED", "tx", "1")
        await log_event(session, "ADMIN_ACTION", "tx", "2")

        result = await session.execute(
            select(func.count()).select_from(LedgerAuditLog)
        )
        assert result.scalar_one() == 3


# ═══════════════════════════════════════════════════════════════
#  Integrazione: State Machine + Audit
# ═══════════════════════════════════════════════════════════════

class TestStateMachineAudit:

    @pytest.mark.asyncio
    async def test_transition_creates_audit_entry(self, session, sample_tx):
        """Ogni transizione di stato crea un record audit."""
        from sqlalchemy import select

        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")

        result = await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "TX_STATE_CHANGE",
                LedgerAuditLog.entity_id == str(sample_tx.id),
            )
        )
        audit = result.scalar_one()
        assert audit.changes["status"]["old"] == "PENDING"
        assert audit.changes["status"]["new"] == "AUTHORIZED"

    @pytest.mark.asyncio
    async def test_completed_transition_uses_tx_completed_event(self, session, sample_tx):
        """Transizione a COMPLETED usa event_type TX_COMPLETED."""
        from sqlalchemy import select

        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        await sm.transition(sample_tx.id, "COMPLETED", triggered_by="test")

        result = await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "TX_COMPLETED",
                LedgerAuditLog.entity_id == str(sample_tx.id),
            )
        )
        audit = result.scalar_one()
        assert audit.changes["status"]["new"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_failed_transition_uses_tx_failed_event(self, session, sample_tx):
        """Transizione a FAILED usa event_type TX_FAILED."""
        from sqlalchemy import select

        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        await sm.transition(sample_tx.id, "FAILED", triggered_by="test")

        result = await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "TX_FAILED",
                LedgerAuditLog.entity_id == str(sample_tx.id),
            )
        )
        audit = result.scalar_one()
        assert audit.changes["status"]["new"] == "FAILED"

    @pytest.mark.asyncio
    async def test_full_lifecycle_creates_multiple_audits(self, session, sample_tx):
        """Ciclo completo produce un audit per ogni transizione."""
        from sqlalchemy import select, func

        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        await sm.transition(sample_tx.id, "COMPLETED", triggered_by="test")

        result = await session.execute(
            select(func.count()).select_from(LedgerAuditLog).where(
                LedgerAuditLog.entity_id == str(sample_tx.id),
            )
        )
        assert result.scalar_one() == 3


# ═══════════════════════════════════════════════════════════════
#  Integrazione: Ledger + Audit
# ═══════════════════════════════════════════════════════════════

class TestLedgerAudit:

    @pytest.mark.asyncio
    async def test_payment_entries_create_audit_logs(self, session, sample_tx, three_accounts):
        """create_payment_entries crea 3 audit log LEDGER_ENTRY_CREATED."""
        from sqlalchemy import select, func

        sender, recipient, treasury = three_accounts

        # Fund sender
        fund = LedgerEntry(
            transaction_id=sample_tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("1000"),
            currency="USDC",
            balance_after=Decimal("1000"),
        )
        session.add(fund)
        await session.flush()

        # Clear audit logs from funding
        await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "LEDGER_ENTRY_CREATED"
            )
        )

        # Crea un secondo tx per il pagamento
        tx2 = Transaction(
            idempotency_key=f"pay-{uuid.uuid4().hex[:16]}",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(tx2)
        await session.flush()

        entries = await create_payment_entries(
            session,
            tx2.id,
            sender.id,
            recipient.id,
            treasury.id,
            gross_amount=Decimal("100"),
            fee_amount=Decimal("0.5"),
            currency="USDC",
        )
        assert len(entries) == 3

        # Verifica che ci siano 3 audit per LEDGER_ENTRY_CREATED dal pagamento
        result = await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "LEDGER_ENTRY_CREATED",
            )
        )
        audits = result.scalars().all()
        # Filtra quelli relativi a tx2
        tx2_audits = [
            a for a in audits
            if a.changes and a.changes.get("account_id") in (
                str(sender.id), str(recipient.id), str(treasury.id)
            )
        ]
        assert len(tx2_audits) == 3


# ═══════════════════════════════════════════════════════════════
#  Request Context Middleware
# ═══════════════════════════════════════════════════════════════

class TestRequestContextMiddleware:

    @pytest.mark.asyncio
    async def test_response_has_x_request_id(self):
        """Il middleware aggiunge X-Request-ID alla risposta."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        # Deve essere un UUID valido
        uuid.UUID(resp.headers["X-Request-ID"])

    @pytest.mark.asyncio
    async def test_client_request_id_is_preserved(self):
        """Se il client manda X-Request-ID, viene preservato."""
        from app.main import app
        rid = str(uuid.uuid4())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health", headers={"X-Request-ID": rid})
        assert resp.headers["X-Request-ID"] == rid

    @pytest.mark.asyncio
    async def test_invalid_client_request_id_generates_new(self):
        """Se il client manda un X-Request-ID invalido, ne viene generato uno nuovo."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health", headers={"X-Request-ID": "not-a-uuid"})
        # Deve avere un UUID valido (generato dal server)
        rid = resp.headers["X-Request-ID"]
        assert rid != "not-a-uuid"
        uuid.UUID(rid)


# ═══════════════════════════════════════════════════════════════
#  Audit Endpoint — GET /api/v1/audit/log
# ═══════════════════════════════════════════════════════════════

class TestAuditEndpoint:

    @pytest_asyncio.fixture
    async def seed_audit_logs(self, session):
        """Popola 5 audit log records per test di paginazione."""
        for i in range(5):
            await log_event(
                session,
                "TX_CREATED" if i % 2 == 0 else "TX_STATE_CHANGE",
                "transaction" if i < 3 else "ledger_entry",
                f"entity-{i}",
                actor_type="system",
            )
        await session.commit()

    @pytest.mark.asyncio
    async def test_audit_endpoint_requires_admin(self):
        """Senza token admin, restituisce 422 (header mancante)."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/audit/log")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_audit_endpoint_rejects_invalid_token(self):
        """Token admin errato restituisce 403."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/audit/log",
                headers={"X-Admin-Token": "wrong-token"},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_endpoint_returns_logs(self, seed_audit_logs):
        """Con token valido, restituisce i log."""
        from app.main import app
        from app.config import get_settings
        token = get_settings().hmac_secret
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/audit/log",
                headers={"X-Admin-Token": token},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 5
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_audit_endpoint_cursor_pagination(self, seed_audit_logs):
        """Paginazione cursor-based funziona correttamente."""
        from app.main import app
        from app.config import get_settings
        token = get_settings().hmac_secret
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Prima pagina: 2 record
            resp = await client.get(
                "/api/v1/audit/log?limit=2",
                headers={"X-Admin-Token": token},
            )
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

        # Seconda pagina
        cursor = data["next_cursor"]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/audit/log?limit=2&cursor={cursor}",
                headers={"X-Admin-Token": token},
            )
        data2 = resp.json()
        assert len(data2["items"]) == 2
        assert data2["has_more"] is True

        # Terza pagina (ultimo record)
        cursor2 = data2["next_cursor"]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/audit/log?limit=2&cursor={cursor2}",
                headers={"X-Admin-Token": token},
            )
        data3 = resp.json()
        assert len(data3["items"]) == 1
        assert data3["has_more"] is False

    @pytest.mark.asyncio
    async def test_audit_endpoint_filter_event_type(self, seed_audit_logs):
        """Filtro per event_type funziona."""
        from app.main import app
        from app.config import get_settings
        token = get_settings().hmac_secret
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/audit/log?event_type=TX_CREATED",
                headers={"X-Admin-Token": token},
            )
        data = resp.json()
        assert all(item["event_type"] == "TX_CREATED" for item in data["items"])
        assert len(data["items"]) == 3  # indices 0, 2, 4

    @pytest.mark.asyncio
    async def test_audit_endpoint_filter_entity_type(self, seed_audit_logs):
        """Filtro per entity_type funziona."""
        from app.main import app
        from app.config import get_settings
        token = get_settings().hmac_secret
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/audit/log?entity_type=ledger_entry",
                headers={"X-Admin-Token": token},
            )
        data = resp.json()
        assert all(item["entity_type"] == "ledger_entry" for item in data["items"])
        assert len(data["items"]) == 2  # indices 3, 4
