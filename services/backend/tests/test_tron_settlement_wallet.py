"""TRON settlement wallet — validation, PATCH, and chain-aware recipient fallback.

`organizations.settlement_wallet` is EVM: validated `^0x[a-fA-F0-9]{40}$` and
STORED LOWERCASE. `settlement_wallet_tron` (migration 0022) is base58check and
must be stored BYTE-IDENTICAL — base58 excludes `0 O I l`, so lowercasing a
T-address does not merely change it, it produces a string that cannot be decoded
and whose checksum no longer verifies. The two columns therefore never share a
validator, and neither accepts the other's format.

The load-bearing behaviour here is the FALLBACK. `resolve_recipient` used to fall
back to the EVM wallet regardless of chain, so a TRON intent with no explicit
recipient either got an EVM payee (rejected later, confusingly, by
RECIPIENT_CHAIN_MISMATCH) or nothing. It is now chain-aware, and a TRON intent
with no TRON wallet fails closed on its OWN code rather than borrowing the EVM
wallet — an intent whose recipient cannot receive on TRON is worse than no intent.

Direct-handler tests (no live server), same pattern as test_settlement_wallet_org.py
and test_tron_watchonly_intent.py: fake `request.state.client`, real SQLite.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_settlement_wallet.py -v
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.org_models import Membership, Organization
from app.models.org_schemas import OrganizationPatchRequest
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key
from app.api.merchant_routes import create_payment_intent
from app.api.organizations_routes import update_org

# A real mainnet T-address with mixed case, and its destroyed lowercase form.
# `TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9` is the payee used across the TRON suites.
TRON_WALLET = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
TRON_WALLET_LOWER = TRON_WALLET.lower()

# TRON's zero address: 0x41 followed by 20 zero bytes, base58check-encoded. It
# has a VALID checksum, so `is_tron_address` accepts it — only an explicit check
# rejects it. This codebase already uses the same string as the native-TRX
# marker (apps/web/lib/chain-adapters/tron-adapter.ts), mirroring EVM's
# `ZERO_ADDRESS == native asset` convention.
TRON_ZERO = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"

EVM_WALLET = "0x1111111111111111111111111111111111111111"


def _fresh_owner() -> str:
    """Unique EVM owner per test, so accumulated rows can never make an owner map
    to >1 org (SETTLEMENT_WALLET_AMBIGUOUS)."""
    return "0x" + secrets.token_hex(20)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
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
def _quiet_audit(monkeypatch):
    import app.api.merchant_routes as mr

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(environment: str = "live", *, owner: str, key_id=None):
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _user(session) -> User:
    u = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
    )
    session.add(u)
    await session.flush()
    return u


async def _org(session, owner: User, *, settlement=None, settlement_tron=None,
               activation_status="not_started"):
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=owner.id,
        is_personal=False,
        plan="free",
        settlement_wallet=settlement,
        settlement_wallet_tron=settlement_tron,
        activation_status=activation_status,
    )
    session.add(org)
    await session.flush()
    return org


async def _org_with_wallets(session, *, owner: str, settlement=None, settlement_tron=None):
    """Org + admin membership + the owner's primary EVM wallet + a real API key.

    Two preconditions, neither of them the subject of these tests:
      * `activation_status="active"` — `tron` and `base` are both MAINNET chains,
        and the chain-access gate 403s `mainnet_activation_required` before
        recipient resolution is ever reached;
      * a real `ApiKey` carrying `org_id` (NOT NULL since 0014) — that gate
        resolves the org THROUGH THE KEY and denies when none resolves, so
        without it every test here would fail on the wrong gate.

    Returns (org, key); the key's id goes into `_req(key_id=...)`.
    """
    user = await _user(session)
    org = await _org(
        session, user, settlement=settlement, settlement_tron=settlement_tron,
        activation_status="active",
    )
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=owner, display_address=owner,
        verified_chain_id=84532, is_primary=True, chain_family="evm",
    ))
    _plaintext, fields = generate_api_key(environment="live")
    key = ApiKey(
        owner_address=owner, org_id=str(org.id), **fields,
        label="tron-settlement", scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return org, key


def _tron_payload():
    return CreatePaymentIntentRequest(
        amount=10.0, currency="USDT", chain="tron", reference_id=secrets.token_hex(8),
    )


def _evm_payload():
    return CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain="base", reference_id=secrets.token_hex(8),
    )


# ═══════════════════════════════════════════════════════════════
#  1. Validation — neither field accepts the other's format
# ═══════════════════════════════════════════════════════════════

def test_a_valid_t_address_survives_validation_byte_identical():
    """Case intact. Lowercasing a base58check address destroys it, so the
    validator must strip whitespace and otherwise not touch the value."""
    patch = OrganizationPatchRequest(settlement_wallet_tron=TRON_WALLET)
    assert patch.settlement_wallet_tron == TRON_WALLET
    assert patch.settlement_wallet_tron != TRON_WALLET_LOWER


def test_an_evm_address_is_rejected_on_the_tron_field():
    """Rejected outright — never normalised, never coerced into the other column."""
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet_tron=EVM_WALLET)


def test_a_tron_address_is_rejected_on_the_evm_field():
    """The pre-existing EVM validator must not have quietly widened."""
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet=TRON_WALLET)


def test_the_empty_string_is_rejected_on_the_tron_field():
    """NULL means unset and is reached by OMITTING the field — replace-only,
    exactly as settlement_wallet behaves. There is no clear-to-empty path."""
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet_tron="")


def test_the_tron_zero_address_is_rejected():
    """0x41 + 20 zero bytes, base58check-encoded. Its checksum is VALID, so
    `is_tron_address` accepts it and only an explicit check rejects it — the same
    reason the EVM validator rejects 0x000…0: a payout there burns funds. It is
    also this codebase's native-TRX marker, so accepting it would be ambiguous
    as well as destructive."""
    with pytest.raises(ValidationError):
        OrganizationPatchRequest(settlement_wallet_tron=TRON_ZERO)


# ═══════════════════════════════════════════════════════════════
#  2. PATCH — persistence, and the two columns are independent
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_patch_persists_the_tron_wallet_byte_identical(session):
    admin = await _user(session)
    org = await _org(session, admin)
    session.add(Membership(user_id=admin.id, org_id=org.id, role="admin"))
    await session.commit()

    resp = await update_org(
        org.id,
        OrganizationPatchRequest(settlement_wallet_tron=TRON_WALLET),
        user_id=admin.id,
        db=session,
    )
    assert resp.settlement_wallet_tron == TRON_WALLET

    fresh = await session.get(Organization, org.id)
    assert fresh.settlement_wallet_tron == TRON_WALLET, "case must survive the round trip"


@pytest.mark.asyncio
async def test_setting_one_wallet_does_not_clear_the_other(session):
    """Replace-only, per field. An org that has set both must not lose one by
    patching the other — omission means 'unchanged', never 'clear'."""
    admin = await _user(session)
    org = await _org(session, admin, settlement=EVM_WALLET, settlement_tron=TRON_WALLET)
    session.add(Membership(user_id=admin.id, org_id=org.id, role="admin"))
    await session.commit()

    # Patch only the EVM side.
    other_evm = "0x2222222222222222222222222222222222222222"
    await update_org(
        org.id,
        OrganizationPatchRequest(settlement_wallet=other_evm),
        user_id=admin.id,
        db=session,
    )
    fresh = await session.get(Organization, org.id)
    assert fresh.settlement_wallet == other_evm
    assert fresh.settlement_wallet_tron == TRON_WALLET, "the TRON wallet was cleared"

    # Patch only the TRON side.
    other_tron = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    await update_org(
        org.id,
        OrganizationPatchRequest(settlement_wallet_tron=other_tron),
        user_id=admin.id,
        db=session,
    )
    fresh = await session.get(Organization, org.id)
    assert fresh.settlement_wallet_tron == other_tron
    assert fresh.settlement_wallet == other_evm, "the EVM wallet was cleared"


# ═══════════════════════════════════════════════════════════════
#  3. Recipient resolution — the fallback is chain-aware
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_tron_intent_with_no_recipient_uses_the_tron_wallet(session):
    owner = _fresh_owner()
    _org, key = await _org_with_wallets(
        session, owner=owner, settlement=EVM_WALLET, settlement_tron=TRON_WALLET,
    )

    resp = await create_payment_intent(
        _tron_payload(), _req(owner=owner, key_id=key.id), db=session,
    )

    stored = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert stored.recipient == TRON_WALLET, (
        "a TRON intent must fall back to the TRON wallet, byte-identical"
    )


@pytest.mark.asyncio
async def test_an_evm_intent_with_no_recipient_still_uses_the_evm_wallet(session):
    """The pre-existing path is unchanged — including the lowercasing that has
    always applied to EVM addresses."""
    owner = _fresh_owner()
    _org, key = await _org_with_wallets(
        session, owner=owner, settlement=EVM_WALLET, settlement_tron=TRON_WALLET,
    )

    resp = await create_payment_intent(
        _evm_payload(), _req(owner=owner, key_id=key.id), db=session,
    )

    stored = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
    )).scalar_one()
    assert stored.recipient == EVM_WALLET.lower()


@pytest.mark.asyncio
async def test_a_tron_intent_without_a_tron_wallet_fails_closed_on_its_own_code(session):
    """THE ONE THAT MATTERS. The org has an EVM wallet set and no TRON wallet.

    Falling back to the EVM wallet would persist an intent whose recipient cannot
    receive on TRON — and it would then be rejected downstream by
    RECIPIENT_CHAIN_MISMATCH, which tells the merchant to pass an explicit
    recipient rather than that their TRON payout address is unset. Fail closed
    here, on a code that names the missing thing.
    """
    owner = _fresh_owner()
    _org, key = await _org_with_wallets(
        session, owner=owner, settlement=EVM_WALLET, settlement_tron=None,
    )

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _tron_payload(), _req(owner=owner, key_id=key.id), db=session,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "SETTLEMENT_WALLET_TRON_MISSING", (
        f"expected a TRON-specific code, got {exc.value.detail['error']!r}"
    )

    # And nothing was persisted against the EVM wallet.
    rows = (await session.execute(select(PaymentIntent))).scalars().all()
    assert rows == [], f"a TRON intent was persisted anyway: {[r.recipient for r in rows]}"
