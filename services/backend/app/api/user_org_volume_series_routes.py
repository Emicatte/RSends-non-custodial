"""Session-authed (JWT) org volume time series — the /app "Volume trend" card.

Sibling of `GET /api/v1/user/org/stats`, deliberately NOT a field on it: the
/app home polls `/stats` every 30 seconds, and a 7-day settlement scan plus
per-row USD pricing has no business running that often. The trend moves slowly;
it gets its own route, its own rate-limit entry, and its own (unpolled) hook.

Scoping is a verbatim copy of the stats route's, and that is load-bearing: this
card sits directly beside the `volume_24h` tile, so if the two scopes ever
diverged the dashboard would show two different answers for the same money.
Settlements are attributed through the intent join —

    PaymentSettlement JOIN PaymentIntent ON settlement.intent_id == intent.intent_id
    WHERE intent.merchant_id == owner AND intent.environment == :env
      AND settlement.status == final

— which is mandatory rather than stylistic, because `PaymentSettlement` has NO
`environment` column: env isolation can ONLY come from the intent side. Only
`final` settlements count (`pending`/`reorged`/`rejected` are money that did not,
or no longer does, settle) — the same rule the 24h tile applies.
`test_org_volume_series.py::test_series_agrees_with_the_stats_tile` pins the
agreement behaviourally.

Bucketing is by `PaymentSettlement.created_at`, the same column every existing
KPI uses and the only non-nullable candidate (`block_timestamp`/`finalized_at`
are nullable and would silently drop rows). Known caveat: `created_at` is
indexer INGEST time, not on-chain time, so a re-index would land historical rows
in today's bucket. Consistency with the neighbouring tile wins over semantic
purity; changing it means changing both together.

USD conversion mirrors the stats route (`app.tokens.registry` for decimals +
coingecko id, `price_service.get_price` for the rate), with one difference: the
price is resolved ONCE per distinct (chain_id, token) rather than once per row,
because a 7-day window carries many more rows than a 24h one. Tokens with no
registry entry or no cached price contribute 0 — inherited, not invented.

Read-only: SELECTs only, no writes, no migration.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_approved import require_org_approved
from app.api.merchant_profile_routes import _resolve_owner_address
from app.api.user_org_stats_routes import _token_info
from app.db.session import get_db
from app.models.dashboard_schemas import VolumeBucket, VolumeSeriesResponse
from app.models.merchant_models import PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.services.price_service import get_price

router = APIRouter(prefix="/api/v1/user/org", tags=["user-org-stats"])

MAX_DAYS = 31


def _as_utc(dt: datetime) -> datetime:
    """Interpret a settlement timestamp as UTC.

    SQLite (and any driver that drops tzinfo) hands back a NAIVE datetime even
    for a `DateTime(timezone=True)` column. `naive.astimezone(utc)` would assume
    the value is in the SERVER's local time and shift it, which silently moves a
    near-midnight settlement into the neighbouring day. Everything is stored UTC,
    so stamp it rather than convert it.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _usd_factors(
    rows: Iterable[PaymentSettlement],
) -> Dict[Tuple[int, str], Optional[Tuple[int, float]]]:
    """(chain_id, token) → (decimals, usd_price), or None when unpriceable.

    One `get_price` per distinct token instead of one per settlement.
    """
    factors: Dict[Tuple[int, str], Optional[Tuple[int, float]]] = {}
    for s in rows:
        key = (int(s.chain_id), (s.token or "").lower())
        if key in factors:
            continue
        info = _token_info(s.chain_id, s.token)
        if info is None:
            factors[key] = None
            continue
        price = await get_price(info.coingecko_id, "usd")
        factors[key] = None if price is None else (info.decimals, price)
    return factors


@router.get("/stats/volume-series", response_model=VolumeSeriesResponse)
async def get_org_volume_series(
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    days: int = Query(7, ge=1, le=MAX_DAYS),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> VolumeSeriesResponse:
    """Settled USD volume per UTC calendar day, oldest bucket first.

    Always returns exactly `days` buckets ending on today (UTC), quiet days
    included as `0.0`. An org with no data — or no owner identity at all, the
    fresh-merchant state — gets 200 with zeroed buckets, never a 404 and never
    an error: having no payments yet is a normal state for this product. A
    contested settlement wallet still propagates the resolver's 409
    `settlement_wallet_conflict`.
    """
    _user_id, org_id, _role = ctx

    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=days - 1)
    # Pre-seeded so a quiet day is a zero bucket, never a missing key.
    totals: Dict[date_, float] = {
        start_day + timedelta(days=i): 0.0 for i in range(days)
    }

    def _response() -> VolumeSeriesResponse:
        return VolumeSeriesResponse(
            days=days,
            buckets=[
                VolumeBucket(date=d, volume_usd=round(totals[d], 2))
                for d in sorted(totals)
            ],
        )

    try:
        owner = await _resolve_owner_address(db, org_id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") != "no_primary_wallet":
            raise
        # No identity yet → no attributable intents. Zeros are the truthful
        # fresh-org series, not an error. Mirrors the stats route's escape hatch.
        return _response()

    window_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

    # Base scope: this org's FINAL settlements, attributed via the intent join.
    # Copied verbatim from user_org_stats_routes.get_org_stats — see module docstring.
    stmt = (
        select(PaymentSettlement)
        .join(
            PaymentIntent, PaymentSettlement.intent_id == PaymentIntent.intent_id
        )
        .where(
            and_(
                PaymentIntent.merchant_id == owner,
                PaymentIntent.environment == environment,
                PaymentSettlement.status == SettlementStatus.final,
                PaymentSettlement.created_at >= window_start,
            )
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    factors = await _usd_factors(rows)
    for s in rows:
        if s.created_at is None:
            continue
        day = _as_utc(s.created_at).date()
        if day not in totals:
            # Rows at/after "tomorrow" (clock skew) are out of the window.
            continue
        factor = factors.get((int(s.chain_id), (s.token or "").lower()))
        if factor is None:
            continue
        decimals, price = factor
        totals[day] += float(Decimal(s.amount) / (Decimal(10) ** decimals)) * price

    return _response()
