"""Security / account settings endpoints — `/api/v1/user/account`.

Covers the three surfaces rendered by `SecuritySettings.tsx`:
- Active sessions (list / revoke one / revoke all others)
- Known devices (list / forget one)
- Account status + GDPR delete request / cancel

The `sid` claim from the access-token JWT marks the caller's current session —
used to (a) flag `is_current=True` in the session list and (b) block the user
from revoking themselves (they'd immediately be logged out with no way to log
back in gracefully). Current-session sign-out is the logout flow, not this one.

Error shape matches the rest of /api/v1/user/* — HTTPException with
`detail={"code": "..."}` — the frontend's `apiCall` reads `detail.code`.

Hard-delete itself is NOT a user-callable endpoint. `POST /delete` only
schedules deletion (writes `deletion_scheduled_for`); the daily Celery beat
task `tasks.run_scheduled_deletions` performs the irreversible purge after the
grace period.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User, UserSession
from app.models.notification_models import KnownDevice
from app.models.user_account_schemas import (
    AccountStatusResponse,
    ActiveSessionResponse,
    ActiveSessionsListResponse,
    DeleteAccountRequest,
    KnownDeviceResponse,
    KnownDevicesListResponse,
    RevokeAllResponse,
    RevokeSessionResponse,
)
from app.services.account_deletion_service import (
    REQUIRED_CONFIRMATION,
    DeletionError,
    cancel_deletion,
    request_deletion,
)
from app.services.auth_audit import record_auth_event
from app.services.auth_service import (
    SESSION_REDIS_PREFIX,
    AuthError,
    verify_access_token,
)
from app.services.cache_service import get_redis

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user/account", tags=["user-account"])


# ─── Auth dependencies ───────────────────────────────────────────────
#
# Two variants: the session-management endpoints need the caller's current
# `sid` to mark it (and to refuse self-revocation); the rest only need the
# user_id. Both raise matching HTTPExceptions on bad/missing tokens.


async def require_user_id(request: Request) -> str:
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


async def require_user_and_sid(request: Request) -> tuple[str, Optional[str]]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "no_token"})
    token = auth[7:]
    try:
        claims = await verify_access_token(token)
    except AuthError as e:
        code = 503 if e.code == "auth_unavailable" else 401
        raise HTTPException(status_code=code, detail={"code": e.code})
    return claims["sub"], claims.get("sid")


# ─── Helpers ─────────────────────────────────────────────────────────


def _days_until(scheduled_for: Optional[datetime]) -> Optional[int]:
    """Ceil-days until hard-delete. Clamped to 0 when cutoff is in the past."""
    if scheduled_for is None:
        return None
    delta = scheduled_for - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return 0
    # Ceiling division: 1 remaining hour should render as "1 day", not "0".
    return (secs + 86399) // 86400


def _status_payload(user: User) -> AccountStatusResponse:
    return AccountStatusResponse(
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        deletion_requested_at=user.deletion_requested_at,
        deletion_scheduled_for=user.deletion_scheduled_for,
        deletion_reason=user.deletion_reason,
        days_until_deletion=_days_until(user.deletion_scheduled_for),
    )


async def _redis_delete_session(session_id: str) -> None:
    """Best-effort removal of `auth:session:{sid}`. DB is authoritative."""
    try:
        r = await get_redis()
        if r is None:
            return
        await r.delete(f"{SESSION_REDIS_PREFIX}{session_id}")
    except Exception:
        log.exception(
            "redis_session_delete_failed",
            extra={"sid_prefix": (session_id or "")[:8]},
        )


# ─── Status ──────────────────────────────────────────────────────────


@router.get("/status", response_model=AccountStatusResponse)
async def get_status(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> AccountStatusResponse:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "user_not_found"})
    return _status_payload(user)


# ─── Sessions ────────────────────────────────────────────────────────


@router.get("/sessions", response_model=ActiveSessionsListResponse)
async def list_sessions(
    ctx: tuple[str, Optional[str]] = Depends(require_user_and_sid),
    db: AsyncSession = Depends(get_db),
) -> ActiveSessionsListResponse:
    user_id, current_sid = ctx
    rows = (
        await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
            .order_by(
                UserSession.last_used_at.desc().nullslast(),
                UserSession.created_at.desc(),
            )
        )
    ).scalars().all()

    sessions = [
        ActiveSessionResponse(
            session_id=str(s.session_id),
            created_at=s.created_at,
            last_activity_at=s.last_used_at,
            ip_address=str(s.ip_address) if s.ip_address is not None else None,
            user_agent_snippet=(s.user_agent or "")[:120] or None,
            is_current=(current_sid is not None and str(s.session_id) == current_sid),
        )
        for s in rows
    ]
    return ActiveSessionsListResponse(sessions=sessions)


@router.delete("/sessions/{session_id}", response_model=RevokeSessionResponse)
async def revoke_session(
    session_id: str,
    ctx: tuple[str, Optional[str]] = Depends(require_user_and_sid),
    db: AsyncSession = Depends(get_db),
) -> RevokeSessionResponse:
    user_id, current_sid = ctx

    if current_sid is not None and session_id == current_sid:
        raise HTTPException(
            status_code=400,
            detail={"code": "cannot_revoke_current_session"},
        )

    sess = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.session_id == session_id,
                UserSession.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    now = datetime.now(timezone.utc)
    sess.revoked_at = now
    sess.revoked_reason = "user_requested"
    await db.commit()

    await _redis_delete_session(session_id)
    await record_auth_event(
        event_type="session_revoked_by_user",
        user_id=user_id,
        session_id=session_id,
        details={"reason": "user_requested"},
    )
    return RevokeSessionResponse(revoked=True, session_id=session_id)


@router.post("/sessions/revoke-all", response_model=RevokeAllResponse)
async def revoke_all_other_sessions(
    ctx: tuple[str, Optional[str]] = Depends(require_user_and_sid),
    db: AsyncSession = Depends(get_db),
) -> RevokeAllResponse:
    user_id, current_sid = ctx
    now = datetime.now(timezone.utc)

    target_rows = (
        await db.execute(
            select(UserSession.session_id).where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.session_id != (current_sid or ""),
            )
        )
    ).all()
    sids = [str(r[0]) for r in target_rows]

    if not sids:
        await record_auth_event(
            event_type="all_other_sessions_revoked",
            user_id=user_id,
            session_id=current_sid,
            details={"count": 0},
        )
        return RevokeAllResponse(revoked_count=0)

    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.session_id != (current_sid or ""),
        )
        .values(revoked_at=now, revoked_reason="user_requested_all")
    )
    await db.commit()

    for sid in sids:
        await _redis_delete_session(sid)

    await record_auth_event(
        event_type="all_other_sessions_revoked",
        user_id=user_id,
        session_id=current_sid,
        details={"count": len(sids)},
    )
    return RevokeAllResponse(revoked_count=len(sids))


# ─── Known devices ───────────────────────────────────────────────────


@router.get("/known-devices", response_model=KnownDevicesListResponse)
async def list_known_devices(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> KnownDevicesListResponse:
    rows = (
        await db.execute(
            select(KnownDevice)
            .where(KnownDevice.user_id == user_id)
            .order_by(KnownDevice.last_seen_at.desc())
        )
    ).scalars().all()
    return KnownDevicesListResponse(
        devices=[KnownDeviceResponse.model_validate(d) for d in rows]
    )


@router.delete("/known-devices/{device_id}", status_code=204)
async def forget_known_device(
    device_id: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    device = (
        await db.execute(
            select(KnownDevice).where(
                KnownDevice.id == device_id,
                KnownDevice.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    await db.delete(device)
    await db.commit()

    await record_auth_event(
        event_type="known_device_forgotten",
        user_id=user_id,
        details={"device_id": device_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── GDPR deletion request / cancel ──────────────────────────────────


@router.post("/delete", response_model=AccountStatusResponse)
async def request_account_deletion(
    body: DeleteAccountRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> AccountStatusResponse:
    if (body.confirmation or "").strip() != REQUIRED_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_confirmation",
                "required": REQUIRED_CONFIRMATION,
            },
        )
    try:
        user = await request_deletion(db, user_id, reason=body.reason)
    except DeletionError as e:
        raise HTTPException(status_code=404, detail={"code": e.code})
    return _status_payload(user)


@router.post("/delete/cancel", response_model=AccountStatusResponse)
async def cancel_account_deletion(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> AccountStatusResponse:
    try:
        user = await cancel_deletion(db, user_id)
    except DeletionError as e:
        raise HTTPException(status_code=404, detail={"code": e.code})
    return _status_payload(user)
