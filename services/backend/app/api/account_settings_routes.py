"""Connected-accounts endpoints — /api/v1/user/account/*.

Co-exists with user_account_routes.py under the same prefix (FastAPI merges
routers). Paths exposed here: /auth-methods, /add-password, /remove-password,
/link-google, /unlink-google, /link-github, /unlink-github.

Each mutation loads the User row, delegates to account_linking_service, then
commits. Errors from the service layer (AccountLinkingError) are translated
to HTTPException with detail={"code","message"} matching the shape the
frontend's apiCall already handles.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User
from app.security.trusted_proxy import get_real_client_ip
from app.services.account_linking_service import (
    AccountLinkingError,
    add_password,
    link_github,
    link_google,
    remove_password,
    unlink_github,
    unlink_google,
    view_methods,
)
from app.services.auth_service import AuthError, verify_access_token

router = APIRouter(prefix="/api/v1/user/account", tags=["account-linking"])


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


async def _load_user(db: AsyncSession, user_id: str) -> User:
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "user_not_found"})
    return user


_STATUS_BY_CODE = {
    "last_auth_method": 409,
    "password_already_set": 409,
    "password_not_set": 409,
    "google_already_linked": 409,
    "google_not_linked": 409,
    "github_already_linked": 409,
    "github_not_linked": 409,
    "google_sub_in_use": 409,
    "github_sub_in_use": 409,
    "email_mismatch": 403,
    "invalid_token": 401,
}


def _err_to_http(e: AccountLinkingError) -> HTTPException:
    status_code = _STATUS_BY_CODE.get(e.code, 400)
    return HTTPException(
        status_code=status_code,
        detail={"code": e.code, "message": e.detail},
    )


class AuthMethodsResponse(BaseModel):
    has_password: bool
    has_google: bool
    has_github: bool
    google_email: Optional[str] = None
    github_username: Optional[str] = None


class AddPasswordRequest(BaseModel):
    password: str = Field(min_length=1)


class LinkGoogleRequest(BaseModel):
    id_token: str = Field(min_length=1)


class LinkGithubRequest(BaseModel):
    access_token: str = Field(min_length=1)


class OkResponse(BaseModel):
    status: str = "ok"


@router.get("/auth-methods", response_model=AuthMethodsResponse)
async def get_auth_methods(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> AuthMethodsResponse:
    user = await _load_user(db, user_id)
    v = view_methods(user)
    return AuthMethodsResponse(
        has_password=v.has_password,
        has_google=v.has_google,
        has_github=v.has_github,
        google_email=v.google_email,
        github_username=v.github_username,
    )


@router.post("/add-password", response_model=OkResponse)
async def add_password_route(
    payload: AddPasswordRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await add_password(
            db,
            user,
            payload.password,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()


@router.post("/remove-password", response_model=OkResponse)
async def remove_password_route(
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await remove_password(
            db,
            user,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()


@router.post("/link-google", response_model=OkResponse)
async def link_google_route(
    payload: LinkGoogleRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await link_google(
            db,
            user,
            payload.id_token,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()


@router.post("/unlink-google", response_model=OkResponse)
async def unlink_google_route(
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await unlink_google(
            db,
            user,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()


@router.post("/link-github", response_model=OkResponse)
async def link_github_route(
    payload: LinkGithubRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await link_github(
            db,
            user,
            payload.access_token,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()


@router.post("/unlink-github", response_model=OkResponse)
async def unlink_github_route(
    request: Request,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user = await _load_user(db, user_id)
    ua = request.headers.get("User-Agent", "")
    try:
        await unlink_github(
            db,
            user,
            ip=get_real_client_ip(request),
            user_agent=ua,
        )
    except AccountLinkingError as e:
        raise _err_to_http(e)
    await db.commit()
    return OkResponse()
