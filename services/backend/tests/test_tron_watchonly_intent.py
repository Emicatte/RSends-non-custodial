"""TRON watch-only payment intents — Phase 1, Slice 1.

Invariant under test: a `chain="TRON"` intent can be created, stores its base58
recipient **byte-identical**, and comes back with `onchain: null` — because TRON
has no router by construction. Nothing settles it yet; nothing watches.

Why the case-preservation assertions are load-bearing: TRON addresses are
base58check, and base58 excludes `0 O I l`. Lowercasing `TR7NHq...` does not
merely produce a different string — it produces one that cannot be decoded at
all. Every EVM address path in this codebase lowercases unconditionally, so the
recipient validator is the single write-side chokepoint that has to learn the
difference.

Direct-handler tests (no live server), same pattern as
test_merchant_chain_gate.py: fake `request.state.client`, real SQLite.
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
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key
from app.api.merchant_routes import create_payment_intent

# The in-scope token contract, and a valid unrelated T-address used as a payee.
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON_PAYEE = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
SETTLE = "0x1111111111111111111111111111111111111111"


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
    """Neutralise the audit write only. `build_onchain_payment` is deliberately
    NOT stubbed here — the onchain-null assertion below is the whole point, and
    stubbing it to None would prove nothing."""
    import app.api.merchant_routes as mr

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(environment: str = "live", *, owner: str, key_id=None):
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _make_org_with_wallet(
    session, *, owner: str, settlement=SETTLE, activation_status="not_started"
):
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
        activation_status=activation_status,
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


async def _org_and_key(
    session, *, owner: str, environment: str = "live", activation_status="not_started"
):
    """Org + a real API key carrying its org_id (NOT NULL since migration 0014).

    The watch-only chain gate resolves the org through the key, and denies when
    no org resolves — same "deny, never assume" rule the mainnet activation gate
    already applies. So the key is a precondition of these tests, not the subject.
    """
    org = await _make_org_with_wallet(
        session, owner=owner, activation_status=activation_status
    )
    _plaintext, fields = generate_api_key(environment=environment)
    key = ApiKey(
        owner_address=owner,
        org_id=str(org.id),
        **fields,
        label="tron-watchonly",
        scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return org, key


def _tron_payload(**kw):
    d = dict(amount=10.0, currency="USDT", chain="TRON", recipient=TRON_PAYEE)
    d.update(kw)
    return CreatePaymentIntentRequest(**d)


async def _row(session, resp):
    return (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()


# ── Case preservation: the whole point of the slice ──────────

@pytest.mark.asyncio
async def test_tron_recipient_round_trips_byte_identical(session, _quiet_audit):
    """create → storage → API response, with the base58 case untouched."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, activation_status="active")

    resp = await create_payment_intent(
        _tron_payload(), _req(owner=owner, key_id=key.id), db=session
    )

    row = await _row(session, resp)
    assert row.recipient == TRON_PAYEE, "stored value must be byte-identical"
    assert resp.recipient == TRON_PAYEE, "API response must echo it unchanged"
    assert row.chain == "TRON"


@pytest.mark.asyncio
async def test_lowercased_tron_address_is_not_accepted(session):
    """The lowercased form is not merely unequal — it is not a decodable TRON
    address (base58 has no `0 O I l`), so it must fail validation outright."""
    with pytest.raises(ValidationError):
        _tron_payload(recipient=TRON_PAYEE.lower())


def test_lowercasing_destroys_a_tron_address():
    """Pins the premise the validator rests on, independent of any handler."""
    from app.security.input_validator import is_tron_address

    assert is_tron_address(TRON_PAYEE) is True
    assert is_tron_address(USDT_TRC20) is True
    assert is_tron_address(TRON_PAYEE.lower()) is False
    # single-character typo — caught by the checksum, not by a shape regex
    assert is_tron_address(USDT_TRC20[:-1] + "u") is False


