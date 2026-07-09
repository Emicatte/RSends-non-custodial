"""Company profile draft lifecycle — session endpoints (direct-handler).

Draft semantics: PATCH creates-or-updates with partial data (server-side
autosave), GET reads it back, everything is nullable until submit, and the
profile becomes READ-ONLY after submission (PATCH -> 409). Org isolation is
inherent to the ctx org_id (server-derived active org) and pinned here: org
B's ctx never sees org A's profile. Same direct-handler pattern as
test_user_org_payments.py.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.onboarding_models import CompanyProfile
from app.models.org_models import Membership, Organization


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_org(session, *, onboarding_status="email_verified"):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=True,
        plan="free",
        onboarding_status=onboarding_status,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    await session.commit()
    return org


def _ctx(org, role="admin"):
    return ("user-unused", str(org.id), role)


def _patch_payload(**fields):
    from app.models.onboarding_schemas import CompanyProfilePatch

    return CompanyProfilePatch(**fields)


# ── GET / PATCH draft ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_404_when_no_draft(session):
    from app.api.user_onboarding_routes import get_org_company_profile

    org = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await get_org_company_profile(ctx=_ctx(org), db=session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_creates_draft_then_updates_partially(session):
    from app.api.user_onboarding_routes import (
        get_org_company_profile,
        patch_org_company_profile,
    )

    org = await _make_org(session)

    first = await patch_org_company_profile(
        payload=_patch_payload(legal_name="RPagos S.R.L.", country="cr"),
        ctx=_ctx(org),
        db=session,
    )
    assert first.legal_name == "RPagos S.R.L."
    assert first.country == "CR"  # normalized upper
    assert first.submitted_at is None

    # Second partial PATCH must not clobber earlier fields.
    second = await patch_org_company_profile(
        payload=_patch_payload(business_category="saas"),
        ctx=_ctx(org),
        db=session,
    )
    assert second.legal_name == "RPagos S.R.L."
    assert second.business_category == "saas"

    read = await get_org_company_profile(ctx=_ctx(org), db=session)
    assert read.legal_name == "RPagos S.R.L."
    assert read.business_category == "saas"


@pytest.mark.asyncio
async def test_patch_after_submit_is_read_only_409(session):
    from datetime import datetime, timezone

    from app.api.user_onboarding_routes import patch_org_company_profile

    org = await _make_org(session)
    session.add(
        CompanyProfile(
            org_id=str(org.id),
            legal_name="Done",
            submitted_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await patch_org_company_profile(
            payload=_patch_payload(legal_name="Nope"),
            ctx=_ctx(org),
            db=session,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "already_submitted"


# ── Cross-org isolation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_org_isolation_on_profile_read_and_patch(session):
    from app.api.user_onboarding_routes import (
        get_org_company_profile,
        patch_org_company_profile,
    )

    org_a = await _make_org(session)
    org_b = await _make_org(session)

    await patch_org_company_profile(
        payload=_patch_payload(legal_name="A Corp"),
        ctx=_ctx(org_a),
        db=session,
    )

    # Org B's ctx: no profile visible (404), and its PATCH creates ITS OWN
    # draft rather than touching A's.
    with pytest.raises(HTTPException) as exc:
        await get_org_company_profile(ctx=_ctx(org_b), db=session)
    assert exc.value.status_code == 404

    b_profile = await patch_org_company_profile(
        payload=_patch_payload(legal_name="B Corp"),
        ctx=_ctx(org_b),
        db=session,
    )
    assert b_profile.legal_name == "B Corp"

    a_read = await get_org_company_profile(ctx=_ctx(org_a), db=session)
    assert a_read.legal_name == "A Corp"


# ── Patch schema validation (server-side reject, never coerce) ────

def test_patch_schema_rejects_bad_enum_and_url_and_country():
    from pydantic import ValidationError

    from app.models.onboarding_schemas import CompanyProfilePatch

    with pytest.raises(ValidationError):
        CompanyProfilePatch(business_category="crypto_casino")
    with pytest.raises(ValidationError):
        CompanyProfilePatch(expected_monthly_volume="a_lot")
    with pytest.raises(ValidationError):
        CompanyProfilePatch(primary_stablecoin="DOGE")
    with pytest.raises(ValidationError):
        CompanyProfilePatch(country="ZZ")
    with pytest.raises(ValidationError):
        CompanyProfilePatch(website="javascript:alert(1)")
    with pytest.raises(ValidationError):
        CompanyProfilePatch(countries_served=["IT", "ZZ"])

    ok = CompanyProfilePatch(
        website="https://rpagos.example",
        countries_served=["it", "CR"],
    )
    assert ok.countries_served == ["IT", "CR"]
