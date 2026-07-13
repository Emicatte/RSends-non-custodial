"""Session-authed (JWT) onboarding endpoints.

The browser wizard reads/writes here: aggregate onboarding state (what the
frontend server guard consumes), consent recording, and the company-profile
draft/submit lifecycle. Routes live under the `/api/v1/user/` prefix, which
is JWT-exempt from the API-key middleware (app/security/api_keys.py
EXEMPT_PATHS) — no change to the auth perimeter — and inside the
email-verified gate's namespace (unverified users get 403
email_not_verified from the middleware; the frontend routes them to the
verify step first).

Environment-agnostic by design: onboarding is a property of the org, not of
test/live data. Org scoping is server-derived (active org via
require_org_role) — org_id is never client-supplied. These routes must NOT
be gated by require_org_company_submitted: they are how a merchant gets
through onboarding.
"""

from __future__ import annotations

from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.api.organizations_routes import require_user_id
from app.db.session import get_db
from app.models.auth_models import User
from app.models.onboarding_schemas import (
    CompanyProfilePatch,
    CompanyProfileResponse,
    ConsentSubmitRequest,
    OnboardingStateResponse,
)
from app.models.org_models import Organization
from app.services.onboarding_service import (
    OnboardingError,
    get_company_profile,
    get_onboarding_state,
    record_consents,
    submit_company_profile,
    upsert_company_profile_draft,
)

router = APIRouter(prefix="/api/v1/user", tags=["user-onboarding"])

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
    "submitted_at",
)


async def _load_user(db: AsyncSession, user_id: str) -> User:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "user_not_found"})
    return user


def _profile_response(profile) -> CompanyProfileResponse:
    return CompanyProfileResponse(
        **{field: getattr(profile, field) for field in _PROFILE_FIELDS}
    )


def _onboarding_error_to_http(e: OnboardingError) -> HTTPException:
    if e.code == "already_submitted":
        return HTTPException(status_code=409, detail={"code": e.code})
    if e.code == "incomplete_profile":
        return HTTPException(
            status_code=422, detail={"code": e.code, "missing": e.missing}
        )
    return HTTPException(status_code=400, detail={"code": e.code})


# ── Aggregate state ───────────────────────────────────────────────

@router.get("/onboarding", response_model=OnboardingStateResponse)
async def get_onboarding_state_route(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStateResponse:
    """The frontend guard's single read: consent currency, age attestation,
    email verification, and the active org's status fields (null when the
    user has no org yet)."""
    user = await _load_user(db, user_id)
    state = await get_onboarding_state(db, user)
    return OnboardingStateResponse(**state)


# ── Consents ──────────────────────────────────────────────────────

@router.post("/consents", response_model=OnboardingStateResponse)
async def post_consents(
    payload: ConsentSubmitRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStateResponse:
    """Record ToS+Privacy acceptance at the current versions + the 18+
    attestation (both checkboxes schema-enforced true). Re-accepting after a
    version bump appends fresh rows — the audit trail, not an error."""
    user = await _load_user(db, user_id)
    await record_consents(db, user, age_attested=payload.age_attested)
    await db.commit()
    state = await get_onboarding_state(db, user)
    return OnboardingStateResponse(**state)


# ── Company profile draft / submit ────────────────────────────────

@router.get("/org/company-profile", response_model=CompanyProfileResponse)
async def get_org_company_profile(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """Read the active org's profile (draft or submitted). 404 when no draft
    exists yet — scoped to the server-derived active org only."""
    _user_id, org_id, _role = ctx
    profile = await get_company_profile(db, org_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return _profile_response(profile)


@router.patch("/org/company-profile", response_model=CompanyProfileResponse)
async def patch_org_company_profile(
    payload: CompanyProfilePatch,
    ctx: Tuple[str, str, str] = Depends(require_org_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """Autosave the draft (partial update; unset fields untouched). `admin`
    only — this is the org's legal identity. 409 once submitted: the profile
    is read-only through the API after submission (edits go through support)."""
    _user_id, org_id, _role = ctx
    fields = payload.model_dump(exclude_unset=True)
    try:
        profile = await upsert_company_profile_draft(db, org_id, fields)
    except OnboardingError as e:
        raise _onboarding_error_to_http(e)
    await db.commit()
    return _profile_response(profile)


@router.post("/org/company-profile/submit", response_model=CompanyProfileResponse)
async def submit_org_company_profile(
    ctx: Tuple[str, str, str] = Depends(require_org_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """Finalize: validates completeness + the two must-be-true declarations +
    an answered has_pep (422 `incomplete_profile` with a `missing` list
    otherwise), stamps submitted_at, advances the org to 'company_submitted'
    (full testnet access, zero human review). 409 on double submit."""
    _user_id, org_id, _role = ctx
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    try:
        profile = await submit_company_profile(db, org)
    except OnboardingError as e:
        raise _onboarding_error_to_http(e)
    await db.commit()

    # Approval-queue notification (convenience only — the merchant is already
    # queued in the DB and the admin page reads from there). Never raises.
    from app.services.approval_notify import notify_merchant_pending

    await notify_merchant_pending(org, profile)

    return _profile_response(profile)
