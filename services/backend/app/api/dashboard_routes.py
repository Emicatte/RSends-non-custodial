"""
RSends Backend — Dashboard API Routes

GET /api/v1/dashboard/stats — Per-wallet KPI snapshot for the merchant dashboard.

Auth: @require_wallet_auth (X-Wallet-Address / X-Wallet-Signature / X-Timestamp).
Scoping: every query is filtered through ForwardingRule.user_id == wallet_address.lower(),
either directly or via the rule_ids subquery. No cross-merchant data is ever returned.

Data source: SweepLog (one row per executed sweep) + ForwardingRule (ownership + chain).
USD amounts come from SweepLog.amount_usd (already populated by sweep_service via the
price service — no on-chain calls needed here).
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
from app.models.forwarding_models import ForwardingRule, SweepLog
from app.security.auth import require_wallet_auth


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


_CHAIN_LABEL = {8453: "Base", 728126428: "Tron", 101: "Sol"}
_STATUS_LABEL = {
    "completed": "confirmed",
    "pending": "pending",
    "executing": "pending",
    "failed": "failed",
    "gas_too_high": "failed",
    "skipped": "failed",
}
_COMPLETED = "completed"


def _chain_label(chain_id: Optional[int]) -> str:
    if chain_id is None:
        return "Base"
    return _CHAIN_LABEL.get(int(chain_id), "Base")


def _status_label(value) -> str:
    if value is None:
        return "pending"
    raw = getattr(value, "value", value)
    return _STATUS_LABEL.get(str(raw), "pending")


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


@router.get("/stats", response_model=DashboardStats)
@require_wallet_auth
async def get_dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
) -> DashboardStats:
    """Per-wallet dashboard metrics derived from SweepLog rows.

    Every query is scoped to ForwardingRule.user_id == wallet_address.lower().
    """
    owner = (wallet_address or "").lower()
    now = datetime.now(timezone.utc)
    win_24h = now - timedelta(hours=24)
    win_48h = now - timedelta(hours=48)
    win_7d = now - timedelta(days=7)
    win_30d = now - timedelta(days=30)

    # Subquery: every rule owned by this wallet.
    rule_ids_subq = select(ForwardingRule.id).where(ForwardingRule.user_id == owner)

    # 1) Current 24h window — volume + count of completed sweeps.
    q_cur = await db.execute(
        select(
            func.coalesce(func.sum(SweepLog.amount_usd), 0).label("vol"),
            func.count(SweepLog.id).label("cnt"),
        ).where(
            and_(
                SweepLog.rule_id.in_(rule_ids_subq),
                SweepLog.status == _COMPLETED,
                SweepLog.created_at >= win_24h,
            )
        )
    )
    cur_row = q_cur.one()
    volume_24h = _to_float(cur_row.vol)
    transactions_24h = int(cur_row.cnt or 0)

    # 2) Previous 24h window (24h–48h ago) — for deltas.
    q_prev = await db.execute(
        select(
            func.coalesce(func.sum(SweepLog.amount_usd), 0).label("vol"),
            func.count(SweepLog.id).label("cnt"),
        ).where(
            and_(
                SweepLog.rule_id.in_(rule_ids_subq),
                SweepLog.status == _COMPLETED,
                SweepLog.created_at >= win_48h,
                SweepLog.created_at < win_24h,
            )
        )
    )
    prev_row = q_prev.one()
    volume_prev = _to_float(prev_row.vol)
    txs_prev = int(prev_row.cnt or 0)

    volume_24h_delta_pct = (
        round(((volume_24h - volume_prev) / volume_prev) * 100.0, 1)
        if volume_prev > 0
        else 0.0
    )
    transactions_24h_delta = transactions_24h - txs_prev

    # 3) All-time totals (balance + distinct chains).
    q_totals = await db.execute(
        select(
            func.coalesce(func.sum(SweepLog.amount_usd), 0).label("tot_usd"),
            func.count(func.distinct(ForwardingRule.chain_id)).label("chains"),
        )
        .select_from(SweepLog)
        .join(ForwardingRule, ForwardingRule.id == SweepLog.rule_id)
        .where(
            and_(
                ForwardingRule.user_id == owner,
                SweepLog.status == _COMPLETED,
            )
        )
    )
    totals_row = q_totals.one()
    total_balance = _to_float(totals_row.tot_usd)
    total_balance_chains = int(totals_row.chains or 0)

    # 4) Active clients = distinct destination_wallet in last 30 days.
    q_active = await db.execute(
        select(func.count(func.distinct(SweepLog.destination_wallet))).where(
            and_(
                SweepLog.rule_id.in_(rule_ids_subq),
                SweepLog.status == _COMPLETED,
                SweepLog.created_at >= win_30d,
                SweepLog.destination_wallet.isnot(None),
            )
        )
    )
    active_clients = int(q_active.scalar() or 0)

    # 5) New active clients this week = destinations seen in last 7d that
    #    DID NOT appear before that window.
    prior_subq = (
        select(SweepLog.destination_wallet)
        .where(
            and_(
                SweepLog.rule_id.in_(rule_ids_subq),
                SweepLog.status == _COMPLETED,
                SweepLog.created_at < win_7d,
                SweepLog.destination_wallet.isnot(None),
            )
        )
        .distinct()
    )
    q_new_clients = await db.execute(
        select(func.count(func.distinct(SweepLog.destination_wallet))).where(
            and_(
                SweepLog.rule_id.in_(rule_ids_subq),
                SweepLog.status == _COMPLETED,
                SweepLog.created_at >= win_7d,
                SweepLog.destination_wallet.isnot(None),
                ~SweepLog.destination_wallet.in_(prior_subq),
            )
        )
    )
    active_clients_this_week = int(q_new_clients.scalar() or 0)

    # 6) Recent 5 sweeps (any status) — joined with rule for chain_id.
    q_recent = await db.execute(
        select(
            SweepLog.id,
            SweepLog.tx_hash,
            SweepLog.is_split,
            SweepLog.amount_usd,
            SweepLog.token_symbol,
            SweepLog.destination_wallet,
            SweepLog.status,
            SweepLog.created_at,
            ForwardingRule.chain_id,
        )
        .join(ForwardingRule, ForwardingRule.id == SweepLog.rule_id)
        .where(ForwardingRule.user_id == owner)
        .order_by(desc(SweepLog.created_at), desc(SweepLog.id))
        .limit(5)
    )
    recent = [
        RecentTransaction(
            id=int(row.id),
            tx_hash=row.tx_hash,
            type="split" if row.is_split else "transfer",
            amount_usd=_to_float(row.amount_usd),
            currency=row.token_symbol or "ETH",
            chain=_chain_label(row.chain_id),
            status=_status_label(row.status),
            recipient=(row.destination_wallet or "").lower(),
            timestamp_iso=row.created_at.isoformat() if row.created_at else "",
        )
        for row in q_recent.all()
    ]

    return DashboardStats(
        volume_24h=volume_24h,
        volume_24h_delta_pct=volume_24h_delta_pct,
        transactions_24h=transactions_24h,
        transactions_24h_delta=transactions_24h_delta,
        total_balance=total_balance,
        total_balance_chains=total_balance_chains,
        active_clients=active_clients,
        active_clients_this_week=active_clients_this_week,
        recent_transactions=recent,
    )
