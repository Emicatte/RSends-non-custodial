"""
RSends Backend — Internal-secret gate (H3).

/api/internal/* is exempt from API-key auth and reachable via the public
Next.js catch-all proxy. Require a shared secret (sent by the Next oracle as
X-Internal-Secret) so only the server-side oracle can reach these endpoints.

Extracted from the (removed) custodial signing_routes module so the surviving
internal endpoints (e.g. ratelimit) keep their gate without pulling in any
signing/KMS code.
"""

import hmac

from fastapi import HTTPException, Request

from app.config import get_settings


async def require_internal_secret(request: Request) -> None:
    settings = get_settings()
    secret = settings.internal_proxy_secret
    if not secret:
        # Not configured: allowed only in dev/debug; in prod it is required
        # (validate_settings fails startup) and we fail-closed as a backstop.
        if settings.debug:
            return
        raise HTTPException(status_code=503, detail="internal endpoint not configured")
    provided = request.headers.get("X-Internal-Secret", "")
    if not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="forbidden")
