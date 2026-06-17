"""CRUD for user API keys. Protected by user session (NOT by API keys themselves).

Management endpoints: a user's session token creates/lists/revokes API keys
that belong to the user's **active organization** (Prompt 11). All members of
the org see the same keys; RBAC gates who can create / revoke.

RBAC (Prompt 11):
    list / available-scopes  → viewer+
    create / patch label     → operator+
    revoke                   → admin only

Error shape: HTTPException(detail={"code": "..."}) matches sibling user_*
routes. apiCall on the frontend reads detail.code into Error.message.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.auth_models import User
from app.models.user_api_keys_models import UserApiKey
from app.models.user_api_keys_schemas import (
    ALL_AVAILABLE_SCOPES,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyListResponse,
    ApiKeyPatchRequest,
    AvailableScopesResponse,
)
from app.services.auth_audit import record_auth_event
from app.services.user_api_key_service import (
    MAX_KEYS_PER_ORG,
    count_active_keys_for_org,
    create_key,
    revoke_key,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user/api-keys", tags=["user-api-keys"])


def _hydrate_item(row: UserApiKey, created_by_email: Optional[str]) -> ApiKeyListItem:
    """Build an `ApiKeyListItem` with the resolved creator email (if any)."""
    item = ApiKeyListItem.model_validate(row)
    item.created_by_email = created_by_email
    return item


@router.get("/available-scopes", response_model=AvailableScopesResponse)
async def list_available_scopes(
    _ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
):
    """Frontend uses this to render the scope checkbox grid in the create modal."""
    return AvailableScopesResponse(scopes=list(ALL_AVAILABLE_SCOPES))


@router.get("", response_model=ApiKeyListResponse)
async def list_keys(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx

    # LEFT JOIN users so viewers see "Added by {email}" when the creator
    # isn't them (purely for UI; auditing is in auth_audit_log).
    result = await db.execute(
        select(UserApiKey, User.email)
        .select_from(UserApiKey)
        .outerjoin(User, User.id == UserApiKey.created_by_user_id)
        .where(UserApiKey.org_id == org_id)
        .order_by(desc(UserApiKey.created_at))
    )
    rows = list(result.all())

    items = [_hydrate_item(r[0], r[1]) for r in rows]
    active_count = sum(
        1 for r in rows if r[0].is_active and r[0].revoked_at is None
    )
    return ApiKeyListResponse(
        keys=items,
        max_allowed=MAX_KEYS_PER_ORG,
        remaining_slots=max(0, MAX_KEYS_PER_ORG - active_count),
    )


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create(
    payload: ApiKeyCreateRequest,
    request: Request,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    user_id, org_id, _role = ctx
    try:
        row, plaintext = await create_key(
            db, user_id, org_id, payload.label, payload.scopes
        )
    except ValueError as e:
        code = str(e)
        if code == "max_keys_reached":
            raise HTTPException(
                status_code=409,
                detail={"code": "max_keys_reached", "max": MAX_KEYS_PER_ORG},
            )
        raise HTTPException(status_code=400, detail={"code": code})

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    await record_auth_event(
        event_type="api_key_created",
        user_id=user_id,
        ip_address=ip,
        user_agent=ua,
        details={
            "key_id": str(row.id),
            "org_id": str(org_id),
            "label": row.label,
            "scopes": list(row.scopes or []),
        },
    )

    await db.commit()
    await db.refresh(row)

    return ApiKeyCreateResponse(
        id=str(row.id),
        label=row.label,
        scopes=list(row.scopes or []),
        plaintext_key=plaintext,
        display_prefix=row.display_prefix,
        created_at=row.created_at,
    )


@router.patch("/{key_id}", response_model=ApiKeyListItem)
async def update_label(
    key_id: str,
    payload: ApiKeyPatchRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    _user_id, org_id, _role = ctx
    result = await db.execute(
        select(UserApiKey, User.email)
        .select_from(UserApiKey)
        .outerjoin(User, User.id == UserApiKey.created_by_user_id)
        .where(
            UserApiKey.id == key_id,
            UserApiKey.org_id == org_id,
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    key, created_by_email = row

    if payload.label is not None:
        key.label = payload.label[:100]

    key.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(key)
    return _hydrate_item(key, created_by_email)


@router.delete("/{key_id}", status_code=204)
async def revoke(
    key_id: str,
    request: Request,
    ctx: Tuple[str, str, str] = Depends(require_org_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-revoke: `is_active=False` + `revoked_at=now()`. Idempotent."""
    user_id, org_id, _role = ctx
    try:
        key = await revoke_key(db, org_id, key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    await record_auth_event(
        event_type="api_key_revoked",
        user_id=user_id,
        ip_address=ip,
        user_agent=ua,
        details={
            "key_id": str(key.id),
            "org_id": str(org_id),
            "label": key.label,
        },
    )

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
