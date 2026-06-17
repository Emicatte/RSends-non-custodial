"""Pydantic schemas for /api/v1/user/notifications."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email_login_new_device: bool
    telegram_tx_confirmed: bool
    telegram_tx_failed: bool
    telegram_price_alerts: bool
    telegram_chat_id: Optional[str]
    updated_at: datetime


class NotificationPreferencesUpdate(BaseModel):
    email_login_new_device: Optional[bool] = None
    telegram_tx_confirmed: Optional[bool] = None
    telegram_tx_failed: Optional[bool] = None
    telegram_price_alerts: Optional[bool] = None


class KnownDeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_agent_snippet: Optional[str]
    ip_last_seen: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime
    login_count: int
