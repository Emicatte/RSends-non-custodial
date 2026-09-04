"""The recipient gate (Phase B) — an intent CANNOT be created without a
resolvable recipient (explicit override OR the org's settlement_wallet default).

Direct-handler tests (no live server): call `create_payment_intent` with a fake
`request.state.client`, against a real SQLite session — the same pattern as
test_merchant_env_isolation.py. The gate lives at the single PaymentIntent
construction site, so these prove no create path yields an empty recipient.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.merchant_routes import create_payment_intent

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE = "0x1111111111111111111111111111111111111111"
OVERRIDE = "0x2222222222222222222222222222222222222222"


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


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    """Neutralise external effects (on-chain quote / audit log) so tests
    exercise ONLY the recipient gate.

    The token gate is deliberately NOT mocked: every payload here is USDC on
    base_sepolia, which the registry enables, so the real gate never fires.
    (It used to be patched on `merchant_routes`; Phase D moved the call into
    `intent_service.create_intent`, which left the patch inert — it neutralised
    nothing. Repointing it would only hide a genuine break in the platform's
    baseline settleable pair.)"""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(owner: str = OWNER, environment: str = "test"):
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _make_org_with_wallet(session, *, owner: str = OWNER, settlement=None):
    """Create an org whose primary EVM wallet is `owner`, with an optional
    settlement_wallet — mirrors a real merchant that linked a wallet in Settings."""
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
            user_id=user.id,
            org_id=org.id,
            address=owner,
            display_address=owner,
            verified_chain_id=84532,
            is_primary=True,
            chain_family="evm",
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


# ── The gate blocks (fail-closed) ────────────────────────────────

@pytest.mark.asyncio
async def test_create_no_recipient_owner_unresolvable_422(session):
    """No override, and the key owner maps to no org with a settlement wallet →
    422 SETTLEMENT_WALLET_MISSING. (Pre-fix this returns 200 — the RED case.)"""
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload(), _req(), db=session)
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "SETTLEMENT_WALLET_MISSING"


@pytest.mark.asyncio
async def test_error_code_stable(session):
    """Org exists for the owner but its settlement_wallet is unset → MISSING
    (not AMBIGUOUS)."""
    await _make_org_with_wallet(session, settlement=None)
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload(), _req(), db=session)
    assert exc.value.detail["error"] == "SETTLEMENT_WALLET_MISSING"


@pytest.mark.asyncio
async def test_create_ambiguous_wallet_org_mapping_422(session):
    """The owner wallet is primary in TWO orgs (both with settlement wallets) →
    422 SETTLEMENT_WALLET_AMBIGUOUS; never guess which org's wallet to use."""
    await _make_org_with_wallet(session, settlement=SETTLE)
    await _make_org_with_wallet(session, settlement=OVERRIDE)
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload(), _req(), db=session)
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "SETTLEMENT_WALLET_AMBIGUOUS"


# ── The gate resolves (happy paths) ──────────────────────────────

@pytest.mark.asyncio
async def test_create_uses_org_default(session):
    await _make_org_with_wallet(session, settlement=SETTLE)
    resp = await create_payment_intent(_payload(), _req(), db=session)
    row = await _created_intent(session, resp)
    assert row.recipient == SETTLE


@pytest.mark.asyncio
async def test_create_override_beats_default(session):
    await _make_org_with_wallet(session, settlement=SETTLE)
    resp = await create_payment_intent(_payload(recipient=OVERRIDE), _req(), db=session)
    row = await _created_intent(session, resp)
    assert row.recipient == OVERRIDE
