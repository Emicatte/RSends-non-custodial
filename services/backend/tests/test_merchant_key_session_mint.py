"""Session-minted rsend_ merchant keys (Option B, 2026-07-15).

Pins the contract of /api/v1/user/org/merchant-keys:

  1. Minting is pinned to environment=test and scope=write; the row carries
     org_id; the plaintext (rsend_test_…) is returned once.
  2. The minted key passes the SAME `verify_api_key` the merchant middleware
     uses, with client_id == the org's resolved owner address — i.e. a
     session-minted key IS a working merchant-API key.
  3. Self-conflict regression: a settlement-wallet-only org that mints key #1
     can still resolve its identity afterwards (stats/payments/key #2) —
     migration 0011's org_id + the owner_identity carve-out. A DIFFERENT org
     copying that settlement wallet still 409s (the conflict stays for
     everyone else).
  4. 409 no_primary_wallet when the org has neither wallet; 5-active-key cap
     → 409 max_keys_reached; list never returns key material; cross-org list
     is empty and cross-org revoke is 404; revoke is soft + idempotent.

Direct-handler tests (ctx tuple injected), same style as
tests/test_org_stats_checklist.py.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization
from app.api.user_org_merchant_keys_routes import (
    MAX_ACTIVE_KEYS,
    create_merchant_key,
    list_merchant_keys,
    revoke_merchant_key,
    MerchantKeyCreateRequest,
)
from app.security.api_keys import verify_api_key
from app.services.owner_identity import resolve_owner_address

SETTLE_A = "0x" + "a" * 40
SETTLE_B = "0x" + "b" * 40


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


async def _org(session, settlement_wallet=None):
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
        settlement_wallet=settlement_wallet,
        extra_metadata={},
    )
    session.add_all([user, org])
    await session.commit()
    return user.id, org.id


async def _mint(session, user_id, org_id, label="Default"):
    return await create_merchant_key(
        payload=MerchantKeyCreateRequest(label=label),
        request=_request(),
        ctx=(user_id, org_id, "admin"),
        db=session,
    )


# ── Mint contract ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mint_pins_test_env_write_scope_and_org(session):
    user_id, org_id = await _org(session, SETTLE_A)
    res = await _mint(session, user_id, org_id, label="Demo")

    assert res.key.startswith("rsend_test_")
    assert res.environment == "test"
    assert res.scope == "write"
    assert res.label == "Demo"
    assert res.prefix and res.prefix != res.key

    # Row carries the org linkage (migration 0011)
    from sqlalchemy import select
    from app.models.api_key_models import ApiKey

    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.org_id == org_id
    assert row.owner_address == SETTLE_A
    assert row.environment == "test"


@pytest.mark.asyncio
async def test_minted_key_passes_merchant_verify(session):
    """The whole point: one login → a key that works on the payment API."""
    user_id, org_id = await _org(session, SETTLE_A)
    res = await _mint(session, user_id, org_id)

    fake_req = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/merchant/payment-intent"),
        headers={"Authorization": f"Bearer {res.key}"},
    )
    client = await verify_api_key(fake_req)
    assert client is not None
    assert client["client_id"] == SETTLE_A  # same tenant identity
    assert client["environment"] == "test"

    # An rsusr_-shaped key is still rejected by the same verifier (unchanged).
    fake_req_usr = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/merchant/payment-intent"),
        headers={"Authorization": "Bearer rsusr_live_notarealkey"},
    )
    assert await verify_api_key(fake_req_usr) is None


@pytest.mark.asyncio
async def test_mint_without_identity_409_no_primary_wallet(session):
    user_id, org_id = await _org(session, settlement_wallet=None)
    with pytest.raises(HTTPException) as exc:
        await _mint(session, user_id, org_id)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "no_primary_wallet"


@pytest.mark.asyncio
async def test_self_conflict_regression(session):
    """Settlement-wallet-only org mints key #1 → its identity still resolves,
    key #2 mints — while another org copying the wallet still conflicts."""
    user_id, org_id = await _org(session, SETTLE_A)
    await _mint(session, user_id, org_id)

    # The org's own resolve is NOT poisoned by its own key…
    assert await resolve_owner_address(session, org_id) == SETTLE_A
    # …and a second mint works.
    res2 = await _mint(session, user_id, org_id, label="second")
    assert res2.key.startswith("rsend_test_")

    # A different org squatting the same settlement wallet still 409s.
    _other_user, other_org = await _org(session, SETTLE_A)
    with pytest.raises(HTTPException) as exc:
        await resolve_owner_address(session, other_org)
    assert exc.value.detail["code"] == "settlement_wallet_conflict"


