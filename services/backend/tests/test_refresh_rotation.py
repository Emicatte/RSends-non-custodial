"""Refresh-rotation strictness — one-time-use, no reuse grace.

Reuse detection is the ONLY defence against a stolen refresh cookie, so it is
deliberately strict: ANY presentation that doesn't match the stored hash —
including the token rotated away one second ago — revokes the whole session.
A 60s reuse-grace window was considered and rejected (2026-07-14): it would
silently hand a 15-min access token to whoever presents a stolen just-rotated
token and defer theft detection by one access-token lifetime. The benign
multi-tab rotation race that motivated it is prevented client-side instead
(cross-tab Web Lock + BroadcastChannel, apps/web/lib/auth-client.ts, pinned
by authClientCrossTab.test.ts).

Direct-service tests with a fake Redis + a minimal-app TestClient for the
route, same styles as tests/test_merchant_env_isolation.py.
"""

import hashlib
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.services import auth_service
from app.services.auth_service import (
    AuthError,
    SESSION_REDIS_PREFIX,
    create_session,
    rotate_refresh_token,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class FakeRedis:
    """Minimal async Redis stand-in: get/set/delete on a dict."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()

    async def _get_redis():
        return r

    monkeypatch.setattr(auth_service, "get_redis", _get_redis)
    return r


class Clock:
    """Controllable time.time() so reuse timing is explicit in the tests."""

    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(auth_service.time, "time", c)
    return c


async def _session(fake_redis):
    sid, access, refresh, refresh_hash = await create_session(
        user_id=str(uuid4()), ip="1.2.3.4", user_agent="pytest",
    )
    return sid, refresh


def _stored(fake_redis, sid):
    return json.loads(fake_redis.store[f"{SESSION_REDIS_PREFIX}{sid}"])


# ── Service: strict one-time-use rotation ────────────────────

@pytest.mark.asyncio
async def test_rotation_happy_path(fake_redis, clock):
    sid, t1 = await _session(fake_redis)
    access, t2, user_id = await rotate_refresh_token(
        session_id=sid, old_refresh_token=t1, ip="1.2.3.4"
    )
    assert access and t2 and user_id
    data = _stored(fake_redis, sid)
    assert data["refresh_hash"] == hashlib.sha256(t2.encode()).hexdigest()

    # The new token keeps rotating.
    _, t3, _ = await rotate_refresh_token(
        session_id=sid, old_refresh_token=t2, ip="1.2.3.4"
    )
    assert t3


@pytest.mark.asyncio
async def test_reuse_revokes_immediately_no_grace(fake_redis, clock):
    """The token rotated away ONE SECOND ago is already theft — the whole
    session is revoked. Pins the no-grace decision."""
    sid, t1 = await _session(fake_redis)
    await rotate_refresh_token(session_id=sid, old_refresh_token=t1, ip="1.2.3.4")

    clock.now += 1
    with pytest.raises(AuthError) as exc:
        await rotate_refresh_token(
            session_id=sid, old_refresh_token=t1, ip="1.2.3.4"
        )
    assert exc.value.code == "refresh_reuse_detected"
    assert f"{SESSION_REDIS_PREFIX}{sid}" not in fake_redis.store


@pytest.mark.asyncio
async def test_unknown_token_revokes_session(fake_redis, clock):
    sid, t1 = await _session(fake_redis)
    with pytest.raises(AuthError) as exc:
        await rotate_refresh_token(
            session_id=sid, old_refresh_token="not-a-real-token", ip="1.2.3.4"
        )
    assert exc.value.code == "refresh_reuse_detected"
    assert f"{SESSION_REDIS_PREFIX}{sid}" not in fake_redis.store


@pytest.mark.asyncio
async def test_revoked_session_cannot_rotate(fake_redis, clock):
    sid, t1 = await _session(fake_redis)
    await fake_redis.delete(f"{SESSION_REDIS_PREFIX}{sid}")
    with pytest.raises(AuthError) as exc:
        await rotate_refresh_token(
            session_id=sid, old_refresh_token=t1, ip="1.2.3.4"
        )
    assert exc.value.code == "session_revoked"


# ── Route: reuse → 401 refresh_reuse_detected, cookies cleared ──

@pytest.mark.asyncio
async def test_refresh_route_reuse_401s_and_clears_cookies(fake_redis, clock):
    from app.api import auth_routes

    user_id = str(uuid4())
    async with async_session() as s:
        s.add(User(
            id=user_id,
            email=f"{user_id}@example.com",
            password_hash="$2b$12$" + "x" * 53,
            email_verified=True,
            account_type="individual",
            status="active",
        ))
        await s.commit()

    sid, _, t1, _ = await create_session(
        user_id=user_id, ip="1.2.3.4", user_agent="pytest",
    )

    app = FastAPI()
    app.include_router(auth_routes.router)
    client = TestClient(app)

    def replay_stale():
        # Pin the Cookie header per request (jar cleared) so every call
        # replays the ORIGINAL pair, not the rotated cookie from res1.
        client.cookies.clear()
        return client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"rsends_sid={sid}; rsends_refresh={t1}"},
        )

    # First presentation rotates and sets a new refresh cookie.
    res1 = replay_stale()
    assert res1.status_code == 200
    assert "rsends_refresh" in res1.headers.get("set-cookie", "")

    # Replaying the rotated-away cookie seconds later is theft: 401, session
    # revoked, cookies cleared.
    clock.now += 1
    res2 = replay_stale()
    assert res2.status_code == 401
    assert res2.json()["detail"]["code"] == "refresh_reuse_detected"
    assert f"{SESSION_REDIS_PREFIX}{sid}" not in fake_redis.store
