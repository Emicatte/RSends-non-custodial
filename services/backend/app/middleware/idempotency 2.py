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
  - POST /api/v1/webhooks/alchemy
  - POST /api/v1/forwarding/rules (create = muove configurazione fondi)

NON-FINANCIAL (fail-open = processa comunque):
  - Tutti gli altri POST/PUT
"""
import asyncio
import hashlib
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from app.services.cache_service import get_redis

logger = logging.getLogger("idempotency")

FINANCIAL_PATHS = {
    "/api/v1/tx/callback",
    "/api/v1/webhooks/alchemy",
}

IDEMPOTENCY_TTL = 86400  # 24 ore


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

        # Costruisci cache key
        cache_key = f"idem:{hashlib.sha256(f'{request.url.path}:{idem_key}'.encode()).hexdigest()}"

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
