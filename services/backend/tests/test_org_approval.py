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


# ── Aggregate onboarding state carries the approval fields ────────


@pytest.mark.asyncio
async def test_onboarding_state_carries_approval_fields(session):
    """The waiting screen polls GET /api/v1/user/onboarding: it must see the
    org's approval_status (and the operator's reason once declined)."""
    from app.services.onboarding_service import get_onboarding_state
    from app.services.org_service import create_personal_org

    user = await _make_user(session)
    org = await create_personal_org(session, user)
    await session.commit()

    state = await get_onboarding_state(session, user)
    assert state["approval_status"] == "pending_approval"
    assert state["decline_reason"] is None

    org.approval_status = "declined"
    org.decline_reason = "prohibited category"
    await session.commit()

    state = await get_onboarding_state(session, user)
    assert state["approval_status"] == "declined"
    assert state["decline_reason"] == "prohibited category"


def test_onboarding_endpoint_has_per_ip_rate_limit():
    """The pending screen polls this endpoint — it needs its own per-IP cap."""
    from app.middleware.rate_limit import ENDPOINT_LIMITS

    assert any(
        method == "GET" and path == "/api/v1/user/onboarding" and key == "ip"
        for method, path, _max, _win, key in ENDPOINT_LIMITS
    )
