"""Company profile submit — completeness validation + status advancement.

Submit validates: all identity/operations fields present, the two
declarations strictly True, has_pep answered (either value). On success it
stamps submitted_at and advances the org to 'company_submitted' (full testnet
access, zero human review). 422 carries a machine-readable `missing` list;
double submit -> 409. Direct-handler pattern.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Membership, Organization


COMPLETE = dict(
    legal_name="RPagos S.R.L.",
    trading_name=None,
    country="CR",
    registration_number="3-101-999999",
    tax_or_vat_number="CR-3101999999",
    website=None,
    business_category="saas",
    expected_monthly_volume="10k_100k",
    countries_served=["CR", "IT"],
    primary_stablecoin="USDC",
    no_sanctioned_countries=True,
    no_prohibited_activities=True,
    has_pep=False,
)


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


async def _patch(session, org, **fields):
    from app.api.user_onboarding_routes import patch_org_company_profile
    from app.models.onboarding_schemas import CompanyProfilePatch

    return await patch_org_company_profile(
        payload=CompanyProfilePatch(**fields), ctx=_ctx(org), db=session
    )


async def _submit(session, org):
    from app.api.user_onboarding_routes import submit_org_company_profile

    return await submit_org_company_profile(ctx=_ctx(org), db=session)


# ── Happy path ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_complete_profile_advances_org(session):
    org = await _make_org(session)
    await _patch(session, org, **{k: v for k, v in COMPLETE.items() if v is not None})

    result = await _submit(session, org)
    assert result.submitted_at is not None

    row = (
        await session.execute(
            select(Organization).where(Organization.id == org.id)
        )
    ).scalar_one()
    assert row.onboarding_status == "company_submitted"
    assert row.activation_status == "not_started"  # untouched by submit


@pytest.mark.asyncio
async def test_double_submit_409(session):
    org = await _make_org(session)
    await _patch(session, org, **{k: v for k, v in COMPLETE.items() if v is not None})
    await _submit(session, org)

    with pytest.raises(HTTPException) as exc:
        await _submit(session, org)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "already_submitted"


# ── Completeness / declarations ───────────────────────────────────

@pytest.mark.asyncio
async def test_submit_without_any_draft_422_lists_all_required(session):
    org = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _submit(session, org)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "incomplete_profile"
    assert "legal_name" in exc.value.detail["missing"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "absent",
    [
        "legal_name",
        "country",
        "registration_number",
        "tax_or_vat_number",
        "business_category",
        "expected_monthly_volume",
        "countries_served",
        "primary_stablecoin",
    ],
)
async def test_submit_each_missing_field_is_reported(session, absent):
    org = await _make_org(session)
    fields = {
        k: v for k, v in COMPLETE.items() if v is not None and k != absent
    }
    await _patch(session, org, **fields)

    with pytest.raises(HTTPException) as exc:
        await _submit(session, org)
    assert exc.value.status_code == 422
    assert exc.value.detail["missing"] == [absent]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "declaration", ["no_sanctioned_countries", "no_prohibited_activities"]
)
async def test_submit_false_declaration_422(session, declaration):
    org = await _make_org(session)
    fields = {k: v for k, v in COMPLETE.items() if v is not None}
    fields[declaration] = False
    await _patch(session, org, **fields)

    with pytest.raises(HTTPException) as exc:
        await _submit(session, org)
    assert exc.value.status_code == 422
    assert declaration in exc.value.detail["missing"]


@pytest.mark.asyncio
async def test_submit_unanswered_pep_422_but_true_is_accepted(session):
    org = await _make_org(session)
    fields = {
        k: v for k, v in COMPLETE.items() if v is not None and k != "has_pep"
    }
    await _patch(session, org, **fields)

    with pytest.raises(HTTPException) as exc:
        await _submit(session, org)
    assert exc.value.detail["missing"] == ["has_pep"]

    # has_pep is a disclosure, not a declaration: True must NOT block submit.
    await _patch(session, org, has_pep=True)
    result = await _submit(session, org)
    assert result.submitted_at is not None
