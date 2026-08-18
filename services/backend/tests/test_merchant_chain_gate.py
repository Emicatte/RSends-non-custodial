"""Categorical chain gate at payment-intent creation.

Invariant under test: a merchant cannot create an intent on a chain the system
categorically cannot settle — i.e. any chain that does not canonicalize into
app/token_registry.json (no tokens, no router, no indexer). TRON is the
canonical case: FeeRouterV4Tron is a never-deployed dead stub and no TRON
network has any settlement path.

Before the gate, the rejection came from the token-policy check with a
misleading error ("Token USDC is not enabled on chain tron" — blaming the
token, implying the chain itself is fine), the verdict depended on the key's
environment (a test key got TESTNET_ONLY instead), and that TESTNET_ONLY
error advertised TRON's own testnets (nile/shasta) in `allowed_chains`.

Direct-handler tests (no live server), same pattern as
test_merchant_env_isolation.py: fake `request.state.client`, real SQLite.
"""

import secrets

import pytest
import pytest_asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.org_models import Organization
from app.security.api_keys import generate_api_key
from app.api.merchant_routes import create_payment_intent

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Start from a known-empty table: earlier modules that clean at SETUP
        # (not teardown — e.g. the indexer suites) leave their intents behind,
        # and this module's not-persisted assertions count GLOBALLY. Deleting
        # here keeps those assertions at full strength without inheriting
        # another module's rows.
        await conn.execute(PaymentIntent.__table__.delete())
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _req(environment: str, *, owner: str = OWNER, key_id=None):
    """Fake Request as APIKeyMiddleware would leave it for an authenticated key."""
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _activated_key(session) -> ApiKey:
    """A live key whose org has completed business verification.

    Mainnet creation goes through check_org_chain_access at the shared
    construction site, so reaching the CHAIN gate on a mainnet chain requires an
    activated org first. This is a precondition of the test, not what it asserts.
    """
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
        activation_status="active",
    )
    session.add(org)
    await session.flush()
    _plaintext, fields = generate_api_key(environment="live")
    key = ApiKey(
        owner_address=OWNER,
        org_id=str(org.id),
        **fields,
        label="chain-gate",
        scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


def _payload(chain: str) -> CreatePaymentIntentRequest:
    # Explicit recipient: these tests exercise the chain gate, not the recipient
    # gate (Phase B). The recipient satisfies the gate so create reaches the
    # chain/env logic under test. Rejection cases fail the chain gate first.
    return CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain=chain,
        recipient="0x1111111111111111111111111111111111111111",
    )


async def _intent_count(session) -> int:
    return (await session.execute(select(func.count(PaymentIntent.intent_id)))).scalar_one()


def _stub_side_effects(monkeypatch):
    """Neutralize the create path's side effects for happy-path tests."""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)


# ── Categorical rejection: TRON has no settlement path ───────

@pytest.mark.asyncio
async def test_tron_rejected_on_live_key_and_not_persisted(session):
    """chain='tron' → 400 UNSUPPORTED_CHAIN naming the chain; nothing persisted."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("tron"), _req("live"), db=session)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_CHAIN"
    assert "tron" in exc.value.detail["message"]
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_tron_rejected_on_test_key_same_categorical_error(session):
    """The verdict is categorical: a test key gets the SAME error, not TESTNET_ONLY."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("tron"), _req("test"), db=session)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_CHAIN"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_tron_testnets_rejected_too(session):
    """nile/shasta are TRON's testnets — same categorical grounds."""
    for chain in ("nile", "shasta"):
        with pytest.raises(HTTPException) as exc:
            await create_payment_intent(_payload(chain), _req("test"), db=session)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "UNSUPPORTED_CHAIN"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_generic_gate_covers_other_unsupported_chains(session):
    """The gate is registry-derived, not a tron denylist: solana is rejected the same way."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("solana"), _req("live"), db=session)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_CHAIN"
    assert "solana" in exc.value.detail["message"]


# ── The env-binding error must stop advertising TRON testnets ─

@pytest.mark.asyncio
async def test_testnet_only_error_no_longer_advertises_tron_testnets(session):
    """Test key + registry-canonical mainnet chain → TESTNET_ONLY, whose
    allowed_chains must list real testnets only (no nile/shasta)."""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload("base"), _req("test"), db=session)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "TESTNET_ONLY"
    allowed = exc.value.detail["allowed_chains"]
    assert "base_sepolia" in allowed
    assert "nile" not in allowed
    assert "shasta" not in allowed


# ── Happy paths: no over-removal ─────────────────────────────

@pytest.mark.asyncio
async def test_base_sepolia_still_creates_on_test_key(session, monkeypatch):
    """Settleable-now chain: intent created, key environment stamped."""
    _stub_side_effects(monkeypatch)

    resp = await create_payment_intent(_payload("base_sepolia"), _req("test"), db=session)

    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert row.environment == "test"
    assert row.chain == "base_sepolia"


@pytest.mark.asyncio
async def test_base_still_accepted_on_live_key(session, monkeypatch):
    """Intended-pending-mainnet chain (in the registry): behavior unchanged."""
    _stub_side_effects(monkeypatch)
    key = await _activated_key(session)

    resp = await create_payment_intent(
        _payload("base"), _req("live", key_id=key.id), db=session
    )

    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert row.environment == "live"
    assert row.chain == "base"
