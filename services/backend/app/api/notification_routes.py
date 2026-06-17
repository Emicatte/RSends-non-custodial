"""User notification preferences (GET/PATCH).

GET lazily creates the default row on first access so the UI never has to
deal with a missing-preferences 404. PATCH applies the partial update and
bumps updated_at.

Known-devices list/revoke is intentionally deferred to the Security pane
(Prompt 8) — rows are written by the celery email task today.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.notification_models import NotificationPreference
from app.models.notification_schemas import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
)
from app.services.auth_service import AuthError, verify_access_token

router = APIRouter(prefix="/api/v1/user/notifications", tags=["notifications"])


async def require_user_id(request: Request) -> str:
    """Extract authenticated user_id from Bearer access token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "no_token"})
    token = auth[7:]
    try:
        claims = await verify_access_token(token)
    except AuthError as e:
        code = 503 if e.code == "auth_unavailable" else 401
        raise HTTPException(status_code=code, detail={"code": e.code})
    return claims["sub"]


async def _get_or_create(
    db: AsyncSession, user_id: str
) -> NotificationPreference:
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


@router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_preferences(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    pref = await _get_or_create(db, user_id)
    await db.commit()
    await db.refresh(pref)
    return NotificationPreferencesResponse.model_validate(pref)


@router.patch("/preferences", response_model=NotificationPreferencesResponse)
async def update_preferences(
    payload: NotificationPreferencesUpdate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    pref = await _get_or_create(db, user_id)
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(pref, k, v)
    pref.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(pref)
    return NotificationPreferencesResponse.model_validate(pref)
