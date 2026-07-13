"""Admin approval surface — server-to-server only, behind the EXISTING
require_admin (X-Admin-Token) dependency. The web app's shared /api/backend
proxy denylists /admin/*; the Next.js admin page reaches these through its own
server-side route that injects the header.

The DB is the source of truth for the queue: Telegram is a convenience
notification, so a lost message never strands a merchant — they are always
listed here. Decisions are allowed only from 'pending_approval' (409
already_decided otherwise) and are audited (APPROVAL_GRANTED /
APPROVAL_DECLINED).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_routes import require_admin
from app.db.session import get_db
from app.models.admin_approval_schemas import (
    ApprovalDecisionResponse,
    DeclineRequest,
    PendingApprovalRow,
)
from app.models.onboarding_models import CompanyProfile
from app.models.org_models import Organization
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

admin_approval_router = APIRouter(
    prefix="/admin/approvals",
    tags=["admin-approvals"],
    dependencies=[Depends(require_admin)],
)

_PROFILE_FIELDS = (
    "legal_name",
    "trading_name",
    "country",
    "registration_number",
    "tax_or_vat_number",
    "website",
    "business_category",
    "expected_monthly_volume",
    "countries_served",
    "primary_stablecoin",
    "no_sanctioned_countries",
    "no_prohibited_activities",
    "has_pep",
)


def _profile_dict(profile: CompanyProfile | None) -> dict:
    if profile is None:
        return {}
    return {f: getattr(profile, f) for f in _PROFILE_FIELDS}


@admin_approval_router.get("", response_model=list[PendingApprovalRow])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
) -> list[PendingApprovalRow]:
    """Pending orgs WITH a submitted company profile — the review queue."""
    rows = (
        await db.execute(
            select(Organization, CompanyProfile)
            .join(CompanyProfile, CompanyProfile.org_id == Organization.id)
            .where(
                Organization.approval_status == "pending_approval",
                Organization.onboarding_status == "company_submitted",
                Organization.deleted_at.is_(None),
            )
            .order_by(Organization.created_at)
        )
    ).all()
    return [
        PendingApprovalRow(
            org_id=str(org.id),
            name=org.name,
            slug=org.slug,
            created_at=org.created_at,
            approval_requested_at=org.approval_requested_at,
            profile_submitted_at=profile.submitted_at,
            company_profile=_profile_dict(profile),
        )
        for org, profile in rows
    ]


async def _load_pending_org(db: AsyncSession, org_id: str) -> Organization:
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == org_id, Organization.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    if org.approval_status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail={"code": "already_decided", "status": org.approval_status},
        )
    return org


@admin_approval_router.post(
    "/{org_id}/approve", response_model=ApprovalDecisionResponse
)
async def approve_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApprovalDecisionResponse:
    org = await _load_pending_org(db, org_id)
    org.approval_status = "approved"
    org.approval_decided_at = datetime.now(timezone.utc)
    org.approval_decided_by = "admin"
    org.decline_reason = None

    await log_event(
        db,
        "APPROVAL_GRANTED",
        "organization",
        str(org.id),
        actor_type="admin",
        changes={"approval_status": "pending_approval -> approved"},
    )
    await db.commit()
    return ApprovalDecisionResponse(org_id=str(org.id), approval_status="approved")


@admin_approval_router.post(
    "/{org_id}/decline", response_model=ApprovalDecisionResponse
)
async def decline_org(
    org_id: str,
    payload: DeclineRequest,
    db: AsyncSession = Depends(get_db),
) -> ApprovalDecisionResponse:
    org = await _load_pending_org(db, org_id)
    org.approval_status = "declined"
    org.approval_decided_at = datetime.now(timezone.utc)
    org.approval_decided_by = "admin"
    org.decline_reason = payload.reason

    await log_event(
        db,
        "APPROVAL_DECLINED",
        "organization",
        str(org.id),
        actor_type="admin",
        changes={
            "approval_status": "pending_approval -> declined",
            "reason": payload.reason[:200],
        },
    )
    await db.commit()
    return ApprovalDecisionResponse(
        org_id=str(org.id),
        approval_status="declined",
        decline_reason=payload.reason,
    )
