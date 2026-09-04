"""
RSend Idempotency Middleware

Intercetta ogni richiesta POST/PUT che ha l'header X-Idempotency-Key.
Se la stessa key è già stata usata:
  → ritorna la risposta precedente (cached)
  → NON ri-esegue la logica

Storage: Redis con TTL 24h.
Se Redis è down: fail-closed per endpoint finanziari, fail-open per il resto.

FINANCIAL ENDPOINTS (fail-closed = rifiuta se non può verificare):
  - POST /api/v1/tx/callback
  - POST /api/v1/forwarding/rules (create = muove configurazione fondi)

NON-FINANCIAL (fail-open = processa comunque):
  - Tutti gli altri POST/PUT
"""
import asyncio
import hashlib
import json
import logging
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from app.config import get_settings
from app.services.cache_service import get_redis

logger = logging.getLogger("idempotency")

FINANCIAL_PATHS = {
    "/api/v1/tx/callback",
}

IDEMPOTENCY_TTL = 86400  # 24 ore


def _tenant(request: Request) -> str | None:
    """Tenant component of the cache key — who the cached response belongs to.

    Returns None when no identity can be established. The caller must then NOT
    cache: a shared "anonymous" bucket is the very bug this component exists to
    remove, and skipping the cache only costs a duplicate the caller already
    risks today.

    Two namespaces, prefixed so they can never collide:

    `k:` API-key requests. `request.state.client` is populated by
        APIKeyMiddleware, which is mounted OUTERMOST (main.py:330 vs :314) and
        so has already run. `client_id` is the owner wallet address — the same
        value stamped on `PaymentIntent.merchant_id`, so the cache is scoped
        exactly like the data it holds. (When the org_id re-key lands, this
        component moves with `merchant_id`, not before it.)

    `u:` Session requests. `/api/v1/user/` is exempt from APIKeyMiddleware, so
        there is no `state.client` and every org would otherwise share one
        bucket. The access token's `sub` is signature-verified here with no I/O.
        `org_id` is deliberately NOT used: it is not a claim — reaching it means
        a DB read (`user.active_org_id`) plus the Redis session check inside
        `verify_access_token`, neither of which belongs in a middleware on the
        money path. `sub` is narrower than the org, so it cannot leak ACROSS
        orgs; the residue is one user reusing a key across an active-org switch
        inside the TTL, who then replays their own earlier response.
    """
    client = getattr(request.state, "client", None)
    if isinstance(client, dict) and client.get("client_id"):
        return f"k:{client['client_id']}"

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = jwt.decode(
                auth[7:], get_settings().auth_jwt_secret, algorithms=["HS256"]
            )
        except Exception:
            return None
        if claims.get("typ") == "access" and claims.get("sub"):
            return f"u:{claims['sub']}"

    return None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Solo POST e PUT
        if request.method not in ("POST", "PUT"):
            return await call_next(request)

        # Leggi l'header
        idem_key = request.headers.get("X-Idempotency-Key")
        if not idem_key:
            # Se è un endpoint finanziario, RICHIEDI la key
            if request.url.path in FINANCIAL_PATHS:
                # Per webhook Alchemy, usa il webhook_id come key implicita
                if "alchemy" in request.url.path:
                    return await call_next(request)
                # Per altri endpoint finanziari senza key: warning ma processa
                # (per backward compat — in futuro sarà obbligatorio)
            return await call_next(request)

        # Costruisci cache key: (tenant, environment, path, idem_key).
        # The idem_key alone is CLIENT-SUPPLIED, so on its own it scopes nothing
        # — two merchants sending "ORD-1024" to the same path used to collide on
        # one record and receive each other's response, recipient included.
        # The request BODY is deliberately NOT in the key: it belongs beside the
        # record instead, or a byte-different retry (reordered JSON, one added
        # field) would MISS the cache and create a second intent — the exact
        # duplicate idempotency exists to prevent.
        tenant = _tenant(request)
        if tenant is None:
            # No identity → no bucket to put this in that isn't shared.
            logger.warning(
                "Idempotency skipped: no tenant identity on %s", request.url.path
            )
            return await call_next(request)

        client = getattr(request.state, "client", None)
        env = client.get("environment", "-") if isinstance(client, dict) else "-"
        cache_key = "idem:" + hashlib.sha256(
            f"{tenant}:{env}:{request.url.path}:{idem_key}".encode()
        ).hexdigest()

        r = await get_redis()
        if r is None:
            is_financial = request.url.path in FINANCIAL_PATHS
            if is_financial:
                logger.error("Redis unavailable for idempotency on financial endpoint %s", request.url.path)
                return JSONResponse(
                    status_code=503,
                    content={"error": "SERVICE_TEMPORARILY_UNAVAILABLE", "message": "Cannot verify idempotency — retry later"}
                )
            # Non-financial: processa comunque
            return await call_next(request)

        # Check se già processata (fast path)
        try:
            cached = await r.get(cache_key)
            if cached:
                logger.info("Idempotency hit: key=%s path=%s", idem_key[:16], request.url.path)
                data = json.loads(cached)
                return JSONResponse(
                    status_code=data["status_code"],
                    content=data["body"],
                    headers={"X-Idempotency-Replayed": "true"},
                )
        except Exception as e:
            logger.warning("Idempotency check failed: %s", e)

        # Acquire in-flight lock. If another request is processing this key,
        # poll for its result briefly then return it (or 409 if it doesn't finish).
        lock_key = f"{cache_key}:lock"
        try:
            acquired = await r.set(lock_key, "processing", nx=True, ex=30)
        except Exception as e:
            logger.warning("Idempotency lock acquire failed: %s", e)
            acquired = True  # degrade gracefully — same as current behavior

        if not acquired:
            for _ in range(20):
                await asyncio.sleep(0.5)
                try:
                    peer_cached = await r.get(cache_key)
                except Exception:
                    peer_cached = None
                if peer_cached:
                    data = json.loads(peer_cached)
                    return JSONResponse(
                        status_code=data["status_code"],
                        content=data["body"],
                        headers={"X-Idempotency-Replayed": "true"},
                    )
            return JSONResponse(
                status_code=409,
                content={
                    "error": "DUPLICATE_REQUEST_IN_FLIGHT",
                    "message": "A request with this idempotency key is still being processed",
                },
            )

        # Processa la richiesta
        try:
            response = await call_next(request)

            # Salva risposta in cache (solo se 2xx)
            if 200 <= response.status_code < 300:
                try:
                    body_bytes = b""
                    async for chunk in response.body_iterator:
                        body_bytes += chunk

                    body_str = body_bytes.decode("utf-8")
                    cache_data = json.dumps({
                        "status_code": response.status_code,
                        "body": json.loads(body_str) if body_str else {},
                    })
                    await r.set(cache_key, cache_data, ex=IDEMPOTENCY_TTL)

                    return Response(
                        content=body_bytes,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                    )
                except Exception as e:
                    logger.warning("Idempotency cache write failed: %s", e)
                    return Response(content=body_bytes, status_code=response.status_code)

            return response
        finally:
            try:
                await r.delete(lock_key)
            except Exception:
                pass
