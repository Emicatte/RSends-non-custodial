"""Staged onboarding: status transitions, consents, company profile lifecycle.

Owns the ONLY mutation path for `Organization.onboarding_status`
(forward-only) and the append-only consent trail. The company profile is
draft-until-submit: `upsert_company_profile_draft` accepts partial data,
`submit_company_profile` validates completeness + declarations, stamps
`submitted_at` and advances the org to 'company_submitted' (full testnet
access, no human review). Nothing here touches `activation_status` — that is
the future business-verification provider's slot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal_versions import CURRENT_VERSIONS
from app.models.auth_models import User
from app.models.onboarding_models import CompanyProfile, ConsentRecord
from app.models.org_models import Organization

# Forward-only ordering. Index = progression; any move to a lower-or-equal
# index is invalid.
_STATUS_ORDER = ("created", "email_verified", "company_submitted")

# Fields that must be present (non-NULL / non-empty) at submit.
# trading_name and website stay optional.
_REQUIRED_AT_SUBMIT = (
    "legal_name",
    "country",
    "registration_number",
    "tax_or_vat_number",
    "business_category",
    "expected_monthly_volume",
    "countries_served",
    "primary_stablecoin",
)


class OnboardingError(Exception):
    def __init__(self, code: str, detail: str = "", missing: Optional[list[str]] = None):
        self.code = code
        self.detail = detail
        self.missing = missing or []
        super().__init__(f"{code}: {detail}")


# ── Status transitions ────────────────────────────────────────────

def advance_onboarding_status(org: Organization, target: str) -> None:
    """Forward-only move of org.onboarding_status; raises on anything else."""
    current = org.onboarding_status
    if current not in _STATUS_ORDER or target not in _STATUS_ORDER:
        raise OnboardingError("invalid_transition", f"{current} -> {target}")
    if _STATUS_ORDER.index(target) <= _STATUS_ORDER.index(current):
        raise OnboardingError("invalid_transition", f"{current} -> {target}")
    org.onboarding_status = target


def initial_onboarding_status(user: User) -> str:
    """Initial state for a fresh org: past 'created' iff the owner is verified."""
    return "email_verified" if user.email_verified else "created"


# ── Consents ──────────────────────────────────────────────────────

async def record_consents(
    db: AsyncSession, user: User, *, age_attested: bool
) -> None:
    """Append tos+privacy acceptances at the CURRENT versions.

    Always inserts fresh rows (append-only audit trail — re-accepting after a
    version bump adds new records, never rewrites). Stamps the user's 18+
    attestation when `age_attested` is True; never un-stamps.
    """
    now = datetime.now(timezone.utc)
    for doc_type in ("tos", "privacy"):
        db.add(
            ConsentRecord(
                id=str(uuid4()),
                user_id=user.id,
                document_type=doc_type,
                document_version=CURRENT_VERSIONS[doc_type],
                accepted_at=now,
            )
        )
    if age_attested and not user.age_attested:
        user.age_attested = True
        user.age_attested_at = now
    await db.flush()


async def consents_current(db: AsyncSession, user_id) -> bool:
    """True iff the LATEST recorded version of BOTH documents equals the
    current constant (string equality — versions are opaque labels)."""
    for doc_type, current_version in CURRENT_VERSIONS.items():
        row = (
            await db.execute(
                select(ConsentRecord.document_version)
                .where(
                    ConsentRecord.user_id == user_id,
                    ConsentRecord.document_type == doc_type,
                )
                .order_by(ConsentRecord.accepted_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row != current_version:
            return False
    return True


# ── Company profile lifecycle ─────────────────────────────────────

async def get_company_profile(
    db: AsyncSession, org_id: str
) -> Optional[CompanyProfile]:
    return (
        await db.execute(
            select(CompanyProfile).where(CompanyProfile.org_id == org_id)
        )
    ).scalar_one_or_none()


async def upsert_company_profile_draft(
    db: AsyncSession, org_id: str, fields: dict
) -> CompanyProfile:
    """Create-or-update the org's draft with the given (partial) fields.

    Raises OnboardingError('already_submitted') once submitted — the profile
    is read-only through the API after submission (no edit endpoint).
    """
    profile = await get_company_profile(db, org_id)
    if profile is None:
        profile = CompanyProfile(id=str(uuid4()), org_id=org_id)
        db.add(profile)
    elif profile.submitted_at is not None:
        raise OnboardingError("already_submitted")

    for key, value in fields.items():
        setattr(profile, key, value)
    await db.flush()
    return profile


async def submit_company_profile(
    db: AsyncSession, org: Organization
) -> CompanyProfile:
    """Validate completeness + declarations, stamp submitted_at, advance org."""
    profile = await get_company_profile(db, str(org.id))
    if profile is None:
        raise OnboardingError(
            "incomplete_profile", missing=list(_REQUIRED_AT_SUBMIT)
        )
    if profile.submitted_at is not None:
        raise OnboardingError("already_submitted")

    missing = [
        field
        for field in _REQUIRED_AT_SUBMIT
        if not getattr(profile, field)  # None or empty string/list
    ]
    # Declarations: the first two MUST be true; has_pep accepts both values
    # but must be answered (it is a disclosure, not a declaration).
    if profile.no_sanctioned_countries is not True:
        missing.append("no_sanctioned_countries")
    if profile.no_prohibited_activities is not True:
        missing.append("no_prohibited_activities")
    if profile.has_pep is None:
        missing.append("has_pep")
    if missing:
        raise OnboardingError("incomplete_profile", missing=missing)

    profile.submitted_at = datetime.now(timezone.utc)
    advance_onboarding_status(org, "company_submitted")
    await db.flush()
    return profile


# ── Aggregate state (GET /api/v1/user/onboarding) ─────────────────

async def get_onboarding_state(db: AsyncSession, user: User) -> dict:
    """Assemble the onboarding state the frontend guard consumes."""
    org = None
    if user.active_org_id is not None:
        org = (
            await db.execute(
                select(Organization).where(Organization.id == user.active_org_id)
            )
        ).scalar_one_or_none()

    profile = None
    if org is not None:
        profile = await get_company_profile(db, str(org.id))

    return {
        "consents_current": await consents_current(db, user.id),
        "age_attested": bool(user.age_attested),
        "email_verified": bool(user.email_verified),
        "active_org_id": str(org.id) if org is not None else None,
        "onboarding_status": org.onboarding_status if org is not None else None,
        "activation_status": org.activation_status if org is not None else None,
        # Approval gate (migration 0010): what the post-KYB waiting screen
        # polls; decline_reason is the operator's text for the decline page.
        "approval_status": org.approval_status if org is not None else None,
        "decline_reason": org.decline_reason if org is not None else None,
        "company_profile": (
            {
                "exists": profile is not None,
                "submitted_at": profile.submitted_at if profile is not None else None,
            }
            if org is not None
            else None
        ),
    }
