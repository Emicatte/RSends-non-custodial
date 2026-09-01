"""Phase E — session-authed (JWT) org webhook management + health.

Browser/session counterpart of the API-key `POST /merchant/webhook/*` +
webhook reads. Authed by the logged-in user's ACTIVE ORG (never a client-supplied
id), mirroring Phase C/D:

    session JWT → require_org_approved(...) → active org_id → _resolve_owner_address
    (org_id) → owner address == MerchantWebhook.merchant_id

Routes live under `/api/v1/user/` (JWT-exempt from the API-key middleware —
EXEMPT_PATHS), so the auth perimeter is untouched. Tenant + environment
isolation are enforced IN THE QUERY; cross-tenant / cross-env / missing → 404.

- GET  /webhooks                     (viewer)  — list, never returns `secret`
- GET  /webhooks/{id}/deliveries     (viewer)  — health rows, no payload/body
- POST /webhooks                     (operator)— register (shared core → SSRF guard)
- POST /webhooks/{id}/test           (operator)— test-fire (shared, egress-guarded)

Environment defaults to "test"; the `/app` UI is hard-locked to test and never
sends the param. Register/test reuse the SAME service logic as the API-key
routes (`create_merchant_webhook` / `send_test_event`) — no divergent path.
"""

from __future__ import annotations

from typing import Literal, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_approved import require_org_approved
from app.api.merchant_profile_routes import _resolve_owner_address
from app.db.session import get_db
from app.models.merchant_models import (
    MerchantWebhook,
    RegisterWebhookRequest,
    RegisterWebhookResponse,
    TestWebhookResponse,
    WebhookDeliveryItem,
    WebhookDeliveryListResponse,
    WebhookItem,
    WebhookListResponse,
)
from app.models.merchant_models import WebhookDelivery
from app.services.audit_service import log_event
from app.services.webhook_service import (
    WebhookEgressError,
    create_merchant_webhook,
    send_test_event,
)

router = APIRouter(prefix="/api/v1/user/org", tags=["user-org-webhooks"])


def _iso(dt) -> str:
    return dt.isoformat() if dt is not None else ""


def _webhook_item(w: MerchantWebhook) -> WebhookItem:
    """One endpoint as the list/enable response shape. `disabled_at` stays None
    rather than `_iso`'s empty string: "never disabled" is an absence, and the
    card must not have to distinguish "" from a date."""
    return WebhookItem(
        webhook_id=w.id,
        url=w.url,
        events=list(w.events or []),
        is_active=w.is_active,
        created_at=_iso(w.created_at),
        disabled_reason=w.disabled_reason,
        disabled_at=w.disabled_at.isoformat() if w.disabled_at else None,
    )


async def _owned_webhook(
    db: AsyncSession, webhook_id: int, owner: str, environment: str
) -> MerchantWebhook | None:
    """Fetch a webhook scoped to (id, owner, env) IN THE QUERY — the tenant +
    environment filter is the SQL, not a post-fetch check. None → the route 404s
    (cross-tenant / cross-env / missing are indistinguishable to the caller)."""
    result = await db.execute(
        select(MerchantWebhook).where(
            and_(
                MerchantWebhook.id == webhook_id,
                MerchantWebhook.merchant_id == owner,
                MerchantWebhook.environment == environment,
            )
        )
    )
    return result.scalar_one_or_none()


@router.get("/webhooks", response_model=WebhookListResponse)
async def list_org_webhooks(
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> WebhookListResponse:
    """List the active org's registered webhooks. Scoped to owner + environment
    in the SQL. `secret` is never included (register-time one-shot only)."""
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    result = await db.execute(
        select(MerchantWebhook)
        .where(
            and_(
                MerchantWebhook.merchant_id == owner,
                MerchantWebhook.environment == environment,
            )
        )
        .order_by(MerchantWebhook.created_at.desc(), MerchantWebhook.id.desc())
    )
    rows = result.scalars().all()
    records = [_webhook_item(w) for w in rows]
    return WebhookListResponse(total=len(records), records=records)


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=WebhookDeliveryListResponse,
)
async def list_org_webhook_deliveries(
    webhook_id: int,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    environment: Literal["test", "live"] = Query("test"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> WebhookDeliveryListResponse:
    """Paginated delivery health for one endpoint. The webhook is resolved with
    the owner+env filter FIRST → 404 when the join is empty (cross-tenant /
    cross-env / missing). Rows exclude `payload`/`response_body` (OQ-E2)."""
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    webhook = await _owned_webhook(db, webhook_id, owner, environment)
    if webhook is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "WEBHOOK_NOT_FOUND", "message": "Webhook not found"},
        )

    total = int(
        (
            await db.execute(
                select(func.count(WebhookDelivery.id)).where(
                    WebhookDelivery.webhook_id == webhook.id
                )
            )
        ).scalar()
        or 0
    )

    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook.id)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    records = [
        WebhookDeliveryItem(
            id=d.id,
            event_type=d.event_type,
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            response_code=d.response_code,
            retries=d.retries,
            next_retry_at=_iso(d.next_retry_at) if d.next_retry_at else None,
            created_at=_iso(d.created_at),
            delivered_at=_iso(d.delivered_at) if d.delivered_at else None,
        )
        for d in result.scalars().all()
    ]
    return WebhookDeliveryListResponse(
        total=total, page=page, per_page=per_page, records=records
    )


