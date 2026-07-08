"""Phase E — session-authed org webhook reads (list + deliveries).

Direct-handler tests (no live server), same pattern as test_user_org_payments.py:
seed User+Organization+Membership+UserWallet + MerchantWebhook/WebhookDelivery
against a real SQLite session and call the route coroutine with the
(user_id, org_id, role) ctx that require_org_role would otherwise produce.

Load-bearing properties: `secret` never leaves; deliveries never carry
`payload`/`response_body`; cross-tenant/cross-env deliveries → 404.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.merchant_models import (
    MerchantWebhook,
    WebhookDelivery,
    DeliveryStatus,
    WebhookItem,
    WebhookDeliveryItem,
)
from app.api.user_org_webhooks_routes import (
    list_org_webhooks,
    list_org_webhook_deliveries,
)

OWNER_A = "0x" + "a" * 40
OWNER_B = "0x" + "b" * 40


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


async def _make_org(session, *, owner_address):
    user = User(id=str(uuid4()), email=f"{secrets.token_hex(6)}@example.com", account_type="individual")
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3), slug=secrets.token_hex(8),
        owner_user_id=user.id, is_personal=False, plan="free",
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if owner_address is not None:
        session.add(UserWallet(
            user_id=user.id, org_id=org.id, address=owner_address,
            display_address=owner_address, verified_chain_id=84532,
            is_primary=True, chain_family="evm",
        ))
    await session.commit()
    return org


def _mk_webhook(merchant_id, *, environment="test", is_active=True):
    return MerchantWebhook(
        merchant_id=merchant_id, environment=environment,
        url="https://merchant.example/hooks", secret=secrets.token_hex(32),
        events=["payment.completed"], is_active=is_active,
    )


def _mk_delivery(webhook_id, *, status=DeliveryStatus.delivered):
    return WebhookDelivery(
        webhook_id=webhook_id, idempotency_key=secrets.token_hex(16),
        event_type="payment.completed", payload={"secret_order": "abc123"},
        status=status, response_code=200, response_body="OK-internal-detail",
        retries=0, delivered_at=datetime.now(timezone.utc),
    )


def _ctx(org, role="viewer"):
    return ("user-unused", str(org.id), role)


# ── secret never leaves ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_excludes_secret(session):
    org = await _make_org(session, owner_address=OWNER_A)
    session.add(_mk_webhook(OWNER_A))
    await session.commit()

    resp = await list_org_webhooks(ctx=_ctx(org), environment="test", db=session)

    assert resp.total == 1
    item = resp.records[0]
    assert isinstance(item, WebhookItem)
    # The response model has no `secret` field at all — belt AND suspenders.
    assert not hasattr(item, "secret")
    assert "secret" not in item.model_dump()


@pytest.mark.asyncio
async def test_list_env_scoped(session):
    """A test view never surfaces live webhooks (and vice versa)."""
    org = await _make_org(session, owner_address=OWNER_A)
    session.add_all([
        _mk_webhook(OWNER_A, environment="test"),
        _mk_webhook(OWNER_A, environment="live"),
    ])
    await session.commit()

    test_view = await list_org_webhooks(ctx=_ctx(org), environment="test", db=session)
    live_view = await list_org_webhooks(ctx=_ctx(org), environment="live", db=session)

    assert test_view.total == 1
    assert live_view.total == 1


@pytest.mark.asyncio
async def test_list_org_isolation(session):
    """Org A never sees org B's webhooks."""
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    session.add_all([_mk_webhook(OWNER_A), _mk_webhook(OWNER_B)])
    await session.commit()

    view_a = await list_org_webhooks(ctx=_ctx(org_a), environment="test", db=session)
    view_b = await list_org_webhooks(ctx=_ctx(org_b), environment="test", db=session)
    assert view_a.total == 1 and view_b.total == 1


# ── deliveries: exclusions + scoping + pagination ────────────────

@pytest.mark.asyncio
async def test_deliveries_excludes_payload_and_response_body(session):
    org = await _make_org(session, owner_address=OWNER_A)
    wh = _mk_webhook(OWNER_A)
    session.add(wh)
    await session.flush()
    session.add(_mk_delivery(wh.id))
    await session.commit()

    resp = await list_org_webhook_deliveries(
        webhook_id=wh.id, ctx=_ctx(org), environment="test",
        page=1, per_page=20, db=session,
    )
    assert resp.total == 1
    row = resp.records[0]
    assert isinstance(row, WebhookDeliveryItem)
    dumped = row.model_dump()
    assert "payload" not in dumped
    assert "response_body" not in dumped
    assert row.status == "delivered" and row.response_code == 200


@pytest.mark.asyncio
async def test_deliveries_cross_tenant_404(session):
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    wh = _mk_webhook(OWNER_A)
    session.add(wh)
    await session.flush()
    session.add(_mk_delivery(wh.id))
    await session.commit()

    # org B asking for org A's webhook deliveries → 404 (not 403, no leak).
    with pytest.raises(HTTPException) as exc:
        await list_org_webhook_deliveries(
            webhook_id=wh.id, ctx=_ctx(org_b), environment="test",
            page=1, per_page=20, db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deliveries_cross_env_404(session):
    """A test-env session can't read a live webhook's deliveries."""
    org = await _make_org(session, owner_address=OWNER_A)
    wh = _mk_webhook(OWNER_A, environment="live")
    session.add(wh)
    await session.flush()
    session.add(_mk_delivery(wh.id))
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await list_org_webhook_deliveries(
            webhook_id=wh.id, ctx=_ctx(org), environment="test",
            page=1, per_page=20, db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deliveries_pagination(session):
    org = await _make_org(session, owner_address=OWNER_A)
    wh = _mk_webhook(OWNER_A)
    session.add(wh)
    await session.flush()
    session.add_all([_mk_delivery(wh.id) for _ in range(3)])
    await session.commit()

    p1 = await list_org_webhook_deliveries(
        webhook_id=wh.id, ctx=_ctx(org), environment="test",
        page=1, per_page=2, db=session,
    )
    p2 = await list_org_webhook_deliveries(
        webhook_id=wh.id, ctx=_ctx(org), environment="test",
        page=2, per_page=2, db=session,
    )
    assert p1.total == 3 and len(p1.records) == 2
    assert p2.total == 3 and len(p2.records) == 1
    seen = {r.id for r in p1.records} | {r.id for r in p2.records}
    assert len(seen) == 3
