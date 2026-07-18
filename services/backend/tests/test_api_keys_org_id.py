"""API-key ownership re-keyed on org_id (migration 0014).

Pins the org_id-as-source-of-truth contract for the api_keys surface:

  1. Backfill (0014): every legacy key (org_id NULL) maps to its org via the
     owner wallet — active user_wallets link first, else the org's
     settlement_wallet — and the migration REPORTS AND STOPS (0007 pattern)
     on any unmappable or ambiguous key. Never guess ownership.
  2. Continuity: a legacy key that gets backfilled still authenticates via
     `verify_api_key` and still creates intents settling to its org's wallet
     (the "one real production key survives 0014" proof in miniature).
  3. Tenancy is org-scoped: a key minted by ANOTHER org is invisible to this
     org's list and 404s on revoke even when owner_address matches (the old
     OR-filter leaked on shared owner addresses).
  4. The legacy wallet-signed generate route stamps org_id (fail-closed 422
     when the wallet resolves to no/ambiguous org) — no NULL-org key can be
     created again after 0014's NOT NULL.

Direct-handler style like tests/test_merchant_key_session_mint.py.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy import select

from app.api.api_key_routes import GenerateKeyRequest, generate_key
from app.api.user_org_merchant_keys_routes import (
    create_merchant_key,
    list_merchant_keys,
    revoke_merchant_key,
    MerchantKeyCreateRequest,
)
from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest
from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key, verify_api_key
from app.services.intent_service import create_intent

WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40
WALLET_C = "0x" + "c" * 40

_MIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0014_api_keys_org_id_backfill.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0014", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Simulate the pre-0014 schema so legacy (org_id NULL) rows are
        # insertable; the model itself is NOT NULL post-0014.
        await conn.execute(
            sa.text("ALTER TABLE api_keys ALTER COLUMN org_id DROP NOT NULL")
        )
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


async def _link_wallet(session, user_id, org_id, address, primary=True):
    session.add(
        UserWallet(
            user_id=user_id,
            org_id=org_id,
            address=address.lower(),
            display_address=address,
            verified_chain_id=84532,
            is_primary=primary,
        )
    )
    await session.commit()


async def _legacy_key(session, owner_address):
    """A wallet-minted key as it exists pre-0014: org_id NULL."""
    plaintext, fields = generate_api_key(environment="test")
    key = ApiKey(
        owner_address=owner_address.lower(),
        org_id=None,
        **fields,
        label="legacy",
        scope="write",
        environment="test",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return plaintext, key


async def _run_backfill():
    mig = _load_migration()
    async with engine.begin() as conn:
        await conn.run_sync(mig.backfill_org_ids)


# ── 0014 backfill ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_maps_legacy_key_via_user_wallet(session):
    user_id, org_id = await _org(session, settlement_wallet=None)
    await _link_wallet(session, user_id, org_id, WALLET_A)
    _plain, key = await _legacy_key(session, WALLET_A)

    await _run_backfill()

    await session.refresh(key)
    assert key.org_id == str(org_id)


@pytest.mark.asyncio
async def test_backfill_maps_legacy_key_via_settlement_wallet(session):
    _user_id, org_id = await _org(session, settlement_wallet=WALLET_B)
    _plain, key = await _legacy_key(session, WALLET_B)

    await _run_backfill()

    await session.refresh(key)
    assert key.org_id == str(org_id)


@pytest.mark.asyncio
async def test_backfill_reports_and_stops_on_unmappable_key(session):
    _plain, key = await _legacy_key(session, WALLET_C)  # no org anywhere

    with pytest.raises(RuntimeError) as exc:
        await _run_backfill()
    assert str(key.id) in str(exc.value)

    # Nothing was written: the key stays NULL for the operator to decide.
    await session.refresh(key)
    assert key.org_id is None


@pytest.mark.asyncio
async def test_backfill_reports_and_stops_on_ambiguous_owner(session):
    user_a, org_a = await _org(session)
    user_b, org_b = await _org(session)
    await _link_wallet(session, user_a, org_a, WALLET_A)
    await _link_wallet(session, user_b, org_b, WALLET_A)
    _plain, key = await _legacy_key(session, WALLET_A)

    with pytest.raises(RuntimeError) as exc:
        await _run_backfill()
    assert str(key.id) in str(exc.value)


@pytest.mark.asyncio
async def test_backfilled_key_still_authenticates_and_settles(session):
    """Continuity guardrail: the one real production key must resolve to its
    org after 0014 — authenticate, create an intent, settle to the org
    wallet, and show up in the org's session key list."""
    user_id, org_id = await _org(session, settlement_wallet=WALLET_A)
    plaintext, key = await _legacy_key(session, WALLET_A)

    await _run_backfill()

    fake_req = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/merchant/payment-intent"),
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    client = await verify_api_key(fake_req)
    assert client is not None
    assert client["client_id"] == WALLET_A

    intent = await create_intent(
        session,
        merchant_id=WALLET_A,
        environment="test",
        payload=CreatePaymentIntentRequest(
            amount=1.0, currency="USDC", chain="BASE_SEPOLIA"
        ),
        org_id=None,  # API-key path
        key_id=str(key.id),
    )
    assert intent.recipient == WALLET_A

    listing = await list_merchant_keys(ctx=(user_id, org_id, "viewer"), db=session)
    assert [k.id for k in listing.keys] == [key.id]


