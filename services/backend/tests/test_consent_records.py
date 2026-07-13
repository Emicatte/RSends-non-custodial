"""Consent recording + versioning: signup persistence, re-consent on bump.

The consent trail is append-only rows in `consent_records`; currency is the
latest recorded version per document compared by string equality against
app.legal_versions.CURRENT_VERSIONS. Bumping a constant is the entire
re-consent trigger. Credentials signup records both documents and derives the
18+ attestation from the already >=18-validated date_of_birth.
"""

import secrets
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session, engine
from app.legal_versions import CURRENT_VERSIONS
from app.models.db_models import Base
from app.models.auth_models import User
from app.models import email_auth_models as _email_auth_models  # noqa: F401 — registers email_verification_tokens for create_all (signup test)
from app.models.onboarding_models import ConsentRecord


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _stub_auth_audit(monkeypatch):
    """record_auth_event is fire-and-forget (own session, never raises). On
    in-memory SQLite the engine's StaticPool shares ONE connection, so the
    audit session's failing commit/rollback would wipe the caller's uncommitted
    rows — a test-env artifact impossible on Postgres. Stub it where the
    services under test import it."""

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.org_service.record_auth_event", _noop)
    monkeypatch.setattr(
        "app.services.email_auth_service.record_auth_event", _noop
    )


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_user(session):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
    )
    session.add(user)
    await session.flush()
    return user


async def _consent_rows(session, user_id):
    return (
        (
            await session.execute(
                select(ConsentRecord).where(ConsentRecord.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


# ── record_consents ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_consents_inserts_both_docs_and_stamps_age(session):
    from app.services.onboarding_service import record_consents

    user = await _make_user(session)
    await record_consents(session, user, age_attested=True)
    await session.commit()

    rows = await _consent_rows(session, user.id)
    assert {(r.document_type, r.document_version) for r in rows} == {
        ("tos", CURRENT_VERSIONS["tos"]),
        ("privacy", CURRENT_VERSIONS["privacy"]),
    }
    assert user.age_attested is True
    assert user.age_attested_at is not None


@pytest.mark.asyncio
async def test_record_consents_without_age_does_not_stamp(session):
    from app.services.onboarding_service import record_consents

    user = await _make_user(session)
    await record_consents(session, user, age_attested=False)
    await session.commit()

    assert user.age_attested is False
    assert user.age_attested_at is None
    assert len(await _consent_rows(session, user.id)) == 2


# ── consents_current + re-consent on version bump ─────────────────

@pytest.mark.asyncio
async def test_consents_current_true_after_recording(session):
    from app.services.onboarding_service import consents_current, record_consents

    user = await _make_user(session)
    assert await consents_current(session, user.id) is False  # nothing recorded

    await record_consents(session, user, age_attested=True)
    await session.commit()
    assert await consents_current(session, user.id) is True


@pytest.mark.asyncio
async def test_version_bump_forces_reconsent(session, monkeypatch):
    from app.services.onboarding_service import consents_current, record_consents

    user = await _make_user(session)
    await record_consents(session, user, age_attested=True)
    await session.commit()
    assert await consents_current(session, user.id) is True

    # Bumping the constant is the whole re-consent trigger.
    monkeypatch.setitem(CURRENT_VERSIONS, "tos", "draft-2")
    assert await consents_current(session, user.id) is False

    # Re-accepting appends fresh rows (audit trail) and restores currency.
    await record_consents(session, user, age_attested=True)
    await session.commit()
    assert await consents_current(session, user.id) is True
    assert len(await _consent_rows(session, user.id)) == 4


@pytest.mark.asyncio
async def test_one_stale_document_is_enough_to_block(session, monkeypatch):
    from app.services.onboarding_service import consents_current, record_consents

    user = await _make_user(session)
    await record_consents(session, user, age_attested=True)
    await session.commit()

    monkeypatch.setitem(CURRENT_VERSIONS, "privacy", "draft-2")
    assert await consents_current(session, user.id) is False


# ── credentials signup persists consents + age ────────────────────

@pytest.mark.asyncio
async def test_signup_records_consents_and_age_attestation(session):
    from app.services.email_auth_service import signup

    email = f"{secrets.token_hex(6)}@example.com"
    user, _ = await signup(
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

    rows = await _consent_rows(session, user.id)
    assert {(r.document_type, r.document_version) for r in rows} == {
        ("tos", CURRENT_VERSIONS["tos"]),
        ("privacy", CURRENT_VERSIONS["privacy"]),
    }
    # DOB was >=18-validated upstream: the attestation derives from it.
    assert user.age_attested is True
    assert user.age_attested_at is not None
