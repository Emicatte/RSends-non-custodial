"""Org settlement_wallet PATCH (Phase B) — replace-only, address-validated.

Schema-level tests pin the reject-never-coerce validator (these surface as 422 at
the API); direct-handler tests pin persistence, RBAC, and that the org list echoes
the field. Mirrors the direct-handler style of test_merchant_env_isolation.py.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.org_schemas import OrganizationPatchRequest
from app.api.organizations_routes import update_org, list_my_orgs

VALID_MIXED = "0xAbC0000000000000000000000000000000000001"
VALID_LOWER = "0xabc0000000000000000000000000000000000001"
ZERO = "0x" + "0" * 40


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


async def _user(session, active_org=None) -> User:
    u = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
        active_org_id=active_org,
    )
    session.add(u)
    await session.flush()
    return u


async def _org(session, owner: User, *, settlement=None) -> Organization:
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=owner.id,
        is_personal=False,
        plan="free",
        settlement_wallet=settlement,
    )
    session.add(org)
    await session.flush()
    return org


async def _member(session, user: User, org: Organization, role: str):
    session.add(Membership(user_id=user.id, org_id=org.id, role=role))
    await session.commit()


# ── Schema validator (reject-never-coerce; surfaces as 422 at the API) ──

def test_patch_valid_persists_lowercase():
    p = OrganizationPatchRequest(settlement_wallet=VALID_MIXED)
    assert p.settlement_wallet == VALID_LOWER  # normalized lowercase


def test_patch_invalid_format_422():
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet="not-an-address")


def test_patch_zero_address_422():
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet=ZERO)


def test_patch_empty_string_422():
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet="")


def test_patch_omitted_leaves_field_none():
    # Omitted → None (handler treats None as "unchanged").
    p = OrganizationPatchRequest(name="New name")
    assert p.settlement_wallet is None


# ── Handler: persistence + RBAC + list echo ──

@pytest.mark.asyncio
async def test_admin_patch_persists_lowercase(session):
    admin = await _user(session)
    org = await _org(session, admin)
    await _member(session, admin, org, "admin")

    resp = await update_org(
        org.id,
        OrganizationPatchRequest(settlement_wallet=VALID_MIXED),
        user_id=admin.id,
        db=session,
    )
    assert resp.settlement_wallet == VALID_LOWER

    fresh = await session.get(Organization, org.id)
    assert fresh.settlement_wallet == VALID_LOWER


@pytest.mark.asyncio
async def test_patch_omitted_leaves_unchanged(session):
    admin = await _user(session)
    org = await _org(session, admin, settlement=VALID_LOWER)
    await _member(session, admin, org, "admin")

    await update_org(
        org.id,
        OrganizationPatchRequest(name="Renamed"),  # no settlement_wallet
        user_id=admin.id,
        db=session,
    )
    fresh = await session.get(Organization, org.id)
    assert fresh.settlement_wallet == VALID_LOWER  # untouched


@pytest.mark.asyncio
async def test_patch_requires_admin_403(session):
    viewer = await _user(session)
    org = await _org(session, viewer)
    await _member(session, viewer, org, "viewer")

    with pytest.raises(HTTPException) as exc:
        await update_org(
            org.id,
            OrganizationPatchRequest(settlement_wallet=VALID_LOWER),
            user_id=viewer.id,
            db=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_patch_not_a_member_403(session):
    stranger = await _user(session)
    owner = await _user(session)
    org = await _org(session, owner)
    await _member(session, owner, org, "admin")

    with pytest.raises(HTTPException) as exc:
        await update_org(
            org.id,
            OrganizationPatchRequest(settlement_wallet=VALID_LOWER),
            user_id=stranger.id,
            db=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_echoes_settlement_wallet(session):
    admin = await _user(session)
    org = await _org(session, admin, settlement=VALID_LOWER)
    await _member(session, admin, org, "admin")

    resp = await list_my_orgs(user_id=admin.id, db=session)
    match = next(o for o in resp.organizations if str(o.id) == str(org.id))
    assert match.settlement_wallet == VALID_LOWER
