"""
RSends Backend — Test Suite: State Machine, Idempotency, Ledger.

Testa:
  - Transizioni state machine valide e invalide
  - Idempotency: stessa chiave restituisce stesso risultato / 409
  - Bilanciamento ledger: sum(DEBIT) == sum(CREDIT)
  - Saldo calcolato dai movimenti
  - Saldo insufficiente
"""

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.db.session import engine
from app.models.db_models import Base
from app.models.ledger_models import Transaction, Account, LedgerEntry
from app.services.state_machine import TransactionStateMachine, InvalidTransitionError
from app.services.idempotency_service import check_idempotency, ConflictError
from app.services.ledger_service import (
    create_payment_entries,
    get_balance,
    InsufficientBalanceError,
    LedgerImbalanceError,
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
    """Sessione DB per test diretti (non via HTTP)."""
    from app.db.session import async_session
    async with async_session() as s:
        yield s


@pytest_asyncio.fixture
async def sample_tx(session):
    """Crea una Transaction PENDING per i test della state machine."""
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
    """Crea sender, recipient e treasury accounts per i test del ledger."""
    sender = Account(
        account_type="MERCHANT",
        currency="USDC",
        label="Test Sender",
    )
    recipient = Account(
        account_type="MERCHANT",
        currency="USDC",
        label="Test Recipient",
    )
    treasury = Account(
        account_type="TREASURY",
        currency="USDC",
        label="RSends Treasury",
    )
    session.add_all([sender, recipient, treasury])
    await session.flush()
    return sender, recipient, treasury


# ═══════════════════════════════════════════════════════════════
#  State Machine Tests
# ═══════════════════════════════════════════════════════════════

class TestStateMachine:

    @pytest.mark.asyncio
    async def test_valid_transition_pending_to_authorized(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        tx = await sm.transition(
            sample_tx.id, "AUTHORIZED", triggered_by="test"
        )
        assert tx.status == "AUTHORIZED"

    @pytest.mark.asyncio
    async def test_valid_full_lifecycle(self, session, sample_tx):
        """PENDING → AUTHORIZED → PROCESSING → COMPLETED — ciclo completo."""
        sm = TransactionStateMachine(session)

        tx = await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        assert tx.status == "AUTHORIZED"

        tx = await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        assert tx.status == "PROCESSING"

        tx = await sm.transition(sample_tx.id, "COMPLETED", triggered_by="test")
        assert tx.status == "COMPLETED"
        assert tx.completed_at is not None

    @pytest.mark.asyncio
    async def test_processing_to_failed(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")

        tx = await sm.transition(
            sample_tx.id, "FAILED",
            triggered_by="system",
            reason="RPC timeout",
        )
        assert tx.status == "FAILED"

    @pytest.mark.asyncio
    async def test_reversal_requires_admin(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        await sm.transition(sample_tx.id, "COMPLETED", triggered_by="test")

        # Senza admin → errore
        with pytest.raises(InvalidTransitionError, match="admin flag required"):
            await sm.transition(sample_tx.id, "REVERSED", triggered_by="user")

        # Con admin → ok
        tx = await sm.transition(
            sample_tx.id, "REVERSED",
            triggered_by="admin@rsend.io",
            admin=True,
            reason="Refund richiesto",
        )
        assert tx.status == "REVERSED"

    @pytest.mark.asyncio
    async def test_invalid_transition_pending_to_completed(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(sample_tx.id, "COMPLETED", triggered_by="test")

    @pytest.mark.asyncio
    async def test_invalid_transition_pending_to_failed(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(sample_tx.id, "FAILED", triggered_by="test")

    @pytest.mark.asyncio
    async def test_invalid_transition_from_failed(self, session, sample_tx):
        """FAILED è uno stato terminale — nessuna transizione in uscita."""
        sm = TransactionStateMachine(session)
        await sm.transition(sample_tx.id, "AUTHORIZED", triggered_by="test")
        await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")
        await sm.transition(sample_tx.id, "FAILED", triggered_by="test")

        with pytest.raises(InvalidTransitionError):
            await sm.transition(sample_tx.id, "PROCESSING", triggered_by="test")

    @pytest.mark.asyncio
    async def test_transition_creates_state_log(self, session, sample_tx):
        sm = TransactionStateMachine(session)
        await sm.transition(
            sample_tx.id, "AUTHORIZED",
            triggered_by="webhook",
            reason="Payment confirmed",
            ip_address="192.168.1.1",
        )

        # Ricarica la transazione per forzare il refresh dei state_logs
        tx_id = sample_tx.id  # cattura prima di expire
        session.expire_all()
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Transaction)
            .where(Transaction.id == tx_id)
            .options(selectinload(Transaction.state_logs))
        )
        tx = result.scalar_one()
        assert len(tx.state_logs) == 1
        log = tx.state_logs[0]
        assert log.from_status == "PENDING"
        assert log.to_status == "AUTHORIZED"
        assert log.triggered_by == "webhook"
        assert log.reason == "Payment confirmed"

    @pytest.mark.asyncio
    async def test_nonexistent_transaction(self, session):
        sm = TransactionStateMachine(session)
        with pytest.raises(ValueError, match="not found"):
            await sm.transition(uuid.uuid4(), "AUTHORIZED", triggered_by="test")


# ═══════════════════════════════════════════════════════════════
#  Idempotency Tests
# ═══════════════════════════════════════════════════════════════

class TestIdempotency:

    @pytest.mark.asyncio
    async def test_new_key_returns_none(self, session):
        result = await check_idempotency(session, "brand-new-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_completed_key_returns_transaction(self, session):
        tx = Transaction(
            idempotency_key="pay-123",
            tx_type="PAYMENT",
            status="COMPLETED",
        )
        session.add(tx)
        await session.flush()

        result = await check_idempotency(session, "pay-123")
        assert result is not None
        assert result.id == tx.id
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_pending_key_raises_conflict(self, session):
        tx = Transaction(
            idempotency_key="pay-456",
            tx_type="PAYMENT",
            status="PENDING",
        )
        session.add(tx)
        await session.flush()

        with pytest.raises(ConflictError) as exc_info:
            await check_idempotency(session, "pay-456")
        assert exc_info.value.transaction.id == tx.id

    @pytest.mark.asyncio
    async def test_processing_key_raises_conflict(self, session):
        tx = Transaction(
            idempotency_key="pay-789",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(tx)
        await session.flush()

        with pytest.raises(ConflictError):
            await check_idempotency(session, "pay-789")

    @pytest.mark.asyncio
    async def test_failed_key_allows_retry(self, session):
        """FAILED → chiave trattata come nuova, permetti retry."""
        tx = Transaction(
            idempotency_key="pay-failed",
            tx_type="PAYMENT",
            status="FAILED",
        )
        session.add(tx)
        await session.flush()

        result = await check_idempotency(session, "pay-failed")
        assert result is None  # Trattata come nuova

    @pytest.mark.asyncio
    async def test_reversed_key_allows_retry(self, session):
        """REVERSED → chiave trattata come nuova, permetti retry."""
        tx = Transaction(
            idempotency_key="pay-reversed",
            tx_type="PAYMENT",
            status="REVERSED",
        )
        session.add(tx)
        await session.flush()

        result = await check_idempotency(session, "pay-reversed")
        assert result is None


# ═══════════════════════════════════════════════════════════════
#  Ledger Tests
# ═══════════════════════════════════════════════════════════════

class TestLedger:

    @pytest.mark.asyncio
    async def test_balance_empty_account(self, session, three_accounts):
        """Account nuovo → saldo 0."""
        sender, _, _ = three_accounts
        balance = await get_balance(session, sender.id, "USDC")
        assert balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_balance_after_credit(self, session, three_accounts):
        """Dopo un CREDIT, il saldo è positivo."""
        sender, _, _ = three_accounts
        tx = Transaction(
            idempotency_key="fund-sender",
            tx_type="FUNDING",
            status="COMPLETED",
        )
        session.add(tx)
        await session.flush()

        entry = LedgerEntry(
            transaction_id=tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("1000.000000000000000000"),
            currency="USDC",
            balance_after=Decimal("1000.000000000000000000"),
        )
        session.add(entry)
        await session.flush()

        balance = await get_balance(session, sender.id, "USDC")
        assert balance == Decimal("1000")

    @pytest.mark.asyncio
    async def test_payment_entries_balanced(self, session, three_accounts):
        """Le entries di un pagamento devono bilanciare: sum(DEBIT) == sum(CREDIT)."""
        sender, recipient, treasury = three_accounts

        # Fund the sender first
        fund_tx = Transaction(
            idempotency_key="fund-for-payment",
            tx_type="FUNDING",
            status="COMPLETED",
        )
        session.add(fund_tx)
        await session.flush()

        funding = LedgerEntry(
            transaction_id=fund_tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("1000.000000000000000000"),
            currency="USDC",
            balance_after=Decimal("1000.000000000000000000"),
        )
        session.add(funding)
        await session.flush()

        # Now create the payment
        pay_tx = Transaction(
            idempotency_key="pay-test-balanced",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(pay_tx)
        await session.flush()

        entries = await create_payment_entries(
            session=session,
            tx_id=pay_tx.id,
            sender_account_id=sender.id,
            recipient_account_id=recipient.id,
            treasury_account_id=treasury.id,
            gross_amount=Decimal("100.000000000000000000"),
            fee_amount=Decimal("0.500000000000000000"),
            currency="USDC",
        )

        assert len(entries) == 3

        total_debits = sum(e.amount for e in entries if e.entry_type == "DEBIT")
        total_credits = sum(e.amount for e in entries if e.entry_type == "CREDIT")
        assert total_debits == total_credits

        # Verifica i saldi
        assert await get_balance(session, sender.id, "USDC") == Decimal("900")
        assert await get_balance(session, recipient.id, "USDC") == Decimal("99.5")
        assert await get_balance(session, treasury.id, "USDC") == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_payment_entries_amounts(self, session, three_accounts):
        """Verifica gli importi specifici delle entries."""
        sender, recipient, treasury = three_accounts

        # Fund sender
        fund_tx = Transaction(
            idempotency_key="fund-amounts",
            tx_type="FUNDING",
            status="COMPLETED",
        )
        session.add(fund_tx)
        await session.flush()
        session.add(LedgerEntry(
            transaction_id=fund_tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("500"),
            currency="USDC",
            balance_after=Decimal("500"),
        ))
        await session.flush()

        pay_tx = Transaction(
            idempotency_key="pay-amounts",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(pay_tx)
        await session.flush()

        gross = Decimal("200")
        fee = Decimal("1")

        entries = await create_payment_entries(
            session=session,
            tx_id=pay_tx.id,
            sender_account_id=sender.id,
            recipient_account_id=recipient.id,
            treasury_account_id=treasury.id,
            gross_amount=gross,
            fee_amount=fee,
            currency="USDC",
        )

        debit_entry = [e for e in entries if e.entry_type == "DEBIT"][0]
        credit_entries = [e for e in entries if e.entry_type == "CREDIT"]
        recipient_entry = [e for e in credit_entries if e.account_id == recipient.id][0]
        treasury_entry = [e for e in credit_entries if e.account_id == treasury.id][0]

        assert debit_entry.amount == Decimal("200")
        assert recipient_entry.amount == Decimal("199")
        assert treasury_entry.amount == Decimal("1")

    @pytest.mark.asyncio
    async def test_insufficient_balance(self, session, three_accounts):
        """Sender senza saldo → InsufficientBalanceError."""
        sender, recipient, treasury = three_accounts

        pay_tx = Transaction(
            idempotency_key="pay-insufficient",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(pay_tx)
        await session.flush()

        with pytest.raises(InsufficientBalanceError) as exc_info:
            await create_payment_entries(
                session=session,
                tx_id=pay_tx.id,
                sender_account_id=sender.id,
                recipient_account_id=recipient.id,
                treasury_account_id=treasury.id,
                gross_amount=Decimal("100"),
                fee_amount=Decimal("0.5"),
                currency="USDC",
            )
        assert exc_info.value.available == Decimal("0")
        assert exc_info.value.requested == Decimal("100")

    @pytest.mark.asyncio
    async def test_balance_per_currency(self, session, three_accounts):
        """Saldi sono separati per currency."""
        sender, _, _ = three_accounts

        tx = Transaction(
            idempotency_key="multi-currency",
            tx_type="FUNDING",
            status="COMPLETED",
        )
        session.add(tx)
        await session.flush()

        # Credit USDC
        session.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("100"),
            currency="USDC",
            balance_after=Decimal("100"),
        ))
        # Credit ETH
        session.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("5"),
            currency="ETH",
            balance_after=Decimal("5"),
        ))
        await session.flush()

        assert await get_balance(session, sender.id, "USDC") == Decimal("100")
        assert await get_balance(session, sender.id, "ETH") == Decimal("5")
        assert await get_balance(session, sender.id, "DAI") == Decimal("0")

    @pytest.mark.asyncio
    async def test_multiple_payments_balance_tracking(self, session, three_accounts):
        """Due pagamenti consecutivi aggiornano correttamente i saldi."""
        sender, recipient, treasury = three_accounts

        # Fund sender con 1000
        fund_tx = Transaction(
            idempotency_key="fund-multi",
            tx_type="FUNDING",
            status="COMPLETED",
        )
        session.add(fund_tx)
        await session.flush()
        session.add(LedgerEntry(
            transaction_id=fund_tx.id,
            account_id=sender.id,
            entry_type="CREDIT",
            amount=Decimal("1000"),
            currency="USDC",
            balance_after=Decimal("1000"),
        ))
        await session.flush()

        # Primo pagamento: 100 lordi, 0.5 fee
        pay1 = Transaction(
            idempotency_key="pay-multi-1",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(pay1)
        await session.flush()
        await create_payment_entries(
            session, pay1.id,
            sender.id, recipient.id, treasury.id,
            Decimal("100"), Decimal("0.5"), "USDC",
        )

        # Secondo pagamento: 200 lordi, 1.0 fee
        pay2 = Transaction(
            idempotency_key="pay-multi-2",
            tx_type="PAYMENT",
            status="PROCESSING",
        )
        session.add(pay2)
        await session.flush()
        await create_payment_entries(
            session, pay2.id,
            sender.id, recipient.id, treasury.id,
            Decimal("200"), Decimal("1.0"), "USDC",
        )

        # Verifica saldi finali
        assert await get_balance(session, sender.id, "USDC") == Decimal("700")
        assert await get_balance(session, recipient.id, "USDC") == Decimal("298.5")
        assert await get_balance(session, treasury.id, "USDC") == Decimal("1.5")
