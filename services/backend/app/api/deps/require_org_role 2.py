"""FastAPI dependency factory for org-scoped session auth + RBAC.

Returns a tuple `(user_id, org_id, role)` to route handlers that protect
org-scoped resources (Prompt 11: user_api_keys, user_wallets).

Usage:
    @router.get("")
    async def list_keys(
        ctx: tuple[str, str, str] = Depends(require_org_role("viewer")),
        db: AsyncSession = Depends(get_db),
    ):
        user_id, org_id, role = ctx
        ...

Role hierarchy (mirrors services/org_service.py):
    viewer (0) < operator (1) < admin (2)

Error shape: HTTPException(detail={"code": "..."}) — same shape used by
sibling user_* routes. Codes:
    401 no_token, user_not_found, invalid_token, auth_unavailable
    403 no_active_org, not_a_member, insufficient_role
"""

from __future__ import annotations

from typing import Callable, Tuple

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.auth_models import User
from app.services.auth_service import AuthError, verify_access_token
from app.services.org_service import get_user_role_in_org

_ROLE_HIERARCHY: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


def require_org_role(min_role: str) -> Callable:
    """Factory: returns a dependency that enforces `min_role` on the user's
    active org. Tuple return makes both the caller and org_id first-class.
    """
    required_rank = _ROLE_HIERARCHY.get(min_role)
    if required_rank is None:
        raise ValueError(f"invalid min_role: {min_role!r}")

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Tuple[str, str, str]:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail={"code": "no_token"}
            )
        token = auth[7:]
        try:
            claims = await verify_access_token(token)
        except AuthError as e:
            code = 503 if e.code == "auth_unavailable" else 401
            raise HTTPException(status_code=code, detail={"code": e.code})

        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401, detail={"code": "invalid_token"}
            )

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=401, detail={"code": "user_not_found"}
            )

        org_id = getattr(user, "active_org_id", None)
        if org_id is None:
            raise HTTPException(
                status_code=403, detail={"code": "no_active_org"}
            )
        org_id = str(org_id)

        role = await get_user_role_in_org(db, user_id, org_id)
        if role is None:
            raise HTTPException(
                status_code=403, detail={"code": "not_a_member"}
            )

        actual_rank = _ROLE_HIERARCHY.get(role, -1)
        if actual_rank < required_rank:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_role",
                    "required": min_role,
                    "actual": role,
                },
            )

        return user_id, org_id, role

    return _dep