# ── Regression pin: EVM behaviour is exactly as before ───────

@pytest.mark.asyncio
async def test_evm_recipient_still_lowercased(session, _quiet_audit):
    """Mixed-case EVM recipients keep folding to lowercase — unchanged."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)
    mixed = "0xAbC0000000000000000000000000000000000001"

    payload = CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain="base_sepolia", recipient=mixed,
    )
    resp = await create_payment_intent(payload, _req("test", owner=owner), db=session)

    row = await _row(session, resp)
    assert row.recipient == mixed.lower()


# ── onchain: null, and NOT a 422 ─────────────────────────────

@pytest.mark.asyncio
async def test_tron_intent_returns_onchain_null_and_does_not_422(session, _quiet_audit):
    """TRON has no router by construction, so the response carries no on-chain
    instructions — but creation must still succeed. `build_onchain_payment` is
    intentionally un-stubbed here."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, activation_status="active")

    resp = await create_payment_intent(
        _tron_payload(), _req(owner=owner, key_id=key.id), db=session
    )

    assert resp.onchain is None
    assert resp.intent_id.startswith("pi_")


@pytest.mark.asyncio
async def test_tron_intent_stores_no_onchain_invoice_id(session, _quiet_audit):
    """A watch-only intent has no on-chain invoice id. It must be NULL, not a
    keccak of the literal string "None"."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, activation_status="active")

    resp = await create_payment_intent(
        _tron_payload(), _req(owner=owner, key_id=key.id), db=session
    )

    row = await _row(session, resp)
    assert row.onchain_invoice_id is None


# ── Chain ↔ address-family consistency ───────────────────────

@pytest.mark.asyncio
async def test_tron_intent_rejects_evm_recipient(session, _quiet_audit):
    """A TRON intent paid to a 0x address is unmatchable nonsense — reject it."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, activation_status="active")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _tron_payload(recipient=SETTLE), _req(owner=owner, key_id=key.id), db=session
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "RECIPIENT_CHAIN_MISMATCH"


