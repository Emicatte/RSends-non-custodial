"""Schemas for the admin approval surface (/admin/approvals, X-Admin-Token)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeclineRequest(BaseModel):
    # Operator-facing text shown verbatim to the merchant on the decline page.
    reason: str = Field(min_length=1, max_length=2000)


class PendingApprovalRow(BaseModel):
    org_id: str
    name: str
    slug: str
    created_at: Optional[datetime] = None
    approval_requested_at: Optional[datetime] = None
    profile_submitted_at: Optional[datetime] = None
    # Explicit allowlisted dump of the KYB company profile (never the ORM row).
    company_profile: dict


class ApprovalDecisionResponse(BaseModel):
    org_id: str
    approval_status: str
    decline_reason: Optional[str] = None
