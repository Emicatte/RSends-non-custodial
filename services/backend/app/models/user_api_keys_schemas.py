"""Pydantic schemas for /api/v1/user/api-keys.

Scopes v1 (6): narrow, explicit, least-privilege. Dedup + reject-unknown via
a field_validator so the DB never stores garbage.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALL_AVAILABLE_SCOPES: List[str] = [
    "transactions:read",
    "transactions:write",
    "routes:read",
    "contacts:read",
    "wallets:read",
    "account:read",
]


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    scopes: List[str] = Field(min_length=1, max_length=len(ALL_AVAILABLE_SCOPES))

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, v: List[str]) -> List[str]:
        invalid = [s for s in v if s not in ALL_AVAILABLE_SCOPES]
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}")
        seen: set[str] = set()
        dedup: List[str] = []
        for s in v:
            if s not in seen:
                dedup.append(s)
                seen.add(s)
        return dedup


class ApiKeyCreateResponse(BaseModel):
    """Plaintext key is returned ONCE — never shown again by any subsequent GET."""

    id: str
    label: str
    scopes: List[str]
    plaintext_key: str
    display_prefix: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    scopes: List[str]
    display_prefix: str
    environment: str
    rate_limit_rpm: int
    is_active: bool
    revoked_at: Optional[datetime]
    created_at: datetime
    last_used_at: Optional[datetime]
    last_used_ip: Optional[str]
    total_requests: int
    created_by_user_id: Optional[str] = None
    created_by_email: Optional[str] = None


class ApiKeyListResponse(BaseModel):
    keys: List[ApiKeyListItem]
    max_allowed: int
    remaining_slots: int


class ApiKeyPatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)


class AvailableScopesResponse(BaseModel):
    scopes: List[str]
