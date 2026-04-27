"""
RSends Backend — Sweeper API Routes (Command Center) — CC-07

POST /api/v1/webhooks/alchemy             → Alchemy webhook (incoming TX)

POST /api/v1/forwarding/rules             → Crea regola (@require_wallet_auth)
GET  /api/v1/forwarding/rules             → Lista regole utente
GET  /api/v1/forwarding/rules/{id}        → Dettaglio regola
PUT  /api/v1/forwarding/rules/{id}        → Aggiorna regola (@require_wallet_auth)
DELETE /api/v1/forwarding/rules/{id}      → Elimina regola (@require_wallet_auth)

POST /api/v1/forwarding/rules/{id}/pause  → Pausa regola (@require_wallet_auth)
POST /api/v1/forwarding/rules/{id}/resume → Riprendi regola (@require_wallet_auth)
POST /api/v1/forwarding/emergency-stop    → Emergency stop (@require_wallet_auth)

GET  /api/v1/forwarding/rules/{id}/batches → Batches (paginate)
GET  /api/v1/forwarding/spending-limits    → Spending limits status

GET  /api/v1/forwarding/logs              → Sweep logs (paginati)
GET  /api/v1/forwarding/logs/export       → Export CSV/JSON

GET  /api/v1/forwarding/stats             → Statistiche aggregate
GET  /api/v1/forwarding/stats/daily       → Volume giornaliero
"""

import asyncio
import csv
import io
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.middleware.request_context import get_request_id
from app.models.forwarding_models import (
    AuditLog,
    ForwardingRule,
    GasStrategy,
    SweepLog,
    SweepStatus,
)
from app.models.command_models import SweepBatch, SweepBatchItem
from app.services.sweep_service import process_incoming_tx, queue_sweep
from app.services import alchemy_webhook_manager
from app.tokens.registry import get_token as _registry_get_token, get_native as _registry_get_native
from app.security.auth import require_wallet_auth
from app.security.webhook_verifier import (
    WebhookVerificationError,
    verify_webhook,
)
from app.api.websocket_routes import feed_manager

logger = logging.getLogger("sweeper_routes")

sweeper_router = APIRouter(prefix="/api/v1", tags=["sweeper"])

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_RULES_PER_OWNER = 20


# ═══════════════════════════════════════════════════════════
#  Pydantic schemas
# ═══════════════════════════════════════════════════════════

def _validate_eth_address(v: str) -> str:
    if not ETH_ADDR_RE.match(v):
        raise ValueError("Must be a valid Ethereum address (0x + 40 hex chars)")
    return v.lower()


