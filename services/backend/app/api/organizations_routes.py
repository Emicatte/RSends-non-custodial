"""CRUD for organizations, memberships, and invites.

Auth: every endpoint requires a valid user session (Bearer access token).
Membership + role checks happen inside service layer via `require_role`.

Error shape: HTTPException(detail={"code": "..."}) — matches sibling
user_* routes so apiCall on the frontend reads `detail.code` into Error.message.

Out of scope: applying these endpoints as a dependency to other user-scoped
endpoints. That's Prompt 11 (api_keys + wallets → org-scope).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User
from app.models.org_models import Membership, Organization
from app.models.org_schemas import (
    ActiveOrgSwitch,
    ActiveOrgSwitchResponse,
    InviteCreateRequest,
    InviteResponse,
    InvitesListResponse,
    MembershipListResponse,
    MembershipResponse,
    MembershipRoleUpdate,
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationPatchRequest,
    OrganizationResponse,
)
from app.services.auth_service import AuthError, verify_access_token
from app.services.org_invite_service import (
    create_invite,
    list_invites,
    revoke_invite,
)
from app.services.org_service import (
    MAX_MEMBERS_PER_ORG,
    OrgError,
    create_org,
    get_user_orgs,
    remove_member,
    require_role,
    set_active_org,
    update_member_role,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


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


def _org_error_to_http(e: OrgError) -> HTTPException:
    """Translate service-level error codes to HTTP status."""
    code = e.code
    if code == "not_a_member":
        return HTTPException(status_code=403, detail={"code": code})
    if code == "insufficient_role":
        return HTTPException(status_code=403, detail={"code": code})
    if code == "not_found":
        return HTTPException(status_code=404, detail={"code": code})
    if code in (
        "already_member",
        "invite_already_pending",
        "max_members_reached",
    ):
        return HTTPException(status_code=409, detail={"code": code})
    return HTTPException(status_code=400, detail={"code": code})


# ═══ List / create orgs ═══════════════════════════════════════════

@router.get("", response_model=OrganizationListResponse)
async def list_my_orgs(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    entries = await get_user_orgs(db, user_id)

    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one()

    items: list[OrganizationResponse] = []
    for entry in entries:
        org = entry["org"]
        items.append(
            OrganizationResponse(
                id=org.id,
                name=org.name,
                slug=org.slug,
                owner_user_id=org.owner_user_id,
                is_personal=org.is_personal,
                plan=org.plan,
                role=entry["role"],
                member_count=entry["member_count"],
                created_at=org.created_at,
            )
        )
    return OrganizationListResponse(
        organizations=items,
        active_org_id=user.active_org_id,
    )


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_new_org(
    payload: OrganizationCreate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one()
    org = await create_org(db, user, payload.name)
    await db.commit()
    await db.refresh(org)
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_user_id=org.owner_user_id,
        is_personal=org.is_personal,
        plan=org.plan,
        role="admin",
        member_count=1,
        created_at=org.created_at,
    )


# ═══ Switch active org ════════════════════════════════════════════

@router.post("/switch", response_model=ActiveOrgSwitchResponse)
async def switch_active_org(
    payload: ActiveOrgSwitch,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await set_active_org(db, user_id, str(payload.org_id))
    except OrgError as e:
        raise _org_error_to_http(e)
    await db.commit()
    return ActiveOrgSwitchResponse(active_org_id=payload.org_id)


# ═══ Update org ═══════════════════════════════════════════════════

@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_org(
    org_id: UUID,
    payload: OrganizationPatchRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await require_role(db, user_id, str(org_id), "admin")
    except OrgError as e:
        raise _org_error_to_http(e)

    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if payload.name is not None:
        org.name = payload.name[:100]
    org.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(org)
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_user_id=org.owner_user_id,
        is_personal=org.is_personal,
        plan=org.plan,
        created_at=org.created_at,
    )


# ═══ Members ══════════════════════════════════════════════════════

@router.get("/{org_id}/members", response_model=MembershipListResponse)
async def list_members(
    org_id: UUID,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await require_role(db, user_id, str(org_id), "viewer")
    except OrgError as e:
        raise _org_error_to_http(e)

    result = await db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
        .order_by(Membership.joined_at.asc())
    )
    members: list[MembershipResponse] = []
    for mem, u in result.all():
        members.append(
            MembershipResponse(
                id=mem.id,
                user_id=u.id,
                user_email=u.email,
                user_display_name=u.display_name,
                role=mem.role,
                joined_at=mem.joined_at,
            )
        )
    return MembershipListResponse(
        memberships=members,
        max_allowed=MAX_MEMBERS_PER_ORG,
    )


@router.patch(
    "/{org_id}/members/{target_user_id}/role",
    response_model=MembershipResponse,
)
async def change_member_role(
    org_id: UUID,
    target_user_id: UUID,
    payload: MembershipRoleUpdate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        mem = await update_member_role(
            db, user_id, str(org_id), str(target_user_id), payload.role
        )
    except OrgError as e:
        raise _org_error_to_http(e)

    await db.commit()
    await db.refresh(mem)

    user_res = await db.execute(
        select(User).where(User.id == target_user_id)
    )
    u = user_res.scalar_one()
    return MembershipResponse(
        id=mem.id,
        user_id=u.id,
        user_email=u.email,
        user_display_name=u.display_name,
        role=mem.role,
        joined_at=mem.joined_at,
    )


@router.delete("/{org_id}/members/{target_user_id}", status_code=204)
async def remove_member_route(
    org_id: UUID,
    target_user_id: UUID,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await remove_member(db, user_id, str(org_id), str(target_user_id))
    except OrgError as e:
        raise _org_error_to_http(e)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ═══ Invites ══════════════════════════════════════════════════════

@router.get("/{org_id}/invites", response_model=InvitesListResponse)
async def list_org_invites(
    org_id: UUID,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        invites = await list_invites(db, user_id, str(org_id))
    except OrgError as e:
        raise _org_error_to_http(e)
    return InvitesListResponse(
        invites=[InviteResponse.model_validate(i) for i in invites]
    )


@router.post(
    "/{org_id}/invites", response_model=InviteResponse, status_code=201
)
async def send_invite(
    org_id: UUID,
    payload: InviteCreateRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        invite, _token = await create_invite(
            db, user_id, str(org_id), payload.email, payload.role
        )
    except OrgError as e:
        raise _org_error_to_http(e)
    await db.commit()
    await db.refresh(invite)
    return InviteResponse.model_validate(invite)


@router.delete(
    "/{org_id}/invites/{invite_id}", status_code=204
)
async def revoke_org_invite(
    org_id: UUID,
    invite_id: UUID,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await revoke_invite(db, user_id, str(invite_id))
    except OrgError as e:
        raise _org_error_to_http(e)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
