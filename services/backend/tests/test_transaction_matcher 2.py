"""
RPagos Backend — Test: Transaction Matcher Service.

Testa il matching tra TX in arrivo e PaymentIntent pendenti:
  - Match esatto (stesso amount, stessa currency, stesso address)
  - Underpayment rifiutato
  - Overpayment accettato con log
  - Intent scaduto
  - Doppio match (stessa TX non matcha due volte)
  - Nessun intent per quell'address

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 DEPOSIT_MASTER_SEED="test-seed" \
    pytest tests/test_transaction_matcher.py -v
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

from app.db.session import engine, async_session
from app.models.db_models import Base
from app.models.merchant_models import PaymentIntent, IntentStatus
from app.services.transaction_matcher import match_transaction, IncomingTx


# ── Constants ────────────────────────────────────────────────

DEPOSIT_ADDR = "0x" + "ab" * 20   # 0xabababab...
MERCHANT_ID = "test-merchant-001"
TX_HASH_1 = "0x" + "11" * 32
TX_HASH_2 = "0x" + "22" * 32


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_intent(
    *,
    deposit_address: str = DEPOSIT_ADDR,
    amount: float = 100.0,
    currency: str = "USDC",
    tolerance: float = 1.0,
    expires_in_minutes: int = 30,
    status: IntentStatus = IntentStatus.pending,
    matched_tx_hash: str = None,
) -> PaymentIntent:
    """Helper: crea un PaymentIntent nel DB."""
    import secrets
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=f"pi_{secrets.token_hex(16)}",
            reference_id=secrets.token_hex(8),
            merchant_id=MERCHANT_ID,
            amount=amount,
            currency=currency,
            chain="BASE",
            deposit_address=deposit_address.lower(),
            amount_tolerance_percent=tolerance,
            status=status,
            matched_tx_hash=matched_tx_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
        return intent


# ═══════════════════════════════════════════════════════════════
#  Test Cases
# ═══════════════════════════════════════════════════════════════

class TestExactMatch:
    """Match esatto: stesso amount, stessa currency, stesso address."""

    @pytest.mark.asyncio
    async def test_exact_match_completes_intent(self):
        intent = await _create_intent(amount=100.0, currency="USDC")

        async with async_session() as db:
            with patch(
                "app.services.transaction_matcher._dispatch_event",
                new_callable=AsyncMock,
            ) as mock_dispatch:
                result = await match_transaction(
                    db,
                    IncomingTx(
                        tx_hash=TX_HASH_1,
                        recipient=DEPOSIT_ADDR,
                        amount=100.0,
                        currency="USDC",
                    ),
                )
                await db.commit()

        assert result.matched is True
        assert result.intent_id == intent.intent_id
        assert result.event == "payment.completed"
        assert result.webhook_triggered is True
        mock_dispatch.assert_called_once()

        # Verifica che l'intent è stato aggiornato
        async with async_session() as db:
            from sqlalchemy import select
            row = await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent.intent_id
                )
            )
            updated = row.scalar_one()
            assert updated.status == IntentStatus.completed
            assert updated.matched_tx_hash == TX_HASH_1.lower()
            assert updated.matched_at is not None
            assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_case_insensitive_address_match(self):
        """deposit_address matching è case insensitive."""
        await _create_intent(
            deposit_address="0xAbCdEf" + "00" * 17,
            amount=50.0,
        )

        async with async_session() as db:
            with patch(
                "app.services.transaction_matcher._dispatch_event",
                new_callable=AsyncMock,
            ):
                result = await match_transaction(
                    db,
                    IncomingTx(
                        tx_hash=TX_HASH_1,
                        recipient="0xabcdef" + "00" * 17,
                        amount=50.0,
                        currency="USDC",
                    ),
                )
                await db.commit()

        assert result.matched is True

    @pytest.mark.asyncio
    async def test_amount_within_tolerance(self):
        """Amount entro la tolleranza (1%) → match positivo."""
        await _create_intent(amount=100.0, tolerance=1.0)

        async with async_session() as db:
            with patch(
                "app.services.transaction_matcher._dispatch_event",
                new_callable=AsyncMock,
            ):
                result = await match_transaction(
                    db,
                    IncomingTx(
                        tx_hash=TX_HASH_1,
                        recipient=DEPOSIT_ADDR,
                        amount=99.5,  # -0.5% → entro 1%
                        currency="USDC",
                    ),
                )
                await db.commit()

        assert result.matched is True


class TestUnderpayment:
    """Underpayment: amount sotto la tolleranza → rifiuto."""

    @pytest.mark.asyncio
    async def test_underpayment_rejected(self):
        intent = await _create_intent(amount=100.0, tolerance=1.0)

        async with async_session() as db:
            result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient=DEPOSIT_ADDR,
                    amount=95.0,  # -5% → fuori tolleranza 1%
                    currency="USDC",
                ),
            )
            await db.commit()

        assert result.matched is False
        assert result.reason == "underpayment"
        assert result.expected == 100.0
        assert result.received == 95.0
        assert result.intent_id == intent.intent_id

    @pytest.mark.asyncio
    async def test_underpayment_does_not_complete_intent(self):
        """L'intent resta pending dopo un underpayment."""
        intent = await _create_intent(amount=100.0, tolerance=1.0)

        async with async_session() as db:
            await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient=DEPOSIT_ADDR,
                    amount=90.0,
                    currency="USDC",
                ),
            )
            await db.commit()

        async with async_session() as db:
            from sqlalchemy import select
            row = await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent.intent_id
                )
            )
            updated = row.scalar_one()
            assert updated.status == IntentStatus.pending
            assert updated.matched_tx_hash is None


