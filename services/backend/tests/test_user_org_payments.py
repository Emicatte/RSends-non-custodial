"""Phase C — session-authed org payments read view.

The `/app` dashboard lists a merchant's payment intents through a session (JWT)
endpoint scoped by the logged-in user's org, reusing the exact query logic of the
API-key `GET /merchant/transactions` path (extracted into
`intent_service.list_org_intents`). The load-bearing property is **org
isolation**: a session must NEVER see another org's intents.

Direct-handler tests (no live server), same pattern as test_recipient_gate.py:
seed User+Organization+Membership+UserWallet against a real SQLite session and
call the route coroutine with the `(user_id, org_id, role)` ctx that
`require_org_role` would otherwise produce. The `environment` param is validated
as a `Literal` by FastAPI (invalid → 422) — framework-enforced, not retested here.
"""

import secrets
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import PaymentIntent, IntentStatus
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.api.deps.require_org_role import require_org_role
from app.api.merchant_routes import list_merchant_transactions
from app.api.user_org_payments_routes import list_org_payment_intents

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40
STRAY = "0x" + "c" * 40  # a merchant address that belongs to no org


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


async def _make_org(session, *, owner_address: str | None):
    """Create an org (+ owner user + admin membership). When `owner_address` is
    given, link it as the org's primary EVM wallet — the bridge the session view
    resolves to `merchant_id`. Pass None to model an org with no primary wallet."""
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
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if owner_address is not None:
        session.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=owner_address,
                display_address=owner_address,
                verified_chain_id=84532,
                is_primary=True,
                chain_family="evm",
            )
        )
    await session.commit()
    return org


def _mk_intent(merchant_id, *, environment="test", status=IntentStatus.pending, **kw):
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment=environment,
        amount=kw.get("amount", 100.0),
        currency=kw.get("currency", "USDC"),
        chain=kw.get("chain", "base_sepolia"),
        status=status,
        recipient=kw.get("recipient"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def _ctx(org, role="viewer"):
    """The (user_id, org_id, role) tuple require_org_role hands the route.
    org_id is always a string in production (require_org_role stringifies it)."""
    return ("user-unused", str(org.id), role)


async def _call(org, session, **overrides):
    params = dict(
        environment="test", status=None, currency=None, page=1, per_page=20
    )
    params.update(overrides)
    return await list_org_payment_intents(ctx=_ctx(org), db=session, **params)


# ── The load-bearing security test: org isolation ────────────────

@pytest.mark.asyncio
async def test_cross_org_isolation_no_leak(session):
    """A session scoped to org A sees ONLY org A's intents — never org B's."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    session.add_all([
        _mk_intent(OWNER_A), _mk_intent(OWNER_A),
        _mk_intent(OWNER_B),
    ])
    await session.commit()

    view_a = await _call(org_a, session)
    view_b = await _call(org_b, session)

    a_ids = {r.intent_id for r in view_a.records}
    b_ids = {r.intent_id for r in view_b.records}

    assert view_a.total == 2 and len(a_ids) == 2
    assert view_b.total == 1 and len(b_ids) == 1
    # The property: disjoint result sets, no leak across the tenant boundary.
    assert a_ids.isdisjoint(b_ids)


@pytest.mark.asyncio
async def test_scoped_to_active_org(session):
    """Intents for a merchant address outside the org are never returned."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    session.add_all([_mk_intent(OWNER_A), _mk_intent(STRAY)])
    await session.commit()

    view = await _call(org_a, session)
    assert view.total == 1
    assert all(r.status for r in view.records)  # real rows


# ── Environment scoping ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_environment_filter(session):
    """environment scopes reads: a test view never surfaces live intents."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    session.add_all([
        _mk_intent(OWNER_A, environment="test"),
        _mk_intent(OWNER_A, environment="live"),
    ])
    await session.commit()

    test_view = await _call(org_a, session, environment="test")
    live_view = await _call(org_a, session, environment="live")

    assert test_view.total == 1
    assert live_view.total == 1
    assert {r.intent_id for r in test_view.records}.isdisjoint(
        {r.intent_id for r in live_view.records}
    )


# ── Validation & fail-closed edges ───────────────────────────────

@pytest.mark.asyncio
async def test_invalid_status_400(session):
    """An unknown status value is rejected 400 (reused API-key semantics)."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    with pytest.raises(HTTPException) as exc:
        await _call(org_a, session, status="bogus")
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "INVALID_STATUS"


@pytest.mark.asyncio
async def test_no_primary_wallet_409(session):
    """An org with no primary EVM wallet cannot resolve an owner → 409."""
    org = await _make_org(session, owner_address=None)
    with pytest.raises(HTTPException) as exc:
        await _call(org, session)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "no_primary_wallet"


@pytest.mark.asyncio
async def test_pagination_bounds(session):
    """Paging is honoured: total is the full count; a page returns its slice."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    session.add_all([_mk_intent(OWNER_A) for _ in range(3)])
    await session.commit()

    p1 = await _call(org_a, session, page=1, per_page=2)
    p2 = await _call(org_a, session, page=2, per_page=2)

    assert p1.total == 3 and len(p1.records) == 2
    assert p2.total == 3 and len(p2.records) == 1
    seen = {r.intent_id for r in p1.records} | {r.intent_id for r in p2.records}
    assert len(seen) == 3  # no overlap between pages


# ── DRY: the session view and the API-key view share one query ───

@pytest.mark.asyncio
async def test_shared_helper_matches_apikey_path(session):
    """Session and API-key list paths return identical records for the same
    owner+environment (both delegate to list_org_intents — no divergent query)."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    session.add_all([_mk_intent(OWNER_A), _mk_intent(OWNER_A)])
    await session.commit()

    session_view = await _call(org_a, session)

    api_req = SimpleNamespace(
        state=SimpleNamespace(client={"client_id": OWNER_A, "environment": "test"})
    )
    api_view = await list_merchant_transactions(
        api_req, status=None, currency=None, page=1, per_page=20, db=session
    )

    assert session_view.total == api_view.total
    assert [r.intent_id for r in session_view.records] == [
        r.intent_id for r in api_view.records
    ]


# ── Auth gate: the route requires a JWT (via require_org_role) ────

@pytest.mark.asyncio
async def test_requires_jwt_401(session):
    """The dependency the route wires rejects a request with no Bearer token."""
    dep = require_org_role("viewer")
    no_auth = SimpleNamespace(headers={})
    with pytest.raises(HTTPException) as exc:
        await dep(request=no_auth, db=session)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "no_token"
