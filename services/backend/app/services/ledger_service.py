"""
RSends Backend — Ledger Service (Double-Entry Bookkeeping).

Operazioni contabili:
  - create_payment_entries: crea scritture DEBIT/CREDIT bilanciate
  - get_balance: calcola il saldo di un account dalla somma dei movimenti

Garanzie:
  - Isolation SERIALIZABLE (PostgreSQL) per consistenza
  - Advisory locks sugli account coinvolti (ordinati per prevenire deadlock)
  - Verifica bilanciamento: sum(DEBIT) == sum(CREDIT) per ogni transazione
  - Tutti i calcoli in Decimal, mai float
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_models import LedgerEntry, Account
from app.services.audit_service import log_event


class InsufficientBalanceError(Exception):
    """Il sender non ha saldo sufficiente."""

    def __init__(self, account_id: UUID, available: Decimal, requested: Decimal):
        self.account_id = account_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"Insufficient balance on account {account_id}: "
            f"available={available}, requested={requested}"
        )


class LedgerImbalanceError(Exception):
    """Le scritture contabili non bilanciano (debiti != crediti)."""

    def __init__(self, total_debits: Decimal, total_credits: Decimal):
        self.total_debits = total_debits
        self.total_credits = total_credits
        super().__init__(
            f"Ledger imbalance: debits={total_debits}, credits={total_credits}"
        )


async def get_balance(
    session: AsyncSession,
    account_id: UUID,
    currency: str,
) -> Decimal:
    """Calcola il saldo di un account dalla somma dei movimenti.

    saldo = sum(CREDIT) - sum(DEBIT) per quel conto/valuta.
    MAI da un campo balance cached.
    """
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == "CREDIT", LedgerEntry.amount),
                        else_=Decimal("0"),
                    )
                ),
                Decimal("0"),
            )
            - func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == "DEBIT", LedgerEntry.amount),
                        else_=Decimal("0"),
                    )
                ),
                Decimal("0"),
            )
        ).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.currency == currency,
        )
    )
    balance = result.scalar_one()
    return Decimal(str(balance)) if balance is not None else Decimal("0")


async def _acquire_advisory_locks(
    session: AsyncSession,
    account_ids: list[UUID],
) -> None:
    """Acquisisce advisory locks PostgreSQL sugli account, ordinati per prevenire deadlock.

    Su SQLite (dev) questa operazione è un no-op sicuro perché
    SQLite serializza automaticamente le scritture.
    """
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    if dialect != "postgresql":
        return

    sorted_ids = sorted(account_ids, key=str)
    for acc_id in sorted_ids:
        lock_key = hash(str(acc_id)) & 0x7FFFFFFF
        await session.execute(text(f"SELECT pg_advisory_xact_lock({lock_key})"))


async def create_payment_entries(
    session: AsyncSession,
    tx_id: UUID,
    sender_account_id: UUID,
    recipient_account_id: UUID,
    treasury_account_id: UUID,
    gross_amount: Decimal,
    fee_amount: Decimal,
    currency: str,
) -> list[LedgerEntry]:
    """Crea le scritture contabili per un pagamento.

    Produce 3 ledger entries:
      1. DEBIT sender  (gross_amount)
      2. CREDIT recipient (gross_amount - fee_amount)
      3. CREDIT treasury (fee_amount)

    Verifica:
      - Il sender ha saldo sufficiente
      - sum(DEBIT) == sum(CREDIT) per la transazione

    Args:
        session: AsyncSession (il chiamante gestisce il commit/rollback)
        tx_id: UUID della transazione associata
        sender_account_id: Account del sender (viene addebitato)
        recipient_account_id: Account del recipient (riceve il netto)
        treasury_account_id: Account del treasury (riceve la fee)
        gross_amount: Importo lordo (Decimal)
        fee_amount: Fee (Decimal)
        currency: Valuta (es. "USDC")

    Returns:
        Lista delle 3 LedgerEntry create.

    Raises:
        InsufficientBalanceError se il sender non ha saldo sufficiente.
        LedgerImbalanceError se le scritture non bilanciano.
    """
    net_amount = gross_amount - fee_amount

    # 1. Advisory locks (ordinati per prevenire deadlock)
    await _acquire_advisory_locks(
        session,
        [sender_account_id, recipient_account_id, treasury_account_id],
    )

    # 2. Verifica saldo sender
    sender_balance = await get_balance(session, sender_account_id, currency)
    if sender_balance < gross_amount:
        raise InsufficientBalanceError(
            sender_account_id, sender_balance, gross_amount
        )

    # 3. Calcola balance_after per ogni account
    recipient_balance = await get_balance(session, recipient_account_id, currency)
    treasury_balance = await get_balance(session, treasury_account_id, currency)

    sender_after = sender_balance - gross_amount
    recipient_after = recipient_balance + net_amount
    treasury_after = treasury_balance + fee_amount

    # 4. Crea le 3 entries
    entries = [
        LedgerEntry(
            transaction_id=tx_id,
            account_id=sender_account_id,
            entry_type="DEBIT",
            amount=gross_amount,
            currency=currency,
            balance_after=sender_after,
        ),
        LedgerEntry(
            transaction_id=tx_id,
            account_id=recipient_account_id,
            entry_type="CREDIT",
            amount=net_amount,
            currency=currency,
            balance_after=recipient_after,
        ),
        LedgerEntry(
            transaction_id=tx_id,
            account_id=treasury_account_id,
            entry_type="CREDIT",
            amount=fee_amount,
            currency=currency,
            balance_after=treasury_after,
        ),
    ]

    for entry in entries:
        session.add(entry)

    await session.flush()

    # 5. Verifica bilanciamento: sum(DEBIT) == sum(CREDIT)
    total_debits = sum(
        e.amount for e in entries if e.entry_type == "DEBIT"
    )
    total_credits = sum(
        e.amount for e in entries if e.entry_type == "CREDIT"
    )

    if total_debits != total_credits:
        raise LedgerImbalanceError(total_debits, total_credits)

    # Audit trail per ogni entry creata
    for entry in entries:
        await log_event(
            session,
            "LEDGER_ENTRY_CREATED",
            "ledger_entry",
            str(entry.id),
            actor_type="system",
            changes={
                "entry_type": entry.entry_type,
                "amount": str(entry.amount),
                "currency": entry.currency,
                "account_id": str(entry.account_id),
                "balance_after": str(entry.balance_after),
            },
            metadata={"transaction_id": str(tx_id)},
        )

    return entries
