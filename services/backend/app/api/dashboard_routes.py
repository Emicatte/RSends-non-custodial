"""
RSends Backend — Dashboard API Routes (NON-CUSTODIAL).

GET /api/v1/dashboard/stats — Per-merchant KPI snapshot for the dashboard.

Auth: @require_wallet_auth (X-Wallet-Address / X-Wallet-Signature / X-Timestamp).
Scoping: every query is filtered by PaymentSettlement.merchant == wallet_address
(lowercased). No cross-merchant data is ever returned.

Data source: PaymentSettlement (one row per on-chain RSendsRouter.PaymentMade
event), replacing the custodial SweepLog/ForwardingRule source.

TODO(scaffold): USD volume requires per-token price + decimals conversion of the
on-chain `amount` (base units). Until that's wired to the price service, volume
fields are reported as 0.0 while transaction counts/recent activity are exact.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.dashboard_schemas import DashboardStats, RecentTransaction
from app.models.settlement_models import PaymentSettlement
from app.security.auth import require_wallet_auth
from app.security.input_validator import display_payment_address
from app.services.chain_display import chain_key_for, legacy_chain_label


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
@require_wallet_auth
async def get_dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
) -> DashboardStats:
    """Per-merchant dashboard metrics derived from on-chain PaymentSettlement rows."""
    owner = (wallet_address or "").lower()
    now = datetime.now(timezone.utc)
    win_24h = now - timedelta(hours=24)
    win_48h = now - timedelta(hours=48)
    win_7d = now - timedelta(days=7)
    win_30d = now - timedelta(days=30)

    scope = PaymentSettlement.merchant == owner

    # 1) Current 24h transaction count.
    transactions_24h = int(
        (await db.execute(
            select(func.count(PaymentSettlement.id)).where(
                and_(scope, PaymentSettlement.created_at >= win_24h)
            )
        )).scalar() or 0
    )

    # 2) Previous 24h window (24h–48h ago) — for delta.
    txs_prev = int(
        (await db.execute(
            select(func.count(PaymentSettlement.id)).where(
                and_(
                    scope,
                    PaymentSettlement.created_at >= win_48h,
                    PaymentSettlement.created_at < win_24h,
                )
            )
        )).scalar() or 0
    )
    transactions_24h_delta = transactions_24h - txs_prev

    # 3) Distinct chains seen all-time.
    total_balance_chains = int(
        (await db.execute(
            select(func.count(func.distinct(PaymentSettlement.chain_id))).where(scope)
        )).scalar() or 0
    )

    # 4) Active clients = distinct payer in last 30 days.
    active_clients = int(
        (await db.execute(
            select(func.count(func.distinct(PaymentSettlement.payer))).where(
                and_(scope, PaymentSettlement.created_at >= win_30d)
            )
        )).scalar() or 0
    )

    # 5) New active clients this week = payers in last 7d not seen before.
    prior_subq = (
        select(PaymentSettlement.payer)
        .where(and_(scope, PaymentSettlement.created_at < win_7d))
        .distinct()
    )
    active_clients_this_week = int(
        (await db.execute(
            select(func.count(func.distinct(PaymentSettlement.payer))).where(
                and_(
                    scope,
                    PaymentSettlement.created_at >= win_7d,
                    ~PaymentSettlement.payer.in_(prior_subq),
                )
            )
        )).scalar() or 0
    )

    # 6) Recent 5 settlements.
    q_recent = await db.execute(
        select(PaymentSettlement)
        .where(scope)
        .order_by(desc(PaymentSettlement.created_at), desc(PaymentSettlement.id))
        .limit(5)
    )
    recent = [
        RecentTransaction(
            id=int(s.id),
            tx_hash=s.tx_hash,
            type="transfer",
            amount_usd=0.0,  # TODO: convert base-unit amount via price service
            currency="ETH" if s.token == "0x" + "0" * 40 else "TOKEN",
            chain=legacy_chain_label(s.chain_id),
            chain_key=chain_key_for(s.chain_id),
            status="confirmed",
            recipient=display_payment_address(s.merchant),
            timestamp_iso=s.created_at.isoformat() if s.created_at else "",
        )
        for s in q_recent.scalars().all()
    ]

    # NON-CUSTODIAL: USD volume requires per-token price conversion (TODO).
    return DashboardStats(
        volume_24h=0.0,
        volume_24h_delta_pct=0.0,
        transactions_24h=transactions_24h,
        transactions_24h_delta=transactions_24h_delta,
        total_balance=0.0,
        total_balance_chains=total_balance_chains,
        active_clients=active_clients,
        active_clients_this_week=active_clients_this_week,
        recent_transactions=recent,
    )
