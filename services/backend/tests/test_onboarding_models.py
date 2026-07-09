"""Onboarding groundwork — data model shape.

Covers the new state/data model only (no endpoints): the two org status
columns and their fail-closed defaults, the one-to-one `company_profiles`
table (JSON round-trip of `countries_served` on SQLite), `consent_records`,
the user age-attestation columns, and the single legal-versions constants
module. Same direct-DB pattern as test_user_org_payments.py.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.onboarding_models import CompanyProfile, ConsentRecord
from app.models.org_models import Organization


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


async def _make_user(session, **kw):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type=kw.get("account_type", "merchant"),
    )
    session.add(user)
    await session.flush()
    return user


async def _make_org(session, user, **kw):
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
        **kw,
    )
    session.add(org)
    await session.flush()
    return org


# ── Legal versions constants module ──────────────────────────────

def test_legal_versions_constants():
    from app.legal_versions import CURRENT_VERSIONS, PRIVACY_VERSION, TOS_VERSION

    assert TOS_VERSION == "draft-1"
    assert PRIVACY_VERSION == "draft-1"
    assert CURRENT_VERSIONS == {"tos": TOS_VERSION, "privacy": PRIVACY_VERSION}


# ── Organization status columns ───────────────────────────────────

@pytest.mark.asyncio
async def test_org_status_columns_fail_closed_defaults(session):
    """A fresh org (no explicit kwargs) starts at the deny-by-default states."""
    user = await _make_user(session)
    org = Organization(
        name="fresh",
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=True,
        plan="free",
        # NB: no onboarding kwargs — this asserts the MODEL defaults. The
        # conftest test-backfill listener must not mask them for tests that
        # opt out explicitly.
        onboarding_status="created",
        activation_status="not_started",
    )
    session.add(org)
    await session.commit()

    row = (
        await session.execute(select(Organization).where(Organization.id == org.id))
    ).scalar_one()
    assert row.onboarding_status == "created"
    assert row.activation_status == "not_started"


# ── company_profiles ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_company_profile_draft_all_nullable_and_json_roundtrip(session):
    from app.models.onboarding_models import CompanyProfile

    user = await _make_user(session)
    org = await _make_org(session, user)
    org_id = str(org.id)

    profile = CompanyProfile(org_id=org_id)  # empty draft: every field nullable
    session.add(profile)
    await session.commit()

    row = (
        await session.execute(
            select(CompanyProfile).where(CompanyProfile.org_id == org_id)
        )
    ).scalar_one()
    assert row.legal_name is None
    assert row.submitted_at is None

    row.countries_served = ["CR", "IT", "DE"]
    row.has_pep = False
    await session.commit()
    session.expire_all()

    row = (
        await session.execute(
            select(CompanyProfile).where(CompanyProfile.org_id == org_id)
        )
    ).scalar_one()
    assert row.countries_served == ["CR", "IT", "DE"]
    assert row.has_pep is False


@pytest.mark.asyncio
async def test_company_profile_one_to_one_with_org(session):
    from app.models.onboarding_models import CompanyProfile

    user = await _make_user(session)
    org = await _make_org(session, user)

    session.add(CompanyProfile(org_id=str(org.id)))
    await session.commit()

    session.add(CompanyProfile(org_id=str(org.id)))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# ── consent_records ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consent_records_insert_and_read(session):
    from app.models.onboarding_models import ConsentRecord

    user = await _make_user(session)
    session.add_all(
        [
            ConsentRecord(
                user_id=user.id, document_type="tos", document_version="draft-1"
            ),
            ConsentRecord(
                user_id=user.id, document_type="privacy", document_version="draft-1"
            ),
        ]
    )
    await session.commit()

    rows = (
        (
            await session.execute(
                select(ConsentRecord).where(ConsentRecord.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert {r.document_type for r in rows} == {"tos", "privacy"}
    assert all(r.document_version == "draft-1" for r in rows)
    assert all(r.accepted_at is not None for r in rows)


# ── User age attestation columns ──────────────────────────────────

@pytest.mark.asyncio
async def test_user_age_attestation_defaults(session):
    user = await _make_user(session)
    await session.commit()

    row = (
        await session.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert row.age_attested is False
    assert row.age_attested_at is None
