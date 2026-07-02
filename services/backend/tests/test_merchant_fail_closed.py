"""Fail-closed merchant identity.

Audit invariant "Fail closed": auth/isolation fallbacks must deny, never fall
into a shared bucket. `_get_merchant_id` used to return the `"unknown"`
sentinel when there was no authenticated client — every such request silently
shared one merchant bucket instead of being denied.

Two behaviors pinned here:
1. An absent or malformed client on an authenticated route → 401 (fail-closed).
2. NO merchant route is public: the merchant GET denies unauthenticated calls
   too (the /pay hosted checkout reads the limited id-as-secret view in
   app/api/public_routes.py instead — see tests/test_public_intent_view.py).

Direct-handler tests, same style as tests/test_merchant_env_isolation.py.
"""

import secrets
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.api.merchant_routes import get_payment_intent, list_merchant_transactions

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"


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


def _unauth_req():
    """Request as the middleware leaves it on the public GET allowlist: no client."""
    return SimpleNamespace(state=SimpleNamespace())


def _malformed_req(client):
    """Authenticated-shaped request whose client dict is broken/empty."""
    return SimpleNamespace(state=SimpleNamespace(client=client))


def _live_intent() -> PaymentIntent:
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=OWNER,
        environment="live",
        amount=100.0,
        currency="USDC",
        chain="base",
        status=IntentStatus.pending,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


# ── fail closed: no shared "unknown" bucket ──────────────────

@pytest.mark.asyncio
async def test_missing_client_denied_401(session):
    """No authenticated client on an authenticated route → 401, not a silent
    empty result under the shared "unknown" merchant bucket."""
    with pytest.raises(HTTPException) as exc:
        await list_merchant_transactions(
            _unauth_req(), status=None, currency=None, page=1, per_page=20,
            db=session,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "INVALID_API_KEY"


@pytest.mark.asyncio
async def test_malformed_client_denied_401(session):
    """A client dict without client_id must deny, never bucket as "unknown"."""
    for broken in ({}, {"scope": "write"}, {"client_id": ""}):
        with pytest.raises(HTTPException) as exc:
            await list_merchant_transactions(
                _malformed_req(broken), status=None, currency=None,
                page=1, per_page=20, db=session,
            )
        assert exc.value.status_code == 401, f"client={broken!r}"


# ── merchant GET: fully fail-closed, no unauthenticated read ──

@pytest.mark.asyncio
async def test_unauth_merchant_get_denied_401(session):
    """The merchant GET is no longer on the public allowlist — an
    unauthenticated call fails closed (401) and leaks nothing. The public
    read is app/api/public_routes.py, id-as-secret."""
    intent = _live_intent()
    session.add(intent)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_payment_intent(intent.intent_id, _unauth_req(), db=session)

    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "INVALID_API_KEY"
    # No leak: nothing about the (existing) intent in the error payload.
    assert intent.merchant_id not in str(exc.value.detail)
    assert str(intent.amount) not in str(exc.value.detail)