def _validate_optional_eth_address(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    return _validate_eth_address(v)


class CreateRulePayload(BaseModel):
    source_wallet: str = Field(..., min_length=42, max_length=42)
    destination_wallet: Optional[str] = Field(None, min_length=42, max_length=42)
    distribution_list_id: Optional[str] = Field(None, description="UUID of distribution list")
    label: Optional[str] = Field(None, max_length=100)

    # Split
    split_enabled: bool = False
    split_percent: int = Field(100, ge=0, le=100)
    split_destination: Optional[str] = Field(None, min_length=42, max_length=42)

    # Condizioni
    min_threshold: float = Field(0.001, ge=0.0001)
    gas_strategy: str = Field("normal")
    max_gas_percent: float = Field(10.0, ge=1.0, le=50.0)
    gas_limit_gwei: int = Field(50, ge=1, le=1000)
    cooldown_sec: int = Field(60, ge=0, le=86400)
    max_daily_vol: Optional[float] = None

    # Token
    token_address: Optional[str] = None
    token_symbol: str = Field("ETH", max_length=16)
    token_filter: list[str] = Field(default_factory=list)

    # Swap
    auto_swap: bool = False
    swap_to_token: Optional[str] = Field(None, min_length=42, max_length=42)

    # Notifiche
    notify_enabled: bool = True
    notify_channel: str = Field("telegram", max_length=20)
    telegram_chat_id: Optional[str] = Field(None, max_length=50)
    email_address: Optional[str] = Field(None, max_length=255)

    # Scheduling
    schedule_json: Optional[dict] = None

    # Chain
    chain_id: int = Field(8453)

    @field_validator("source_wallet")
    @classmethod
    def validate_source(cls, v: str) -> str:
        return _validate_eth_address(v)

    @field_validator("destination_wallet", "split_destination", "token_address", "swap_to_token")
    @classmethod
    def validate_optional_addresses(cls, v: Optional[str]) -> Optional[str]:
        return _validate_optional_eth_address(v)

    @field_validator("gas_strategy")
    @classmethod
    def validate_gas_strategy(cls, v: str) -> str:
        if v not in {"fast", "normal", "slow"}:
            raise ValueError("gas_strategy must be fast, normal, or slow")
        return v

    @field_validator("split_percent")
    @classmethod
    def validate_split_percent(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("split_percent must be between 0 and 100")
        return v


class UpdateRulePayload(BaseModel):
    version: Optional[int] = Field(
        None,
        description="Current version for optimistic locking. If omitted, lock is skipped.",
    )
    label: Optional[str] = None
    destination_wallet: Optional[str] = Field(None, min_length=42, max_length=42)
    distribution_list_id: Optional[str] = Field(None, description="UUID of distribution list")
    is_active: Optional[bool] = None
    min_threshold: Optional[float] = Field(None, ge=0.0001)
    gas_strategy: Optional[str] = None
    max_gas_percent: Optional[float] = Field(None, ge=1.0, le=50.0)
    gas_limit_gwei: Optional[int] = Field(None, ge=1, le=1000)
    cooldown_sec: Optional[int] = Field(None, ge=0, le=86400)
    max_daily_vol: Optional[float] = None

    split_enabled: Optional[bool] = None
    split_percent: Optional[int] = Field(None, ge=0, le=100)
    split_destination: Optional[str] = Field(None, min_length=42, max_length=42)

    token_filter: Optional[list[str]] = None
    auto_swap: Optional[bool] = None
    swap_to_token: Optional[str] = Field(None, min_length=42, max_length=42)

    notify_enabled: Optional[bool] = None
    notify_channel: Optional[str] = Field(None, max_length=20)
    telegram_chat_id: Optional[str] = Field(None, max_length=50)
    email_address: Optional[str] = Field(None, max_length=255)

    schedule_json: Optional[dict] = None

    @field_validator("destination_wallet", "split_destination", "swap_to_token")
    @classmethod
    def validate_optional_addr(cls, v: Optional[str]) -> Optional[str]:
        return _validate_optional_eth_address(v)


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

async def _get_rule_or_404(db: AsyncSession, rule_id: int) -> ForwardingRule:
    result = await db.execute(
        select(ForwardingRule).where(ForwardingRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


async def _verify_owner(rule: ForwardingRule, owner_address: str) -> None:
    if rule.user_id != owner_address.lower():
        raise HTTPException(status_code=403, detail="Not the owner of this rule")


def _response(data: dict) -> dict:
    """Inject request_id into response."""
    rid = get_request_id()
    if rid:
        data["request_id"] = str(rid)
    return data


def _serialize_rule(r: ForwardingRule) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "label": r.label,
        "source_wallet": r.source_wallet,
        "destination_wallet": r.destination_wallet,
        "distribution_list_id": str(r.distribution_list_id) if r.distribution_list_id else None,
        "split_enabled": r.split_enabled,
        "split_percent": r.split_percent,
        "split_destination": r.split_destination,
        "is_active": r.is_active,
        "is_paused": r.is_paused,
        "min_threshold": r.min_threshold,
        "gas_strategy": r.gas_strategy.value if r.gas_strategy else "normal",
        "max_gas_percent": r.max_gas_percent,
        "gas_limit_gwei": r.gas_limit_gwei,
        "cooldown_sec": r.cooldown_sec,
        "max_daily_vol": float(r.max_daily_vol) if r.max_daily_vol else None,
        "token_address": r.token_address,
        "token_symbol": r.token_symbol,
        "token_filter": r.token_filter or [],
        "auto_swap": r.auto_swap,
        "swap_to_token": r.swap_to_token,
        "notify_enabled": r.notify_enabled,
        "notify_channel": r.notify_channel,
        "telegram_chat_id": r.telegram_chat_id,
        "email_address": r.email_address,
        "schedule_json": r.schedule_json,
        "version": r.version,
        "chain_id": r.chain_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _serialize_log(lg: SweepLog) -> dict:
    return {
        "id": lg.id,
        "rule_id": lg.rule_id,
        "source_wallet": lg.source_wallet,
        "destination_wallet": lg.destination_wallet,
        "is_split": lg.is_split,
        "split_index": lg.split_index,
        "split_percent": lg.split_percent,
        "split_tx_hash": lg.split_tx_hash,
        "amount_wei": lg.amount_wei,
        "amount_human": lg.amount_human,
        "amount_display": float(lg.amount_display) if lg.amount_display else None,
        "amount_usd": float(lg.amount_usd) if lg.amount_usd else None,
        "primary_amount": float(lg.primary_amount) if lg.primary_amount else None,
        "split_amount": float(lg.split_amount) if lg.split_amount else None,
        "token_symbol": lg.token_symbol,
        "gas_used": lg.gas_used,
        "gas_price_gwei": float(lg.gas_price_gwei) if lg.gas_price_gwei else None,
        "gas_cost_eth": float(lg.gas_cost_eth) if lg.gas_cost_eth else None,
        "gas_percent": lg.gas_percent,
        "status": lg.status.value if lg.status else "unknown",
        "tx_hash": lg.tx_hash,
        "error_message": lg.error_message,
        "retry_count": lg.retry_count,
        "trigger_tx_hash": lg.trigger_tx_hash,
        "fiscal_ref": lg.fiscal_ref,
        "compliance_check": lg.compliance_check,
        "created_at": lg.created_at.isoformat() if lg.created_at else None,
        "executed_at": lg.executed_at.isoformat() if lg.executed_at else None,
    }


def _period_to_timedelta(period: str) -> Optional[timedelta]:
    mapping = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    return mapping.get(period)


# ═══════════════════════════════════════════════════════════
#  POST /api/v1/webhooks/alchemy — Webhook Listener
# ═══════════════════════════════════════════════════════════


@sweeper_router.post("/webhooks/alchemy")
async def alchemy_webhook(request: Request):
    """Alchemy Address Activity Webhook with five-layer security.

    Security chain (all in verify_webhook):
      1. Rate limit   — 100/min per source IP
      2. IP whitelist — known Alchemy egress IPs
      3. HMAC-SHA256  — body signature verification
      4. Timestamp    — createdAt freshness < 5 min
      5. Idempotency  — webhook_id dedup via Redis SETNX

    Responds 200 immediately; background task dispatches to Celery.
    """
    # ── Full security pipeline ────────────────────────────
    try:
        payload = await verify_webhook(request)
    except WebhookVerificationError as exc:
        if exc.status_code == 200:
            # Duplicate webhook — ACK so Alchemy doesn't retry
            return {"status": "duplicate", "reason": exc.reason}
        if exc.status_code == 503:
            # Redis down — tell Alchemy to retry later (fail-closed)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"status": "retry_later", "reason": "idempotency_unavailable"},
            )
        raise HTTPException(status_code=exc.status_code, detail=exc.reason)

    # ── Extract activity ──────────────────────────────────
    webhook_id = payload.get("webhookId", "")
    event = payload.get("event", {})
    network = event.get("network", "")
    activity = event.get("activity", [])

    if not activity:
        return {"status": "ignored", "reason": "no_activity"}

    logger.info(
        "[webhook] Verified & accepted %d activities from %s (network: %s)",
        len(activity), webhook_id[:12], network,
    )

    # ── Respond 200 immediately, process in background ────
    asyncio.create_task(_process_alchemy_activity(activity, network=network))

    return {"status": "accepted", "activity_count": len(activity)}


# ── Redis health check (cached 5s) ────────────────────────
_redis_healthy: bool = False
_redis_checked_at: float = 0.0
_REDIS_CHECK_TTL: float = 5.0

# ── Log rate-limiting for ConnectionRefusedError ──────────
_last_conn_error_log: float = 0.0
_CONN_ERROR_LOG_INTERVAL: float = 60.0

_CELERY_DISPATCH_TIMEOUT: float = 2.0

# ── Celery worker availability check (cached 30s) ───────
_celery_workers_available: bool = False
_celery_workers_checked_at: float = 0.0
_CELERY_CHECK_INTERVAL: float = 30.0


async def _check_celery_workers() -> bool:
    """Return True if at least one Celery worker is registered. Cached for 30s."""
    global _celery_workers_available, _celery_workers_checked_at
    now = time.monotonic()
    if now - _celery_workers_checked_at < _CELERY_CHECK_INTERVAL:
        return _celery_workers_available

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _ping_celery_workers),
            timeout=2.0,
        )
        _celery_workers_available = result
    except (asyncio.TimeoutError, Exception):
        _celery_workers_available = False

    _celery_workers_checked_at = now
    if not _celery_workers_available:
        logger.debug("[webhook] No Celery workers detected — using direct async fallback")
    return _celery_workers_available


def _ping_celery_workers() -> bool:
    """Synchronous Celery worker ping (runs in thread pool)."""
    try:
        from app.celery_app import celery as celery_app
        inspect = celery_app.control.inspect(timeout=1.0)
        pong = inspect.ping()
        return bool(pong)
    except Exception:
        return False


async def _check_redis_health() -> bool:
    """Return True if Redis broker is reachable. Result cached for 5s."""
    global _redis_healthy, _redis_checked_at
    now = time.monotonic()
    if now - _redis_checked_at < _REDIS_CHECK_TTL:
        return _redis_healthy
    try:
        import redis
        settings = get_settings()
        url = settings.celery_broker_url
        r = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        r.ping()
        r.close()
        _redis_healthy = True
    except Exception:
        _redis_healthy = False
    _redis_checked_at = now
    return _redis_healthy


async def _dispatch_to_celery(celery_task, payload: dict) -> bool:
    """Dispatch to Celery in a thread pool with timeout. Returns True on success."""
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, celery_task.delay, payload),
            timeout=_CELERY_DISPATCH_TIMEOUT,
        )
        return True
    except (asyncio.TimeoutError, Exception) as exc:
        global _last_conn_error_log
        now = time.monotonic()
        if now - _last_conn_error_log >= _CONN_ERROR_LOG_INTERVAL:
            logger.warning(
                "[webhook] Celery dispatch failed (%s: %s) — falling back to async",
                type(exc).__name__, exc,
            )
            _last_conn_error_log = now
        return False


