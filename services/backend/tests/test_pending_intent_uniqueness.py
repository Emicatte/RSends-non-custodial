"""`uq_intent_pending_amount` — the key it enforces, and the 409 that reports it.

Migration 0019 declares

    UNIQUE (merchant_id, environment, chain, currency, amount)
    WHERE status = 'pending'

A watch-only transfer carries no `invoiceId`, so it can only be matched on
(recipient, token, amount, window); two pending intents that agree on all of
those make an arriving payment genuinely ambiguous, and the live lookup uses
`scalar_one_or_none()` — a tie is a crash, not a wrong match. `environment` and
`chain` are IN the key because a test intent and a live one are not duplicates
of each other, and neither are a pending Base intent and a pending TRON intent
at the same amount: those are two different payments.

WHY THIS FILE TESTS AT TWO LEVELS.

The 409 translation is a property of `create_intent` and is exercised through
the handler. The `environment` and `chain` dimensions of the key are NOT
reachable through it, for reasons that are themselves invariants:

  * `environment` can never vary alone — the env↔chain gate refuses a testnet
    chain on a live key and a mainnet chain on a test key
    (`intent_service._TESTNET_CHAINS` / `_MAINNET_CHAINS`), so changing the
    environment forces the chain to change with it;
  * `chain` can never vary alone — no currency is enabled on two chains inside
    one environment (base has ETH/USDC/EURC, TRON has USDT, base_sepolia has
    ETH/USDC), so changing the chain forces the currency to change with it.

Those two dimensions are therefore asserted against the schema directly, with
real `PaymentIntent` rows. That is the honest place for them: they are
properties of the index, not of the handler, and a handler-level test would
have to fake a registry to reach them.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import (
    CreatePaymentIntentRequest,
    IntentStatus,
    PaymentIntent,
)
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key
from app.api.merchant_routes import create_payment_intent

SETTLE = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"

# The conflict the index exists to prevent, spelled once.
CONFLICT_CODE = "DUPLICATE_PENDING_INTENT"


def _fresh_owner() -> str:
    """Unique EVM owner per test so accumulated rows can never make an owner map
    to >1 org (SETTLEMENT_WALLET_AMBIGUOUS). Mirrors the org-intent suites."""
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


@pytest.fixture
def _quiet_audit(monkeypatch):
    """Neutralise the audit write only — it is not the subject here."""
    import app.api.merchant_routes as mr

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(environment: str = "test", *, owner: str, key_id=None):
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _org_and_key(session, *, owner: str, environment: str = "test"):
    """Org + a real API key carrying its org_id (NOT NULL since migration 0014)."""
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
        settlement_wallet=SETTLE,
        activation_status="not_started",
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
    _plaintext, fields = generate_api_key(environment=environment)
    key = ApiKey(
        owner_address=owner, org_id=str(org.id), **fields,
        label="pending-uniqueness", scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return org, key


def _payload(**kw):
    """A settleable testnet intent — no mainnet activation gate in the way."""
    d = dict(amount=100.0, currency="USDC", chain="base_sepolia", recipient=PAYEE)
    d.update(kw)
    return CreatePaymentIntentRequest(**d)


def _row(merchant_id, *, environment="test", chain="base_sepolia",
         currency="USDC", amount=100.0, status=IntentStatus.pending):
    """A PaymentIntent built straight against the schema, to exercise the index
    itself on the dimensions create_intent cannot vary (see module docstring)."""
    from datetime import datetime, timedelta, timezone

    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment=environment,
        amount=amount,
        currency=currency,
        chain=chain,
        status=status,
        recipient=PAYEE,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


async def _pending_count(session, merchant_id) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PaymentIntent)
            .where(PaymentIntent.merchant_id == merchant_id)
        )
    ).scalar_one()


# ── The 409: the constraint must not surface as a 500 ────────────

@pytest.mark.asyncio
async def test_duplicate_pending_intent_returns_409_not_500(session, _quiet_audit):
    """The second identical pending intent is refused with a named 409.

    Before this, `create_intent` had no IntegrityError handling around
    flush/commit, so the index surfaced to the merchant as an unhandled
    exception — a 500 on a condition the server understands perfectly.
    """
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner)
    req = _req(owner=owner, key_id=key.id)

    first = await create_payment_intent(_payload(), req, db=session)
    assert first.intent_id

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload(), req, db=session)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == CONFLICT_CODE
    # The message must name the field set, or the merchant cannot tell which of
    # their inputs to change.
    message = exc.value.detail["message"].lower()
    for field in ("amount", "currency", "chain", "environment"):
        assert field in message, f"{field!r} missing from {message!r}"

    # Refused, not half-written.
    assert await _pending_count(session, owner) == 1


@pytest.mark.asyncio
async def test_a_different_amount_is_never_refused(session, _quiet_audit):
    """The gate closes on the exact tuple and nothing wider — otherwise it would
    be blocking ordinary invoicing rather than an ambiguous match."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner)
    req = _req(owner=owner, key_id=key.id)

    await create_payment_intent(_payload(amount=100.0), req, db=session)
    await create_payment_intent(_payload(amount=101.0), req, db=session)

    assert await _pending_count(session, owner) == 2


