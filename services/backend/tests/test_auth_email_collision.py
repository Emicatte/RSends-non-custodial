"""One account per email across login providers (block-and-guide).

Account-linking audit, case (b): Google login had no "email already exists"
guard — it looked up by google_sub only and silently created a SECOND account
for an email already registered via password or GitHub. GitHub's path already
guarded (409 email_already_registered). Product decision: block-and-guide —
409 + the frontend guides to the original method; NO auto-linking/merging.

Pinned here:
- Google login on an email owned by a password or GitHub account → 409,
  no second row (parity with GitHub's guard).
- Emails are normalized (lower/trim) on the Google path, so mixed case can't
  bypass the guard, and fresh Google signups store lowercase.
- The Google existing-user email sync cannot overwrite INTO a collision
  (login still succeeds; stored email kept).
- Regression pins for the already-safe cases: email/password signup on an
  OAuth-only email blocks; GitHub login on a password-owned email blocks.
- DB backstop: the lower(email) unique index rejects duplicates by
  construction (schema built via Base.metadata.create_all, like all tests).

Direct-handler style vs SQLite (see tests/test_merchant_env_isolation.py).
"""

import secrets as pysecrets
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.auth_schemas import GitHubLoginRequest, GoogleLoginRequest
from app.api.auth_routes import github_login, google_login
from app.services.auth_service import GoogleUserInfo
from app.services.github_oauth_service import GitHubProfile


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


@pytest.fixture
def auth_stubs(monkeypatch):
    """Stub everything around the upsert logic under test: token verification
    is parametrized per-test; network/redis/session plumbing is inert."""
    import app.api.auth_routes as ar
    import app.services.github_oauth_service as gh

    async def _no_event(*a, **k):
        return None

    async def _fake_session(*, user_id, ip, user_agent):
        return ("sid" + pysecrets.token_hex(8), "access", "refresh", "hash")

    monkeypatch.setattr(ar, "record_auth_event", _no_event)
    monkeypatch.setattr(ar, "create_session", _fake_session)
    monkeypatch.setattr(ar, "_set_auth_cookies", lambda *a, **k: None)
    monkeypatch.setattr(ar, "get_real_client_ip", lambda request: "127.0.0.1")
    monkeypatch.setattr(ar, "peek_unverified_email", lambda tok: None)  # skip quota

    def set_google(info: GoogleUserInfo):
        async def _verify(id_token, expected_nonce=None):
            return info
        monkeypatch.setattr(ar, "verify_google_id_token", _verify)

    def set_github(profile: GitHubProfile):
        async def _verify(access_token):
            return profile
        monkeypatch.setattr(gh, "verify_github_access_token", _verify)

    return SimpleNamespace(google=set_google, github=set_github)


def _req():
    return SimpleNamespace(
        state=SimpleNamespace(),
        headers={"User-Agent": "pytest"},
    )


def _google_payload():
    return GoogleLoginRequest(id_token="x" * 32)


def _github_payload():
    return GitHubLoginRequest(access_token="x" * 32)


def _google_info(email: str, sub: str = "gsub-1") -> GoogleUserInfo:
    return GoogleUserInfo(sub=sub, email=email, email_verified=True)


def _github_profile(email: str, sub: str = "ghsub-1") -> GitHubProfile:
    return GitHubProfile(
        sub=sub, email=email, email_verified=True, username="octo",
    )


def _password_user(email: str) -> User:
    return User(
        id=str(uuid4()),
        email=email,
        password_hash="$2b$12$" + "x" * 53,
        email_verified=True,
        account_type="individual",
    )


def _github_user(email: str, sub: str = "ghsub-existing") -> User:
    return User(
        id=str(uuid4()),
        email=email,
        github_sub=sub,
        github_username="octo",
        email_verified=True,
        account_type="individual",
    )


async def _user_count(session) -> int:
    return (await session.execute(select(func.count(User.id)))).scalar() or 0


# ── Google collision guard (the bug: case b) ─────────────────

