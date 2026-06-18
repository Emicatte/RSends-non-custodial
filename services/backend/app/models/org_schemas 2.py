"""Pydantic v2 schemas for the Organizations API.

Design notes
------------
- Email fields: plain `str` with a regex `field_validator`, NOT `EmailStr`.
  `EmailStr` requires `email-validator` which is not in `requirements.txt`.
  A conservative regex is sufficient for our use case (the authoritative
  check is whether the invite email matches the Google-verified email at
  accept time).
- OrgRole is a Literal restricted to the three roles the RBAC hierarchy
  knows about — any other role string must never reach the DB.
- `from_attributes=True` everywhere that wraps a SQLAlchemy row so routes
  can `ModelName.model_validate(orm_row)` directly.
"""

import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

OrgRole = Literal["admin", "operator", "viewer"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("invalid_email")
    if len(value) > 254:
        raise ValueError("invalid_email")
    return value


# ─── Organization ────────────────────────────────────────────────

class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class OrganizationPatchRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    owner_user_id: UUID
    is_personal: bool
    plan: str
    role: Optional[OrgRole] = None
    member_count: Optional[int] = None
    created_at: datetime


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]
    active_org_id: Optional[UUID]


class ActiveOrgSwitch(BaseModel):
    org_id: UUID


class ActiveOrgSwitchResponse(BaseModel):
    active_org_id: UUID


# ─── Membership ──────────────────────────────────────────────────

class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    user_email: str
    user_display_name: Optional[str]
    role: OrgRole
    joined_at: datetime


class MembershipListResponse(BaseModel):
    memberships: list[MembershipResponse]
    max_allowed: int


class MembershipRoleUpdate(BaseModel):
    role: OrgRole


# ─── Invite ──────────────────────────────────────────────────────

class InviteCreateRequest(BaseModel):
    email: str
    role: OrgRole

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)


class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: str
    status: str
    created_at: datetime
    expires_at: datetime


class InvitesListResponse(BaseModel):
    invites: list[InviteResponse]


# ─── Invite public landing (accept/decline preview) ──────────────

class InvitePreviewResponse(BaseModel):
    org_name: str
    role: str
    invite_email: str
    status: str
    email_matches: bool
    user_email: str
    expires_at: datetime


class InviteAcceptResponse(BaseModel):
    org_id: UUID
    role: str
