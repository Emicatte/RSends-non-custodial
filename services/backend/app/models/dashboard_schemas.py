from __future__ import annotations

from datetime import date as date_
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class RecentTransaction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tx_hash: Optional[str]
    type: str
    amount_usd: float
    currency: str
    chain: str
    status: str
    recipient: str
    timestamp_iso: str


class DashboardStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    volume_24h: float
    volume_24h_delta_pct: float
    transactions_24h: int
    transactions_24h_delta: int
    total_balance: float
    total_balance_chains: int
    active_clients: int
    active_clients_this_week: int
    recent_transactions: List[RecentTransaction]


class OrgDashboardStats(DashboardStats):
    """Session org-stats response: the KPI snapshot plus the get-started
    checklist facts for the /app home card. ONLY `GET /api/v1/user/org/stats`
    uses this — the frozen legacy dashboard_routes.py keeps plain
    DashboardStats. All three required: a construction that forgets one must
    fail loudly, not default."""

    settlement_wallet_set: bool
    has_api_key: bool
    has_paid_payment: bool


class VolumeBucket(BaseModel):
    """One UTC calendar day of settled USD volume.

    `date` is a bare UTC calendar date with no time and no offset, so the
    client never has to guess a timezone to place the point; it decides only
    how to LABEL it. A quiet day is a bucket with `volume_usd == 0.0`, never an
    omitted entry — a gap in this array is how a chart draws a misleading line.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_
    volume_usd: float


class VolumeSeriesResponse(BaseModel):
    """`GET /api/v1/user/org/stats/volume-series` — the /app volume-trend card.

    `days` is echoed back so the client never infers the series length from
    `len(buckets)`; the two are always equal, and a mismatch is a bug worth
    seeing rather than silently rendering a short chart.
    """

    model_config = ConfigDict(from_attributes=True)

    days: int
    buckets: List[VolumeBucket]
