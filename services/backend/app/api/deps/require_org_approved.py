"""FastAPI dependency factory: org RBAC + KYB gate + manual-approval gate.

Wraps `require_org_role` (org resolution + role check happen exactly once,
same `(user_id, org_id, role)` tuple contract) and adds ONE indexed read of
the org's `(onboarding_status, approval_status)`, enforced in this order:

    onboarding_status != 'company_submitted'
        -> 403 {"code": "company_profile_required"}   (finish KYB first)
    approval_status == 'approved'   -> ctx passes through unchanged
    approval_status == 'declined'   -> 403 {"code": "approval_declined",
                                            "reason": <operator text>}
    anything else (pending_approval, unknown, missing)
        -> 403 {"code": "approval_pending"}           (fail closed)

The ordering is intrinsic (one query, one function), not an artifact of the
dependency graph: a pre-KYB merchant is always told to finish the profile,
never that they're pending. This dependency SUPERSEDES the former
`require_org_company_submitted` on every operational session route.

Error ordering with the wrapped dep is preserved: 401 (no/invalid token) and
403 insufficient_role fire BEFORE this gate.

Usage — a one-token swap on operational session routes:
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer"))
"""

from __future__ import annotations

from typing import Callable, Tuple

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.org_models import Organization


def require_org_approved(min_role: str) -> Callable:
    base = require_org_role(min_role)

    async def _dep(
        ctx: Tuple[str, str, str] = Depends(base),
        db: AsyncSession = Depends(get_db),
    ) -> Tuple[str, str, str]:
        _user_id, org_id, _role = ctx
        row = (
            await db.execute(
                select(
                    Organization.onboarding_status,
                    Organization.approval_status,
                    Organization.decline_reason,
                ).where(Organization.id == org_id)
            )
        ).one_or_none()
        onboarding = row[0] if row else None
        approval = row[1] if row else None

        if onboarding != "company_submitted":
            raise HTTPException(
                status_code=403,
                detail={"code": "company_profile_required"},
            )
        if approval == "approved":
            return ctx
        if approval == "declined":
            raise HTTPException(
                status_code=403,
                detail={"code": "approval_declined", "reason": row[2] or ""},
            )
        raise HTTPException(status_code=403, detail={"code": "approval_pending"})

    return _dep
