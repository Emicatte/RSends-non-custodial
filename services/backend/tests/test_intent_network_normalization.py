"""ITEM 1 — `intent.network` is DERIVED from the validated chain, never trusted
from merchant free-text.

`CreatePaymentIntentRequest.network` is optional and unvalidated, so a merchant
could stamp "BASE_MAINNET" on a base_sepolia intent (or "lol", or nothing) and it
would propagate verbatim into lifecycle webhooks. The fix normalizes it to the
chain's canonical network at the single construction site (`create_intent`), so
it can never contradict `chain`.

Harness mirrors test_recipient_gate.py: direct handler call against a real SQLite
session, external effects (on-chain quote / audit) neutralised.
"""
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.merchant_routes import create_payment_intent

SETTLE = "0x1111111111111111111111111111111111111111"


def _fresh_owner() -> str:
    """A unique EVM address per test, so accumulated rows from a prior test's
    failed drop_all can never make an owner map to >1 org (SETTLEMENT_WALLET_
    AMBIGUOUS). Mirrors the per-test-unique-owner isolation used by the org-intent
    suites."""
    return "0x" + secrets.token_hex(20)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Best-effort: Base.metadata.drop_all can trip on a cross-Base FK
    # (user_api_keys → organizations) in a fully-migrated local DB. Isolation is
    # by unique owner per test, so a failed drop never leaks into assertions.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "token_is_enabled", lambda chain, cur: True)
    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(owner: str, environment: str = "test"):
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _make_org_with_wallet(session, *, owner: str, settlement=SETTLE):
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
        settlement_wallet=settlement,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(
        UserWallet(
            user_id=user.id, org_id=org.id, address=owner, display_address=owner,
            verified_chain_id=84532, is_primary=True, chain_family="evm",
        )
    )
    await session.commit()
    return org


def _payload(**kw):
    d = dict(amount=10.0, currency="USDC", chain="base_sepolia")
    d.update(kw)
    return CreatePaymentIntentRequest(**d)


async def _created_intent(session, resp):
    return (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_network_contradicting_chain_is_normalized(session):
    """A merchant-supplied network that contradicts the chain is corrected to the
    chain's true network — BASE_MAINNET on base_sepolia becomes BASE_SEPOLIA."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)
    resp = await create_payment_intent(
        _payload(network="BASE_MAINNET"), _req(owner), db=session
    )
    row = await _created_intent(session, resp)
    assert row.network == "BASE_SEPOLIA"


@pytest.mark.asyncio
async def test_network_omitted_is_derived(session):
    """The common case (dashboard intents send no network) fills it from chain."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)
    resp = await create_payment_intent(_payload(), _req(owner), db=session)
    row = await _created_intent(session, resp)
    assert row.network == "BASE_SEPOLIA"


@pytest.mark.asyncio
async def test_network_consistent_passes_through(session):
    """A network already matching the chain is unchanged."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)
    resp = await create_payment_intent(
        _payload(network="BASE_SEPOLIA"), _req(owner), db=session
    )
    row = await _created_intent(session, resp)
    assert row.network == "BASE_SEPOLIA"


@pytest.mark.asyncio
async def test_network_malformed_is_normalized(session):
    """Garbage in the network field is normalized, not propagated (no 4xx)."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)
    resp = await create_payment_intent(_payload(network="lol"), _req(owner), db=session)
    row = await _created_intent(session, resp)
    assert row.network == "BASE_SEPOLIA"