# ── org-scoped tenancy (the OR-filter leak) ───────────────────


@pytest.mark.asyncio
async def test_foreign_org_key_invisible_even_with_same_owner_address(session):
    """A key belonging to another org must not surface in this org's list or
    revoke scope, even if owner_address matches this org's resolved owner."""
    user_a, org_a = await _org(session)
    await _link_wallet(session, user_a, org_a, WALLET_A)

    _user_b, org_b = await _org(session)
    _plain, foreign = await _legacy_key(session, WALLET_A)
    foreign.org_id = str(org_b)  # minted by org B, same owner address
    await session.commit()

    listing = await list_merchant_keys(ctx=(user_a, org_a, "viewer"), db=session)
    assert listing.keys == []

    with pytest.raises(HTTPException) as exc:
        await revoke_merchant_key(
            key_id=foreign.id,
            request=_request(),
            ctx=(user_a, org_a, "admin"),
            db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_session_mint_still_org_scoped(session):
    """Sanity: the session mint keeps stamping org_id and its own org sees it."""
    user_id, org_id = await _org(session, settlement_wallet=WALLET_B)
    res = await create_merchant_key(
        payload=MerchantKeyCreateRequest(label="mine"),
        request=_request(),
        ctx=(user_id, org_id, "admin"),
        db=session,
    )
    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.org_id == str(org_id)

    listing = await list_merchant_keys(ctx=(user_id, org_id, "viewer"), db=session)
    assert [k.id for k in listing.keys] == [res.id]


# ── legacy wallet-signed generate: org stamped, fail-closed ───


@pytest.mark.asyncio
async def test_wallet_generate_stamps_org_id(session):
    user_id, org_id = await _org(session)
    await _link_wallet(session, user_id, org_id, WALLET_A)

    res = await generate_key.__wrapped__(
        request=_request(),
        req=GenerateKeyRequest(owner_address="ignored", environment="test"),
        db=session,
        wallet_address=WALLET_A,
    )
    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.org_id == str(org_id)
    assert row.owner_address == WALLET_A


@pytest.mark.asyncio
async def test_wallet_generate_fails_closed_without_org(session):
    with pytest.raises(HTTPException) as exc:
        await generate_key.__wrapped__(
            request=_request(),
            req=GenerateKeyRequest(owner_address="ignored", environment="test"),
            db=session,
            wallet_address=WALLET_C,  # no org anywhere
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_wallet_generate_fails_closed_on_ambiguous_wallet(session):
    user_a, org_a = await _org(session)
    user_b, org_b = await _org(session)
    await _link_wallet(session, user_a, org_a, WALLET_A)
    await _link_wallet(session, user_b, org_b, WALLET_A)

    with pytest.raises(HTTPException) as exc:
        await generate_key.__wrapped__(
            request=_request(),
            req=GenerateKeyRequest(owner_address="ignored", environment="test"),
            db=session,
            wallet_address=WALLET_A,
        )
    assert exc.value.status_code == 422
