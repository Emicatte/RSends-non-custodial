"""User-scoped saved-routes CRUD.

All endpoints require a valid access token (Bearer) issued by
/api/v1/auth/google. Every query is filtered by the authenticated user's id
so a user cannot see or mutate another user's routes.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthError, verify_access_token
from app.models.user_routes_models import UserRoute
from app.models.user_routes_schemas import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
)

router = APIRouter(prefix="/api/v1/user/routes", tags=["user-routes"])


async def require_user_id(request: Request) -> str:
    """Extract authenticated user_id from Bearer access token.

    Mirrors the pattern in /api/v1/auth/me (auth_routes.py):
    - AuthError.code "auth_unavailable" → 503
    - anything else auth-ish → 401
    """
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


@router.get("", response_model=List[RouteResponse])
async def list_routes(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[RouteResponse]:
    result = await db.execute(
        select(UserRoute)
        .where(UserRoute.user_id == user_id)
        .order_by(
            UserRoute.is_favorite.desc(),
            UserRoute.last_used_at.desc().nullslast(),
            UserRoute.created_at.desc(),
        )
    )
    return [RouteResponse.model_validate(r) for r in result.scalars()]


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(
    payload: RouteCreate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> RouteResponse:
    import uuid

    route = UserRoute(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=payload.name,
        route_config=payload.route_config,
        is_favorite=bool(payload.is_favorite),
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return RouteResponse.model_validate(route)


@router.patch("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    payload: RouteUpdate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> RouteResponse:
    result = await db.execute(
        select(UserRoute).where(
            UserRoute.id == route_id,
            UserRoute.user_id == user_id,
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if payload.name is not None:
        route.name = payload.name
    if payload.is_favorite is not None:
        route.is_favorite = payload.is_favorite
    if payload.route_config is not None:
        route.route_config = payload.route_config

    await db.commit()
    await db.refresh(route)
    return RouteResponse.model_validate(route)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(UserRoute).where(
            UserRoute.id == route_id,
            UserRoute.user_id == user_id,
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    await db.delete(route)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