@pytest.mark.asyncio
async def test_five_active_key_cap(session):
    user_id, org_id = await _org(session, SETTLE_A)
    for i in range(MAX_ACTIVE_KEYS):
        await _mint(session, user_id, org_id, label=f"k{i}")
    with pytest.raises(HTTPException) as exc:
        await _mint(session, user_id, org_id, label="overflow")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "max_keys_reached"

    # Revoking one frees a slot.
    listing = await list_merchant_keys(ctx=(user_id, org_id, "viewer"), db=session)
    await revoke_merchant_key(
        key_id=listing.keys[0].id,
        request=_request(),
        ctx=(user_id, org_id, "admin"),
        db=session,
    )
    res = await _mint(session, user_id, org_id, label="after-revoke")
    assert res.key.startswith("rsend_test_")


@pytest.mark.asyncio
async def test_minted_key_creates_intent_settling_to_org_wallet(session):
    """API-key path recipient gate: a settlement-wallet-only org has no
    SIWE-linked wallet for the reverse lookup, but its session-minted key is
    org-stamped (0011) — create_intent must resolve the recipient via the
    MINTING org instead of 422 SETTLEMENT_WALLET_MISSING."""
    from app.models.merchant_models import CreatePaymentIntentRequest
    from app.services.intent_service import create_intent

    user_id, org_id = await _org(session, SETTLE_A)
    minted = await _mint(session, user_id, org_id)

    intent = await create_intent(
        session,
        merchant_id=SETTLE_A,
        environment="test",
        payload=CreatePaymentIntentRequest(
            amount=10.5, currency="USDC", chain="BASE_SEPOLIA"
        ),
        org_id=None,  # API-key path
        key_id=str(minted.id),
    )
    assert intent.recipient == SETTLE_A
    assert intent.environment == "test"


# ── List / revoke: material never leaks, tenants isolated ────

@pytest.mark.asyncio
async def test_list_prefix_only_and_cross_org_isolation(session):
    user_a, org_a = await _org(session, SETTLE_A)
    user_b, org_b = await _org(session, SETTLE_B)
    minted = await _mint(session, user_a, org_a)

    listing_a = await list_merchant_keys(ctx=(user_a, org_a, "viewer"), db=session)
    assert listing_a.owner_address == SETTLE_A
    assert len(listing_a.keys) == 1
    item = listing_a.keys[0]
    assert item.session_minted is True
    assert item.prefix == minted.prefix
    assert not hasattr(item, "key")  # response model carries no material
    assert listing_a.remaining_slots == MAX_ACTIVE_KEYS - 1

    listing_b = await list_merchant_keys(ctx=(user_b, org_b, "viewer"), db=session)
    assert listing_b.keys == []

    # Cross-tenant revoke → 404, not 403 (no existence leak).
    with pytest.raises(HTTPException) as exc:
        await revoke_merchant_key(
            key_id=minted.id,
            request=_request(),
            ctx=(user_b, org_b, "admin"),
            db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_soft_and_idempotent(session):
    user_id, org_id = await _org(session, SETTLE_A)
    minted = await _mint(session, user_id, org_id)

    first = await revoke_merchant_key(
        key_id=minted.id, request=_request(), ctx=(user_id, org_id, "admin"), db=session
    )
    assert first.is_active is False
    assert first.revoked_at is not None

    second = await revoke_merchant_key(
        key_id=minted.id, request=_request(), ctx=(user_id, org_id, "admin"), db=session
    )
    assert second.is_active is False
    assert second.revoked_at == first.revoked_at

    # A revoked key no longer authenticates.
    fake_req = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/merchant/payment-intent"),
        headers={"Authorization": f"Bearer {minted.key}"},
    )
    assert await verify_api_key(fake_req) is None