@pytest.mark.asyncio
async def test_tron_intent_requires_explicit_recipient(session, _quiet_audit):
    """Without an override the recipient gate falls back to the org's EVM
    settlement wallet, which cannot receive TRC-20. Fail closed."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, activation_status="active")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _tron_payload(recipient=None), _req(owner=owner, key_id=key.id), db=session
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "RECIPIENT_CHAIN_MISMATCH"


# ── Environment classification ───────────────────────────────

def test_tron_is_classified_live_not_test():
    """TRON mainnet must never be mistaken for a testnet. Mirrors
    test_chain_access_guard.py::test_testnet_membership."""
    from app.services.chain_access import is_testnet_chain
    from app.services.router_registry import chain_id_for

    # TRON deliberately has no entry in CHAIN_IDS — no fake integer.
    assert chain_id_for("tron") is None
    # and the unknown-id classifier is fail-closed to mainnet
    assert is_testnet_chain(chain_id_for("tron")) is False


@pytest.mark.asyncio
async def test_tron_rejected_on_a_test_key(session):
    """TRON is mainnet-only in this slice: a test key must not create one."""
    owner = _fresh_owner()
    await _make_org_with_wallet(session, owner=owner)

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_tron_payload(), _req("test", owner=owner), db=session)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "TESTNET_ONLY"


# ── Watch-only chain class ───────────────────────────────────

def test_tron_is_a_watch_only_chain_with_no_router():
    from app.services.router_registry import (
        chain_has_settlement_router,
        chain_is_supported,
        is_watch_only_chain,
    )

    assert chain_is_supported("tron") is True, "must canonicalize into the registry"
    assert chain_has_settlement_router("tron") is False, "watch-only has no router"
    assert is_watch_only_chain("tron") is True
    # the exemption must be explicit, never inferred from a missing chain id
    assert is_watch_only_chain("ethereum") is False


def test_tron_usdt_is_registered_and_enabled():
    from app.services.router_registry import token_for, token_is_enabled

    assert token_is_enabled("tron", "USDT") is True
    tok = token_for("tron", "USDT")
    assert tok is not None
    address, decimals = tok
    assert decimals == 6
    # stored lowercased by the loader; compare case-insensitively
    assert address.lower() == USDT_TRC20.lower()


# ── Session (dashboard) path — the second create path ────────

@pytest.mark.asyncio
async def test_session_path_creates_tron_intent(session, _quiet_audit):
    """create_intent is shared, but the session route has its own chain pre-gate
    keyed on CHAIN_ID_BY_NAME — which TRON is absent from. It must still work."""
    from app.api.user_org_payments_routes import create_org_payment_intent

    owner = _fresh_owner()
    org = await _make_org_with_wallet(session, owner=owner, activation_status="active")

    resp = await create_org_payment_intent(
        payload=_tron_payload(),
        ctx=(None, str(org.id), "admin"),
        environment="live",
        db=session,
    )

    row = await _row(session, resp)
    assert row.recipient == TRON_PAYEE
    assert row.chain == "TRON"
    assert resp.onchain is None


@pytest.mark.asyncio
async def test_session_path_tron_requires_company_submitted(session, _quiet_audit):
    """The session pre-gate skips chains with no chain id, and the router gate no
    longer catches TRON — so without an explicit branch an unverified org could
    create mainnet intents. Pin that it cannot."""
    from app.api.user_org_payments_routes import create_org_payment_intent

    owner = _fresh_owner()
    org = await _make_org_with_wallet(session, owner=owner)
    org.onboarding_status = "pending"
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_org_payment_intent(
            payload=_tron_payload(),
            ctx=(None, str(org.id), "admin"),
            environment="live",
            db=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "company_profile_required"


# ── The KYB gate applies to watch-only mainnet chains too ────

@pytest.mark.asyncio
async def test_unactivated_org_cannot_create_mainnet_tron_intent(session, _quiet_audit):
    """TRON is mainnet, so business verification is required exactly as it is for
    Base. The gate keys on testnet-ness, not on whether the chain happens to have
    an EVM chain id — a watch-only chain has none, and skipping it there would
    leave the KYB check as the only control between an unverified org and a live
    payable page.

    Asserted as byte-identical to the Base refusal: the point is that watch-only
    is not a second, weaker class of mainnet.
    """
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner)  # activation: not_started

    with pytest.raises(HTTPException) as tron_exc:
        await create_payment_intent(
            _tron_payload(), _req(owner=owner, key_id=key.id), db=session
        )

    base_payload = CreatePaymentIntentRequest(
        amount=10.0, currency="USDC", chain="base", recipient=SETTLE,
    )
    with pytest.raises(HTTPException) as base_exc:
        await create_payment_intent(
            base_payload, _req(owner=owner, key_id=key.id), db=session
        )

    assert tron_exc.value.status_code == 403
    assert tron_exc.value.detail == {"code": "mainnet_activation_required"}
    # identical to the established mainnet refusal, not a bespoke one
    assert tron_exc.value.status_code == base_exc.value.status_code
    assert tron_exc.value.detail == base_exc.value.detail


@pytest.mark.asyncio
async def test_session_environment_live_cannot_bypass_activation_for_tron(session):
    """`environment` is a client-supplied query param on the session route, so an
    operator can ask for live directly. That must not reach a live TRON intent
    without activation — this is the path that made the gap worth closing."""
    from app.api.user_org_payments_routes import create_org_payment_intent

    owner = _fresh_owner()
    org = await _make_org_with_wallet(session, owner=owner)  # activation: not_started

    with pytest.raises(HTTPException) as exc:
        await create_org_payment_intent(
            payload=_tron_payload(),
            ctx=(None, str(org.id), "admin"),
            environment="live",
            db=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "mainnet_activation_required"}
