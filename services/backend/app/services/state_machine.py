"""
RSends Backend — Transaction State Machine.

Transizioni valide:
  PENDING    → AUTHORIZED
  AUTHORIZED → PROCESSING
  PROCESSING → COMPLETED
  PROCESSING → FAILED
  COMPLETED  → REVERSED   (solo admin)

Ogni transizione:
  1. Valida che la coppia (from_status, to_status) sia ammessa
  2. Aggiorna lo status nella tabella transactions (atomico)
  3. Crea un record in transaction_state_log per audit trail
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_models import Transaction, TransactionStateLog
from app.services.audit_service import log_event


class InvalidTransitionError(Exception):
    """La transizione di stato richiesta non è valida."""

    def __init__(self, from_status: str, to_status: str, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        msg = f"Invalid transition: {from_status} → {to_status}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


# Mappa delle transizioni valide: from_status → set di to_status ammessi
_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"AUTHORIZED"},
    "AUTHORIZED": {"PROCESSING"},
    "PROCESSING": {"COMPLETED", "FAILED"},
    "COMPLETED": {"REVERSED"},
    # FAILED e REVERSED sono stati terminali (nessuna transizione in uscita)
}


class TransactionStateMachine:
    """Gestisce le transizioni di stato per le transazioni double-entry."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def transition(
        self,
        tx_id: UUID,
        new_status: str,
        *,
        triggered_by: Optional[str] = None,
        reason: Optional[str] = None,
        admin: bool = False,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Transaction:
        """Esegue una transizione di stato atomica.

        Args:
            tx_id: UUID della transazione
            new_status: Nuovo stato desiderato
            triggered_by: Identificativo di chi ha triggerato la transizione
            reason: Motivo della transizione (opzionale)
            admin: Flag admin per transizioni privilegiate (COMPLETED → REVERSED)
            ip_address: IP dell'attore (audit)
            user_agent: User-Agent dell'attore (audit)

        Returns:
            La Transaction aggiornata.

        Raises:
            InvalidTransitionError se la transizione non è valida.
            ValueError se la transazione non esiste.
        """
        # 1. Carica la transazione
        result = await self._session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )
        tx = result.scalar_one_or_none()
        if tx is None:
            raise ValueError(f"Transaction {tx_id} not found")

        old_status = tx.status

        # 2. Valida la transizione
        allowed = _TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(old_status, new_status)

        # 3. COMPLETED → REVERSED richiede admin=True
        if old_status == "COMPLETED" and new_status == "REVERSED" and not admin:
            raise InvalidTransitionError(
                old_status, new_status, "admin flag required for reversal"
            )

        # 4. Aggiorna lo status sulla transazione
        tx.status = new_status
        now = datetime.now(timezone.utc)
        tx.updated_at = now
        if new_status == "COMPLETED":
            tx.completed_at = now

        # 5. Crea il record in transaction_state_log
        log = TransactionStateLog(
            transaction_id=tx_id,
            from_status=old_status,
            to_status=new_status,
            reason=reason,
            triggered_by=triggered_by,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(log)

        # flush per rendere visibili i cambiamenti nella stessa sessione
        await self._session.flush()

        # Audit trail
        event = "TX_COMPLETED" if new_status == "COMPLETED" else (
            "TX_FAILED" if new_status == "FAILED" else "TX_STATE_CHANGE"
        )
        await log_event(
            self._session,
            event,
            "transaction",
            str(tx_id),
            actor_type="admin" if admin else "system",
            actor_id=triggered_by,
            changes={"status": {"old": old_status, "new": new_status}},
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": reason} if reason else None,
        )

        return tx