_ALCHEMY_NETWORK_TO_CHAIN: dict[str, int] = {
    "BASE_MAINNET": 8453,
    "BASE_SEPOLIA": 84532,
    "ETH_MAINNET": 1,
    "ARB_MAINNET": 42161,
}


async def _process_alchemy_activity(activity: list, network: str = "") -> None:
    """Process Alchemy Address Activity webhook entries in background.

    Fast path: if Redis is healthy, dispatch to Celery via run_in_executor
    with a 2s timeout. If Redis is down or dispatch fails, fall back
    immediately to direct async processing. Never blocks the event loop.
    """
    from app.tasks.sweep_tasks import process_incoming_tx as celery_process_tx

    # Resolve chain_id from Alchemy network string
    chain_id = _ALCHEMY_NETWORK_TO_CHAIN.get(network.upper(), 8453)

    redis_up = await _check_redis_health()

    for tx in activity:
        from_addr = (tx.get("fromAddress") or "").lower()
        to_addr = (tx.get("toAddress") or "").lower()
        value = tx.get("value", 0)
        tx_hash = tx.get("hash", "")
        asset = tx.get("asset", "ETH")
        block_num = tx.get("blockNum")
        category = tx.get("category", "")

        if not to_addr or value <= 0:
            continue

        # Per-TX dedup: protects against Alchemy retrying with different webhook_id
        if tx_hash:
            from app.services.idempotency_service import is_tx_processed, mark_tx_processed
            if await is_tx_processed(tx_hash):
                logger.info("[webhook] TX %s already processed, skipping", tx_hash[:16])
                continue

        # ERC-20: extract contract address and decimals from rawContract
        raw_contract = tx.get("rawContract") or {}
        token_address = (raw_contract.get("address") or "").lower() or None
        token_decimals = int(raw_contract.get("decimals") or 18)

        if token_address and token_address == "0x":
            token_address = None

        # Resolve token from registry for reliable symbol + decimals
        token_info = (
            _registry_get_token(chain_id, token_address)
            if token_address
            else _registry_get_native(chain_id)
        )
        if token_info:
            asset = token_info.symbol
            token_decimals = token_info.decimals

        logger.info(
            "[webhook] TX %s: %s -> %s | %.6f %s | cat=%s | chain=%d | block=%s",
            tx_hash[:16] if tx_hash else "?",
            from_addr[:10], to_addr[:10],
            value, asset, category, chain_id, block_num,
        )

        # Build Celery payload matching sweep_tasks.process_incoming_tx schema
        payload = {
            "tx_hash": tx_hash,
            "from_address": from_addr,
            "to_address": to_addr,
            "value_wei": str(int(value * 10**token_decimals)) if value else "0",
            "chain_id": chain_id,
            "token_address": token_address,
            "token_symbol": asset,
            "block_number": block_num,
        }

        # ── Split contract priority path ──────────────────
        # Se esiste uno SplitContract attivo per questo (wallet, chain),
        # esegui il piano multi-wallet (SplitEngine + SplitExecutor) PRIMA
        # delle forwarding rules. Idempotente su (contract_id, tx_hash):
        # una stessa TX non viene mai ri-splittata.
        # Se ritorna handled=True, skip forwarding rules per questa TX.
        try:
            from app.services.split_webhook_bridge import maybe_execute_split

            split_result = await maybe_execute_split(
                to_addr=to_addr,
                chain_id=chain_id,
                amount_human=value,
                token_symbol=asset,
                token_decimals=token_decimals,
                source_tx_hash=tx_hash,
            )
        except Exception as split_err:
            logger.error(
                "[webhook] split bridge raised for TX %s: %s — falling back to forwarding",
                tx_hash[:16] if tx_hash else "?", split_err,
            )
            split_result = None

        if split_result is not None and split_result.get("handled"):
            logger.info(
                "[webhook] Split handled TX %s: contract=%s execution=%s status=%s%s",
                tx_hash[:16] if tx_hash else "?",
                split_result.get("contract_id"),
                split_result.get("execution_id"),
                split_result.get("status"),
                " (duplicate)" if split_result.get("duplicate") else "",
            )
            if tx_hash:
                await mark_tx_processed(tx_hash)
            continue  # Skip forwarding rules for this TX

        # Fast path: Celery via thread pool (non-blocking, 2s timeout)
        # Only dispatch if Redis is up AND at least one Celery worker is running
        dispatched = False
        if redis_up and await _check_celery_workers():
            dispatched = await _dispatch_to_celery(celery_process_tx, payload)

        # Slow path: direct async processing (still non-blocking)
        if not dispatched:
            try:
                await process_incoming_tx(
                    from_addr=from_addr,
                    to_addr=to_addr,
                    value=value,
                    tx_hash=tx_hash,
                    asset=asset,
                    token_address=token_address,
                    token_decimals=token_decimals,
                    block_num=block_num,
                )
            except Exception as e:
                logger.error(
                    "[webhook] process_incoming_tx failed for TX %s: %s",
                    tx_hash[:16] if tx_hash else "?", e,
                )

        if tx_hash:
            await mark_tx_processed(tx_hash)


