"""
═══════════════════════════════════════════════════════════════
  RPagos Backend Core — Production Server

  Stack:
  - FastAPI + Uvicorn (4 workers)
  - PostgreSQL via asyncpg
  - Redis per cache + rate limiting + WS event buffer
  - Sentry per error tracking
  - Prometheus per metriche
  - WebSocket sweep feed (real-time)
═══════════════════════════════════════════════════════════════
"""

# ═══════════════════════════════════════════════════════════════
# Load .env ONLY in local dev. On Render/production, env vars are
# injected by the platform — load_dotenv() would be a no-op anyway
# but we skip it explicitly to avoid surprises.
# ═══════════════════════════════════════════════════════════════
import os
if not os.getenv("RENDER"):
    from dotenv import load_dotenv
    load_dotenv()

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, validate_settings, validate_dev_flags, is_prod_posture
from app.db.session import close_db, async_session, _is_sqlite, engine
from app.api.routes import router
from app.services.cache_service import close_redis
from app.services.payment_indexer import start_indexer_if_needed, stop_indexer
from app.services.price_service import fetch_all_prices, price_refresh_loop
from app.logging_config import setup_logging
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    settings = get_settings()

    # ── Block dev/bypass flags in non-dev environments ─────
    validate_dev_flags(settings)

    # ── Structured JSON logging ─────────────────────
    # Livello e logger rumorosi guidati dalla posture unificata (H6), non dal
    # solo flag DEBUG; la redazione segreti è attiva in ogni posture.
    setup_logging(debug=settings.debug, prod_posture=is_prod_posture(settings))

    # ── Validate critical env vars ──────────────────
    validate_settings(settings)

    # ── Sentry ───────────────────────────────────────
    if settings.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.2,
            profiles_sample_rate=0.1,
            environment="production" if not settings.debug else "development",
        )

    # ── OpenTelemetry tracing ───────────────────────
    from app.observability import setup_telemetry
    otel_enabled = setup_telemetry(app, engine)
    if otel_enabled:
        logger.info("OpenTelemetry tracing active")

    # ── Verifica connessione DB ─────────────────────
    from sqlalchemy import text
    try:
        async with async_session() as test_db:
            await test_db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"ERROR: {e}"
        if not settings.debug:
            raise SystemExit(f"Cannot connect to database: {e}")

    if _is_sqlite:
        pool_display = "SQLite (test only)"
    else:
        pool_display = f"{engine.pool.size()}/{engine.pool.size() + engine.pool.overflow()}"

    logger.info("DB status: %s | Pool: %s", db_status, pool_display)

    # ── Verifica connessione Redis ──────────────────
    from app.services.cache_service import get_redis, is_redis_healthy
    try:
        r = await get_redis()
        if r:
            await r.ping()
            redis_status = "connected"
        else:
            redis_status = "NOT CONFIGURED"
    except Exception as e:
        redis_status = f"ERROR: {e}"

    logger.info("Redis status: %s", redis_status)
    if redis_status != "connected":
        logger.warning(
            "Redis required for idempotency — webhooks will be rejected (fail-closed) without Redis"
        )

    # ── Initialise AlertService ──────────────────────
    from app.services.alert_service import init_alert_service
    alert_chat = settings.telegram_alert_chat_id or settings.telegram_chat_id
    init_alert_service(
        telegram_token=settings.telegram_bot_token or None,
        telegram_chat_id=alert_chat or None,
        webhook_url=settings.alert_webhook_url or None,
    )

    # ── Start on-chain PaymentMade indexer (non-custodial) ──
    # Watches RSendsRouter.PaymentMade per configured chain. No-op if no
    # RSENDS_ROUTER addresses are configured (e.g. dev/test).
    watchers = await start_indexer_if_needed()

    # ── Proactive RPC health checks (per indexer chain) ──
    # One eth_blockNumber per provider per 30s; feeds health-based failover
    # routing, the rpc_provider_healthy/rpc_block_height gauges and the
    # all-providers-down CRITICAL. Rollback = RPC_HEALTH_CHECKS_ENABLED=false.
    if settings.rpc_health_checks_enabled and watchers:
        from app.services.rpc_manager import start_health_checks

        await start_health_checks([w.chain_id for w in watchers])

    # ── Token registry boot guard (defense-in-depth) ──
    # Re-check enabled tokens' on-chain symbol()/decimals() against the registry.
    # Mismatch → panic (real danger); RPC unreachable → retry/backoff then continue.
    # No-op when no router addresses are configured. The deploy-script gate
    # (SetFeeConfig.verifyAndSet) remains the primary backstop.
    from app.services.router_registry import verify_enabled_tokens_onchain
    try:
        await verify_enabled_tokens_onchain()
    except SystemExit:
        raise  # metadata mismatch → refuse to start
    except Exception as e:  # never let a guard bug break startup
        logger.warning("[registry-guard] skipped due to unexpected error: %s", e)

    # ── Price service: initial fetch + background loop ──
    import asyncio as _aio
    _price_refresh_task = None
    try:
        await fetch_all_prices()
        _price_refresh_task = _aio.create_task(price_refresh_loop())
        logger.info("Price service started (interval=%ds)", 60)
    except Exception as e:
        logger.warning("Price service init failed: %s — prices will be unavailable", e)

    # ── Webhook delivery + intent expiration loops (asyncio fallback) ──
    # Se Celery non e' raggiungibile, usa background tasks asyncio
    _webhook_delivery_task = None
    _intent_expiration_task = None
    try:
        from app.celery_app import celery as celery_app
        inspector = celery_app.control.inspect(timeout=2)
        celery_active = bool(inspector.ping())
    except Exception:
        celery_active = False

    if not celery_active:
        from app.tasks.webhook_tasks import webhook_delivery_loop, intent_expiration_loop
        _webhook_delivery_task = _aio.create_task(webhook_delivery_loop(15.0))
        _intent_expiration_task = _aio.create_task(intent_expiration_loop(60.0))
        logger.info("Celery not available — webhook delivery + expiration running as asyncio tasks")
    else:
        logger.info("Celery active — webhook delivery + expiration delegated to Celery beat")
    # /health/deep reads this: with the asyncio fallback covering the queues,
    # zero Celery workers is the CONFIGURED state, not a degradation.
    app.state.celery_fallback_active = not celery_active

    db_display = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    logger.info(
        "RPagos Backend Core started",
        extra={
            "mode": "DEV" if settings.debug else "PRODUCTION",
            "db": db_display,
            "redis": settings.redis_url,
            "sentry": bool(settings.sentry_dsn),
            # On-chain PaymentMade polling via the indexer is the ONLY
            # detection path — there is no inbound webhook.
            "tx_detection": "polling",
        },
    )

    yield

    # ── Cleanup ──────────────────────────────────────────────
    # Order: cancel background asyncio tasks → stop jobs/pollers/WS
    # managers → close connections LAST (close_db / close_redis), so
    # nothing still in flight touches a disposed engine / closed redis.
    import asyncio as _aio  # local alias (matches startup section)

    # 1) Cancel orphaned background tasks (mirror of stop_* helpers).
    for _task in (_price_refresh_task, _webhook_delivery_task, _intent_expiration_task):
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except _aio.CancelledError:
                pass
            except Exception as _e:  # never let cleanup raise
                logger.warning("Error awaiting cancelled task during shutdown: %s", _e)

    # 2) Stop indexer / RPC health loops / WS managers (these may use the
    #    DB/Redis or have HTTP probes in flight).
    await stop_indexer()
    from app.services.rpc_manager import stop_all_managers

    try:
        await stop_all_managers()
    except Exception as _e:  # never let cleanup raise
        logger.warning("Error stopping RPC health checks during shutdown: %s", _e)

    # 3) Close shared connections LAST.
    await close_db()
    await close_redis()


