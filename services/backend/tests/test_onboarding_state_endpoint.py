"""GET /api/v1/user/onboarding + POST /api/v1/user/consents + org-creation hooks.

The state endpoint is what the frontend server guard consumes: consent
currency, age attestation, email verification, and the active org's two
status fields. The consents endpoint records both documents at the current
versions (both checkboxes must be true — 422 otherwise).

Org-creation hooks for the email path (the OAuth path already creates the
personal org at first login):
- verify_email creates the personal org (prod posture — dev auto-verify
  bypasses verify_email, so that test forces prod posture and captures the
  raw token from the outgoing mail context);
- the email login route carries an idempotent recovery hook for accounts
  verified outside verify_email (dev auto-verify, legacy users), tested
  app-level via httpx AsyncClient (needs local Redis, like test_security).
"""

import secrets
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import async_session, engine
from app.legal_versions import CURRENT_VERSIONS
from app.models.db_models import Base
from app.models.auth_models import User
from app.models import email_auth_models as _email_auth_models  # noqa: F401 — registers verification-token tables for create_all
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


@pytest.fixture(autouse=True)
def _stub_auth_audit(monkeypatch):
    """Fire-and-forget audit uses its own session; on the shared StaticPool
    SQLite connection its failing commit/rollback would wipe the caller's
    uncommitted rows (test-env artifact, impossible on Postgres)."""

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.org_service.record_auth_event", _noop)
    monkeypatch.setattr(
        "app.services.email_auth_service.record_auth_event", _noop
    )


async def _make_user(session, *, email_verified=True, with_org=True):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
        email_verified=email_verified,
    )
    session.add(user)
    await session.flush()
    if with_org:
        org = Organization(
            name="Org " + secrets.token_hex(3),
            slug=secrets.token_hex(8),
            owner_user_id=user.id,
            is_personal=True,
            plan="free",
            onboarding_status="email_verified",
        )
        session.add(org)
        await session.flush()
        session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        user.active_org_id = org.id
    await session.commit()
    return user


# ── GET /onboarding ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_shape_no_org(session):
    from app.api.user_onboarding_routes import get_onboarding_state_route

    user = await _make_user(session, with_org=False)
    state = await get_onboarding_state_route(user_id=str(user.id), db=session)

    assert state.consents_current is False
    assert state.age_attested is False
    assert state.email_verified is True
    assert state.active_org_id is None
    assert state.onboarding_status is None
    assert state.company_profile is None


@pytest.mark.asyncio
async def test_state_reflects_org_and_consents(session):
    from app.api.user_onboarding_routes import (
        get_onboarding_state_route,
        post_consents,
    )
    from app.models.onboarding_schemas import ConsentSubmitRequest

    user = await _make_user(session)
    state = await post_consents(
        payload=ConsentSubmitRequest(accept_documents=True, age_attested=True),
        user_id=str(user.id),
        db=session,
    )
    assert state.consents_current is True
    assert state.age_attested is True
    assert state.onboarding_status == "email_verified"
    assert state.activation_status == "not_started"
    assert state.company_profile.exists is False
    assert state.company_profile.submitted_at is None


def test_consent_request_rejects_unchecked_boxes():
    from pydantic import ValidationError

    from app.models.onboarding_schemas import ConsentSubmitRequest

    with pytest.raises(ValidationError):
        ConsentSubmitRequest(accept_documents=False, age_attested=True)
    with pytest.raises(ValidationError):
        ConsentSubmitRequest(accept_documents=True, age_attested=False)


@pytest.mark.asyncio
async def test_unknown_user_401(session):
    from app.api.user_onboarding_routes import get_onboarding_state_route

    with pytest.raises(HTTPException) as exc:
        await get_onboarding_state_route(user_id=str(uuid4()), db=session)
    assert exc.value.status_code == 401


# ── Email-path org creation: at signup; verify_email only advances ─

