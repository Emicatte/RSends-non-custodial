"""Phase E — session-authed (JWT) org stats with USD price conversion.

The `/app` home widget reads its KPI snapshot here. This is the correctly-scoped
replacement for the legacy wallet-sig `GET /api/v1/dashboard/stats`, whose
`PaymentSettlement.merchant == owner` filter breaks post-Phase-B (once an org's
`settlement_wallet` ≠ its primary wallet the settlements land on the settlement
wallet, and the primary-wallet filter reads zero). `dashboard_routes.py` is left
untouched (frozen); this route is the fix.

Scoping — settlements attributed to the org through the INTENT join:

    PaymentSettlement JOIN PaymentIntent ON settlement.intent_id == intent.intent_id
    WHERE intent.merchant_id == owner AND intent.environment == :env
      AND settlement.status == final

The join is load-bearing twice over: (1) it attributes a settlement to the org
via the intent regardless of which recipient wallet received funds, and (2)
`PaymentSettlement` has NO environment column — env scoping can ONLY come from
the intent. Same response shape as `DashboardStats` so the widget re-point is a
one-line URL change.

USD volume: `PaymentSettlement.amount` is base units; per row we map
(chain_id, token) → decimals + coingecko_id via `app.tokens.registry`, normalize,
and multiply by the cached USD price (`price_service.get_price`). Tokens with no
registry entry or no cached price are counted but contribute 0 to USD volume.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.api.merchant_profile_routes import _resolve_owner_address
from app.db.session import get_db
from app.models.dashboard_schemas import DashboardStats, RecentTransaction
from app.models.merchant_models import PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.services.price_service import get_price
from app.tokens.registry import get_token

router = APIRouter(prefix="/api/v1/user/org", tags=["user-org-stats"])

_NATIVE = "0x" + "0" * 40
_CHAIN_LABEL = {8453: "Base", 84532: "Base Sepolia", 1: "Ethereum", 42161: "Arbitrum"}


def _chain_label(chain_id: Optional[int]) -> str:
    if chain_id is None:
        return "Base"
    return _CHAIN_LABEL.get(int(chain_id), f"chain:{chain_id}")


def _token_info(chain_id, token_addr):
    is_native = (token_addr or "").lower() == _NATIVE
    return get_token(int(chain_id), None if is_native else token_addr)


async def _usd_value(chain_id, token_addr, amount_base) -> Optional[float]:
    """USD controvalue of one settlement's base-unit amount, or None when the
    token is unknown or unpriced."""
    info = _token_info(chain_id, token_addr)
    if info is None:
        return None
    price = await get_price(info.coingecko_id, "usd")
    if price is None:
        return None
    human = Decimal(amount_base) / (Decimal(10) ** info.decimals)
    return float(human) * price


@router.get("/stats", response_model=DashboardStats)
async def get_org_stats(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """Per-org KPI snapshot from on-chain settlements, scoped through the intent
    join (owner + environment) with USD conversion. 409 `no_primary_wallet` if
    the org has no primary EVM wallet yet."""
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    now = datetime.now(timezone.utc)
    win_24h = now - timedelta(hours=24)
    win_48h = now - timedelta(hours=48)
    win_7d = now - timedelta(days=7)
    win_30d = now - timedelta(days=30)

    # Base scope: this org's FINAL settlements, attributed via the intent join.
    def scoped(stmt):
        return stmt.join(
            PaymentIntent, PaymentSettlement.intent_id == PaymentIntent.intent_id
        ).where(
            and_(
                PaymentIntent.merchant_id == owner,
                PaymentIntent.environment == environment,
                PaymentSettlement.status == SettlementStatus.final,
            )
        )

    # ── Transaction counts (24h + previous 24h for the delta) ──
    transactions_24h = int(
        (
            await db.execute(
                scoped(select(func.count(PaymentSettlement.id))).where(
                    PaymentSettlement.created_at >= win_24h
                )
            )
        ).scalar()
        or 0
    )
    txs_prev = int(
        (
            await db.execute(
                scoped(select(func.count(PaymentSettlement.id))).where(
                    and_(
                        PaymentSettlement.created_at >= win_48h,
                        PaymentSettlement.created_at < win_24h,
                    )
                )
            )
        ).scalar()
        or 0
    )
    transactions_24h_delta = transactions_24h - txs_prev

    # ── Distinct chains all-time ──
    total_balance_chains = int(
        (
            await db.execute(
                scoped(select(func.count(func.distinct(PaymentSettlement.chain_id))))
            )
        ).scalar()
        or 0
    )

    # ── Active clients (distinct payer, 30d) + new-this-week (7d) ──
    active_clients = int(
        (
            await db.execute(
                scoped(
                    select(func.count(func.distinct(PaymentSettlement.payer)))
                ).where(PaymentSettlement.created_at >= win_30d)
            )
        ).scalar()
        or 0
    )
    prior_payers = scoped(select(PaymentSettlement.payer)).where(
        PaymentSettlement.created_at < win_7d
    )
    active_clients_this_week = int(
        (
            await db.execute(
                scoped(
                    select(func.count(func.distinct(PaymentSettlement.payer)))
                ).where(
                    and_(
                        PaymentSettlement.created_at >= win_7d,
                        ~PaymentSettlement.payer.in_(prior_payers),
                    )
                )
            )
        ).scalar()
        or 0
    )

    # ── USD volume: 24h + previous 24h (rows fetched, priced in Python) ──
    async def _volume(since, until=None) -> float:
        stmt = scoped(select(PaymentSettlement)).where(
            PaymentSettlement.created_at >= since
        )
        if until is not None:
            stmt = stmt.where(PaymentSettlement.created_at < until)
        rows = (await db.execute(stmt)).scalars().all()
        total = 0.0
        for s in rows:
            usd = await _usd_value(s.chain_id, s.token, s.amount)
            if usd is not None:
                total += usd
        return round(total, 2)

    volume_24h = await _volume(win_24h)
    volume_prev = await _volume(win_48h, win_24h)
    volume_24h_delta_pct = (
        round((volume_24h - volume_prev) / volume_prev * 100, 1)
        if volume_prev > 0
        else 0.0
    )

    # ── Recent 5 settlements (with per-row USD) ──
    recent_rows = (
        await db.execute(
            scoped(select(PaymentSettlement))
            .order_by(desc(PaymentSettlement.created_at), desc(PaymentSettlement.id))
            .limit(5)
        )
    ).scalars().all()
    recent = []
    for s in recent_rows:
        usd = await _usd_value(s.chain_id, s.token, s.amount)
        info = _token_info(s.chain_id, s.token)
        recent.append(
            RecentTransaction(
                id=int(s.id),
                tx_hash=s.tx_hash,
                type="transfer",
                amount_usd=round(usd, 2) if usd is not None else 0.0,
                currency=info.symbol if info else "TOKEN",
                chain=_chain_label(s.chain_id),
                status="confirmed",
                recipient=(s.merchant or "").lower(),
                timestamp_iso=s.created_at.isoformat() if s.created_at else "",
            )
        )

    return DashboardStats(
        volume_24h=volume_24h,
        volume_24h_delta_pct=volume_24h_delta_pct,
        transactions_24h=transactions_24h,
        transactions_24h_delta=transactions_24h_delta,
        total_balance=0.0,  # non-custodial: no held balance
        total_balance_chains=total_balance_chains,
        active_clients=active_clients,
        active_clients_this_week=active_clients_this_week,
        recent_transactions=recent,
    )
