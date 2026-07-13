"""Merchant approval state on organizations (migration 0010).

Every org is born `pending_approval` (stamped at creation by org_service, with
`approval_requested_at`); operational access requires `approved` (see the gate
tests in test_approval_gate.py). Inline-constructed test orgs are grandfathered
`approved` by the conftest init-listener, mirroring migration 0010's backfill of
every pre-existing production org.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _stub_auth_audit(monkeypatch):
    """See test_onboarding_status_transitions._stub_auth_audit — StaticPool artifact."""

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.org_service.record_auth_event", _noop)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_user(session):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
        email_verified=False,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_personal_org_created_pending_approval(session):
    from app.services.org_service import create_personal_org

    user = await _make_user(session)
    org = await create_personal_org(session, user)
    await session.commit()

    assert org.approval_status == "pending_approval"
    assert org.approval_requested_at is not None
    assert org.approval_decided_at is None
    assert org.approval_decided_by is None
    assert org.decline_reason is None


@pytest.mark.asyncio
async def test_non_personal_org_also_pending(session):
    from app.services.org_service import create_org

    user = await _make_user(session)
    org = await create_org(session, user, "Acme")
    await session.commit()

    assert org.approval_status == "pending_approval"


def test_inline_test_orgs_grandfathered_approved():
    """conftest listener mirrors 0010's backfill: pre-existing suites stay approved."""
    org = Organization(
        name="legacy",
        slug=secrets.token_hex(8),
        owner_user_id=str(uuid4()),
        is_personal=False,
        plan="free",
    )
    assert org.approval_status == "approved"


def test_explicit_approval_status_wins_over_grandfather():
    org = Organization(
        name="fresh",
        slug=secrets.token_hex(8),
        owner_user_id=str(uuid4()),
        is_personal=True,
        plan="free",
        approval_status="pending_approval",
    )
    assert org.approval_status == "pending_approval"
