"""Onboarding status: forward-only transitions + initial state at org creation.

`advance_onboarding_status` is the ONLY mutator of `onboarding_status`
(created -> email_verified -> company_submitted): any backward or same-state
move raises. Org constructors (org_service) set the initial state from the
owner's email verification, and the conftest init-listener grandfathers
inline-constructed test orgs exactly like migration 0009's backfill.
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
    """record_auth_event is fire-and-forget (opens its own session, never
    raises). On in-memory SQLite the engine uses a StaticPool — ONE shared
    connection — so the audit session's failing commit/rollback would nuke the
    caller's uncommitted rows: a test-env artifact impossible on Postgres.
    Stub it where org_service imports it."""

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.org_service.record_auth_event", _noop)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_user(session, *, email_verified: bool):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
        email_verified=email_verified,
    )
    session.add(user)
    await session.flush()
    return user


# ── Forward-only transition matrix ────────────────────────────────

def _org_at(status: str) -> Organization:
    return Organization(
        name="t",
        slug=secrets.token_hex(8),
        owner_user_id=str(uuid4()),
        is_personal=True,
        plan="free",
        onboarding_status=status,
    )


@pytest.mark.parametrize(
    "start,target",
    [
        ("created", "email_verified"),
        ("email_verified", "company_submitted"),
        ("created", "company_submitted"),  # forward skip is still forward
    ],
)
def test_forward_transitions_allowed(start, target):
    from app.services.onboarding_service import advance_onboarding_status

    org = _org_at(start)
    advance_onboarding_status(org, target)
    assert org.onboarding_status == target


@pytest.mark.parametrize(
    "start,target",
    [
        ("email_verified", "created"),
        ("company_submitted", "email_verified"),
        ("company_submitted", "created"),
        ("created", "created"),
        ("email_verified", "email_verified"),
        ("company_submitted", "company_submitted"),
    ],
)
def test_backward_and_same_state_transitions_raise(start, target):
    from app.services.onboarding_service import OnboardingError, advance_onboarding_status

    org = _org_at(start)
    with pytest.raises(OnboardingError) as exc:
        advance_onboarding_status(org, target)
    assert exc.value.code == "invalid_transition"
    assert org.onboarding_status == start  # unchanged on failure


def test_unknown_states_raise():
    from app.services.onboarding_service import OnboardingError, advance_onboarding_status

    with pytest.raises(OnboardingError):
        advance_onboarding_status(_org_at("created"), "kyb_pending")
    with pytest.raises(OnboardingError):
        advance_onboarding_status(_org_at("bogus"), "email_verified")


# ── Initial status at org creation (org_service) ──────────────────

@pytest.mark.asyncio
async def test_personal_org_starts_email_verified_for_verified_owner(session):
    from app.services.org_service import create_personal_org

    user = await _make_user(session, email_verified=True)
    org = await create_personal_org(session, user)
    await session.commit()

    assert org.onboarding_status == "email_verified"
    assert org.activation_status == "not_started"


@pytest.mark.asyncio
async def test_personal_org_starts_created_for_unverified_owner(session):
    from app.services.org_service import create_personal_org

    user = await _make_user(session, email_verified=False)
    org = await create_personal_org(session, user)
    await session.commit()

    assert org.onboarding_status == "created"
    assert org.activation_status == "not_started"


@pytest.mark.asyncio
async def test_non_personal_org_gets_initial_status_too(session):
    from app.services.org_service import create_org

    user = await _make_user(session, email_verified=True)
    org = await create_org(session, user, "Acme")
    await session.commit()

    # A later org for an onboarded user still starts un-submitted: each org
    # needs its own company profile before operational access.
    assert org.onboarding_status == "email_verified"
    assert org.activation_status == "not_started"


# ── conftest grandfather listener (pins the D5 mechanism) ─────────

def test_inline_test_orgs_are_grandfathered_like_backfill():
    org = Organization(
        name="legacy",
        slug=secrets.token_hex(8),
        owner_user_id=str(uuid4()),
        is_personal=False,
        plan="free",
    )
    assert org.onboarding_status == "company_submitted"