@pytest.mark.asyncio
async def test_signup_creates_org_and_verify_email_advances_it(session, monkeypatch):
    from app.services import email_auth_service

    monkeypatch.setattr(
        email_auth_service, "is_prod_posture", lambda settings: True
    )

    captured = {}

    async def _capture_email(**kwargs):
        captured.update(kwargs.get("context") or {})
        return None

    monkeypatch.setattr(email_auth_service, "send_email", _capture_email)

    email = f"{secrets.token_hex(6)}@example.com"
    user, _ = await email_auth_service.signup(
        session,
        email=email,
        password="longenough123",
        first_name="Ada",
        last_name="Lovelace",
        date_of_birth=date(1990, 5, 1),
        country_of_residence="IT",
        account_type="merchant",
    )
    await session.commit()
    assert user.email_verified is False
    # Org is born AT SIGNUP now (email wall removed), pending approval,
    # onboarding at 'created' (owner unverified in prod posture).
    assert user.active_org_id is not None
    signup_org = (
        await session.execute(
            select(Organization).where(Organization.owner_user_id == user.id)
        )
    ).scalar_one()
    assert signup_org.onboarding_status == "created"
    assert signup_org.approval_status == "pending_approval"

    token = captured["verify_url"].split("token=")[1]

    # SQLite test artifact: DateTime(timezone=True) reads back tz-naive from
    # SQLite (Postgres returns aware). Normalize the token row's expiry so the
    # service's aware comparison works; hold the reference so the identity map
    # serves this instance to verify_email.
    from datetime import timezone as _tz

    from app.models.email_auth_models import EmailVerificationToken

    vt_row = (
        await session.execute(select(EmailVerificationToken))
    ).scalars().first()
    if vt_row.expires_at.tzinfo is None:
        vt_row.expires_at = vt_row.expires_at.replace(tzinfo=_tz.utc)

    verified = await email_auth_service.verify_email(session, token=token)
    await session.commit()

    assert verified.email_verified is True
    org = (
        await session.execute(
            select(Organization).where(Organization.owner_user_id == user.id)
        )
    ).scalar_one()
    assert org.is_personal is True
    assert org.onboarding_status == "email_verified"
    assert str(verified.active_org_id) == str(org.id)


# ── Email-path org creation: login recovery hook (app-level) ──────

@pytest.mark.asyncio
async def test_login_recovery_creates_missing_org(monkeypatch):
    """Orgs are created at signup now — the login hook is pure recovery for
    legacy accounts that predate org-at-signup. Simulate one by deleting the
    signup-created org; login must recreate it (verified or not)."""
    from app.main import app

    email = f"{secrets.token_hex(6)}@example.com"
    payload = {
        "email": email,
        "password": "longenough123",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "date_of_birth": "1990-05-01",
        "country_of_residence": "IT",
        "account_type": "merchant",
        "terms_accepted": True,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/signup", json=payload)
        assert r.status_code == 201, r.text
        assert r.json()["email_verified"] is True  # dev auto-verify

        # Simulate a legacy account: wipe the signup-created org + pointer.
        from sqlalchemy import delete as sa_delete

        async with async_session() as s:
            u = (
                await s.execute(select(User).where(User.email == email))
            ).scalar_one()
            u.active_org_id = None
            await s.execute(
                sa_delete(Organization).where(Organization.owner_user_id == u.id)
            )
            await s.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "longenough123"}
        )
        assert r.status_code == 200, r.text

    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.email == email))
        ).scalar_one()
        assert user.active_org_id is not None
        org = (
            await s.execute(
                select(Organization).where(Organization.id == user.active_org_id)
            )
        ).scalar_one()
        assert org.onboarding_status == "email_verified"

        # Consents were persisted at signup with the current versions.
        from app.models.onboarding_models import ConsentRecord

        docs = (
            (
                await s.execute(
                    select(ConsentRecord).where(ConsentRecord.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert {(c.document_type, c.document_version) for c in docs} == {
            ("tos", CURRENT_VERSIONS["tos"]),
            ("privacy", CURRENT_VERSIONS["privacy"]),
        }
