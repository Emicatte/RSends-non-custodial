"""Owner-identity resolution — settlement-wallet fallback (custodial-residue unblock).

`_resolve_owner_address` is the session dashboard's tenant-key resolver: org →
owner address == PaymentIntent.merchant_id. Historically it REQUIRED a SIWE-linked
primary EVM wallet (`user_wallets.is_primary`), so an email-onboarded merchant with
only a settlement wallet got 409 `no_primary_wallet` on every org route. The
fallback: when no primary wallet exists, resolve the org's `settlement_wallet` —
but ONLY if that address has no competing identity claim anywhere (fail-closed):

- any `user_wallets` row with the address, ANY org, INCLUDING unlinked/historical
  rows (someone once proved control via SIWE);
- any OTHER org with the same `settlement_wallet` (column is not unique);
- any `api_keys.owner_address` equal to it, active OR revoked (an rsend_ mint
  proved control via EIP-191).

A conflicting claim → 409 `settlement_wallet_conflict`, never a leak. A primary
wallet, when present, always wins (existing orgs resolve exactly as before).

Direct-handler tests, same pattern as test_user_org_payments.py /
test_user_org_intent_create.py: seed against a real SQLite session, call the
resolver and route coroutines directly.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    CreatePaymentIntentRequest,
    IntentStatus,
    PaymentIntent,
)
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.api_key_models import ApiKey
from app.api.merchant_profile_routes import _resolve_owner_address
from app.api.user_org_payments_routes import (
    create_org_payment_intent,
    list_org_payment_intents,
)

PRIMARY = "0x" + "a" * 40
SETTLE_A = "0x" + "1" * 40
SETTLE_B = "0x" + "2" * 40


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


async def _make_org(session, *, wallet=None, settlement=None, unlinked_wallet=None):
    """Org (+ owner user + admin membership). `wallet` links a primary EVM wallet;
    `unlinked_wallet` links a historical (soft-deleted) one; `settlement` sets
    the org-level settlement_wallet."""
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
    if wallet is not None:
        session.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=wallet,
                display_address=wallet,
                verified_chain_id=84532,
                is_primary=True,
                chain_family="evm",
            )
        )
    if unlinked_wallet is not None:
        session.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=unlinked_wallet,
                display_address=unlinked_wallet,
                verified_chain_id=84532,
                is_primary=False,
                chain_family="evm",
                unlinked_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()
    return org


def _mk_intent(merchant_id, **kw):
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment=kw.get("environment", "test"),
        amount=kw.get("amount", 100.0),
        currency=kw.get("currency", "USDC"),
        chain=kw.get("chain", "base_sepolia"),
        status=kw.get("status", IntentStatus.pending),
        recipient=kw.get("recipient"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def _mk_api_key(owner_address, *, revoked=False):
    return ApiKey(
        owner_address=owner_address,
        # A FOREIGN org's key (org_id NOT NULL since 0014) — still a
        # competing claim; only the org's OWN keys are carved out.
        org_id=str(uuid4()),
        key_hash=secrets.token_hex(32),
        key_prefix="rsend_test_" + secrets.token_hex(4),
        is_active=not revoked,
        environment="test",
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )


def _ctx(org, role="operator"):
    return ("user-unused", str(org.id), role)


async def _list(org, session):
    return await list_org_payment_intents(
        ctx=_ctx(org, "viewer"), db=session,
        environment="test", status=None, currency=None, page=1, per_page=20,
    )


# ── Resolution precedence ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_neither_wallet_nor_settlement_409(session):
    """No primary wallet, no settlement wallet → 409 no_primary_wallet."""
    org = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _resolve_owner_address(session, str(org.id))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "no_primary_wallet"


@pytest.mark.asyncio
async def test_settlement_fallback_happy_path(session):
    """No primary wallet, unclaimed settlement wallet → it becomes the owner
    identity and the dashboard list works, returning settlement-keyed intents."""
    org = await _make_org(session, settlement=SETTLE_A)
    seeded = _mk_intent(SETTLE_A)
    session.add(seeded)
    await session.commit()

    owner = await _resolve_owner_address(session, str(org.id))
    assert owner == SETTLE_A

    page = await _list(org, session)
    assert page.total == 1
    assert page.records[0].intent_id == seeded.intent_id


@pytest.mark.asyncio
async def test_primary_wallet_precedence(session):
    """A linked primary wallet always wins over settlement_wallet — existing
    orgs resolve exactly as before the fallback."""
    org = await _make_org(session, wallet=PRIMARY, settlement=SETTLE_A)
    owner = await _resolve_owner_address(session, str(org.id))
    assert owner == PRIMARY


@pytest.mark.asyncio
async def test_fallback_is_lowercased(session):
    """A checksummed settlement address resolves lowercase (merchant_id space)."""
    checksummed = "0x" + "A" * 40
    org = await _make_org(session, settlement=checksummed)
    owner = await _resolve_owner_address(session, str(org.id))
    assert owner == "0x" + "a" * 40


# ── Fail-closed conflict checks ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_squat_active_wallet_conflict_409(session):
    """Org B sets settlement = org A's SIWE-linked address → 409 conflict,
    org A's intents are never exposed."""
    await _make_org(session, wallet=PRIMARY)  # org A, proven control
    session.add(_mk_intent(PRIMARY))
    org_b = await _make_org(session, settlement=PRIMARY)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await _resolve_owner_address(session, str(org_b.id))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "settlement_wallet_conflict"

    with pytest.raises(HTTPException) as exc:
        await _list(org_b, session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_unlinked_wallet_still_blocks_fallback(session):
    """A historical (unlinked) wallet row still counts as a claim — intents
    created under that identity remain keyed to it."""
    await _make_org(session, unlinked_wallet=SETTLE_A)  # org A once linked it
    org_b = await _make_org(session, settlement=SETTLE_A)

    with pytest.raises(HTTPException) as exc:
        await _resolve_owner_address(session, str(org_b.id))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "settlement_wallet_conflict"


@pytest.mark.asyncio
async def test_shared_settlement_wallet_conflict_409(session):
    """Two wallet-less orgs with the same settlement wallet → both fail closed."""
    org_a = await _make_org(session, settlement=SETTLE_A)
    org_b = await _make_org(session, settlement=SETTLE_A)

    for org in (org_a, org_b):
        with pytest.raises(HTTPException) as exc:
            await _resolve_owner_address(session, str(org.id))
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "settlement_wallet_conflict"


@pytest.mark.asyncio
async def test_apikey_owner_conflict_409(session):
    """The address is an rsend_ API-key identity (active or revoked) → 409;
    a pure-API-key merchant's intents/webhooks can't be squatted."""
    for revoked in (False, True):
        settle = SETTLE_A if not revoked else SETTLE_B
        session.add(_mk_api_key(settle, revoked=revoked))
        org = await _make_org(session, settlement=settle)
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await _resolve_owner_address(session, str(org.id))
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "settlement_wallet_conflict"


# ── Fallback identity flows into create, isolation intact ─────────────────


@pytest.mark.asyncio
async def test_fallback_create_lands_in_own_scope(session):
    """Session create on a fallback-identity org stamps merchant_id =
    settlement_wallet; visible in own list, invisible to another fallback org."""
    org_a = await _make_org(session, settlement=SETTLE_A)
    org_b = await _make_org(session, settlement=SETTLE_B)

    created = await create_org_payment_intent(
        payload=CreatePaymentIntentRequest(
            amount=10.0, currency="USDC", chain="base_sepolia"
        ),
        ctx=_ctx(org_a), environment="test", db=session,
    )
    assert created.recipient == SETTLE_A  # recipient gate resolved the same org
    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == created.intent_id)
        )
    ).scalar_one()
    assert row.merchant_id == SETTLE_A  # fallback identity stamped as tenant key

    page_a = await _list(org_a, session)
    assert page_a.total == 1
    page_b = await _list(org_b, session)
    assert page_b.total == 0
