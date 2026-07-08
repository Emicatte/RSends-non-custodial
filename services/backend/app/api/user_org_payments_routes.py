"""Phase C — session-authed (JWT) org payments read view.

The `/app` dashboard reads a merchant's payment intents here, scoped by the
logged-in user's ACTIVE ORG. This is the browser/session counterpart of the
API-key `GET /api/v1/merchant/transactions` path — identical query logic
(`intent_service.list_org_intents`), authed differently:

    session JWT → require_org_role("viewer") → active org_id (server-derived,
    never client-supplied) → _resolve_owner_address(org_id) → owner address
    == PaymentIntent.merchant_id

Routes live under the `/api/v1/user/` prefix, which is JWT-exempt from the
API-key middleware (app/security/api_keys.py EXEMPT_PATHS) — so this adds no
change to the auth perimeter.

Environment: `environment` defaults to "test". The `/app` UI never sends it and
shows no test/live toggle (mainnet routers aren't deployed; live intents are
unpayable), so the param exists only for future mainnet-readiness. Tenant +
environment isolation are enforced IN THE QUERY. Read-only.
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.api.merchant_profile_routes import _resolve_owner_address
from app.db.session import get_db
from app.models.merchant_models import MerchantTransactionListResponse
from app.services.intent_service import list_org_intents

router = APIRouter(prefix="/api/v1/user/org", tags=["user-org-payments"])


@router.get("/payment-intents", response_model=MerchantTransactionListResponse)
async def list_org_payment_intents(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
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
