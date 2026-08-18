"""FastAPI dependency factory: org RBAC + KYB gate + approval gate.

Wraps `require_org_role` (org resolution + role check happen exactly once,
same `(user_id, org_id, role)` tuple contract) and adds ONE indexed read of
the org's `(onboarding_status, approval_status)`, enforced in this order:

    onboarding_status != 'company_submitted'
        -> 403 {"code": "company_profile_required"}   (finish KYB first)
    then app.api.deps.approval_policy.approval_denial(...) decides:
        declined                     -> 403 {"code": "approval_declined",
                                             "reason": <operator text>}
        sandbox ("test") surface     -> ctx passes through, INCLUDING
                                        `pending_approval`
        live surface                 -> requires 'approved', fails closed

The ordering is intrinsic (one query, one function), not an artifact of the
dependency graph: a pre-KYB merchant is always told to finish the profile,
never that they're pending. This dependency SUPERSEDES the former
`require_org_company_submitted` on every operational session route.

**Sandbox default (2026-08-08).** `environment` defaults to SANDBOX_ENVIRONMENT
because every route using this dep today is hard-pinned to testnet: `/app` sends
no environment and shows no toggle, and the session merchant-key mint pins
`ENVIRONMENT = "test"`. Submitting the company profile therefore grants testnet
access immediately, with no operator in the loop — which is what
`submit_company_profile` has always claimed ("full testnet access, zero human
review"); the manual gate on top of it was the divergence.

**When `/app` grows an environment toggle, pass the real environment here**
(`require_org_approved("operator", environment=env)`) and the strict live rule
applies for free. The policy itself lives in one place — see approval_policy.

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

from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial
from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.org_models import Organization


def require_org_approved(
    min_role: str, *, environment: str = SANDBOX_ENVIRONMENT
) -> Callable:
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

        denial = approval_denial(
            approval,
            environment=environment,
            decline_reason=row[2] if row else None,
        )
        if denial is not None:
            raise denial
        return ctx

    return _dep
