"""Signup after the email-verification wall removal.

- The org is created AT SIGNUP (pending approval) — verification no longer
  gates anything, so it can't be the org-creation trigger anymore.
- The verification email still goes out (non-blocking nicety), and its send
  outcome is SURFACED, not swallowed: the service returns it and the route
  exposes `verification_email` ∈ {sent, skipped_dev_mode, failed} — a
  production that can't send email must be distinguishable from a bare 201.
- The EmailVerifiedGateMiddleware is gone.
"""

from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import async_session, engine
from app.main import app
from app.models.db_models import Base
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


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from app.services import email_auth_service as eas

    async def _no_rl(*a, **k):
        return None

    monkeypatch.setattr(eas, "_rate_limit_check", _no_rl)

    # record_auth_event opens its OWN session: on in-memory SQLite (StaticPool,
    # one shared connection) that nukes the caller's uncommitted rows — a
    # test-env artifact impossible on Postgres (see
    # test_onboarding_status_transitions._stub_auth_audit).
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.email_auth_service.record_auth_event", _noop)
    monkeypatch.setattr("app.services.org_service.record_auth_event", _noop)


def _signup_kwargs(email: str) -> dict:
    return dict(
        email=email,
        password="C0rrect-Horse-Battery-Staple!",
        first_name="Ada",
        last_name="Lovelace",
        date_of_birth=date(1990, 1, 1),
        country_of_residence="IT",
        account_type="merchant",
    )


def _signup_body(email: str) -> dict:
    return {
        "email": email,
        "password": "C0rrect-Horse-Battery-Staple!",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "date_of_birth": "1990-01-01",
        "country_of_residence": "IT",
        "account_type": "merchant",
        "terms_accepted": True,
    }


# ── Service level ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_creates_pending_personal_org(session):
    from app.services import email_auth_service as eas

    user, _ = await eas.signup(db=session, **_signup_kwargs("ada@example.com"))
    await session.commit()

    org = (
        await session.execute(
            select(Organization).where(
                Organization.owner_user_id == user.id,
                Organization.is_personal.is_(True),
            )
        )
    ).scalar_one()
    assert org.approval_status == "pending_approval"
    assert user.active_org_id == org.id


@pytest.mark.asyncio
async def test_signup_reports_email_skipped_in_dev_mode(session):
    # Test env runs email_dev_mode=True → send_email short-circuits.
    from app.services import email_auth_service as eas

    _, email_state = await eas.signup(db=session, **_signup_kwargs("b@example.com"))
    assert email_state == "skipped_dev_mode"


@pytest.mark.asyncio
async def test_signup_reports_email_failed(session, monkeypatch):
    from app.services import email_auth_service as eas

    async def _fail(**kwargs):
        return None

    monkeypatch.setattr(eas, "send_email", _fail)
    _, email_state = await eas.signup(db=session, **_signup_kwargs("c@example.com"))
    assert email_state == "failed"


@pytest.mark.asyncio
async def test_signup_reports_email_sent(session, monkeypatch):
    from app.services import email_auth_service as eas

    async def _sent(**kwargs):
        return "re_12345"

    monkeypatch.setattr(eas, "send_email", _sent)
    _, email_state = await eas.signup(db=session, **_signup_kwargs("d@example.com"))
    assert email_state == "sent"


# ── Route level ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_route_surfaces_verification_email_state(client):
    r = await client.post("/api/v1/auth/signup", json=_signup_body("e@example.com"))
    assert r.status_code == 201, r.text
    assert r.json()["verification_email"] == "skipped_dev_mode"


# ── Wall removal ──────────────────────────────────────────────


def test_email_verified_gate_middleware_is_gone():
    assert all(
        "EmailVerifiedGate" not in str(m) for m in app.user_middleware
    ), "EmailVerifiedGateMiddleware must not be registered anymore"