app = FastAPI(
    title="RPagos Backend Core",
    description="Compliance & Data Engine per transazioni Web3.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().debug else None,  # Nascondi Swagger in prod
    redoc_url=None,
    # No public schema in prod: FastAPI's default openapi_url would expose the
    # full API surface even with /docs off.
    openapi_url="/openapi.json" if get_settings().debug else None,
)

# ── CORS ─────────────────────────────────────────────────
settings = get_settings()
if settings.debug:
    cors_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:5173",
        "https://fee-router-dapp.vercel.app",
    ]
else:
    cors_origins = (
        [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        if settings.cors_origins
        else ["https://rsends.io", "https://www.rsends.io"]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Correlation ID Middleware ──────────────────────────
from app.middleware.correlation import CorrelationMiddleware
app.add_middleware(CorrelationMiddleware)

# ── Request Context Middleware ──────────────────────────
from app.middleware.request_context import RequestContextMiddleware
app.add_middleware(RequestContextMiddleware)

# ── Input Sanitization Middleware ──────────────────────
from app.middleware.input_sanitization import InputSanitizationMiddleware
app.add_middleware(InputSanitizationMiddleware)

# ── Rate Limiting Middleware ─────────────────────────────
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# (The email-verification gate middleware was removed 2026-07-13: verification
# no longer gates anything — merchants are gated on org approval_status
# instead, enforced per-route by require_org_approved and the merchant
# API-key approval check.)

# ── Idempotency Middleware ──────────────────────────────
from app.middleware.idempotency import IdempotencyMiddleware
app.add_middleware(IdempotencyMiddleware)

# ── Request Timeout Middleware ─────────────────────────
from app.middleware.request_timeout import RequestTimeoutMiddleware
app.add_middleware(RequestTimeoutMiddleware)

# ── DB Backpressure Middleware ────────────────────────
from app.middleware.db_backpressure import DBBackpressureMiddleware
app.add_middleware(DBBackpressureMiddleware)

# ── Global Error Handler ───────────────────────────────
from app.middleware.error_handler import ErrorHandlerMiddleware
app.add_middleware(ErrorHandlerMiddleware)

# ── API Key Authentication (production only) ───────────
from app.middleware.api_auth import APIKeyMiddleware
app.add_middleware(APIKeyMiddleware)

# ── Prometheus Metrics ───────────────────────────────────
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=True,
        should_group_untemplated=True,
        excluded_handlers=["/health", "/metrics", "/ws/*"],
    ).instrument(app).expose(app, endpoint="/metrics")
except ImportError:
    pass  # Skip if not installed

# ── Routes ───────────────────────────────────────────────
app.include_router(router)
from app.api.audit_routes import audit_router
app.include_router(audit_router)
from app.api.price_routes import price_router
app.include_router(price_router)
from app.api.merchant_routes import merchant_router
app.include_router(merchant_router)
from app.api.public_routes import public_router  # payer-facing, id-as-secret
app.include_router(public_router)
from app.api.health_routes import health_router
app.include_router(health_router)
from app.api.ratelimit_routes import ratelimit_router
app.include_router(ratelimit_router)
from app.api.aml_routes import aml_router
app.include_router(aml_router)
from app.api.admin_approval_routes import admin_approval_router  # X-Admin-Token only
app.include_router(admin_approval_router)
from app.api.api_key_routes import api_key_router
app.include_router(api_key_router)
from app.api.auth_routes import router as auth_router
app.include_router(auth_router)
from app.api.auth_email_routes import router as auth_email_router
app.include_router(auth_email_router)
from app.api.wallet_session_routes import router as wallet_session_router
app.include_router(wallet_session_router)
from app.api.user_routes import router as user_routes_router
app.include_router(user_routes_router)
from app.api.user_tx_routes import router as user_tx_routes_router
app.include_router(user_tx_routes_router)
from app.api.user_contacts_routes import router as user_contacts_router
app.include_router(user_contacts_router)
from app.api.notification_routes import router as notifications_router
app.include_router(notifications_router)
from app.api.user_wallets_routes import router as user_wallets_router
app.include_router(user_wallets_router)
from app.api.user_account_routes import router as user_account_router
app.include_router(user_account_router)
from app.api.account_settings_routes import router as account_linking_router
app.include_router(account_linking_router)
from app.api.user_api_keys_routes import router as user_api_keys_router
app.include_router(user_api_keys_router)
from app.api.organizations_routes import router as organizations_router
app.include_router(organizations_router)
from app.api.org_invites_public_routes import router as org_invites_public_router
app.include_router(org_invites_public_router)
from app.api.dashboard_routes import router as dashboard_router
app.include_router(dashboard_router)
from app.api.merchant_profile_routes import router as merchant_profile_router
app.include_router(merchant_profile_router)
from app.api.merchant_invoice_routes import router as merchant_invoice_router
app.include_router(merchant_invoice_router)
from app.api.user_org_payments_routes import router as user_org_payments_router
app.include_router(user_org_payments_router)
from app.api.user_org_webhooks_routes import router as user_org_webhooks_router
app.include_router(user_org_webhooks_router)
from app.api.user_org_stats_routes import router as user_org_stats_router
app.include_router(user_org_stats_router)
from app.api.user_org_merchant_keys_routes import router as user_org_merchant_keys_router
app.include_router(user_org_merchant_keys_router)
from app.api.user_onboarding_routes import router as user_onboarding_router
app.include_router(user_onboarding_router)


# ── Health checks ────────────────────────────────────────
@app.get("/health")
async def health():
    from app.services.cache_service import is_redis_healthy
    from app.services.payment_indexer import indexer_status
    redis_ok = await is_redis_healthy()
    # Fail loud: a stalled watcher is silent payment loss — surface it as
    # `degraded` here, not only in logs/metrics.
    indexer = indexer_status()
    indexer_stalled = any(s.get("stalled") for s in indexer.values())
    return {
        "status": "healthy" if (redis_ok and not indexer_stalled) else "degraded",
        "service": "rpagos-backend-core",
        "version": "2.0.0",
        "redis": "connected" if redis_ok else "disconnected",
        "idempotency": "active" if redis_ok else "FAIL-CLOSED (webhooks rejected)",
        "indexer": indexer or "disabled",
    }


@app.get("/health/live")
async def health_live():
    """Liveness probe: 200 se il processo è vivo (per container orchestrator)."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe: 200 se DB e Redis raggiungibili (per load balancer)."""
    from fastapi.responses import JSONResponse
    from app.db.session import engine
    from app.services.cache_service import get_redis

    checks = {"db": False, "redis": False}

    # DB check
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception as e:
        logger.warning("Readiness: DB check failed: %s", e)

    # Redis check
    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = True
    except Exception as e:
        logger.warning("Readiness: Redis check failed: %s", e)

    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@app.get("/health/dependencies")
async def health_dependencies():
    """External services health: circuit breaker states for all dependencies."""
    from app.services.external_health import get_dependency_summary
    return await get_dependency_summary()


@app.get("/health/rpc")
async def health_rpc():
    """RPC provider health: per-chain provider status, block heights, circuit states."""
    from app.services.rpc_manager import get_rpc_manager
    chains = {8453: "base_mainnet", 84532: "base_sepolia", 1: "ethereum", 42161: "arbitrum"}
    return {
        label: get_rpc_manager(chain_id).info()
        for chain_id, label in chains.items()
    }


# Detailed health endpoints below leak deploy fingerprint / hot-wallet balance /
# Celery+Redis topology — gate them behind the admin token (M7). Basic liveness
# (/health, /health/live, /health/ready) stays open for orchestrator probes.
from app.api.audit_routes import require_admin


@app.get("/health/config")
async def health_config(_admin: str = Depends(require_admin)):
    """Configuration status: which env vars are set (values never exposed)."""
    settings = get_settings()
    is_prod = not settings.debug

    def _check(val: str, required: bool = False, prod_only: bool = False) -> str:
        has_value = bool(val and val not in (
            "change-me-in-production",
            "change_this_to_random_string",
        ))
        if has_value:
            return "ok"
        if required and (not prod_only or is_prod):
            return "MISSING"
        return "not_set"

    return {
        "environment": "production" if is_prod else "development",
        "vars": {
            "DATABASE_URL": _check(settings.database_url, required=True),
            "REDIS_URL": _check(settings.redis_url, required=True, prod_only=True),
            "ALCHEMY_API_KEY": _check(settings.alchemy_api_key, required=True),
            # NON-CUSTODIAL: no SWEEP_PRIVATE_KEY / SIGNER_MODE / KMS_KEY_ID.
            "RSENDS_ROUTER_ADDRESSES": _check(settings.rsends_router_addresses_json),
            "HMAC_SECRET": _check(settings.hmac_secret, required=True, prod_only=True),
            "TELEGRAM_BOT_TOKEN": _check(settings.telegram_bot_token),
            "TELEGRAM_CHAT_ID": _check(settings.telegram_chat_id),
            "SENTRY_DSN": _check(settings.sentry_dsn),
            "DEBUG": settings.debug,
        },
    }


if __name__ == "__main__":
    import uvicorn
    s = get_settings()
    uvicorn.run(
        "app.main:app",
        host=s.host,
        port=s.port,
        reload=s.debug,
        workers=1 if s.debug else 4,
    )
