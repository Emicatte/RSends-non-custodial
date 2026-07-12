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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_company_submitted import require_org_company_submitted
from app.api.merchant_profile_routes import _resolve_owner_address
from app.db.session import get_db
from app.models.dashboard_schemas import OrgDashboardStats, RecentTransaction
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.org_models import Organization
from app.models.settlement_models import PaymentSettlement, SettlementStatus

# The route reads user_api_keys via count_active_keys_for_org, whose model
# import is lazy — import it here so Base.metadata registers the table for
# any consumer that create_all's after importing this module.
from app.models.user_api_keys_models import UserApiKey  # noqa: F401
from app.services.price_service import get_price
from app.services.user_api_key_service import count_active_keys_for_org
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


@router.get("/stats", response_model=OrgDashboardStats)
async def get_org_stats(
    ctx: Tuple[str, str, str] = Depends(require_org_company_submitted("viewer")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> OrgDashboardStats:
    """Per-org KPI snapshot from on-chain settlements, scoped through the intent
    join (owner + environment) with USD conversion, plus the get-started
    checklist facts (`settlement_wallet_set` / `has_api_key` /
    `has_paid_payment`) for the /app home card. An org with no owner identity
    at all (no primary EVM wallet, no settlement wallet — the fresh-merchant
    state) gets 200 with zeroed KPIs and the org-scoped booleans, NOT the
    resolver's 409 `no_primary_wallet`; a contested settlement wallet still
    propagates 409 `settlement_wallet_conflict`."""
    _user_id, org_id, _role = ctx

    # Checklist facts that need no owner identity — computed FIRST so the
    # fresh-merchant state (resolver 409) still reports them truthfully.
    # Truthiness, not IS NOT NULL: the resolver treats "" as absent too.
    settlement_wallet_set = bool(
        (
            await db.execute(
                select(Organization.settlement_wallet).where(
                    Organization.id == org_id
                )
            )
        ).scalar_one_or_none()
    )
    has_api_key = (await count_active_keys_for_org(db, org_id)) > 0

    try:
        owner = await _resolve_owner_address(db, org_id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") != "no_primary_wallet":
            raise
        # No identity yet → the org can't have attributable intents. Zeroed
        # KPIs are the truthful fresh-org snapshot, not an error.
        return OrgDashboardStats(
            volume_24h=0.0,
            volume_24h_delta_pct=0.0,
            transactions_24h=0,
            transactions_24h_delta=0,
            total_balance=0.0,
            total_balance_chains=0,
            active_clients=0,
            active_clients_this_week=0,
            recent_transactions=[],
            settlement_wallet_set=settlement_wallet_set,
            has_api_key=has_api_key,
            has_paid_payment=False,
        )

    has_paid_payment = (
        (
            await db.execute(
                select(PaymentIntent.id)
                .where(
                    PaymentIntent.merchant_id == owner,
                    PaymentIntent.environment == environment,
                    PaymentIntent.status == IntentStatus.paid,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        is not None
    )

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

    return OrgDashboardStats(
        volume_24h=volume_24h,
        volume_24h_delta_pct=volume_24h_delta_pct,
        transactions_24h=transactions_24h,
        transactions_24h_delta=transactions_24h_delta,
        total_balance=0.0,  # non-custodial: no held balance
        total_balance_chains=total_balance_chains,
        active_clients=active_clients,
        active_clients_this_week=active_clients_this_week,
        recent_transactions=recent,
        settlement_wallet_set=settlement_wallet_set,
        has_api_key=has_api_key,
        has_paid_payment=has_paid_payment,
    )