# ═══════════════════════════════════════════════════════════
#  1. POST /forwarding/rules — Crea regola
# ═══════════════════════════════════════════════════════════

@sweeper_router.post("/forwarding/rules")
@require_wallet_auth
async def create_rule(
    request: Request,
    payload: CreateRulePayload,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    owner = wallet_address.lower()

    # Must have either destination_wallet or distribution_list_id
    if not payload.destination_wallet and not payload.distribution_list_id:
        raise HTTPException(
            status_code=422,
            detail="Either destination_wallet or distribution_list_id is required",
        )

    # Validate distribution_list_id if provided
    dist_list_id = None
    if payload.distribution_list_id:
        try:
            dist_list_id = uuid.UUID(payload.distribution_list_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid distribution_list_id format")

        from app.models.command_models import DistributionList
        dl_result = await db.execute(
            select(DistributionList).where(
                DistributionList.id == dist_list_id,
                DistributionList.is_active == True,  # noqa: E712
            )
        )
        dl = dl_result.scalar_one_or_none()
        if not dl:
            raise HTTPException(status_code=404, detail="Distribution list not found")
        if dl.owner_address != owner:
            raise HTTPException(status_code=403, detail="Not the owner of this distribution list")

    # Limite regole per owner
    count_result = await db.execute(
        select(func.count()).select_from(ForwardingRule).where(
            ForwardingRule.user_id == owner,
            ForwardingRule.is_active == True,  # noqa: E712
        )
    )
    if count_result.scalar() >= MAX_RULES_PER_OWNER:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum {MAX_RULES_PER_OWNER} active rules per owner",
        )

    # Split validation
    if payload.split_enabled and not payload.split_destination:
        raise HTTPException(status_code=422, detail="split_destination required when split_enabled is true")
    if payload.split_enabled and payload.split_percent == 100:
        raise HTTPException(status_code=422, detail="split_percent must be < 100 when split is enabled")

    rule = ForwardingRule(
        user_id=owner,
        source_wallet=payload.source_wallet,
        destination_wallet=payload.destination_wallet,
        distribution_list_id=dist_list_id,
        label=payload.label,
        split_enabled=payload.split_enabled,
        split_percent=payload.split_percent,
        split_destination=payload.split_destination,
        min_threshold=payload.min_threshold,
        gas_strategy=GasStrategy(payload.gas_strategy),
        max_gas_percent=payload.max_gas_percent,
        gas_limit_gwei=payload.gas_limit_gwei,
        cooldown_sec=payload.cooldown_sec,
        max_daily_vol=payload.max_daily_vol,
        token_address=payload.token_address,
        token_symbol=payload.token_symbol,
        token_filter=payload.token_filter,
        auto_swap=payload.auto_swap,
        swap_to_token=payload.swap_to_token,
        notify_enabled=payload.notify_enabled,
        notify_channel=payload.notify_channel,
        telegram_chat_id=payload.telegram_chat_id,
        email_address=payload.email_address,
        schedule_json=payload.schedule_json,
        chain_id=payload.chain_id,
        version=1,
    )
    db.add(rule)
    await db.flush()

    audit = AuditLog(
        rule_id=rule.id,
        action="create",
        actor=owner,
        new_values=_serialize_rule(rule),
    )
    db.add(audit)
    await db.commit()

    # Register source address with Alchemy webhook (background, non-blocking)
    asyncio.create_task(
        alchemy_webhook_manager.add_address_to_webhook(
            rule.source_wallet, rule.chain_id
        )
    )

    return _response({"status": "created", "rule": _serialize_rule(rule)})


# ═══════════════════════════════════════════════════════════
#  2. GET /forwarding/rules — Lista regole
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/rules")
@require_wallet_auth
async def list_rules(
    request: Request,
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()

    result = await db.execute(
        select(ForwardingRule).where(
            ForwardingRule.user_id == owner,
        ).order_by(ForwardingRule.created_at.desc())
    )
    rules = result.scalars().all()

    items = []
    for r in rules:
        # Stats base per ogni regola
        stats_q = await db.execute(
            select(
                func.count().label("sweep_count"),
                func.max(SweepLog.executed_at).label("last_sweep"),
            ).where(SweepLog.rule_id == r.id)
        )
        stats = stats_q.one()

        item = _serialize_rule(r)
        item["sweep_count"] = stats.sweep_count
        item["last_sweep"] = stats.last_sweep.isoformat() if stats.last_sweep else None
        items.append(item)

    return _response({"rules": items, "total": len(items)})


# ═══════════════════════════════════════════════════════════
#  3. GET /forwarding/rules/{rule_id} — Dettaglio
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/rules/{rule_id}")
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
):
    rule = await _get_rule_or_404(db, rule_id)

    stats_q = await db.execute(
        select(
            func.count().label("total_sweeps"),
            func.count().filter(SweepLog.status == SweepStatus.completed).label("completed"),
            func.count().filter(SweepLog.status == SweepStatus.failed).label("failed"),
            func.sum(SweepLog.amount_human).label("total_volume"),
            func.sum(
                case((SweepLog.gas_cost_eth.isnot(None), SweepLog.gas_cost_eth), else_=0)
            ).label("total_gas"),
            func.max(SweepLog.executed_at).label("last_sweep"),
        ).where(SweepLog.rule_id == rule_id)
    )
    stats = stats_q.one()

    data = _serialize_rule(rule)
    data["stats"] = {
        "total_sweeps": stats.total_sweeps,
        "completed": stats.completed,
        "failed": stats.failed,
        "total_volume_eth": float(stats.total_volume or 0),
        "total_gas_eth": float(stats.total_gas or 0),
        "last_sweep": stats.last_sweep.isoformat() if stats.last_sweep else None,
        "success_rate": round(stats.completed / stats.total_sweeps * 100, 1) if stats.total_sweeps > 0 else 0,
    }

    return _response({"rule": data})


# ═══════════════════════════════════════════════════════════
#  4. PUT /forwarding/rules/{rule_id} — Aggiorna
# ═══════════════════════════════════════════════════════════

@sweeper_router.put("/forwarding/rules/{rule_id}")
@require_wallet_auth
async def update_rule(
    request: Request,
    rule_id: int,
    payload: UpdateRulePayload,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    rule = await _get_rule_or_404(db, rule_id)
    await _verify_owner(rule, wallet_address)

    # Optimistic locking: opt-in. Verifica solo se il client ha inviato version.
    if payload.version is not None and rule.version != payload.version:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "VERSION_CONFLICT",
                "message": "Rule was modified by another request. Refresh and retry.",
                "current_version": rule.version,
                "submitted_version": payload.version,
            },
        )

    old_values = _serialize_rule(rule)

    # Build update dict — only include explicitly set fields
    updates = {}
    update_fields = payload.model_dump(exclude={"version"}, exclude_unset=True)

    # source_wallet is immutable (security)
    if "source_wallet" in update_fields:
        raise HTTPException(status_code=422, detail="Cannot modify source_wallet")

    # Handle distribution_list_id
    if "distribution_list_id" in update_fields:
        dl_id_str = update_fields.pop("distribution_list_id")
        if dl_id_str is not None:
            try:
                dl_uuid = uuid.UUID(dl_id_str)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid distribution_list_id format")
            from app.models.command_models import DistributionList
            dl_result = await db.execute(
                select(DistributionList).where(
                    DistributionList.id == dl_uuid,
                    DistributionList.is_active == True,  # noqa: E712
                )
            )
            if not dl_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Distribution list not found")
            updates["distribution_list_id"] = dl_uuid
        else:
            updates["distribution_list_id"] = None

    for field, value in update_fields.items():
        if field == "gas_strategy" and value is not None:
            updates[field] = GasStrategy(value)
        else:
            updates[field] = value

    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    # Split validation
    split_enabled = updates.get("split_enabled", rule.split_enabled)
    split_pct = updates.get("split_percent", rule.split_percent)
    split_dest = updates.get("split_destination", rule.split_destination)
    if split_enabled and not split_dest:
        raise HTTPException(status_code=422, detail="split_destination required when split_enabled is true")
    if split_enabled and split_pct == 100:
        raise HTTPException(status_code=422, detail="split_percent must be < 100 when split is enabled")

    for field, value in updates.items():
        setattr(rule, field, value)

    # Increment version
    rule.version += 1

    await db.flush()

    new_values = _serialize_rule(rule)
    # Compute diff — only log changed fields
    changed_old = {}
    changed_new = {}
    for key in new_values:
        if old_values.get(key) != new_values.get(key) and key not in ("updated_at", "version"):
            changed_old[key] = old_values.get(key)
            changed_new[key] = new_values.get(key)

    audit = AuditLog(
        rule_id=rule.id,
        action="update",
        actor=wallet_address.lower(),
        old_values=changed_old,
        new_values=changed_new,
    )
    db.add(audit)
    await db.commit()

    # ── WS: rule_updated ────────────────────────────
    await feed_manager.broadcast(wallet_address.lower(), "rule_updated", {
        "rule_id": rule.id,
        "action": "update",
        "changed_fields": list(changed_new.keys()),
        "new_values": changed_new,
    })

    return _response({"status": "updated", "rule": new_values})


