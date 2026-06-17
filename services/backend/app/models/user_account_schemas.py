"""Pydantic v2 schemas for the /api/v1/user/account router.

Naming notes
- ActiveSessionResponse.last_activity_at is the API-facing name for the
  backing column UserSession.last_used_at (kept for frontend consistency
  with other "last_activity" fields — see user_wallets).
- AccountStatusResponse.days_until_deletion is derived in the route layer,
  not stored. Values ≥ 0; clamped at 0 when deletion cutoff is in the past.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ActiveSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    created_at: datetime
    last_activity_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent_snippet: Optional[str] = None
    is_current: bool = False


class ActiveSessionsListResponse(BaseModel):
    sessions: list[ActiveSessionResponse]


class KnownDeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_agent_snippet: Optional[str] = None
    ip_last_seen: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    login_count: int


class KnownDevicesListResponse(BaseModel):
    devices: list[KnownDeviceResponse]


class AccountStatusResponse(BaseModel):
    email: str
    display_name: Optional[str] = None
    created_at: datetime
    deletion_requested_at: Optional[datetime] = None
    deletion_scheduled_for: Optional[datetime] = None
    deletion_reason: Optional[str] = None
    days_until_deletion: Optional[int] = None


class DeleteAccountRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    confirmation: str = Field(min_length=1)


class RevokeSessionResponse(BaseModel):
    revoked: bool
    session_id: str


class RevokeAllResponse(BaseModel):
    revoked_count: int
