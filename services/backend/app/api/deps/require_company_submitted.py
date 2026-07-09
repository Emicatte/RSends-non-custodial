"""FastAPI dependency factory: org RBAC + company-profile-submitted gate.

Wraps `require_org_role` (org resolution + role check happen exactly once,
same tuple contract) and adds ONE indexed read of the org's
`onboarding_status`: anything other than 'company_submitted' -> 403 with the
machine-readable reason code the frontend maps to a redirect:

    {"detail": {"code": "company_profile_required"}}

Error ordering is preserved: 401 (no/invalid token) and 403
insufficient_role from the wrapped dependency fire BEFORE this gate.

Usage — a one-token swap on operational session routes:
    ctx: Tuple[str, str, str] = Depends(require_org_company_submitted("viewer"))
"""

from __future__ import annotations

from typing import Callable, Tuple

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.org_models import Organization


def require_org_company_submitted(min_role: str) -> Callable:
    base = require_org_role(min_role)

    async def _dep(
        ctx: Tuple[str, str, str] = Depends(base),
        db: AsyncSession = Depends(get_db),
    ) -> Tuple[str, str, str]:
        _user_id, org_id, _role = ctx
        status = (
            await db.execute(
                select(Organization.onboarding_status).where(
                    Organization.id == org_id
                )
            )
        ).scalar_one_or_none()
        if status != "company_submitted":
            raise HTTPException(
                status_code=403,
                detail={"code": "company_profile_required"},
            )
        return ctx

    return _dep