@pytest.mark.asyncio
async def test_google_login_blocks_on_password_owned_email(session, auth_stubs):
    session.add(_password_user("mario@example.com"))
    await session.commit()

    auth_stubs.google(_google_info("mario@example.com"))
    with pytest.raises(HTTPException) as exc:
        await google_login(_google_payload(), _req(), Response(), db=session)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "email_already_registered"
    assert await _user_count(session) == 1  # no second account


@pytest.mark.asyncio
async def test_google_login_blocks_on_github_owned_email(session, auth_stubs):
    session.add(_github_user("mario@example.com"))
    await session.commit()

    auth_stubs.google(_google_info("mario@example.com"))
    with pytest.raises(HTTPException) as exc:
        await google_login(_google_payload(), _req(), Response(), db=session)

    assert exc.value.status_code == 409
    assert await _user_count(session) == 1


@pytest.mark.asyncio
async def test_mixed_case_google_email_cannot_bypass_guard(session, auth_stubs):
    session.add(_password_user("mario@example.com"))
    await session.commit()

    auth_stubs.google(_google_info("MaRiO@Example.COM"))
    with pytest.raises(HTTPException) as exc:
        await google_login(_google_payload(), _req(), Response(), db=session)

    assert exc.value.status_code == 409
    assert await _user_count(session) == 1


# ── Normalization on fresh Google signup ────────────────────

@pytest.mark.asyncio
async def test_fresh_google_signup_stores_lowercase_email(session, auth_stubs):
    auth_stubs.google(_google_info("  NeW.UsEr@Example.COM "))
    await google_login(_google_payload(), _req(), Response(), db=session)

    row = (await session.execute(
        select(User).where(User.google_sub == "gsub-1")
    )).scalar_one()
    assert row.email == "new.user@example.com"


# ── Existing-google-user email sync cannot collide ──────────

@pytest.mark.asyncio
async def test_google_email_change_does_not_overwrite_into_collision(
    session, auth_stubs,
):
    google_a = User(
        id=str(uuid4()), email="a@example.com", google_sub="gsub-a",
        email_verified=True, account_type="individual",
    )
    session.add_all([google_a, _password_user("b@example.com")])
    await session.commit()

    # Same google_sub, but the token now carries the OTHER user's email.
    auth_stubs.google(_google_info("B@Example.com", sub="gsub-a"))
    resp = await google_login(_google_payload(), _req(), Response(), db=session)

    assert resp.access_token  # login still succeeds
    row = (await session.execute(
        select(User).where(User.google_sub == "gsub-a")
    )).scalar_one()
    assert row.email == "a@example.com"  # stored email kept — no takeover
    assert await _user_count(session) == 2


# ── Regression pins: the already-safe cases (a) and (c) ─────

@pytest.mark.asyncio
async def test_password_signup_blocks_on_oauth_owned_email(session, monkeypatch):
    from app.services import email_auth_service as eas

    async def _no_rl(*a, **k):
        return None

    monkeypatch.setattr(eas, "_rate_limit_check", _no_rl)

    google_user = User(
        id=str(uuid4()), email="mario@example.com", google_sub="gsub-x",
        email_verified=True, account_type="individual",
    )
    session.add(google_user)
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


@pytest.mark.asyncio
async def test_github_login_blocks_on_password_owned_email(session, auth_stubs):
    session.add(_password_user("mario@example.com"))
    await session.commit()

    auth_stubs.github(_github_profile("mario@example.com"))
    with pytest.raises(HTTPException) as exc:
        await github_login(_github_payload(), _req(), Response(), db=session)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "email_already_registered"
    assert await _user_count(session) == 1


# ── DB backstop: lower(email) unique index ───────────────────

@pytest.mark.asyncio
async def test_db_rejects_duplicate_email_case_insensitive(session):
    session.add(_password_user("dup@example.com"))
    await session.commit()

    session.add(User(
        id=str(uuid4()), email="DUP@example.com", google_sub="gsub-dup",
        email_verified=True, account_type="individual",
    ))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
