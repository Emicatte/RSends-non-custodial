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

from app.security.input_validator import TRON_ZERO_ADDRESS, is_tron_address

OrgRole = Literal["admin", "operator", "viewer"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_settlement_wallet(value: Optional[str]) -> Optional[str]:
    """Reject-never-coerce EVM address for the org settlement wallet. `None`
    means "field omitted → leave unchanged"; any provided value must be a valid,
    non-zero EVM address (a zero settlement wallet would burn funds). Stored
    lowercase to match on-chain merchant comparisons. Replace-only: there is no
    clear-to-empty path — an empty string fails validation."""
    if value is None:
        return None
    value = value.strip()
    if not _EVM_ADDR_RE.match(value):
        raise ValueError("settlement_wallet must be a valid EVM address")
    if int(value, 16) == 0:
        raise ValueError("settlement_wallet cannot be the zero address")
    return value.lower()


def _validate_settlement_wallet_tron(value: Optional[str]) -> Optional[str]:
    """Reject-never-coerce TRON address for the org's TRON payout wallet.

    Deliberately NOT the EVM validator with a wider regex. A base58check address
    is case-SENSITIVE and its alphabet excludes `0 O I l`, so the `.lower()` that
    normalises an EVM address turns a T-address into a string that cannot be
    decoded and whose checksum no longer verifies. The value is therefore
    stripped and otherwise stored byte-identical.

    An 0x address is rejected outright rather than migrated to the other field:
    a payout address is not something to guess about.

    `is_tron_address` (input_validator) is the ONE decoder — it verifies the full
    double-SHA256 checksum, not just the shape, because a mistyped character
    means funds sent nowhere and the watch-only path has no contract to reject it
    for us. Same `None` = "omitted → unchanged" and replace-only semantics as
    `settlement_wallet`: the empty string fails, so there is no clear-to-empty
    path.
    """
    if value is None:
        return None
    value = value.strip()
    if not is_tron_address(value):
        raise ValueError("settlement_wallet_tron must be a valid TRON address")
    if value == TRON_ZERO_ADDRESS:
        raise ValueError("settlement_wallet_tron cannot be the zero address")
    return value


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
    settlement_wallet: Optional[str] = Field(default=None, max_length=42)
    # max_length stays at 42 (the EVM width) rather than 34 (the TRON width) so
    # an 0x address reaches the validator and is refused with a message about
    # the address FAMILY, instead of a bare length error that says nothing.
    settlement_wallet_tron: Optional[str] = Field(default=None, max_length=42)

    @field_validator("settlement_wallet")
    @classmethod
    def _check_settlement_wallet(cls, v: Optional[str]) -> Optional[str]:
        return _validate_settlement_wallet(v)

    @field_validator("settlement_wallet_tron")
    @classmethod
    def _check_settlement_wallet_tron(cls, v: Optional[str]) -> Optional[str]:
        return _validate_settlement_wallet_tron(v)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    owner_user_id: UUID
    is_personal: bool
    plan: str
    settlement_wallet: Optional[str] = None
    # Compatible addition: defaulted, so every existing caller and every org that
    # has not set a TRON payout address is unaffected.
    settlement_wallet_tron: Optional[str] = None
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