class TestOverpayment:
    """Overpayment: completa l'intent ma logga l'eccesso."""

    @pytest.mark.asyncio
    async def test_overpayment_accepted_with_log(self):
        intent = await _create_intent(amount=100.0, tolerance=1.0)

        async with async_session() as db:
            with patch(
                "app.services.transaction_matcher._dispatch_event",
                new_callable=AsyncMock,
            ) as mock_dispatch:
                result = await match_transaction(
                    db,
                    IncomingTx(
                        tx_hash=TX_HASH_1,
                        recipient=DEPOSIT_ADDR,
                        amount=120.0,  # +20% → overpayment
                        currency="USDC",
                    ),
                )
                await db.commit()

        assert result.matched is True
        assert result.overpaid_amount == pytest.approx(20.0)
        assert result.event == "payment.completed"
        mock_dispatch.assert_called_once()

        # Verifica che overpaid_amount è salvato sull'intent
        async with async_session() as db:
            from sqlalchemy import select
            row = await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent.intent_id
                )
            )
            updated = row.scalar_one()
            assert updated.status == IntentStatus.completed
            assert updated.overpaid_amount == "20.0"


class TestExpiredIntent:
    """Intent scaduto al momento del match."""

    @pytest.mark.asyncio
    async def test_expired_intent_not_matched(self):
        intent = await _create_intent(
            amount=100.0,
            expires_in_minutes=-5,  # già scaduto 5 min fa
        )

        async with async_session() as db:
            result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient=DEPOSIT_ADDR,
                    amount=100.0,
                    currency="USDC",
                ),
            )
            await db.commit()

        assert result.matched is False
        assert result.reason == "intent_expired"
        assert result.intent_id == intent.intent_id

    @pytest.mark.asyncio
    async def test_expired_intent_status_updated(self):
        """Lo status viene aggiornato a 'expired' quando scoperto al match time."""
        intent = await _create_intent(expires_in_minutes=-1)

        async with async_session() as db:
            await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient=DEPOSIT_ADDR,
                    amount=100.0,
                    currency="USDC",
                ),
            )
            await db.commit()

        async with async_session() as db:
            from sqlalchemy import select
            row = await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.intent_id == intent.intent_id
                )
            )
            updated = row.scalar_one()
            assert updated.status == IntentStatus.expired


class TestDuplicateMatch:
    """Anti-duplicato: stessa TX non può matchare due intent."""

    @pytest.mark.asyncio
    async def test_same_tx_does_not_match_twice(self):
        """Prima TX matcha, seconda TX con stesso hash viene ignorata."""
        await _create_intent(
            deposit_address="0x" + "aa" * 20,
            amount=100.0,
        )

        # Primo match
        async with async_session() as db:
            with patch(
                "app.services.transaction_matcher._dispatch_event",
                new_callable=AsyncMock,
            ):
                result1 = await match_transaction(
                    db,
                    IncomingTx(
                        tx_hash=TX_HASH_1,
                        recipient="0x" + "aa" * 20,
                        amount=100.0,
                        currency="USDC",
                    ),
                )
                await db.commit()

        assert result1.matched is True

        # Crea un secondo intent con un indirizzo diverso
        await _create_intent(
            deposit_address="0x" + "bb" * 20,
            amount=100.0,
        )

        # Stesso TX hash → deve essere ignorato
        async with async_session() as db:
            result2 = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,  # stesso hash!
                    recipient="0x" + "bb" * 20,
                    amount=100.0,
                    currency="USDC",
                ),
            )
            await db.commit()

        assert result2.matched is False
        assert result2.reason == "tx_already_matched"

    @pytest.mark.asyncio
    async def test_already_matched_intent_skipped(self):
        """Intent con matched_tx_hash != null non viene re-matchato."""
        await _create_intent(
            deposit_address=DEPOSIT_ADDR,
            amount=100.0,
            matched_tx_hash=TX_HASH_1,  # già matchato
        )

        async with async_session() as db:
            result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_2,
                    recipient=DEPOSIT_ADDR,
                    amount=100.0,
                    currency="USDC",
                ),
            )
            await db.commit()

        assert result.matched is False
        assert result.reason == "no_matching_intent"


class TestNoMatchingIntent:
    """Nessun intent trovato per l'address."""

    @pytest.mark.asyncio
    async def test_no_intent_for_address(self):
        # Nessun intent creato per questo indirizzo
        async with async_session() as db:
            result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient="0x" + "ff" * 20,
                    amount=100.0,
                    currency="USDC",
                ),
            )

        assert result.matched is False
        assert result.reason == "no_matching_intent"

    @pytest.mark.asyncio
    async def test_currency_mismatch(self):
        """Intent con currency diversa non matcha."""
        intent = await _create_intent(currency="USDC")

        async with async_session() as db:
            result = await match_transaction(
                db,
                IncomingTx(
                    tx_hash=TX_HASH_1,
                    recipient=DEPOSIT_ADDR,
                    amount=100.0,
                    currency="ETH",  # diverso!
                ),
            )

        assert result.matched is False
        assert result.reason == "currency_mismatch"
        assert result.intent_id == intent.intent_id