@pytest.mark.asyncio
async def test_slot_frees_when_first_intent_leaves_pending(session, _quiet_audit):
    """The index is partial: once the first intent is no longer `pending` the
    merchant may re-issue the identical invoice. Re-issuing after a cancellation
    (or an expiry) is ordinary business, and the predicate is what keeps it
    legal."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner)
    req = _req(owner=owner, key_id=key.id)

    first = await create_payment_intent(_payload(), req, db=session)

    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == first.intent_id)
        )
    ).scalar_one()
    row.status = IntentStatus.cancelled
    await session.commit()

    second = await create_payment_intent(_payload(), req, db=session)
    assert second.intent_id != first.intent_id
    assert await _pending_count(session, owner) == 2


# ── Fail-closed: only THIS violation is translated ───────────────

@pytest.mark.asyncio
async def test_unrelated_integrity_error_still_propagates(
    session, _quiet_audit, monkeypatch
):
    """A different constraint must not be reported as a duplicate-intent 409.

    Pinning the unique `reference_id` makes the second create violate
    `ix_payment_intents_reference_id` instead — a real IntegrityError from the
    real code path, on a different constraint. It has to come out as an
    IntegrityError, not be swallowed or relabelled: catching IntegrityError
    broadly here would turn every future schema violation into a misleading
    409 about amounts.
    """
    import app.services.intent_service as svc

    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner)
    req = _req(owner=owner, key_id=key.id)

    # Unique per run: the collision must be between THIS test's two intents,
    # never with a row an earlier run left behind in a dirty dev database.
    # Exactly 16 chars — `reference_id` is varchar(16), and overflowing it
    # raises a DataError instead of the IntegrityError under test.
    pinned = secrets.token_hex(8)
    monkeypatch.setattr(svc, "generate_reference_id", lambda *_a, **_k: pinned)

    await create_payment_intent(_payload(amount=100.0), req, db=session)

    # Different amount, so uq_intent_pending_amount is NOT what fires.
    with pytest.raises(IntegrityError):
        await create_payment_intent(_payload(amount=101.0), req, db=session)


# ── The key's shape: environment and chain are part of it ────────

@pytest.mark.asyncio
async def test_same_tuple_different_environment_both_persist(session):
    """A test intent and a live intent are not duplicates of each other.

    Unreachable through create_intent (the env↔chain gate forces the chain to
    move with the environment), so asserted against the schema directly.
    """
    owner = _fresh_owner()
    session.add_all([
        _row(owner, environment="test"),
        _row(owner, environment="live"),
    ])
    await session.commit()

    assert await _pending_count(session, owner) == 2


@pytest.mark.asyncio
async def test_same_tuple_different_chain_both_persist(session):
    """A pending Base intent and a pending TRON intent at the same amount are
    two different payments, not a duplicate.

    Unreachable through create_intent (no currency is enabled on two chains
    within one environment), so asserted against the schema directly.
    """
    owner = _fresh_owner()
    session.add_all([
        _row(owner, environment="live", chain="base"),
        _row(owner, environment="live", chain="tron"),
    ])
    await session.commit()

    assert await _pending_count(session, owner) == 2


@pytest.mark.asyncio
async def test_identical_tuple_is_still_refused_at_the_schema(session):
    """The counterpart of the two above: with environment and chain equal, the
    index still bites. Without this, widening the key could silently disable it."""
    owner = _fresh_owner()
    session.add_all([_row(owner), _row(owner)])

    with pytest.raises(IntegrityError):
        await session.commit()
