"""Admin approval surface + Telegram notification at KYB submit.

- /admin/approvals routes are gated by the EXISTING require_admin
  (X-Admin-Token) dependency — no second auth system.
- Approve/decline are operator decisions: allowed only from
  'pending_approval' (409 already_decided otherwise), stamp the decision
  metadata, and write APPROVAL_GRANTED / APPROVAL_DECLINED audit events.
- The Telegram message fires at company-profile SUBMIT (full profile in the
  message) and is a CONVENIENCE: submit must succeed when Telegram raises,
  and the admin list reads the DB — a lost message never strands a merchant.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Membership, Organization
from app.models.audit_models import LedgerAuditLog


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


async def _make_pending_org(session, *, submitted=True, legal_name="Acme Srl"):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="merchant",
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=True,
        plan="free",
        onboarding_status="company_submitted" if submitted else "created",
        approval_status="pending_approval",
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    if submitted:
        from app.services.onboarding_service import upsert_company_profile_draft

        await upsert_company_profile_draft(
            session,
            str(org.id),
            {
                "legal_name": legal_name,
                "country": "IT",
                "registration_number": "REG123",
                "tax_or_vat_number": "IT0001",
                "business_category": "saas",
                "expected_monthly_volume": "lt_10k",
                "countries_served": ["IT"],
                "primary_stablecoin": "USDC",
                "no_sanctioned_countries": True,
                "no_prohibited_activities": True,
                "has_pep": False,
            },
        )
    await session.commit()
    return user, org


# ── Wiring: require_admin on every /admin/approvals route ─────────


def _route_dep_names(app, method: str, path: str) -> set[str]:
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            names = set()

            def _walk(dependant):
                for sub in dependant.dependencies:
                    if sub.call is not None:
                        names.add(getattr(sub.call, "__qualname__", ""))
                    _walk(sub)

            _walk(route.dependant)
            return names
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin/approvals"),
        ("POST", "/admin/approvals/{org_id}/approve"),
        ("POST", "/admin/approvals/{org_id}/decline"),
    ],
)
def test_admin_approval_routes_require_admin(method, path):
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert any("require_admin" in n for n in names), (
        f"{method} {path} must be gated by the existing require_admin"
    )


def test_admin_approvals_rate_limited():
    from app.middleware.rate_limit import ENDPOINT_LIMITS

    paths = {p for _m, p, _x, _w, _k in ENDPOINT_LIMITS}
    assert any(p.startswith("/admin/approvals") for p in paths)


# ── List pending ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_only_pending_with_profile(session):
    from app.api.admin_approval_routes import list_pending_approvals

    _u, pending = await _make_pending_org(session, legal_name="Pending Srl")
    _u2, approved = await _make_pending_org(session, legal_name="Done Srl")
    approved.approval_status = "approved"
    await session.commit()

    rows = await list_pending_approvals(db=session)
    ids = {r.org_id for r in rows}
    assert str(pending.id) in ids
    assert str(approved.id) not in ids
    row = next(r for r in rows if r.org_id == str(pending.id))
    assert row.company_profile["legal_name"] == "Pending Srl"
    assert row.company_profile["business_category"] == "saas"


# ── Approve / decline ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_flips_org_and_audits(session):
    from app.api.admin_approval_routes import approve_org

    _u, org = await _make_pending_org(session)
    resp = await approve_org(org_id=str(org.id), db=session)
    assert resp.approval_status == "approved"

    await session.refresh(org)
    assert org.approval_status == "approved"
    assert org.approval_decided_at is not None
    assert org.approval_decided_by == "admin"
    assert org.decline_reason is None

    audit = (
        await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "APPROVAL_GRANTED"
            )
        )
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].entity_id == str(org.id)


@pytest.mark.asyncio
async def test_decline_sets_reason_and_audits(session):
    from app.api.admin_approval_routes import decline_org
    from app.models.admin_approval_schemas import DeclineRequest

    _u, org = await _make_pending_org(session)
    resp = await decline_org(
        org_id=str(org.id),
        payload=DeclineRequest(reason="prohibited category"),
        db=session,
    )
    assert resp.approval_status == "declined"

    await session.refresh(org)
    assert org.approval_status == "declined"
    assert org.decline_reason == "prohibited category"
    assert org.approval_decided_at is not None

    audit = (
        await session.execute(
            select(LedgerAuditLog).where(
                LedgerAuditLog.event_type == "APPROVAL_DECLINED"
            )
        )
    ).scalars().all()
    assert len(audit) == 1


@pytest.mark.asyncio
async def test_decline_unknown_org_is_404(session):
    from app.api.admin_approval_routes import decline_org
    from app.models.admin_approval_schemas import DeclineRequest

    with pytest.raises(HTTPException) as exc:
        await decline_org(
            org_id=str(uuid4()),
            payload=DeclineRequest(reason="x"),
            db=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_decision_only_from_pending(session):
    from app.api.admin_approval_routes import approve_org

    _u, org = await _make_pending_org(session)
    org.approval_status = "declined"
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await approve_org(org_id=str(org.id), db=session)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "already_decided"


def test_decline_reason_is_bounded():
    from pydantic import ValidationError

    from app.models.admin_approval_schemas import DeclineRequest

    with pytest.raises(ValidationError):
        DeclineRequest(reason="x" * 5000)
    with pytest.raises(ValidationError):
        DeclineRequest(reason="")


# ── Audit registry ────────────────────────────────────────────────


def test_audit_registry_knows_the_new_and_missing_types():
    from app.services.audit_service import EVENT_TYPES

    assert "APPROVAL_GRANTED" in EVENT_TYPES
    assert "APPROVAL_DECLINED" in EVENT_TYPES
    assert "INTENT_CREATED" in EVENT_TYPES  # was emitted but unregistered


# ── Telegram at KYB submit ────────────────────────────────────────


def _telegram_configured(monkeypatch):
    from types import SimpleNamespace

    from app.services import approval_notify

    monkeypatch.setattr(
        approval_notify,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="tg-token",
            telegram_approvals_chat_id="-100123",
            telegram_chat_id="",
            app_url="https://demo.rsends.io",
        ),
    )


@pytest.mark.asyncio
async def test_submit_fires_telegram_with_profile_and_link(session, monkeypatch):
    from app.api.user_onboarding_routes import submit_org_company_profile
    from app.services import approval_notify

    _telegram_configured(monkeypatch)
    captured = {}

    async def _capture(message, chat_id=None):
        captured["message"] = message
        return True

    monkeypatch.setattr(approval_notify, "send_telegram_alert", _capture)

    _u, org = await _make_pending_org(session, submitted=True)
    org.onboarding_status = "created"  # allow the submit transition
    await session.commit()

    await submit_org_company_profile(ctx=("u", str(org.id), "admin"), db=session)

    assert "Acme Srl" in captured["message"]
    assert "/admin/approvals" in captured["message"]


@pytest.mark.asyncio
async def test_submit_succeeds_when_telegram_raises(session, monkeypatch):
    from app.api.user_onboarding_routes import submit_org_company_profile
    from app.services import approval_notify

    _telegram_configured(monkeypatch)

    async def _boom(message, chat_id=None):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(approval_notify, "send_telegram_alert", _boom)

    _u, org = await _make_pending_org(session, submitted=True)
    org.onboarding_status = "created"
    await session.commit()

    resp = await submit_org_company_profile(
        ctx=("u", str(org.id), "admin"), db=session
    )
    assert resp.submitted_at is not None

    await session.refresh(org)
    assert org.onboarding_status == "company_submitted"
