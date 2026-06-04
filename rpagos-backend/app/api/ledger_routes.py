"""
RSend Ledger API — Export, integrity check, balance query.

Endpoints:
  GET /api/v1/ledger/export/csv    — Export filtrato in CSV
  GET /api/v1/ledger/export/json   — Export filtrato in JSON
  GET /api/v1/ledger/integrity     — Verifica sum(DEBIT) == sum(CREDIT)
  GET /api/v1/ledger/balance/{account_id} — Saldo di un account
"""

import csv
import io
import logging
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, func, case, cast, Date

from app.api.audit_routes import require_admin  # admin-token (X-Admin-Token) gate
from app.db.session import async_session
from app.models.ledger_models import LedgerEntry, Account

logger = logging.getLogger("ledger_routes")

ledger_router = APIRouter(prefix="/api/v1/ledger", tags=["Ledger"])


@ledger_router.get("/export/csv")
async def ledger_export_csv(
    account_id: Optional[str] = Query(None, description="UUID dell'account"),
    currency: Optional[str] = Query(None, description="Filtra per valuta (es. USDC)"),
    date_from: Optional[date] = Query(None, description="Data inizio (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Data fine (YYYY-MM-DD)"),
    _admin: str = Depends(require_admin),
):
    """Export ledger entries in CSV per compliance/audit."""
    async with async_session() as db:
        q = select(LedgerEntry).order_by(LedgerEntry.created_at)

        if account_id:
            q = q.where(LedgerEntry.account_id == UUID(account_id))
        if currency:
            q = q.where(LedgerEntry.currency == currency)
        if date_from:
            q = q.where(cast(LedgerEntry.created_at, Date) >= date_from)
        if date_to:
            q = q.where(cast(LedgerEntry.created_at, Date) <= date_to)

        result = await db.execute(q)
        entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "timestamp", "transaction_id", "account_id",
        "entry_type", "amount", "currency", "balance_after",
    ])
    for e in entries:
        writer.writerow([
            str(e.id), e.created_at.isoformat(), str(e.transaction_id),
            str(e.account_id), e.entry_type, str(e.amount),
            e.currency, str(e.balance_after),
        ])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=rsend_ledger_{date.today()}.csv"
        },
    )


@ledger_router.get("/export/json")
async def ledger_export_json(
    account_id: Optional[str] = Query(None, description="UUID dell'account"),
    currency: Optional[str] = Query(None, description="Filtra per valuta"),
    limit: int = Query(100, ge=1, le=1000),
    _admin: str = Depends(require_admin),
):
    """Export ledger entries in JSON."""
    async with async_session() as db:
        q = select(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(limit)

        if account_id:
            q = q.where(LedgerEntry.account_id == UUID(account_id))
        if currency:
            q = q.where(LedgerEntry.currency == currency)

        result = await db.execute(q)
        entries = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "timestamp": e.created_at.isoformat(),
            "transaction_id": str(e.transaction_id),
            "account_id": str(e.account_id),
            "entry_type": e.entry_type,
            "amount": str(e.amount),
            "currency": e.currency,
            "balance_after": str(e.balance_after),
        }
        for e in entries
    ]


@ledger_router.get("/integrity")
async def ledger_integrity(_admin: str = Depends(require_admin)):
    """Verifica che sum(DEBIT) == sum(CREDIT) globalmente. Deve essere 0."""
    async with async_session() as db:
        result = await db.execute(
            select(
                LedgerEntry.entry_type,
                func.coalesce(func.sum(LedgerEntry.amount), Decimal("0")),
            ).group_by(LedgerEntry.entry_type)
        )
        totals = {row[0]: row[1] for row in result.all()}

    total_debits = Decimal(str(totals.get("DEBIT", 0)))
    total_credits = Decimal(str(totals.get("CREDIT", 0)))
    imbalance = total_credits - total_debits

    return {
        "total_debits": str(total_debits),
        "total_credits": str(total_credits),
        "imbalance": str(imbalance),
        "balanced": imbalance == Decimal("0"),
    }


@ledger_router.get("/balance/{account_id}")
async def ledger_balance(
    account_id: str,
    currency: str = Query("USDC"),
    _admin: str = Depends(require_admin),
):
    """Saldo di un account calcolato dal ledger: sum(CREDIT) - sum(DEBIT)."""
    from app.services.ledger_service import get_balance

    async with async_session() as db:
        balance = await get_balance(db, UUID(account_id), currency)

    return {
        "account_id": account_id,
        "currency": currency,
        "balance": str(balance),
    }


@ledger_router.get("/accounts")
async def list_accounts(
    active_only: bool = Query(True),
    _admin: str = Depends(require_admin),
):
    """Lista account contabili."""
    async with async_session() as db:
        q = select(Account).order_by(Account.created_at)
        if active_only:
            q = q.where(Account.is_active.is_(True))
        result = await db.execute(q)
        accounts = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "account_type": a.account_type,
            "address": a.address,
            "currency": a.currency,
            "label": a.label,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat(),
        }
        for a in accounts
    ]
