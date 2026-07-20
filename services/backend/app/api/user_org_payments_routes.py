"""Phase C/D — session-authed (JWT) org payments: read (C) + create/cancel (D).

The `/app` dashboard reads AND creates a merchant's payment intents here, scoped
by the logged-in user's ACTIVE ORG — the browser/session counterpart of the
API-key merchant API, authed differently:

    session JWT → require_org_approved(...) (wraps require_org_role +
    the staged-onboarding gate: 403 company_profile_required until the org's
    company profile is submitted) → active org_id (server-derived, never
    client-supplied) → _resolve_owner_address(org_id) → owner address
    == PaymentIntent.merchant_id

Reads require `viewer`; create/cancel require `operator`. Create goes through the
SAME single construction site as the API-key path (`intent_service.create_intent`),
so Phase B's recipient gate applies uniformly. Routes live under the
`/api/v1/user/` prefix, which is JWT-exempt from the API-key middleware
(app/security/api_keys.py EXEMPT_PATHS) — no change to the auth perimeter.

Environment: `environment` defaults to "test". The `/app` UI never sends it and
shows no test/live toggle (mainnet routers aren't deployed; live intents are
unpayable). Tenant + environment isolation are enforced IN THE QUERY.
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_approved import require_org_approved
from app.api.merchant_profile_routes import _resolve_owner_address
from app.api.merchant_routes import _intent_to_response
from app.db.session import get_db
from app.models.merchant_models import (
    CreatePaymentIntentRequest,
    IntentStatus,
    MerchantTransactionListResponse,
    PaymentIntent,
    PaymentIntentResponse,
)
from app.models.org_models import Organization
from app.services.audit_service import log_event
from app.services.chain_access import (
    CHAIN_ID_BY_NAME,
    ChainAccessError,
    check_org_chain_access,
)
from app.services.intent_service import create_intent, has_settlement_hold, list_org_intents

router = APIRouter(prefix="/api/v1/user/org", tags=["user-org-payments"])


@router.get("/payment-intents", response_model=MerchantTransactionListResponse)
async def list_org_payment_intents(
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    environment: Literal["test", "live"] = Query("test"),
    status: Optional[str] = Query(
        None, description="pending, completed, expired, cancelled, review, refunded, partial, overpaid"
    ),
    currency: Optional[str] = Query(None, description="USDC, ETH, …"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> MerchantTransactionListResponse:
    """List the active org's payment intents, most-recent-first, paginated.

    Scoped to the org's owner address AND `environment` in the SQL. `viewer`+
    may read. 409 `no_primary_wallet` if the org has no primary EVM wallet
    linked yet. An unknown `status` → 400 INVALID_STATUS; an unknown
    `environment` → 422 (FastAPI Literal validation).
    """
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)
    return await list_org_intents(
        db,
        owner,
        environment,
        status=status,
        currency=currency,
        page=page,
        per_page=per_page,
    )


@router.post("/payment-intents", response_model=PaymentIntentResponse)
async def create_org_payment_intent(
    payload: CreatePaymentIntentRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("operator")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """Create a payment intent (invoice) for the active org — session path.

    `operator`+ (viewers cannot create). merchant_id is the org's owner address,
    so the intent lands in this org's read scope (the /app list). Goes through the
    SAME construction site as the API-key path (`intent_service.create_intent`):
    the recipient gate resolves the org's settlement_wallet or a per-intent
    override, else fail-closed **422 SETTLEMENT_WALLET_MISSING**. `environment`
    defaults to test; the UI never sends it. 409 `no_primary_wallet` if the org
    has no primary EVM wallet.
    """
    _user_id, org_id, _role = ctx

    # Central chain guard (defense in depth on top of the route gate): testnet
    # chains need 'company_submitted'; mainnet chains additionally need
    # activation_status == 'active' — which nothing sets in-app yet, so mainnet
    # is uniformly denied here. Unknown chain names fall through to
    # create_intent's existing 422 UNSUPPORTED_CHAIN.
    requested_chain = (payload.chain or "base").lower()
    chain_id = CHAIN_ID_BY_NAME.get(requested_chain)
    if chain_id is not None:
        org = (
            await db.execute(
                select(Organization).where(Organization.id == org_id)
            )
        ).scalar_one()
        try:
            check_org_chain_access(
                org.onboarding_status, org.activation_status, chain_id
            )
        except ChainAccessError as e:
            raise HTTPException(status_code=403, detail={"code": e.code})

    owner = await _resolve_owner_address(db, org_id)
    intent = await create_intent(
        db, owner, environment, payload, org_id=org_id, key_id=None
    )
    return await _intent_to_response(intent)


@router.post(
    "/payment-intents/{intent_id}/cancel", response_model=PaymentIntentResponse
)
async def cancel_org_payment_intent(
    intent_id: str,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("operator")),
    environment: Literal["test", "live"] = Query("test"),
    db: AsyncSession = Depends(get_db),
) -> PaymentIntentResponse:
    """Cancel a pending intent for the active org — session path.

    `operator`+. Scoped by (intent_id, owner, environment) IN the query → **404**
    on miss/cross-tenant (the merchant-resource 404-not-403 rule). Only `pending`
    intents cancel → `cancelled` (400 otherwise). Mirrors the API-key cancel
    semantics inline; does not touch that handler.
    """
    _user_id, org_id, _role = ctx
    owner = await _resolve_owner_address(db, org_id)

    intent = (
        await db.execute(
            select(PaymentIntent).where(
                and_(
                    PaymentIntent.intent_id == intent_id,
                    PaymentIntent.merchant_id == owner,
                    PaymentIntent.environment == environment,
                )
            )
        )
    ).scalar_one_or_none()

    if intent is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "INTENT_NOT_FOUND",
                "message": f"Payment intent '{intent_id}' not found",
            },
        )
    if intent.status != IntentStatus.pending:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_STATE",
                "message": (
                    f"Cannot cancel intent in '{intent.status.value}' state. "
                    "Only 'pending' intents can be cancelled."
                ),
            },
        )

    # F-5: an observed on-chain payment (pending/final settlement) wins over
    # cancel — same guard as the expiry writers. rejected/reorged do NOT hold.
    if await has_settlement_hold(db, intent.intent_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "SETTLEMENT_IN_FLIGHT",
                "message": "An on-chain payment for this intent has been observed; it can no longer be cancelled.",
            },
        )

    intent.status = IntentStatus.cancelled
    await log_event(
        db,
        "INTENT_CANCELLED",
        "payment_intent",
        intent.intent_id,
        actor_type="user",
        actor_id=_user_id,
        changes={
            "previous_status": "pending",
            "new_status": "cancelled",
            "org_id": org_id,
        },
    )
    await db.commit()
    return await _intent_to_response(intent)
