"""One account per email (block-and-guide).

Social login (Google/GitHub) was removed from the product, and its
handler-level collision guards went with it. What remains pinned here is the
provider-agnostic invariant that survives the removal:

- Email/password signup on an already-registered email → `email_already_exists`
  (the service-level guard; the frontend guides to login).
- DB backstop: the lower(email) unique index (`uq_users_email_lower`) rejects
  duplicate emails by construction, case-insensitively (schema built via
  Base.metadata.create_all, like all tests).

Direct-service style vs SQLite (see tests/test_merchant_env_isolation.py).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User


# ── Fixtures ─────────────────────────────────────────────────

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


def _password_user(email: str) -> User:
    return User(
        id=str(uuid4()),
        email=email,
        password_hash="$2b$12$" + "x" * 53,
        email_verified=True,
        account_type="individual",
    )


# ── Service guard: signup on an existing email blocks ────────

@pytest.mark.asyncio
async def test_password_signup_blocks_on_existing_email(session, monkeypatch):
    from app.services import email_auth_service as eas

    async def _no_rl(*a, **k):
        return None

    monkeypatch.setattr(eas, "_rate_limit_check", _no_rl)

    session.add(_password_user("mario@example.com"))
    await session.commit()

    from datetime import date

    with pytest.raises(eas.EmailAuthError) as exc:
        await eas.signup(
            db=session,
            email="mario@example.com",
            password="C0rrect-Horse-Battery-Staple!",
            first_name="Mario", last_name="Rossi",
            date_of_birth=date(1990, 1, 1),
            country_of_residence="IT",
            account_type="individual",
        )
    assert exc.value.code == "email_already_exists"


# ── DB backstop: lower(email) unique index ───────────────────

@pytest.mark.asyncio
async def test_db_rejects_duplicate_email_case_insensitive(session):
    session.add(_password_user("dup@example.com"))
    await session.commit()

    session.add(_password_user("DUP@example.com"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
