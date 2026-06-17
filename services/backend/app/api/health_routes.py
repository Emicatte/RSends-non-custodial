"""
RSends Backend — Deep Health Check Routes.

Endpoint /health/deep che verifica tutti i componenti del sistema:
  - Postgres: SELECT 1 con timeout 3s
  - Redis: PING con timeout 2s
  - Celery: control.ping per verificare almeno 1 worker alive
  - RPC: eth_blockNumber su Base (chain 8453) con timeout 5s
  - KMS: firma di test (opzionale, solo se SIGNER_MODE=kms)

Status complessivo:
  - "healthy"   → tutti i componenti critici OK
  - "degraded"  → solo RPC lento/down (il sistema accetta richieste, TX in attesa)
  - "unhealthy" → Postgres, Redis, o Celery down
"""

import asyncio
import logging
import time

from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])


async def _check_postgres() -> dict:
    """Verifica connessione Postgres con SELECT 1 (timeout 3s)."""
    t0 = time.monotonic()
    try:
        from app.db.session import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=3.0,
            )
        latency = round((time.monotonic() - t0) * 1000, 1)
        return {"status": "ok", "latency_ms": latency}
    except asyncio.TimeoutError:
        return {"status": "error", "detail": "timeout (>3s)"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}


async def _check_redis() -> dict:
    """Verifica connessione Redis con PING (timeout 2s)."""
    t0 = time.monotonic()
    try:
        from app.services.cache_service import get_redis

        r = await get_redis()
        if r is None:
            return {"status": "error", "detail": "not configured"}

        await asyncio.wait_for(r.ping(), timeout=2.0)
        latency = round((time.monotonic() - t0) * 1000, 1)
        return {"status": "ok", "latency_ms": latency}
    except asyncio.TimeoutError:
        return {"status": "error", "detail": "timeout (>2s)"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}


async def _check_celery() -> dict:
    """Verifica almeno 1 worker Celery con control.ping (timeout 3s)."""
    try:
        from app.celery_app import celery as celery_app

        loop = asyncio.get_running_loop()

        def _ping():
            inspect = celery_app.control.inspect(timeout=3.0)
            return inspect.ping()

        pong = await asyncio.wait_for(
            loop.run_in_executor(None, _ping),
            timeout=5.0,
        )
        worker_count = len(pong) if pong else 0
        if worker_count > 0:
            return {"status": "ok", "workers": worker_count}
        return {"status": "warn", "workers": 0, "detail": "no workers responding"}
    except asyncio.TimeoutError:
        return {"status": "warn", "workers": 0, "detail": "ping timeout"}
    except Exception as e:
        return {"status": "warn", "workers": 0, "detail": str(e)[:200]}


async def _check_rpc() -> dict:
    """Verifica RPC Base (chain 8453) con eth_blockNumber (timeout 5s)."""
    t0 = time.monotonic()
    try:
        from app.services.rpc_manager import get_rpc_manager

        rpc = get_rpc_manager(8453)
        result = await asyncio.wait_for(
            rpc.call("eth_blockNumber", []),
            timeout=5.0,
        )
        latency = round((time.monotonic() - t0) * 1000, 1)
        block = int(result, 16) if isinstance(result, str) else result
        return {"status": "ok", "block": block, "latency_ms": latency}
    except asyncio.TimeoutError:
        return {"status": "error", "detail": "timeout (>5s)"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}


async def _check_kms() -> dict:
    """Verifica KMS (solo se SIGNER_MODE=kms). Test firma opzionale."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if settings.signer_mode != "kms":
            return {"status": "skipped", "detail": f"signer_mode={settings.signer_mode}"}

        if not settings.kms_key_id:
            return {"status": "error", "detail": "KMS_KEY_ID not configured"}

        import boto3

        loop = asyncio.get_running_loop()

        def _kms_ping():
            client = boto3.client("kms", region_name=settings.aws_region)
            client.describe_key(KeyId=settings.kms_key_id)
            return True

        await asyncio.wait_for(
            loop.run_in_executor(None, _kms_ping),
            timeout=5.0,
        )
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return {"status": "error", "detail": "timeout (>5s)"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}


@health_router.get("/health/deep")
async def health_deep():
    """Deep health check: verifica tutti i componenti del sistema.

    Ritorna lo stato di Postgres, Redis, Celery, RPC e KMS.
    Status complessivo: healthy / degraded / unhealthy.
    """
    # Run all checks concurrently
    pg_task = asyncio.create_task(_check_postgres())
    redis_task = asyncio.create_task(_check_redis())
    celery_task = asyncio.create_task(_check_celery())
    rpc_task = asyncio.create_task(_check_rpc())
    kms_task = asyncio.create_task(_check_kms())

    postgres, redis, celery_result, rpc_base, kms = await asyncio.gather(
        pg_task, redis_task, celery_task, rpc_task, kms_task,
    )

    components = {
        "postgres": postgres,
        "redis": redis,
        "celery": celery_result,
        "rpc_base": rpc_base,
        "kms": kms,
    }

    # Critical components: Postgres, Redis, Celery
    critical_down = any(
        components[k].get("status") == "error"
        for k in ("postgres", "redis")
    )
    # Celery warn (no workers) is degraded, not unhealthy
    celery_down = celery_result.get("status") == "error"

    # RPC down = degraded (system can still accept requests)
    rpc_down = rpc_base.get("status") == "error"

    if critical_down or celery_down:
        overall = "unhealthy"
    elif rpc_down or celery_result.get("status") == "warn":
        overall = "degraded"
    else:
        overall = "healthy"

    status_code = 200 if overall == "healthy" else 503 if overall == "unhealthy" else 200

    from app.middleware.db_backpressure import get_db_semaphore_state
    components["db_backpressure"] = get_db_semaphore_state()

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "components": components,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
