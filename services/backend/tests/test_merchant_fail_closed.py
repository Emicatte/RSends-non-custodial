"""Fail-closed merchant identity.

Audit invariant "Fail closed": auth/isolation fallbacks must deny, never fall
into a shared bucket. `_get_merchant_id` used to return the `"unknown"`
sentinel when there was no authenticated client — every such request silently
shared one merchant bucket instead of being denied.

Two behaviors pinned here:
1. An absent or malformed client on an authenticated route → 401 (fail-closed).
2. The public checkout GET (`/api/v1/merchant/payment-intent/{id}` is in
   GET_PUBLIC_PREFIXES and legitimately reaches the handler unauthenticated)
   keeps its exact pre-existing behavior: 404, revealing nothing. This test
   guards the fail-closed change from breaking the public /pay path.

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


# ── public checkout GET: behavior preserved, no leak ─────────

@pytest.mark.asyncio
async def test_public_get_intent_stays_404_without_leak(session):
    """The allowlisted unauthenticated GET must keep returning a bare 404
    (today's behavior) — not 401, and never the intent data."""
    intent = _live_intent()
    session.add(intent)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_payment_intent(intent.intent_id, _unauth_req(), db=session)

    assert exc.value.status_code == 404
    assert exc.value.detail["error"] == "INTENT_NOT_FOUND"
    # No leak: nothing about the (existing) intent in the error payload.
    assert intent.merchant_id not in str(exc.value.detail)
    assert str(intent.amount) not in str(exc.value.detail)
