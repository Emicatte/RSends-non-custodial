"""FastAPI dependency factory for user API key auth.

Usage on a user-scoped endpoint (NOT applied in this prompt — infrastructure
only, binding arrives in a later prompt):

    @router.get("/example")
    async def example(
        ctx = Depends(require_api_key_scope("transactions:read")),
    ):
        key, user_id, org_id = ctx
        ...

Returns a 3-tuple `(UserApiKey, user_id, org_id)`:
- `key` is the authenticated row (already mutated with usage) and commits are
  flushed so the caller doesn't have to.
- `user_id` is the key's originating user (`UserApiKey.user_id`).
- `org_id` is the owning org (`UserApiKey.org_id`) — after Prompt 11 every key
  is org-scoped, so this is always non-null. A defensive 409 is raised if not.
"""

from typing import Tuple

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user_api_keys_models import UserApiKey
from app.services.user_api_key_service import UserApiKeyError, verify_request_key


def require_api_key_scope(scope: str):
    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Tuple[UserApiKey, str, str]:
        auth = request.headers.get("Authorization", "")
        ip = request.client.host if request.client else None
        try:
            key = await verify_request_key(db, auth, scope, request_ip=ip)
            await db.commit()
        except UserApiKeyError as e:
            status_code = 429 if e.code == "rate_limit_exceeded" else 401
            raise HTTPException(
                status_code=status_code, detail={"code": e.code}
            )

        # Post-Prompt-11 defensive guard: every key must have an org_id. If
        # somehow a pre-migration row slipped through, fail closed — a caller
        # that can't attribute the request to an org cannot enforce RBAC.
        if getattr(key, "org_id", None) is None:
            raise HTTPException(
                status_code=409, detail={"code": "key_not_org_scoped"}
            )

        return key, str(key.user_id), str(key.org_id)

    return _dep
