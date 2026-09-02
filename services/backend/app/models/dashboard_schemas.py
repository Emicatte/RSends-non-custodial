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
    # Machine-stable snake chain name — `base`, `base_sepolia`, `ethereum`,
    # `arbitrum`, `tron`, `tron_nile` — or the honest `chain:{id}` for a chain
    # id we cannot name. Clients key badges and explorer links on this and
    # derive display text from it.
    #
    # It replaced a `chain` field that carried a HUMAN LABEL and was also the
    # only thing a client could key on. That double duty is what let a badge map
    # keyed on labels and an explorer map keyed on snake names disagree about
    # the same row; keeping the label as well would have kept the second source
    # of truth, free to drift with nothing able to catch it.
    #
    # REQUIRED, deliberately. `amount_usd_known` below is defaulted because the
    # frozen legacy route had to keep constructing unedited; that route now
    # calls the same shared helper, so the reason is gone and a construction
    # that forgets this must fail loudly rather than invent a chain.
    chain_key: str
    status: str
    recipient: str
    timestamp_iso: str

    # False ⇒ `amount_usd` carries no information and must NOT be rendered as a
    # dollar figure: the token has no USD peg, so "$0.00" next to a real payment
    # would be a lie. Clients show the token symbol instead.
    #
    # Defaulted, unlike the OrgDashboardStats fields below, precisely because
    # this model is SHARED with the frozen legacy `dashboard_routes.py`, which
    # hardcodes `amount_usd=0.0` and must keep constructing without edits. That
    # route therefore reports `True` over a hardcoded zero — which is exactly
    # what it already implied; it stays frozen and is tracked separately.
    amount_usd_known: bool = True


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
    checklist facts for the /app home card, plus what `volume_24h` had to leave
    out. ONLY `GET /api/v1/user/org/stats` uses this — the frozen legacy
    dashboard_routes.py keeps plain DashboardStats. All required: a
    construction that forgets one must fail loudly, not default."""

    settlement_wallet_set: bool
    has_api_key: bool
    has_paid_payment: bool

    # Settlements inside the 24h window that `volume_24h` could NOT value and
    # therefore did not sum — they are excluded, not counted as zero.
    #
    # Without this the response cannot tell two very different situations
    # apart, because both report `volume_24h == 0.0`:
    #   transactions_24h=0, unpriced=0 → nobody paid
    #   transactions_24h=N, unpriced=N → paid, in something we cannot value
    # The second reads as the first, which is the defect these fields close.
    volume_24h_unpriced_count: int
    # Distinct symbols behind that count, so the UI can name them ("ETH")
    # instead of saying "some payments". A token the registry does not know at
    # all has no symbol to report and contributes to the count only — never an
    # invented label.
    volume_24h_unpriced_symbols: List[str]

    # ── The two tiles that replaced `total_balance` / `active_clients` ──
    #
    # `total_balance` is hard-coded 0.0 upstream and always was: RSends is
    # non-custodial, it holds nothing, so a balance tile can only ever assert a
    # custody the product does not have. `active_clients` is a fact about the
    # business, not about the interface. Both are still SENT — narrowing a
    # response is a wire change nothing here forces — but the /app home reads
    # these two instead, and so does the landing page's device mockup, which
    # renders the same `MetricCards` component against a fixture.
    #
    # `volume_30d` carries the same "unpriced is excluded, never zero" contract
    # as `volume_24h`; its exclusions are not reported separately, because the
    # 24h counters above are what the disclosure line on the page is built from.
    volume_30d: float
    volume_30d_delta_pct: float
    # Deliveries ATTEMPTED is the denominator of the rate the UI shows. Sending
    # the two counts rather than a pre-divided percentage keeps "no webhooks at
    # all" (0/0) distinguishable from "every one failed" (0/N) — the same
    # absent-is-not-zero rule the volume fields above follow.
    webhooks_delivered_24h: int
    webhooks_attempted_24h: int


class VolumeBucket(BaseModel):
    """One UTC calendar day of settled USD volume.

    `date` is a bare UTC calendar date with no time and no offset, so the
    client never has to guess a timezone to place the point; it decides only
    how to LABEL it. A quiet day is a bucket with `volume_usd == 0.0`, never an
    omitted entry — a gap in this array is how a chart draws a misleading line.

    `unpriced_count` is per-bucket rather than window-level only because a
    single flat-looking day is exactly where a dropped payment hides: a bucket
    reading 0.0 with `unpriced_count > 0` was NOT a quiet day.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_
    volume_usd: float
    unpriced_count: int


class VolumeSeriesResponse(BaseModel):
    """`GET /api/v1/user/org/stats/volume-series` — the /app volume-trend card.

    `days` is echoed back so the client never infers the series length from
    `len(buckets)`; the two are always equal, and a mismatch is a bug worth
    seeing rather than silently rendering a short chart.

    `unpriced_count` is the window total — always equal to the sum of the
    buckets' counts — so the card can state its exclusion once without walking
    the array. A whole series of zeros with a non-zero count is a chart that
    must say why it is flat.
    """

    model_config = ConfigDict(from_attributes=True)

    days: int
    buckets: List[VolumeBucket]
    unpriced_count: int