# ═══════════════════════════════════════════════════════════
#  5. DELETE /forwarding/rules/{rule_id}
# ═══════════════════════════════════════════════════════════

@sweeper_router.delete("/forwarding/rules/{rule_id}")
@require_wallet_auth
async def delete_rule(
    request: Request,
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    rule = await _get_rule_or_404(db, rule_id)
    await _verify_owner(rule, wallet_address)

    # Controlla se ci sono sweep logs
    log_count = await db.execute(
        select(func.count()).select_from(SweepLog).where(SweepLog.rule_id == rule_id)
    )
    has_logs = log_count.scalar() > 0

    action = "soft_delete" if has_logs else "delete"

    # Audit log creato e flushato PRIMA del delete: rule_id ancora valido,
    # old_values cattura lo stato pre-mutazione. Su hard-delete il successivo
    # ondelete=SET NULL azzererà rule_id anche su questa riga, ma action,
    # actor e old_values["id"] preservano l'identità per DAC8.
    audit = AuditLog(
        rule_id=rule_id,
        action=action,
        actor=wallet_address.lower(),
        old_values=_serialize_rule(rule),
    )
    db.add(audit)
    await db.flush()

    if has_logs:
        # Soft delete — mantieni per audit trail
        rule.is_active = False
        rule.is_paused = True
    else:
        # Hard delete — nessun log collegato
        await db.delete(rule)

    await db.commit()

    # Remove source address from Alchemy webhook if no other rules need it
    asyncio.create_task(
        alchemy_webhook_manager.remove_address_from_webhook(
            rule.source_wallet, rule.chain_id
        )
    )

    return _response({"status": "deleted", "mode": "soft" if has_logs else "hard", "rule_id": rule_id})


# ═══════════════════════════════════════════════════════════
#  6. POST /forwarding/rules/{rule_id}/pause
# ═══════════════════════════════════════════════════════════

@sweeper_router.post("/forwarding/rules/{rule_id}/pause")
@require_wallet_auth
async def pause_rule(
    request: Request,
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    rule = await _get_rule_or_404(db, rule_id)
    await _verify_owner(rule, wallet_address)

    if rule.is_paused:
        raise HTTPException(status_code=409, detail="Rule is already paused")

    rule.is_paused = True
    audit = AuditLog(rule_id=rule_id, action="pause", actor=wallet_address.lower())
    db.add(audit)
    await db.commit()

    await feed_manager.broadcast(wallet_address.lower(), "rule_updated", {
        "rule_id": rule_id, "action": "pause",
    })

    return _response({"status": "paused", "rule_id": rule_id})


# ═══════════════════════════════════════════════════════════
#  7. POST /forwarding/rules/{rule_id}/resume
# ═══════════════════════════════════════════════════════════

@sweeper_router.post("/forwarding/rules/{rule_id}/resume")
@require_wallet_auth
async def resume_rule(
    request: Request,
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    rule = await _get_rule_or_404(db, rule_id)
    await _verify_owner(rule, wallet_address)

    if not rule.is_paused:
        raise HTTPException(status_code=409, detail="Rule is not paused")

    rule.is_paused = False
    audit = AuditLog(rule_id=rule_id, action="resume", actor=wallet_address.lower())
    db.add(audit)
    await db.commit()

    await feed_manager.broadcast(wallet_address.lower(), "rule_updated", {
        "rule_id": rule_id, "action": "resume",
    })

    return _response({"status": "resumed", "rule_id": rule_id})


# ═══════════════════════════════════════════════════════════
#  8. POST /forwarding/emergency-stop
# ═══════════════════════════════════════════════════════════

@sweeper_router.post("/forwarding/emergency-stop")
@require_wallet_auth
async def emergency_stop(
    request: Request,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    owner = wallet_address.lower()

    result = await db.execute(
        select(ForwardingRule).where(
            ForwardingRule.user_id == owner,
            ForwardingRule.is_active == True,   # noqa: E712
            ForwardingRule.is_paused == False,   # noqa: E712
        )
    )
    rules = result.scalars().all()

    if not rules:
        return _response({"status": "no_active_rules", "paused_count": 0})

    paused_ids = []
    for rule in rules:
        rule.is_paused = True
        audit = AuditLog(rule_id=rule.id, action="emergency_stop", actor=owner)
        db.add(audit)
        paused_ids.append(rule.id)

    await db.commit()

    await feed_manager.broadcast(owner, "emergency_stop", {
        "paused_count": len(paused_ids),
        "paused_rule_ids": paused_ids,
    })

    return _response({
        "status": "emergency_stop",
        "paused_count": len(paused_ids),
        "paused_rule_ids": paused_ids,
    })


# ═══════════════════════════════════════════════════════════
#  9. GET /forwarding/logs — Sweep logs (paginati)
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/logs")
@require_wallet_auth
async def list_logs(
    request: Request,
    rule_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="pending|executing|completed|failed|gas_too_high"),
    token: Optional[str] = Query(None, description="Filter by token symbol"),
    date_from: Optional[datetime] = Query(None, description="ISO datetime"),
    date_to: Optional[datetime] = Query(None, description="ISO datetime"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()

    # Subquery: rule IDs belonging to this owner
    rule_ids_q = select(ForwardingRule.id).where(ForwardingRule.user_id == owner)

    # Base query
    q = select(SweepLog).where(SweepLog.rule_id.in_(rule_ids_q))
    count_q = select(func.count()).select_from(SweepLog).where(SweepLog.rule_id.in_(rule_ids_q))

    # Filters
    if rule_id is not None:
        q = q.where(SweepLog.rule_id == rule_id)
        count_q = count_q.where(SweepLog.rule_id == rule_id)
    if status:
        try:
            status_enum = SweepStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        q = q.where(SweepLog.status == status_enum)
        count_q = count_q.where(SweepLog.status == status_enum)
    if token:
        q = q.where(SweepLog.token_symbol == token.upper())
        count_q = count_q.where(SweepLog.token_symbol == token.upper())
    if date_from:
        q = q.where(SweepLog.created_at >= date_from)
        count_q = count_q.where(SweepLog.created_at >= date_from)
    if date_to:
        q = q.where(SweepLog.created_at <= date_to)
        count_q = count_q.where(SweepLog.created_at <= date_to)

    # Count
    total = (await db.execute(count_q)).scalar()

    # Paginate
    offset = (page - 1) * per_page
    q = q.order_by(SweepLog.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(q)
    logs = result.scalars().all()

    return _response({
        "logs": [_serialize_log(lg) for lg in logs],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page if total else 0,
        },
    })


# ═══════════════════════════════════════════════════════════
#  10. GET /forwarding/logs/export — Export CSV/JSON
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/logs/export")
@require_wallet_auth
async def export_logs(
    request: Request,
    format: str = Query("csv", description="csv or json"),
    rule_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="format must be csv or json")

    rule_ids_q = select(ForwardingRule.id).where(ForwardingRule.user_id == owner)
    q = select(SweepLog).where(SweepLog.rule_id.in_(rule_ids_q))

    if rule_id is not None:
        q = q.where(SweepLog.rule_id == rule_id)
    if status:
        q = q.where(SweepLog.status == SweepStatus(status))
    if token:
        q = q.where(SweepLog.token_symbol == token.upper())
    if date_from:
        q = q.where(SweepLog.created_at >= date_from)
    if date_to:
        q = q.where(SweepLog.created_at <= date_to)

    q = q.order_by(SweepLog.created_at.desc()).limit(5000)
    result = await db.execute(q)
    logs = result.scalars().all()
    rows = [_serialize_log(lg) for lg in logs]

    if format == "json":
        return {"logs": rows, "count": len(rows)}

    # CSV streaming
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    content = output.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sweep_logs.csv"},
    )


# ═══════════════════════════════════════════════════════════
#  11. GET /forwarding/stats — Statistiche aggregate
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/stats")
@require_wallet_auth
async def get_stats(
    request: Request,
    period: str = Query("30d", description="24h|7d|30d|all"),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()
    rule_ids_q = select(ForwardingRule.id).where(ForwardingRule.user_id == owner)

    q_base = SweepLog.rule_id.in_(rule_ids_q)
    td = _period_to_timedelta(period)
    if td:
        cutoff = datetime.now(timezone.utc) - td
        time_filter = SweepLog.created_at >= cutoff
    else:
        time_filter = True  # "all" — no time filter

    result = await db.execute(
        select(
            func.count().label("total_sweeps"),
            func.count().filter(SweepLog.status == SweepStatus.completed).label("completed"),
            func.count().filter(SweepLog.status == SweepStatus.failed).label("failed"),
            func.coalesce(func.sum(SweepLog.amount_human), 0).label("total_volume_eth"),
            func.coalesce(func.sum(
                case((SweepLog.amount_usd.isnot(None), SweepLog.amount_usd), else_=0)
            ), 0).label("total_volume_usd"),
            func.coalesce(func.sum(
                case((SweepLog.gas_cost_eth.isnot(None), SweepLog.gas_cost_eth), else_=0)
            ), 0).label("total_gas_spent"),
            func.avg(
                case(
                    (SweepLog.executed_at.isnot(None),
                     func.extract("epoch", SweepLog.executed_at) - func.extract("epoch", SweepLog.created_at)),
                    else_=None,
                )
            ).label("avg_sweep_seconds"),
        ).where(q_base, time_filter)
    )
    row = result.one()

    total = row.total_sweeps
    success_rate = round(row.completed / total * 100, 1) if total > 0 else 0

    # ── Per-token volume breakdown ────────────────────
    token_vol_result = await db.execute(
        select(
            SweepLog.token_symbol,
            func.coalesce(func.sum(SweepLog.amount_human), 0).label("amount"),
            func.coalesce(func.sum(
                case((SweepLog.amount_usd.isnot(None), SweepLog.amount_usd), else_=0)
            ), 0).label("eur"),
        )
        .where(q_base, time_filter, SweepLog.status == SweepStatus.completed)
        .group_by(SweepLog.token_symbol)
    )
    token_vol_rows = token_vol_result.all()
    total_volume_by_token = {
        r.token_symbol: {
            "amount": str(round(float(r.amount), 6)),
            "eur": round(float(r.eur), 2),
        }
        for r in token_vol_rows
        if r.token_symbol
    }

    return _response({
        "period": period,
        "total_sweeps": total,
        "completed": row.completed,
        "failed": row.failed,
        "total_volume_eth": round(float(row.total_volume_eth), 6),
        "total_volume_usd": round(float(row.total_volume_usd), 2),
        "total_gas_spent_eth": round(float(row.total_gas_spent), 8),
        "avg_sweep_time_sec": round(float(row.avg_sweep_seconds), 1) if row.avg_sweep_seconds else None,
        "success_rate": success_rate,
        "total_volume_by_token": total_volume_by_token,
    })


# ═══════════════════════════════════════════════════════════
#  12. GET /forwarding/stats/daily — Volume giornaliero
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/stats/daily")
@require_wallet_auth
async def get_daily_stats(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()
    rule_ids_q = select(ForwardingRule.id).where(ForwardingRule.user_id == owner)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            cast(SweepLog.created_at, Date).label("date"),
            func.count().label("sweep_count"),
            func.coalesce(func.sum(SweepLog.amount_human), 0).label("volume_eth"),
            func.coalesce(func.sum(
                case((SweepLog.amount_usd.isnot(None), SweepLog.amount_usd), else_=0)
            ), 0).label("volume_usd"),
            func.coalesce(func.sum(
                case((SweepLog.gas_cost_eth.isnot(None), SweepLog.gas_cost_eth), else_=0)
            ), 0).label("gas_total"),
        )
        .where(SweepLog.rule_id.in_(rule_ids_q), SweepLog.created_at >= cutoff)
        .group_by(cast(SweepLog.created_at, Date))
        .order_by(cast(SweepLog.created_at, Date))
    )
    rows = result.all()

    return _response({
        "period_days": days,
        "data": [
            {
                "date": row.date.isoformat() if row.date else None,
                "sweep_count": row.sweep_count,
                "volume_eth": round(float(row.volume_eth), 6),
                "volume_usd": round(float(row.volume_usd), 2),
                "gas_total": round(float(row.gas_total), 8),
            }
            for row in rows
        ],
    })


# ═══════════════════════════════════════════════════════════
#  13. GET /forwarding/rules/{rule_id}/batches — Sweep batches
# ═══════════════════════════════════════════════════════════

def _serialize_batch(b: SweepBatch) -> dict:
    return {
        "id": str(b.id),
        "incoming_tx_hash": b.incoming_tx_hash,
        "source_address": b.source_address,
        "chain_id": b.chain_id,
        "total_amount_wei": b.total_amount_wei,
        "token_symbol": b.token_symbol,
        "status": b.status,
        "item_count": len(b.items) if b.items else 0,
        "gas_price_wei": b.gas_price_wei,
        "total_gas_cost_wei": b.total_gas_cost_wei,
        "error_message": b.error_message,
        "retry_count": b.retry_count,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "items": [
            {
                "id": str(item.id),
                "recipient_address": item.recipient_address,
                "amount_wei": item.amount_wei,
                "percent_bps": item.percent_bps,
                "tx_hash": item.tx_hash,
                "status": item.status,
                "gas_used": item.gas_used,
                "error_message": item.error_message,
            }
            for item in (b.items or [])
        ],
    }


@sweeper_router.get("/forwarding/rules/{rule_id}/batches")
async def list_batches(
    rule_id: int,
    status: Optional[str] = Query(None, description="PENDING|PROCESSING|COMPLETED|FAILED|PARTIAL"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # Verify rule exists
    await _get_rule_or_404(db, rule_id)

    q = select(SweepBatch).where(SweepBatch.forwarding_rule_id == rule_id)
    count_q = select(func.count()).select_from(SweepBatch).where(
        SweepBatch.forwarding_rule_id == rule_id,
    )

    if status:
        valid_statuses = {"PENDING", "PROCESSING", "COMPLETED", "FAILED", "PARTIAL"}
        if status.upper() not in valid_statuses:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        q = q.where(SweepBatch.status == status.upper())
        count_q = count_q.where(SweepBatch.status == status.upper())
    if date_from:
        q = q.where(SweepBatch.created_at >= date_from)
        count_q = count_q.where(SweepBatch.created_at >= date_from)
    if date_to:
        q = q.where(SweepBatch.created_at <= date_to)
        count_q = count_q.where(SweepBatch.created_at <= date_to)

    total = (await db.execute(count_q)).scalar()
    offset = (page - 1) * per_page
    q = q.order_by(SweepBatch.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(q)
    batches = result.scalars().all()

    return _response({
        "batches": [_serialize_batch(b) for b in batches],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page if total else 0,
        },
    })


# ═══════════════════════════════════════════════════════════
#  14. GET /forwarding/spending-limits — Spending limits status
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/spending-limits")
async def spending_limits_status(
    source_address: str = Query(..., description="Source wallet address"),
    chain_id: int = Query(8453),
):
    source = source_address.lower()
    if not ETH_ADDR_RE.match(source_address):
        raise HTTPException(status_code=422, detail="Invalid source_address format")

    try:
        from app.services.spending_policy import SpendingPolicy
        policy = SpendingPolicy()
        status = await policy.get_status(source, chain_id)

        return _response({
            "source_address": status.source,
            "chain_id": status.chain_id,
            "limits": {
                "per_hour": {
                    "spent_wei": status.per_hour_spent_wei,
                    "limit_wei": status.per_hour_limit_wei,
                },
                "per_day": {
                    "spent_wei": status.per_day_spent_wei,
                    "limit_wei": status.per_day_limit_wei,
                },
                "global_daily": {
                    "spent_wei": status.global_daily_spent_wei,
                    "limit_wei": status.global_daily_limit_wei,
                },
                "velocity": {
                    "sweeps_this_hour": status.sweeps_this_hour,
                    "max_sweeps_per_hour": status.max_sweeps_per_hour,
                },
            },
        })
    except Exception as exc:
        logger.warning("[spending] Failed to get status: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Spending limits status temporarily unavailable",
        )


# ═══════════════════════════════════════════════════════════
#  GAS ESTIMATION — L2 + L1 fee breakdown
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/forwarding/estimate-gas")
async def estimate_gas(
    recipients: int = Query(ge=1, le=1000, description="Number of recipients"),
    chain_id: int = Query(default=8453, description="Chain ID"),
):
    """Estimate total gas cost for a distribution (L2 execution + L1 data fee).

    Returns fee breakdown so the frontend can show accurate cost estimates,
    especially on OP Stack chains where L1 data fee can be 50-90% of total.
    """
    from app.services.gas_estimator import estimate_distribution_cost

    try:
        estimate = await estimate_distribution_cost(recipients, chain_id)
        return {
            "chain_id": chain_id,
            "recipients": recipients,
            **estimate,
        }
    except Exception as exc:
        logger.warning("Gas estimation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Gas estimation unavailable")


# ═══════════════════════════════════════════════════════════
#  HEALTH CHECK — Sweep Subsystem
# ═══════════════════════════════════════════════════════════

@sweeper_router.get("/health/sweep")
async def health_sweep(db: AsyncSession = Depends(get_db)):
    """
    Sweep subsystem health check.
    Verifies: DB connection, Redis connection, recent sweep activity, WebSocket status.
    """
    checks = {}
    healthy = True

    # 1. DB connection
    try:
        await db.execute(select(func.count()).select_from(ForwardingRule))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"
        healthy = False

    # 2. Redis connection
    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"
        healthy = False

    # 3. Last sweep freshness (only relevant if active rules exist)
    try:
        active_count = (await db.execute(
            select(func.count()).select_from(ForwardingRule).where(
                ForwardingRule.is_active == True,
                ForwardingRule.is_paused == False,
            )
        )).scalar() or 0

        checks["active_rules"] = active_count

        # Refresh Prometheus gauge
        from app.services.sweep_service import refresh_active_rules_gauge, ACTIVE_RULES_TOTAL
        ACTIVE_RULES_TOTAL.set(active_count)

        if active_count > 0:
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            last_sweep = (await db.execute(
                select(SweepLog.created_at)
                .where(SweepLog.status == SweepStatus.completed)
                .order_by(SweepLog.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()

            if last_sweep and last_sweep >= one_hour_ago:
                checks["last_sweep"] = "ok"
            elif last_sweep:
                checks["last_sweep"] = f"stale: last at {last_sweep.isoformat()}"
            else:
                checks["last_sweep"] = "no completed sweeps"
        else:
            checks["last_sweep"] = "n/a (no active rules)"
    except Exception as e:
        checks["last_sweep"] = f"error: {str(e)[:100]}"

    # 4. WebSocket server
    try:
        from app.api.websocket_routes import feed_manager
        checks["websocket"] = {
            "status": "ok",
            "active_connections": feed_manager.active_connections,
        }
    except Exception as e:
        checks["websocket"] = f"error: {str(e)[:100]}"
        healthy = False

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "degraded",
            "service": "sweep-subsystem",
            "checks": checks,
        },
    )
