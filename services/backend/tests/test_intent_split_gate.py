"""The split gate (non-custodial split-at-payment) — an intent whose split BPS
do not sum to EXACTLY 10000 cannot be created; a valid split set satisfies the
recipient gate (no settlement wallet needed) and persists N child rows with
`recipient` NULL.

Direct-handler tests (no live server) mirroring test_recipient_gate.py: call
`create_payment_intent` with a fake `request.state.client` against a real DB
session. Split creation is fail-closed on config: without a configured
RSendsSplitRouter for the chain, creation 422s SPLIT_UNAVAILABLE — the operator
enables splits by setting SPLIT_ROUTER_ADDRESSES_JSON after deploy.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.merchant_routes import create_payment_intent
from app.services.intent_service import create_intent

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE = "0x1111111111111111111111111111111111111111"
SPLIT_A = "0x3333333333333333333333333333333333333333"
SPLIT_B = "0x5555555555555555555555555555555555555555"
SPLIT_C = "0x7777777777777777777777777777777777777777"
SPLIT_ROUTER = "0x4444444444444444444444444444444444444444"


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
    exercise ONLY the split gate."""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)
    monkeypatch.setattr("app.services.intent_service.log_event", _no_log)


@pytest.fixture
def split_enabled(monkeypatch):
    """Configure a split router for base_sepolia (84532) — the operator env flip."""
    monkeypatch.setattr(
        get_settings(),
        "split_router_addresses_json",
        '{"84532": "' + SPLIT_ROUTER + '"}',
    )


def _req(owner: str = OWNER, environment: str = "test"):
    client = {"client_id": owner, "environment": environment}
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _make_org_with_wallet(session, *, owner: str = OWNER, settlement=None):
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


def _split(*pairs):
    return [{"address": a, "share_bps": bps} for a, bps in pairs]


async def _split_rows(session, intent_id: str):
    from app.models.merchant_models import PaymentIntentRecipient

    return (
        await session.execute(
            select(PaymentIntentRecipient)
            .where(PaymentIntentRecipient.intent_id == intent_id)
            .order_by(PaymentIntentRecipient.position)
        )
    ).scalars().all()


# ── BPS-exact invariant: reject at the schema, never coerce ──────

def test_create_rejects_bps_sum_not_10000():
    """THE load-bearing invariant: sum != 10000 (either side) is rejected at
    intent creation. No 'close enough'."""
    with pytest.raises(ValidationError):
        _payload(split=_split((SPLIT_A, 5000), (SPLIT_B, 4999)))
    with pytest.raises(ValidationError):
        _payload(split=_split((SPLIT_A, 5000), (SPLIT_B, 5001)))


def test_create_rejects_bad_split_shapes():
    with pytest.raises(ValidationError):  # < 2 recipients
        _payload(split=_split((SPLIT_A, 10000)))
    with pytest.raises(ValidationError):  # > 20 recipients
        _payload(split=[
            {"address": f"0x{i:040x}", "share_bps": 476} for i in range(1, 21)
        ] + [{"address": f"0x{99:040x}", "share_bps": 480}])
    with pytest.raises(ValidationError):  # duplicate address
        _payload(split=_split((SPLIT_A, 5000), (SPLIT_A, 5000)))
    with pytest.raises(ValidationError):  # zero-bps leg
        _payload(split=_split((SPLIT_A, 10000), (SPLIT_B, 0)))
    with pytest.raises(ValidationError):  # malformed address
        _payload(split=_split(("not-an-address", 5000), (SPLIT_B, 5000)))


def test_split_and_recipient_mutually_exclusive():
    """An explicit single recipient AND a split cannot coexist — reject, never
    pick one."""
    with pytest.raises(ValidationError):
        _payload(
            recipient=SETTLE,
            split=_split((SPLIT_A, 5000), (SPLIT_B, 5000)),
        )


# ── Fail-closed availability gate ────────────────────────────────

@pytest.mark.asyncio
async def test_split_unavailable_without_router_config(session):
    """Valid split but NO split router configured for the chain → 422
    SPLIT_UNAVAILABLE. No intent may exist that /pay cannot pay."""
    await _make_org_with_wallet(session, settlement=SETTLE)
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload(split=_split((SPLIT_A, 6000), (SPLIT_B, 4000))),
            _req(),
            db=session,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "SPLIT_UNAVAILABLE"


# ── Happy path: split satisfies the recipient gate ───────────────

@pytest.mark.asyncio
async def test_create_split_persists_child_rows_and_null_recipient(
    session, split_enabled
):
    """A valid split set IS the recipient gate: child rows persisted in
    position order, `recipient` stays NULL (no single payee), and the response
    carries the split."""
    await _make_org_with_wallet(session, settlement=SETTLE)  # default NOT used

    resp = await create_payment_intent(
        _payload(split=_split((SPLIT_A, 5000), (SPLIT_B, 3000), (SPLIT_C, 2000))),
        _req(),
        db=session,
    )

    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()
    assert row.recipient is None  # a split intent has no single payee

    legs = await _split_rows(session, resp.intent_id)
    assert [(r.position, r.address, r.share_bps) for r in legs] == [
        (0, SPLIT_A, 5000),
        (1, SPLIT_B, 3000),
        (2, SPLIT_C, 2000),
    ]

    assert [(s.address, s.share_bps) for s in resp.split] == [
        (SPLIT_A, 5000), (SPLIT_B, 3000), (SPLIT_C, 2000),
    ]


@pytest.mark.asyncio
async def test_split_needs_no_settlement_wallet(session, split_enabled):
    """An org with NO settlement wallet can still create a split intent — the
    split set satisfies the gate (it IS the recipient set)."""
    await _make_org_with_wallet(session, settlement=None)

    resp = await create_payment_intent(
        _payload(split=_split((SPLIT_A, 7000), (SPLIT_B, 3000))),
        _req(),
        db=session,
    )
    legs = await _split_rows(session, resp.intent_id)
    assert len(legs) == 2


@pytest.mark.asyncio
async def test_session_path_split_create(session, split_enabled):
    """Session (org_id) path goes through the SAME create_intent: split works
    identically — no divergent construction site."""
    org = await _make_org_with_wallet(session, settlement=None)

    intent = await create_intent(
        session,
        OWNER,
        "test",
        _payload(split=_split((SPLIT_A, 9000), (SPLIT_B, 1000))),
        org_id=org.id,
        key_id=None,
    )
    legs = await _split_rows(session, intent.intent_id)
    assert [(r.address, r.share_bps) for r in legs] == [
        (SPLIT_A, 9000), (SPLIT_B, 1000),
    ]
    assert intent.recipient is None


# ── The single-recipient path is untouched ───────────────────────

@pytest.mark.asyncio
async def test_single_recipient_path_unchanged(session, split_enabled):
    """No `split` in the payload → the pre-existing recipient gate resolves the
    org default exactly as before, and no split rows are created."""
    await _make_org_with_wallet(session, settlement=SETTLE)

    resp = await create_payment_intent(_payload(), _req(), db=session)

    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()
    assert row.recipient == SETTLE
    assert await _split_rows(session, resp.intent_id) == []
    assert resp.split is None
