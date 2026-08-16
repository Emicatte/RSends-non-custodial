"""Router-availability gate at payment-intent creation.

Invariant under test: an intent may not be created on a chain that has no
configured settlement router (neither RSendsRouter v1 nor RouterV2). Before
this gate, such a request was accepted — the intent was persisted, the key's
monthly quota consumed, and `build_onchain_payment` returned None, so the
merchant received **HTTP 201 with `onchain: null`**: no payment instructions,
no indexer watcher for the chain, no settlement, no webhook, and not a single
log line. Silent failure on the money path.

The refusal must land BEFORE persistence and BEFORE quota consumption, and it
must be observable (warning log), on both the API-key and the session path.

Direct-handler tests (no live server), same pattern as
test_merchant_chain_gate.py: fake `request.state.client`, real SQLite.
"""

import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.merchant_routes import create_payment_intent
from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.security.api_keys import generate_api_key

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
RECIPIENT = "0x1111111111111111111111111111111111111111"


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # This module counts intents GLOBALLY to prove nothing was persisted;
        # start from a known-empty table so another module's leftovers can't
        # weaken the assertion.
        await conn.execute(PaymentIntent.__table__.delete())
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _req(environment: str, *, key_id=None, owner: str = OWNER):
    """Fake Request as APIKeyMiddleware would leave it for an authenticated key."""
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


def _payload(chain: str) -> CreatePaymentIntentRequest:
    # Explicit recipient: these tests exercise the router gate, not the
    # recipient gate, so the recipient resolves and create reaches the gate.
    return CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain=chain, recipient=RECIPIENT,
    )


async def _intent_count(session) -> int:
    return (
        await session.execute(select(func.count(PaymentIntent.intent_id)))
    ).scalar_one()


def _unconfigure_routers(monkeypatch):
    """Drop every router map — the production shape for an unserved chain."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "rsends_router_addresses_json", "")
    monkeypatch.setattr(s, "rsends_router_v2_addresses_json", "")


async def _make_key(session, environment: str) -> ApiKey:
    _plaintext, fields = generate_api_key(environment=environment)
    key = ApiKey(
        owner_address=OWNER,
        org_id="org-router-gate",
        **fields,
        label="router-gate",
        scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


# ── Refusal: supported chain, no router ──────────────────────

@pytest.mark.asyncio
async def test_live_key_on_unrouted_chain_refused_and_not_persisted(session):
    """`ethereum` is in the token registry but has no router → 422, nothing written."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("ethereum"), _req("live"), db=session)

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "ROUTER_UNAVAILABLE"
    assert "ethereum" in exc.value.detail["message"]
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_refusal_when_no_router_is_configured_at_all(session, monkeypatch):
    """Even the chain the suite normally routes fails closed once unconfigured."""
    _unconfigure_routers(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("base_sepolia"), _req("test"), db=session)

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "ROUTER_UNAVAILABLE"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_session_path_refused_on_unrouted_chain(session, monkeypatch):
    """The session (JWT) path goes through the same shared construction site."""
    from app.services.intent_service import create_intent

    _unconfigure_routers(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await create_intent(
            session, OWNER, "test", _payload("base_sepolia"),
            org_id="org-router-gate", key_id=None,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "ROUTER_UNAVAILABLE"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_quota_not_consumed_on_refusal(session):
    """The refusal precedes the monthly-limit check and the usage increment."""
    key = await _make_key(session, "live")
    before = key.total_intents_created or 0

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("ethereum"), _req("live", key_id=key.id), db=session
        )
    assert exc.value.detail["error"] == "ROUTER_UNAVAILABLE"

    await session.refresh(key)
    assert (key.total_intents_created or 0) == before
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_refusal_is_logged_at_warning(session, caplog):
    """Silent degradation is the bug being fixed — the refusal must be observable."""
    with caplog.at_level(logging.WARNING, logger="app.services.intent_service"):
        with pytest.raises(HTTPException):
            await create_payment_intent(
                _payload("ethereum"), _req("live"), db=session
            )

    records = [r for r in caplog.records if "ROUTER_UNAVAILABLE" in r.getMessage()]
    assert records, "no warning emitted for the router-availability refusal"
    assert any("ethereum" in r.getMessage() for r in records)


# ── Regression guard: the routed path is untouched ───────────

@pytest.mark.asyncio
async def test_base_sepolia_still_creates_when_router_configured(session, monkeypatch):
    """The existing test path must behave exactly as before."""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)

    resp = await create_payment_intent(
        _payload("base_sepolia"), _req("test"), db=session
    )

    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()
    assert row.chain == "base_sepolia"
    assert row.environment == "test"
