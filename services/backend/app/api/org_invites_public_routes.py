"""Invite preview + accept + decline — auth required, no membership.

These endpoints complement `organizations_routes.py`: they're the
counterparty side of the invite flow. The user is authenticated via the
standard Bearer session token, but they have NO membership in the target
org yet — the point of accepting is to create one.

Security
--------
- Preview does not mutate state, so leaking the URL to a logged-in attacker
  only reveals the org name/role (already implied by the invitation itself).
  The accept path enforces `user.email == invite.email`.
- All three endpoints require authentication: an unauthenticated user must
  first sign in with the correct Google account before accepting.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User
from app.models.org_schemas import (
    InviteAcceptResponse,
    InvitePreviewResponse,
)
from app.services.auth_service import AuthError, verify_access_token
from app.services.org_invite_service import (
    accept_invite,
    decline_invite,
    preview_invite,
)
from app.services.org_service import OrgError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


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


def _invite_error_to_http(e: OrgError) -> HTTPException:
    code = e.code
    if code == "invite_not_found":
        return HTTPException(status_code=404, detail={"code": code})
    return HTTPException(status_code=400, detail={"code": code})


@router.get("/{token}/preview", response_model=InvitePreviewResponse)
async def preview(
    token: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one()
    try:
        data = await preview_invite(db, token, user)
    except OrgError as e:
        raise _invite_error_to_http(e)
    return InvitePreviewResponse(
        org_name=data["org_name"],
        role=data["role"],
        invite_email=data["invite_email"],
        status=data["status"],
        email_matches=data["email_matches"],
        user_email=data["user_email"],
        expires_at=data["expires_at"],
    )


@router.post("/{token}/accept", response_model=InviteAcceptResponse)
async def accept(
    token: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one()
    try:
        mem = await accept_invite(db, token, user)
    except OrgError as e:
        await db.commit()
        raise _invite_error_to_http(e)
    await db.commit()
    return InviteAcceptResponse(org_id=mem.org_id, role=mem.role)


@router.post("/{token}/decline", status_code=204)
async def decline(
    token: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one()
    try:
        await decline_invite(db, token, user)
    except OrgError as e:
        raise _invite_error_to_http(e)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