@router.post("/webhooks", response_model=RegisterWebhookResponse)
async def register_org_webhook(
    payload: RegisterWebhookRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("operator")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> RegisterWebhookResponse:
    """Register a webhook for the active org. `operator`+ only. Goes through the
    SAME `create_merchant_webhook` as the API-key path (SSRF egress guard + env
    stamp); `secret` is returned exactly once here."""
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    try:
        webhook = await create_merchant_webhook(
            db,
            merchant_id=owner,
            environment=environment,
            url=payload.url,
            events=payload.events,
        )
    except WebhookEgressError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "WEBHOOK_URL_FORBIDDEN",
                "message": f"Webhook URL is not an allowed target ({exc.reason})",
            },
        )

    await log_event(
        db,
        "WEBHOOK_REGISTERED",
        "merchant_webhook",
        str(webhook.id),
        actor_type="user",
        actor_id=org_id,
        changes={"url": payload.url, "events": payload.events},
    )
    await db.commit()

    return RegisterWebhookResponse(
        webhook_id=webhook.id,
        url=webhook.url,
        secret=webhook.secret,
        events=webhook.events,
        is_active=webhook.is_active,
    )


@router.post("/webhooks/{webhook_id}/test", response_model=TestWebhookResponse)
async def test_org_webhook(
    webhook_id: int,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("operator")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> TestWebhookResponse:
    """Fire a test event to the endpoint. `operator`+ only. Scoped (id, owner,
    env) → 404 on miss, 400 if inactive. Uses the shared `send_test_event`,
    which egress-guards the outbound POST."""
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    webhook = await _owned_webhook(db, webhook_id, owner, environment)
    if webhook is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "WEBHOOK_NOT_FOUND", "message": "Webhook not found"},
        )
    if not webhook.is_active:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "WEBHOOK_INACTIVE",
                "message": "Cannot test an inactive webhook",
            },
        )

    success, status_code, message = await send_test_event(webhook)
    return TestWebhookResponse(
        status="ok" if success else "failed",
        response_code=status_code,
        message=message,
    )


@router.post("/webhooks/{webhook_id}/enable", response_model=WebhookItem)
async def enable_org_webhook(
    webhook_id: int,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("operator")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> WebhookItem:
    """Re-enable an endpoint that auto-disable switched off. `operator`+ only.
    Scoped (id, owner, env) → 404 on miss.

    Auto-disable is only honest if the merchant can undo it, which is why this
    route exists at all: without it, three permanent failures would end a
    merchant's notifications with no in-product remedy.

    Clears ALL THREE columns — a re-enabled endpoint gets a genuinely fresh
    start, not one that disables again on its next single permanent failure.
    Idempotent: re-enabling an already-active endpoint is a no-op that returns
    the same 200.

    RATE LIMIT — deliberately shared, not its own entry. `_match_endpoint`
    (middleware/rate_limit.py) is FIRST-MATCHING-PREFIX-WINS, and `{webhook_id}`
    is a variable segment, so this path is already covered by the
    `("POST", "/api/v1/user/org/webhooks/", 10, 60, "ip")` rule that exists for
    test-fire. 10/min per IP is generous for re-enabling, and the only way to
    isolate a separate limit would be to reshape the URL (e.g.
    /webhooks/enable/{id}) — contorting the route structure around a limit that
    is not hurting. The sharing is documented here and at the rule itself.
    """
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    webhook = await _owned_webhook(db, webhook_id, owner, environment)
    if webhook is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "WEBHOOK_NOT_FOUND", "message": "Webhook not found"},
        )

    previous_reason = webhook.disabled_reason
    webhook.is_active = True
    webhook.consecutive_permanent_failures = 0
    webhook.disabled_reason = None
    webhook.disabled_at = None

    await log_event(
        db,
        "WEBHOOK_REENABLED",
        "merchant_webhook",
        str(webhook.id),
        actor_type="user",
        actor_id=org_id,
        changes={"url": webhook.url, "previous_disabled_reason": previous_reason},
    )
    await db.commit()

    return _webhook_item(webhook)
