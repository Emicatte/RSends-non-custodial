"""Shared pytest fixtures for the backend test suite.

Root cause this addresses: the app's async SQLAlchemy engine is created at
module-import time (app/db/session.py) and is module-global, while each async
test runs on its own per-function event loop. An asyncpg connection left in the
engine pool by one test is bound to that test's (now-closed) loop; the next test
either reuses it from a different loop ("attached to a different loop") or opens
a brand-new one, leaking connections until Postgres max_connections is exhausted
(TooManyConnectionsError).

Fix (paired with asyncio_default_fixture_loop_scope="function" in pyproject):
reset the engine's connection pool around every test, so each test opens and
uses its connections entirely within its own loop. No app code or per-module
fixtures are modified.
"""

import pytest_asyncio
from sqlalchemy import event

from app.models.org_models import Organization


@event.listens_for(Organization, "init")
def _default_onboarded_org(target, args, kwargs):
    """Mirror migration 0009's backfill for inline-constructed test orgs.

    Existing test files construct `Organization(...)` directly (pre-dating the
    onboarding gates); in production every org that predates migration 0009 was
    backfilled to onboarding_status='company_submitted'. This listener gives
    inline test orgs the same grandfathered state so the
    `require_org_company_submitted` gate doesn't 403 pre-existing suites.
    App code paths are unaffected: org_service always passes onboarding_status
    explicitly, so tests exercising real initial states still see them; new
    onboarding tests opt out by passing the kwarg.
    """
    kwargs.setdefault("onboarding_status", "company_submitted")
    # Same grandfathering for the approval gate (migration 0010 backfilled
    # every pre-existing org to 'approved'); approval tests opt out by
    # passing approval_status explicitly.
    kwargs.setdefault("approval_status", "approved")


@pytest_asyncio.fixture(autouse=True)
async def _isolate_engine_per_test():
    # Dispose before: drop any connection bound to a previous test's loop.
    from app.db.session import engine

    await engine.dispose()
    yield
    # Dispose after: leave a clean pool for the next test's loop.
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _flush_redis_between_tests():
    """Circuit-breaker state (cb:*) and rate-limit counters (rl:*) are stored in
    Redis when it's reachable, so they leak across tests and cause spurious
    CircuitOpenError / RATE_LIMIT_EXCEEDED. Flush the test Redis db before each
    test for isolation. No-op when Redis is down (code falls back to in-memory).
    """
    try:
        import redis.asyncio as _redis
        from app.config import get_settings

        client = _redis.from_url(get_settings().redis_url)
        try:
            await client.flushdb()
        finally:
            await client.aclose()
    except Exception:
        pass
    yield
