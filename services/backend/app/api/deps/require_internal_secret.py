"""Shared-secret gate for `/api/internal/*` — the Auto Split keeper's only auth.

Restored from `app/security/internal_auth.py`, deleted in cc768dde when the last
`/api/internal/*` route went away. That commit was right to take the setting and
its prod guard with it: "the guard would otherwise demand a secret in prod that
protects nothing (misleading deploy failure)". The keeper gives it something to
protect again.

Two deliberate differences from the deleted version:

  • NO `settings.debug` early return. The old gate allowed an unconfigured
    secret through whenever DEBUG was set, which makes the one posture where a
    developer is most likely to point a real keeper at a real chain also the one
    where the door is open. Unconfigured now denies in every posture.

  • The docstring's premise is corrected. The old one said this surface was
    "reachable via the public Next.js catch-all proxy", so the secret was a
    second layer behind it. It is not: the proxy denylists `api/internal` and
    404s it (`apps/web/app/api/backend/[...path]/route.ts`). A caller reaches
    this endpoint by hitting the backend origin directly, so this secret is the
    ONLY thing in front of a deliberately cross-tenant read.

Shape follows `require_admin` (`app/api/audit_routes.py`): required header,
emptiness checked BEFORE the comparison — `compare_digest("", "")` is True, so
an unconfigured secret would otherwise be matchable by an absent one — and a
constant-time compare on encoded bytes.

Attach this to the ROUTER, never to a single handler: `api_auth.py` exempts the
whole prefix by `startswith`, so an endpoint added later under it would
otherwise be reachable with no auth at all.
"""

import secrets

from fastapi import Header, HTTPException

from app.config import get_settings

#: Follows the `X-RSend-…` convention this secret already uses on the proxy hop.
INTERNAL_SECRET_HEADER = "X-RSend-Internal-Secret"


async def require_internal_secret(
    x_rsend_internal_secret: str = Header(
        ..., alias=INTERNAL_SECRET_HEADER, description="INTERNAL_PROXY_SECRET"
    ),
) -> None:
    settings = get_settings()
    expected = settings.internal_proxy_secret
    if not expected:
        # Fail closed, in every posture. `validate_settings` already refuses to
        # boot prod without it; this is the backstop for everywhere else.
        raise HTTPException(
            status_code=503, detail="internal endpoint not configured"
        )
    if not secrets.compare_digest(
        x_rsend_internal_secret.encode(), expected.encode()
    ):
        raise HTTPException(status_code=403, detail="forbidden")
    return None
