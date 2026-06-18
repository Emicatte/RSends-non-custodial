from __future__ import annotations

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
