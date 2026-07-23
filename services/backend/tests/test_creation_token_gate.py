"""The intent-creation token gate — the LOAD-BEARING check declared in
packages/contracts/AUDIT_HANDOFF_ROUTERV2.md.

With the ownerless RSendsRouterV2 there is no on-chain token whitelist: the
ONLY thing preventing an intent from being born on a weird token is
`token_is_enabled` inside `intent_service.create_intent`. The real damage
scenario is not a griefer (F-4 eats that: they pay out of pocket, the intent
never moves) — it is a merchant creating an intent on a fee-on-transfer /
unregistered token: the payer pays, less arrives, F-4 rejects for
under-amount, and the payer has lost funds with the merchant unpaid. This
file pins that the gate rejects BOTH flavors (absent-from-registry and
present-but-disabled) at the single construction site, plus a CONTROL test
proving the rejection is attributable to the gate itself (with the gate
mocked open the identical request succeeds) — the same discipline as the
topic-hash literals: never a constant compared with itself.

NOTE: the Pydantic schema whitelist ({ETH, USDC, USDT, DAI, cbBTC, DEGEN})
is NOT sufficient — it admits tokens the registry has absent (cbBTC, DEGEN)
or disabled (DAI): the registry gate is the line that holds.

Direct-handler harness mirrored from test_recipient_gate.py.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.merchant_routes import create_payment_intent

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE = "0x1111111111111111111111111111111111111111"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """create_all + FK-ordered ROW wipe (children first) — no drop_all: the
    shared Postgres carries tables outside this module's metadata and a drop
    dies on their FKs (the known drop_all gotcha)."""
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import PaymentIntentRecipient
    from app.models.settlement_models import PaymentSettlement

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in (
            PaymentIntentRecipient.__table__,
            PaymentSettlement.__table__,
            PaymentIntent.__table__,
            UserWallet.__table__,
            Membership.__table__,
            Organization.__table__,
            User.__table__,
        ):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _neutralize_downstream(monkeypatch):
    """Neutralize effects DOWNSTREAM of the gate under test (response build,
    audit log). The token gate itself is deliberately NOT patched here."""
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


async def _make_org_with_wallet(session, *, owner: str = OWNER, settlement=SETTLE):
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


async def _intent_count(session) -> int:
    return (
        await session.execute(select(func.count()).select_from(PaymentIntent))
    ).scalar_one()


# ── The gate rejects (fail-closed) ───────────────────────────────

@pytest.mark.asyncio
async def test_unregistered_token_rejected_no_intent_row(session):
    """Schema-valid but registry-ABSENT token (DEGEN) → 400 UNSUPPORTED_TOKEN
    and NO intent row is born. Everything else about the request is valid
    (resolvable recipient), so this rejection is the token gate's."""
    await _make_org_with_wallet(session)
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(_payload(currency="DEGEN"), _req(), db=session)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_TOKEN"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_disabled_token_rejected_no_intent_row(session):
    """Registry-PRESENT but disabled token (DAI on base, enabled=false) →
    same 400, no row. Live environment so the mainnet chain passes the
    env gate and the token gate is the deciding check."""
    await _make_org_with_wallet(session)
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload(currency="DAI", chain="base"),
            _req(environment="live"),
            db=session,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_TOKEN"
    assert await _intent_count(session) == 0


# ── Control: the rejection above is ATTRIBUTABLE to the gate ─────

@pytest.mark.asyncio
async def test_control_gate_mocked_open_identical_request_succeeds(session, monkeypatch):
    """With ONLY the gate mocked open, the byte-identical DEGEN request
    succeeds — proving the rejections above come from the gate and not from
    some other validation failing first. If this control ever fails, the two
    pins above have gone vacuous."""
    import app.services.intent_service as isvc

    await _make_org_with_wallet(session)
    monkeypatch.setattr(isvc, "token_is_enabled", lambda chain, cur: True)

    resp = await create_payment_intent(_payload(currency="DEGEN"), _req(), db=session)
    row = (
        await session.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == resp.intent_id)
        )
    ).scalar_one()
    assert row.currency == "DEGEN"
    assert row.recipient == SETTLE
