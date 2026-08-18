"""Approval gate on the wallet-signed mint route (POST /api/v1/keys/generate).

This route is registered in production and exempt from the API-key middleware
(EXEMPT_PATHS carries "/api/v1/keys"), so its only auth is a wallet signature.
Its request model defaulted `environment` to "live" and it never consulted the
approval policy — meaning anyone whose wallet resolves to exactly one org could
mint a LIVE key for an org that was never approved. The session mint route has
had that guard all along; this one did not.

Two changes under test:
  - the default flips to "test" (the powerless environment);
  - the request goes through `approval_denial`, the SAME policy the merchant API
    and session surfaces use. No second rule.

The five-key cap, the wallet auth and the org resolution are untouched.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.api_key_routes import GenerateKeyRequest, generate_key
from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet

def _fresh_wallet() -> str:
    """A distinct EVM address per test.

    Base.metadata.drop_all cannot always run in this module (user_api_keys holds
    an FK to organizations), so rows outlive a test. A shared address would then
    resolve to several orgs and every mint would 422 org_ambiguous before the
    gate under test was reached.
    """
    return "0x" + secrets.token_hex(20)


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="1.2.3.4"),
        headers={"user-agent": "pytest"},
    )


async def _org_with_wallet(session, approval_status: str) -> str:
    """Org whose primary EVM wallet is `address`, with an explicit approval state.

    approval_status is passed explicitly: conftest grandfathers inline-built orgs
    to 'approved', which is exactly what these tests must not inherit. Returns
    the wallet address to sign with.
    """
    address = _fresh_wallet()
    user = User(
        id=str(uuid4()),
        email=f"{uuid4()}@example.com",
        password_hash="$2b$12$" + "x" * 53,
        email_verified=True,
        account_type="merchant",
    )
    org = Organization(
        id=str(uuid4()),
        name="Org",
        slug=f"org-{uuid4()}",
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
        approval_status=approval_status,
        extra_metadata={},
    )
    session.add_all([user, org])
    await session.flush()
    session.add(
        UserWallet(
            user_id=user.id,
            org_id=org.id,
            address=address.lower(),
            display_address=address,
            verified_chain_id=84532,
            chain_family="evm",
            is_primary=True,
        )
    )
    await session.commit()
    return address


async def _mint(session, wallet: str, **kwargs):
    return await generate_key.__wrapped__(
        request=_request(),
        req=GenerateKeyRequest(owner_address="ignored", **kwargs),
        db=session,
        wallet_address=wallet,
    )


# ── The default is the powerless environment ─────────────────

@pytest.mark.asyncio
async def test_default_environment_is_test(session):
    """Omitting `environment` must no longer hand out a live key."""
    wallet = await _org_with_wallet(session, "approved")

    res = await _mint(session, wallet)

    assert res.environment == "test"
    assert res.key.startswith("rsend_test_")
    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.environment == "test"


# ── Live minting is gated by the shared approval policy ──────

@pytest.mark.asyncio
async def test_live_mint_denied_for_pending_org(session):
    """The hole: a wallet signature alone could mint a live key."""
    wallet = await _org_with_wallet(session, "pending_approval")

    with pytest.raises(HTTPException) as exc:
        await _mint(session, wallet, environment="live")

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_pending"
    minted = (
        await session.execute(
            select(ApiKey).where(ApiKey.owner_address == wallet.lower())
        )
    ).first()
    assert minted is None


@pytest.mark.asyncio
async def test_live_mint_allowed_for_approved_org(session):
    """An approved org is unaffected."""
    wallet = await _org_with_wallet(session, "approved")

    res = await _mint(session, wallet, environment="live")

    assert res.environment == "live"
    assert res.key.startswith("rsend_live_")


@pytest.mark.asyncio
async def test_live_mint_denied_for_declined_org(session):
    """`declined` is an explicit operator decision and must stay enforceable."""
    wallet = await _org_with_wallet(session, "declined")

    with pytest.raises(HTTPException) as exc:
        await _mint(session, wallet, environment="live")

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approval_declined"


@pytest.mark.asyncio
async def test_unknown_approval_status_fails_closed_on_live(session):
    """Anything that is not an explicit approval is denied on the live path."""
    wallet = await _org_with_wallet(session, "some_future_state")

    with pytest.raises(HTTPException) as exc:
        await _mint(session, wallet, environment="live")

    assert exc.value.status_code == 403


# ── Sandbox parity with the session mint route ───────────────

@pytest.mark.asyncio
async def test_test_mint_allowed_for_pending_org(session):
    """KYB self-service: a pending org still gets a sandbox key, as elsewhere."""
    wallet = await _org_with_wallet(session, "pending_approval")

    res = await _mint(session, wallet, environment="test")

    assert res.environment == "test"
    assert res.key.startswith("rsend_test_")


@pytest.mark.asyncio
async def test_test_mint_denied_for_declined_org(session):
    """`declined` blocks in BOTH environments."""
    wallet = await _org_with_wallet(session, "declined")

    with pytest.raises(HTTPException) as exc:
        await _mint(session, wallet, environment="test")

    assert exc.value.detail["code"] == "approval_declined"


# ── Out-of-range values are still refused at the boundary ────

@pytest.mark.asyncio
async def test_environment_outside_the_enum_is_rejected(session):
    with pytest.raises(ValidationError):
        GenerateKeyRequest(owner_address="ignored", environment="production")
