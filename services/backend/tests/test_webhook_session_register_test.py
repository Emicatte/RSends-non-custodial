"""Phase E — session-authed org webhook register + test-fire, and the shared
egress/SSRF guard (E1b).

register/test reuse the SAME service core as the API-key routes; these tests
pin: env stamping, cross-tenant 404, inactive 400, and that the egress guard
blocks private/loopback/metadata targets WITHOUT making an outbound request.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

import app.services.webhook_service as whsvc
from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.merchant_models import MerchantWebhook, RegisterWebhookRequest
from app.services.webhook_service import check_webhook_egress, send_test_event
from app.api.user_org_webhooks_routes import (
    register_org_webhook,
    test_org_webhook as fire_test_org_webhook,
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
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=owner_address,
        display_address=owner_address, verified_chain_id=84532,
        is_primary=True, chain_family="evm",
    ))
    await session.commit()
    return org


def _ctx(org, role="operator"):
    return ("user-unused", str(org.id), role)


# ── register ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_stamps_env_and_owner(session):
    org = await _make_org(session, owner_address=OWNER_A)
    resp = await register_org_webhook(
        payload=RegisterWebhookRequest(url="https://merchant.example/hooks"),
        ctx=_ctx(org), environment="test", db=session,
    )
    assert resp.secret  # one-shot secret returned here
    row = (await session.execute(
        select(MerchantWebhook).where(MerchantWebhook.id == resp.webhook_id)
    )).scalar_one()
    assert row.merchant_id == OWNER_A
    assert row.environment == "test"


@pytest.mark.asyncio
async def test_register_ssrf_blocks_private_ip(session):
    org = await _make_org(session, owner_address=OWNER_A)
    with pytest.raises(HTTPException) as exc:
        await register_org_webhook(
            payload=RegisterWebhookRequest(url="https://127.0.0.1/hook"),
            ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "WEBHOOK_URL_FORBIDDEN"


# ── test-fire ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_test_fire_404_cross_tenant(session):
    org_a = await _make_org(session, owner_address=OWNER_A)
    org_b = await _make_org(session, owner_address=OWNER_B)
    wh = MerchantWebhook(
        merchant_id=OWNER_A, environment="test", url="https://merchant.example/hooks",
        secret=secrets.token_hex(32), events=["payment.completed"], is_active=True,
    )
    session.add(wh)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await fire_test_org_webhook(
            webhook_id=wh.id, ctx=_ctx(org_b), environment="test", db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_test_fire_inactive_400(session):
    org = await _make_org(session, owner_address=OWNER_A)
    wh = MerchantWebhook(
        merchant_id=OWNER_A, environment="test", url="https://merchant.example/hooks",
        secret=secrets.token_hex(32), events=["payment.completed"], is_active=False,
    )
    session.add(wh)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await fire_test_org_webhook(
            webhook_id=wh.id, ctx=_ctx(org), environment="test", db=session,
        )
    assert exc.value.status_code == 400


# ── egress guard (E1b) — no outbound request to blocked targets ──

@pytest.mark.asyncio
async def test_send_test_event_blocks_private_host_no_request(monkeypatch):
    """send_test_event must refuse a private/loopback URL and NEVER instantiate
    an httpx client."""
    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("httpx.AsyncClient must not be called for a blocked URL")

    monkeypatch.setattr(whsvc.httpx, "AsyncClient", _Boom)
    wh = MerchantWebhook(
        merchant_id=OWNER_A, environment="test", url="https://127.0.0.1/hook",
        secret="s", events=[], is_active=True,
    )
    ok, code, msg = await send_test_event(wh)
    assert ok is False and code is None and "Blocked" in msg


@pytest.mark.asyncio
@pytest.mark.parametrize("url,reason_frag", [
    ("http://example.com/x", "scheme_not_https"),       # non-HTTPS
    ("https://127.0.0.1/x", "private_or_reserved_ip"),  # loopback literal
    ("https://10.0.0.5/x", "private_or_reserved_ip"),   # RFC1918 literal
    ("https://169.254.169.254/x", "private_or_reserved_ip"),  # cloud metadata
    ("https://[::1]/x", "private_or_reserved_ip"),      # IPv6 loopback
])
async def test_check_webhook_egress_blocks(url, reason_frag):
    reason = await check_webhook_egress(url)
    assert reason == reason_frag


@pytest.mark.asyncio
async def test_check_webhook_egress_allows_unresolvable_reserved_domain():
    """`*.example` is unresolvable → not our SSRF concern → None (allowed to try;
    the POST fails on its own). Keeps reserved test domains working."""
    assert await check_webhook_egress("https://merchant.example/hooks") is None
