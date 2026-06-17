"""
RSends Backend — Sweep Execution Service v3

Full Command Center sweep pipeline:
  - Multi-chain EVM (Base, Ethereum, Arbitrum)
  - ETH native + ERC-20 token transfers
  - Redis distributed lock (anti double-sweep)
  - Rule validation: schedule, cooldown, daily volume, token filter, gas limit
  - EIP-1559 gas estimation with eth_estimateGas
  - Split routing (2 sequential TXs)
  - Retry with exponential backoff (max 3)
  - Notifications: WebSocket + Telegram + email (stub)
"""

import asyncio
import json
import logging
import time as _time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from prometheus_client import Counter, Histogram, Gauge
from sqlalchemy import select, update, func, cast, Date

from app.config import get_settings
from app.db.session import async_session
from app.tokens.registry import (
    get_token as _registry_get_token,
    get_native as _registry_get_native,
    get_decimals as _registry_get_decimals,
    TOKEN_REGISTRY as _UNIFIED_REGISTRY,
    TokenInfo,
)
from app.services.price_service import get_usd_value, get_eur_value
from app.models.forwarding_models import (
    ForwardingRule, SweepLog, SweepStatus, GasStrategy,
)
from app.services.cache_service import get_redis
from app.services.circuit_breaker import (
    CircuitBreaker, CircuitOpenError, SweepBlockedError, dependency_guard,
)
from app.services.rpc_manager import get_rpc_manager

logger = logging.getLogger("sweep_service")

# ── Prometheus Metrics ─────────────────────────────────────
SWEEP_TOTAL = Counter(
    "sweep_total",
    "Total sweep executions",
    ["status", "chain_id"],
)
SWEEP_LATENCY = Histogram(
    "sweep_latency_seconds",
    "Sweep execution duration",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
)
SWEEP_AMOUNT_ETH = Histogram(
    "sweep_amount_eth",
    "Sweep amount in ETH (or ETH-equivalent)",
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 50],
)
SWEEP_GAS_GWEI = Gauge(
    "sweep_gas_gwei",
    "Last observed gas price in gwei",
    ["chain_id"],
)
ACTIVE_RULES_TOTAL = Gauge(
    "active_rules_total",
    "Number of active (non-paused) forwarding rules",
)


async def refresh_active_rules_gauge():
    """Update the active_rules_total Prometheus gauge."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(func.count()).select_from(ForwardingRule).where(
                    ForwardingRule.is_active == True,
                    ForwardingRule.is_paused == False,
                )
            )
            ACTIVE_RULES_TOTAL.set(result.scalar() or 0)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

# Supported chains (provider URLs are managed by RPCManager)
SUPPORTED_CHAINS: set[int] = {8453, 84532, 1, 42161}

CHAIN_NAMES: dict[int, str] = {
    8453: "Base", 84532: "Base Sepolia",
    1: "Ethereum", 42161: "Arbitrum One",
}

# L2 chains that use EIP-1559 (type 2) transactions
EIP1559_CHAINS = {8453, 84532, 42161}

GAS_MULT: dict[GasStrategy, float] = {
    GasStrategy.fast:   1.5,
    GasStrategy.normal: 1.1,
    GasStrategy.slow:   0.9,
}

# Token registry — delegated to app.tokens.registry (single source of truth)
# Legacy dict format for backward compatibility within this file
TOKEN_REGISTRY: dict[tuple[int, str], dict] = {
    k: {"symbol": t.symbol, "decimals": t.decimals, "name": t.name}
    for k, t in _UNIFIED_REGISTRY.items()
    if k[1] != "native"  # exclude native tokens (ETH) — sweep deals with ERC-20
}

# ERC-20 transfer(address,uint256) function selector
ERC20_TRANSFER_SELECTOR = "a9059cbb"

MAX_RETRY_COUNT = 3
RETRY_BASE_DELAY = 10  # seconds
LOCK_TTL = 300          # 5 minutes




# ═══════════════════════════════════════════════════════════════
#  REDIS DISTRIBUTED LOCK
# ═══════════════════════════════════════════════════════════════

async def acquire_sweep_lock(key: str, ttl: int = LOCK_TTL) -> bool:
    """SETNX-based distributed lock. Returns True if acquired.

    Fail-closed: if Redis is unavailable, returns False to prevent
    duplicate sweeps. The DB-level dedup in process_incoming_tx
    provides the safety net for legitimate sweeps.
    """
    try:
        r = await get_redis()
        return bool(await r.set(f"sweep_lock:{key}", "1", nx=True, ex=ttl))
    except Exception:
        logger.warning("Redis lock unavailable for %s — rejecting (fail-closed)", key)
        return False  # fail-closed: reject to prevent duplicate sweeps

_acquire_lock = acquire_sweep_lock


async def release_sweep_lock(key: str) -> None:
    """Release a distributed lock."""
    try:
        r = await get_redis()
        await r.delete(f"sweep_lock:{key}")
    except Exception:
        pass

_release_lock = release_sweep_lock


HEARTBEAT_INTERVAL_S = 60
HEARTBEAT_EXTEND_TTL_S = 300


async def _heartbeat_loop(key: str) -> None:
    """Extend the sweep lock TTL periodically until cancelled."""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            r = await get_redis()
            if r is not None:
                await r.expire(f"sweep_lock:{key}", HEARTBEAT_EXTEND_TTL_S)
                logger.debug(
                    "Sweep heartbeat extended: key=%s ttl=%ds",
                    key, HEARTBEAT_EXTEND_TTL_S,
                )
        except asyncio.CancelledError:
            logger.debug("Sweep heartbeat cancelled: key=%s", key)
            raise
        except Exception as e:
            logger.warning(
                "Sweep heartbeat error (will retry): key=%s err=%s", key, e,
            )


def start_sweep_heartbeat(key: str) -> asyncio.Task:
    """Start a background heartbeat task for the given lock key.

    Returns the Task handle — caller MUST cancel it when the
    protected work completes, regardless of success/failure.
    """
    return asyncio.create_task(
        _heartbeat_loop(key),
        name=f"sweep_heartbeat:{key}",
    )


async def stop_sweep_heartbeat(task: asyncio.Task) -> None:
    """Cancel a heartbeat task and wait for it to exit cleanly."""
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning("Sweep heartbeat task ended with error: %s", e)


# ═══════════════════════════════════════════════════════════════
#  VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════

def _check_schedule(rule: ForwardingRule) -> tuple[bool, Optional[str]]:
    """Check if current time is within the rule's schedule window."""
    if not rule.schedule_json:
        return True, None

    sched = rule.schedule_json
    tz_name = sched.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    allowed_days = sched.get("days")  # list of weekday ints (0=Mon..6=Sun)
    if allowed_days is not None and now.weekday() not in allowed_days:
        return False, f"Schedule: day {now.strftime('%A')} not in allowed days"

    h_start = sched.get("hours_start", 0)
    h_end = sched.get("hours_end", 24)
    if not (h_start <= now.hour < h_end):
        return False, f"Schedule: hour {now.hour} outside {h_start}-{h_end}"

    return True, None


async def _check_cooldown(rule: ForwardingRule) -> tuple[bool, Optional[str]]:
    """Check that enough time has passed since the last completed sweep."""
    if rule.cooldown_sec <= 0:
        return True, None

    async with async_session() as db:
        result = await db.execute(
            select(SweepLog.executed_at)
            .where(
                SweepLog.rule_id == rule.id,
                SweepLog.status == SweepStatus.completed,
            )
            .order_by(SweepLog.executed_at.desc())
            .limit(1)
        )
        last_at = result.scalar_one_or_none()

    if last_at is None:
        return True, None

    elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
    if elapsed < rule.cooldown_sec:
        remaining = int(rule.cooldown_sec - elapsed)
        return False, f"Cooldown: {remaining}s remaining (need {rule.cooldown_sec}s)"

    return True, None


async def _check_daily_volume(rule: ForwardingRule) -> tuple[bool, Optional[str]]:
    """Check that today's total sweep volume hasn't exceeded max_daily_vol."""
    if rule.max_daily_vol is None:
        return True, None

    async with async_session() as db:
        today = datetime.now(timezone.utc).date()
        result = await db.execute(
            select(func.coalesce(func.sum(SweepLog.amount_human), 0.0))
            .where(
                SweepLog.rule_id == rule.id,
                SweepLog.status == SweepStatus.completed,
                cast(SweepLog.created_at, Date) == today,
            )
        )
        vol_today = float(result.scalar())

    limit = float(rule.max_daily_vol)
    if vol_today >= limit:
        return False, f"Daily volume limit: {vol_today:.4f}/{limit:.4f}"

    return True, None


def _check_token_filter(
    rule: ForwardingRule,
    incoming_symbol: str,
    token_address: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Check if the incoming token is allowed by the rule's token filter.

    token_filter semantics:
      - [] (empty) → match ALL tokens (ETH + any ERC-20)
      - ["native", "0x833589..."] → match ETH + USDC
      - ["0x833589..."] → match only USDC
      - ["ETH", "USDC"] → legacy symbol-based matching (still supported)
    """
    filt = rule.token_filter
    if not filt:
        return True, None

    incoming_addr = (token_address or "").lower()

    for entry in filt:
        entry_lower = entry.lower()
        # "native" keyword → matches native ETH (no token_address)
        if entry_lower == "native" and not token_address:
            return True, None
        # Hex address → matches by contract address
        if entry_lower.startswith("0x") and incoming_addr == entry_lower:
            return True, None
        # Symbol fallback → matches by symbol (backward compat)
        if not entry_lower.startswith("0x") and entry_lower != "native":
            if incoming_symbol.upper() == entry.upper():
                return True, None

    return False, f"Token {incoming_symbol} ({token_address or 'native'}) not in filter: {filt}"


async def _check_gas_limit(chain_id: int, gas_limit_gwei: int) -> tuple[bool, float, Optional[str]]:
    """Check that current gas price doesn't exceed the rule's gas_limit_gwei."""
    try:
        rpc = get_rpc_manager(chain_id)
        raw = await rpc.call("eth_gasPrice", [])
        gas_wei = int(raw, 16)
        gas_gwei = gas_wei / 1e9
    except Exception as e:
        logger.warning("Gas price check failed on chain %d: %s", chain_id, e)
        return True, 0.0, None  # fail-open

    if gas_gwei > gas_limit_gwei:
        return False, gas_gwei, f"Gas {gas_gwei:.2f} gwei > limit {gas_limit_gwei} gwei"

    return True, gas_gwei, None


async def validate_all_conditions(
    rule: ForwardingRule,
    incoming_symbol: str = "ETH",
    token_address: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Run all validation checks. Short-circuits on first failure."""
    ok, reason = _check_schedule(rule)
    if not ok:
        return False, reason

    ok, reason = await _check_cooldown(rule)
    if not ok:
        return False, reason

    ok, reason = await _check_daily_volume(rule)
    if not ok:
        return False, reason

    ok, reason = _check_token_filter(rule, incoming_symbol, token_address)
    if not ok:
        return False, reason

    ok, _, reason = await _check_gas_limit(rule.chain_id, rule.gas_limit_gwei)
    if not ok:
        return False, reason

    return True, None


# ═══════════════════════════════════════════════════════════════
#  GAS BUMP (replacement TX support)
# ═══════════════════════════════════════════════════════════════

GAS_BUMP_FACTOR = 1.15  # 15% bump — exceeds the 10% minimum required by most mempools
MIN_PRIORITY_FEE_WEI = 100_000_000  # 0.1 gwei floor
REPLACEMENT_MODE_DURATION = 300  # 5 minutes

# Replacement mode state — Redis-backed so it is shared across all Celery
# workers (separate processes). Per-chain key with TTL = REPLACEMENT_MODE_DURATION.
def _replacement_mode_key(chain_id: int) -> str:
    return f"sweep:replacement_mode:{chain_id}"


async def _replacement_mode_active(chain_id: int) -> bool:
    """Return True if we are within the replacement window for this chain.

    Shared cross-worker via Redis. If Redis is unavailable, degrade to the
    pre-existing no-replacement behaviour (return False) rather than raise.
    """
    from app.services.cache_service import get_redis
    r = await get_redis()
    if not r:
        return False
    return bool(await r.exists(_replacement_mode_key(chain_id)))


async def _activate_replacement_mode(chain_id: int) -> None:
    """Activate replacement mode for REPLACEMENT_MODE_DURATION seconds (cross-worker)."""
    from app.services.cache_service import get_redis
    r = await get_redis()
    if not r:
        logger.warning(
            "Replacement mode: Redis unavailable, cannot activate (chain=%d)", chain_id,
        )
        return
    await r.set(_replacement_mode_key(chain_id), "1", ex=REPLACEMENT_MODE_DURATION)
    logger.warning(
        "Replacement mode ACTIVATED for %ds (chain=%d) — all TXes will use 15%% gas bump",
        REPLACEMENT_MODE_DURATION, chain_id,
    )


async def initialize_nonce_with_gap_detection(chain_id: int = 8453) -> dict:
    """Initialize the NonceManager and detect nonce gaps from a previous crash.

    Called at server startup. If redis_nonce > chain_pending_nonce, there are
    pending/queued TXes in the mempool from a previous run. In that case,
    activate replacement mode for 5 minutes so new TXes bump gas and replace
    stale mempool entries.

    Returns:
        Dict with initialization state.
    """
    from app.services.nonce_manager import get_nonce_manager

    nm = get_nonce_manager(chain_id)
    try:
        nonce_value = await nm.initialize()
    except Exception as e:
        logger.error("NonceManager init failed for chain %d: %s", chain_id, e)
        return {"chain_id": chain_id, "status": "error", "error": str(e)}

    # Check for gap
    try:
        state = await nm.get_state()
        gap = state.get("gap", 0) or 0
    except Exception as e:
        logger.warning("NonceManager get_state failed: %s — skipping gap check", e)
        return {"chain_id": chain_id, "nonce": nonce_value, "gap": None}

    result = {
        "chain_id": chain_id,
        "nonce": nonce_value,
        "redis_nonce": state.get("redis_nonce"),
        "chain_pending": state.get("chain_pending"),
        "chain_latest": state.get("chain_latest"),
        "gap": gap,
    }

    if gap > 0:
        logger.warning(
            "NONCE GAP detected on chain %d: redis=%s chain_pending=%s gap=%d "
            "— activating replacement mode for %ds",
            chain_id, state.get("redis_nonce"), state.get("chain_pending"),
            gap, REPLACEMENT_MODE_DURATION,
        )
        await _activate_replacement_mode(chain_id)

        # Prometheus metric
        try:
            from app.services.metrics import NONCE_GAPS_ON_STARTUP
            NONCE_GAPS_ON_STARTUP.labels(chain_id=str(chain_id)).inc()
        except Exception:
            pass
    else:
        logger.info(
            "NonceManager initialized clean: chain=%d nonce=%d gap=0",
            chain_id, nonce_value,
        )

    return result


async def get_bumped_gas_params(
    chain_id: int,
    base_gas_price: int,
    is_replacement: bool = False,
) -> dict:
    """Return gas parameters for a TX, with optional bump for replacement.

    When is_replacement=True, all gas fields are bumped by at least 15%
    to guarantee the new TX replaces any pending TX at the same nonce.

    Returns:
        EIP-1559 dict ``{maxFeePerGas, maxPriorityFeePerGas}`` for chains
        in EIP1559_CHAINS, or legacy ``{gasPrice}`` otherwise.
    """
    if is_replacement:
        bumped = int(base_gas_price * GAS_BUMP_FACTOR)
    else:
        bumped = base_gas_price

    if chain_id in EIP1559_CHAINS:
        priority = max(bumped // 10, MIN_PRIORITY_FEE_WEI)
        return {
            "maxFeePerGas": bumped,
            "maxPriorityFeePerGas": priority,
        }
    else:
        return {"gasPrice": bumped}


# ═══════════════════════════════════════════════════════════════
#  GAS ESTIMATION (EIP-1559 aware)
# ═══════════════════════════════════════════════════════════════

async def estimate_gas_cost(
    chain_id: int,
    strategy: GasStrategy,
    tx_params: Optional[dict] = None,
) -> tuple[int, float, float, dict]:
    """
    Estimate gas for a transaction.

    Returns:
        (gas_limit, effective_gas_gwei, cost_eth, fee_params)
        fee_params is either {"gasPrice": int} or {"maxFeePerGas": int, "maxPriorityFeePerGas": int}
    """
    mult = GAS_MULT.get(strategy, 1.1)

    # Gas limit estimation
    rpc = get_rpc_manager(chain_id)

    if tx_params:
        try:
            raw_estimate = await rpc.call("eth_estimateGas", [tx_params])
            gas_limit = int(int(raw_estimate, 16) * 1.2)  # 20% buffer
        except Exception:
            gas_limit = 65000 if tx_params.get("data") else 21000
    else:
        gas_limit = 21000

    # Gas price
    raw_price = await rpc.call("eth_gasPrice", [])
    base_gas_wei = int(raw_price, 16)

    if chain_id in EIP1559_CHAINS:
        # EIP-1559 type 2 transaction
        try:
            raw_priority = await rpc.call("eth_maxPriorityFeePerGas", [])
            priority_fee = int(raw_priority, 16)
        except Exception:
            priority_fee = int(0.001 * 1e9)  # 0.001 gwei fallback (Base has very low priority fees)

        max_fee = int(base_gas_wei * mult)
        priority_fee = min(priority_fee, max_fee)
        effective_gas_wei = max_fee
        fee_params = {
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
        }
    else:
        # Legacy transaction (Ethereum L1)
        adjusted = int(base_gas_wei * mult)
        effective_gas_wei = adjusted
        fee_params = {"gasPrice": adjusted}

    effective_gwei = effective_gas_wei / 1e9
    l2_cost_wei = effective_gas_wei * gas_limit

    # Add L1 data fee for OP Stack chains
    l1_cost_wei = 0
    from app.services.gas_estimator import is_op_stack, estimate_l1_data_fee
    if is_op_stack(chain_id):
        try:
            # Estimate calldata size: single ETH transfer ≈ 0 bytes,
            # ERC-20 transfer ≈ 68 bytes, distribution ≈ varies by recipient count
            calldata_bytes = 0
            if tx_params and tx_params.get("data"):
                data_hex = tx_params["data"]
                if isinstance(data_hex, str) and data_hex.startswith("0x"):
                    calldata_bytes = (len(data_hex) - 2) // 2
                elif isinstance(data_hex, bytes):
                    calldata_bytes = len(data_hex)
            l1_cost_wei = await estimate_l1_data_fee(chain_id, calldata_bytes)
        except Exception as exc:
            logger.debug("L1 fee estimation failed: %s", exc)

    total_cost_wei = l2_cost_wei + l1_cost_wei
    cost_eth = total_cost_wei / 1e18

    return gas_limit, effective_gwei, cost_eth, fee_params


async def estimate_simple_gas_cost(
    chain_id: int, strategy: GasStrategy,
) -> tuple[int, float, float]:
    """Backward-compatible wrapper for quick gas estimation (ETH transfer)."""
    gas_limit, gas_gwei, cost_eth, _ = await estimate_gas_cost(chain_id, strategy)
    return gas_limit, gas_gwei, cost_eth


# ═══════════════════════════════════════════════════════════════
#  ERC-20 TRANSFER BUILDING
# ═══════════════════════════════════════════════════════════════

def _build_erc20_transfer_data(to_address: str, amount_raw: int) -> str:
    """Build calldata for ERC-20 transfer(address, uint256)."""
    addr = to_address.lower().replace("0x", "").zfill(64)
    amt = hex(amount_raw)[2:].zfill(64)
    return "0x" + ERC20_TRANSFER_SELECTOR + addr + amt


def _get_token_decimals(chain_id: int, token_address: str) -> int:
    """Look up token decimals from unified registry. Defaults to 18."""
    return _registry_get_decimals(chain_id, token_address)


def _human_to_token_units(amount_human: float, decimals: int) -> int:
    """Convert human-readable amount to raw token units (decimal-safe)."""
    return int(Decimal(str(amount_human)) * Decimal(10 ** decimals))


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET NOTIFICATION
# ═══════════════════════════════════════════════════════════════

async def _notify(owner: str, event_type: str, data: dict) -> None:
    """Send event to the WebSocket feed. Non-blocking, never raises."""
    try:
        from app.api.websocket_routes import feed_manager
        await feed_manager.broadcast(owner, event_type, data)
    except Exception:
        pass


async def _resolve_owner(rule_id: int) -> Optional[str]:
    """Resolve rule_id → user_id (owner address)."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(ForwardingRule.user_id).where(ForwardingRule.id == rule_id)
            )
            return result.scalar_one_or_none()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM / EMAIL NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════

_telegram_cb = CircuitBreaker(
    name="telegram",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max_calls=1,
)


async def _telegram_send(token: str, chat_id: str, message: str) -> bool:
    """Raw Telegram API call."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram API returned {resp.status_code}")
        return True


async def _notify_telegram(chat_id: str, message: str) -> bool:
    """Send a Telegram message via Bot API (circuit-breaker protected)."""
    token = get_settings().telegram_bot_token
    if not token:
        logger.debug("Telegram bot token not configured — skipping notification")
        return False

    try:
        return await _telegram_cb.call(_telegram_send, token, chat_id, message)
    except CircuitOpenError:
        logger.warning("Telegram circuit OPEN — notification skipped")
        return False
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)
        return False


async def _notify_email(email: str, subject: str, body: str) -> bool:
    """Email notification stub — not yet implemented."""
    logger.info("Email notification skipped (not implemented): to=%s subj=%s", email, subject)
    return False


async def _send_notification(
    rule: ForwardingRule,
    event: str,
    details: dict,
) -> None:
    """Unified notification dispatcher: WS + Telegram/Email if configured."""
    owner = rule.user_id

    # Always send WebSocket notification
    await _notify(owner, event, details)

    if not rule.notify_enabled:
        return

    # Build human-readable message
    chain = CHAIN_NAMES.get(rule.chain_id, str(rule.chain_id))
    amount = details.get("amount_eth") or details.get("amount_human", "?")
    token = details.get("token", rule.token_symbol or "ETH")
    status = details.get("status", event)
    tx_hash = details.get("tx_hash", "")

    msg = (
        f"*RSends Sweep — {status.upper()}*\n"
        f"Chain: {chain}\n"
        f"Amount: {amount} {token}\n"
        f"To: `{details.get('destination', rule.destination_wallet)}`\n"
    )
    if tx_hash:
        msg += f"TX: `{tx_hash}`\n"
    if details.get("error"):
        msg += f"Error: {details['error']}\n"

    if rule.notify_channel == "telegram" and rule.telegram_chat_id:
        await _notify_telegram(rule.telegram_chat_id, msg)
    elif rule.notify_channel == "email" and rule.email_address:
        await _notify_email(rule.email_address, f"RSends: {event}", msg)


# ═══════════════════════════════════════════════════════════════
#  CORE SWEEP EXECUTION
# ═══════════════════════════════════════════════════════════════

def _get_private_key() -> Optional[str]:
    """Retrieve the sweep wallet private key from settings.

    .. deprecated::
        Prefer ``get_signer()`` from ``key_manager`` for new code.
        Kept for backward-compat with callers that need the raw key string.
    """
    key = get_settings().sweep_private_key
    if not key or not key.startswith("0x") or len(key) != 66:
        return None
    return key


async def execute_single_sweep(
    sweep_id: int,
    source: str,
    destination: str,
    amount_wei: int,
    chain_id: int = 8453,
    strategy: GasStrategy = GasStrategy.normal,
    max_gas_pct: float = 10.0,
    owner: Optional[str] = None,
    token_address: Optional[str] = None,
    token_symbol: str = "ETH",
    token_decimals: int = 18,
) -> dict:
    """
    Execute a single sweep transaction (ETH native or ERC-20).

    For ETH: gas is deducted from the transfer amount.
    For ERC-20: gas is paid in ETH separately; full token amount is transferred.
    """
    _t0 = _time.monotonic()

    if chain_id not in SUPPORTED_CHAINS:
        SWEEP_TOTAL.labels(status="failed", chain_id=str(chain_id)).inc()
        return {"status": "failed", "error": f"Chain {chain_id} not supported"}

    from app.services.key_manager import get_signer, SignerError

    try:
        signer = get_signer()
    except SignerError as e:
        SWEEP_TOTAL.labels(status="failed", chain_id=str(chain_id)).inc()
        return {"status": "failed", "error": f"Signer not configured: {e}"}

    # Execution lock
    if not await _acquire_lock(f"exec:{sweep_id}"):
        SWEEP_TOTAL.labels(status="failed", chain_id=str(chain_id)).inc()
        return {"status": "failed", "error": "Sweep already in progress (lock)"}

    chain_name = CHAIN_NAMES.get(chain_id, f"Chain {chain_id}")
    is_erc20 = token_address is not None
    amount_human = amount_wei / (10 ** token_decimals)

    if not owner:
        owner = await _resolve_owner(sweep_id)

    ws_base = {
        "sweep_id": sweep_id,
        "source": source,
        "destination": destination,
        "amount_human": round(amount_human, 8),
        "amount_eth": round(amount_wei / 1e18, 8) if not is_erc20 else None,
        "chain": chain_name,
        "chain_id": chain_id,
        "token": token_symbol,
    }

    from app.db.session import db_write_lock

    # Helper: locked status update (serializes SQLite writes)
    async def _update_sweep(**values):
        async with db_write_lock():
            async with async_session() as _db:
                await _db.execute(
                    update(SweepLog).where(SweepLog.id == sweep_id).values(**values)
                )
                await _db.commit()

    try:
        # Mark executing
        await _update_sweep(status=SweepStatus.executing)

        if owner:
            await _notify(owner, "sweep_executing", ws_base)

        # ── Build TX params for gas estimation ─────────
        signer_address = await signer.get_address()
        rpc = get_rpc_manager(chain_id)
        nonce_raw = await rpc.consensus_call("eth_getTransactionCount", [source, "latest"])
        nonce = int(nonce_raw, 16)

        if is_erc20:
            calldata = _build_erc20_transfer_data(destination, amount_wei)
            est_params = {"from": source, "to": token_address, "data": calldata}
        else:
            est_params = {"from": source, "to": destination, "value": hex(amount_wei)}

        # ── Gas estimation ─────────────────────────────
        gas_limit, gas_gwei, gas_cost_eth, fee_params = await estimate_gas_cost(
            chain_id, strategy, est_params,
        )
        SWEEP_GAS_GWEI.labels(chain_id=str(chain_id)).set(gas_gwei)

        # ── Gas % guard (ETH transfers only) ──────────
        if not is_erc20:
            amount_eth = amount_wei / 1e18
            gas_pct = (gas_cost_eth / amount_eth * 100) if amount_eth > 0 else 100

            if gas_pct > max_gas_pct:
                await _update_sweep(
                    status=SweepStatus.gas_too_high,
                    gas_price_gwei=gas_gwei,
                    gas_cost_eth=gas_cost_eth,
                    gas_percent=round(gas_pct, 2),
                    error_message=f"Gas {gas_pct:.1f}% > max {max_gas_pct}% on {chain_name}",
                )
                err_data = {**ws_base, "error": f"Gas too high: {gas_pct:.1f}%", "status": "gas_too_high", "gas_gwei": gas_gwei}
                if owner:
                    await _notify(owner, "sweep_error", err_data)
                await _release_lock(f"exec:{sweep_id}")
                SWEEP_TOTAL.labels(status="gas_too_high", chain_id=str(chain_id)).inc()
                SWEEP_LATENCY.observe(_time.monotonic() - _t0)
                return {"status": "gas_too_high", "gas_percent": gas_pct}

            # Deduct gas from ETH amount
            net_wei = amount_wei - int(gas_cost_eth * 1e18)
            if net_wei <= 0:
                await _update_sweep(
                    status=SweepStatus.failed,
                    error_message="Amount too small after gas",
                )
                if owner:
                    await _notify(owner, "sweep_error", {**ws_base, "error": "Amount too small after gas", "status": "failed"})
                await _release_lock(f"exec:{sweep_id}")
                SWEEP_TOTAL.labels(status="failed", chain_id=str(chain_id)).inc()
                SWEEP_LATENCY.observe(_time.monotonic() - _t0)
                return {"status": "failed", "error": "Too small after gas"}

            tx_value = net_wei
            tx_to = destination
            tx_data = None
        else:
            # ERC-20: full token amount, gas paid in ETH separately
            tx_value = 0
            tx_to = token_address
            tx_data = _build_erc20_transfer_data(destination, amount_wei)
            gas_pct = 0.0

        # ── Build & sign transaction ──────────────────
        tx = {
            "to": tx_to,
            "value": tx_value,
            "gas": gas_limit,
            "nonce": nonce,
            "chainId": chain_id,
            **fee_params,
        }
        if tx_data:
            tx["data"] = tx_data

        raw_tx = await signer.sign_transaction(tx)
        raw_hex = "0x" + raw_tx.hex()

        # ── Broadcast-idempotency guard: claim BEFORE sending (crash-safe) ──
        # Persists intent (nonce + key) atomically so a crash between broadcast
        # and DB commit cannot cause a double broadcast on retry. The Redis lock
        # above only guards concurrent entry; this survives a process restart.
        from app.services.tx_intent_guard import (
            claim_or_reconcile,
            mark_confirmed,
            reconcile_via_rpc,
        )

        _intent_key = f"standalone_sweep:{sweep_id}"
        _decision, _verdict = await claim_or_reconcile(
            _intent_key,
            site="standalone_sweep",
            chain_id=chain_id,
            from_addr=source,
            nonce=nonce,
            reconcile_fn=lambda row: reconcile_via_rpc(rpc, source, row),
        )

        # ── Send transaction (primary only — never duplicate) ──
        if _decision == "already":
            if (_verdict or {}).get("status") != "completed":
                # A concurrent attempt holds the broadcast claim and is still
                # in-flight — back off WITHOUT broadcasting (never double-send).
                logger.warning(
                    "[sweep] #%d broadcast claim held by another run — skipping",
                    sweep_id,
                )
                await _release_lock(f"exec:{sweep_id}")
                SWEEP_TOTAL.labels(status="skipped", chain_id=str(chain_id)).inc()
                SWEEP_LATENCY.observe(_time.monotonic() - _t0)
                return {"status": "in_progress", "tx_hash": ""}
            # Crash/retry: a prior attempt already broadcast this sweep and the
            # chain confirms it — NEVER re-broadcast, just reconcile state.
            tx_hash = (_verdict or {}).get("tx_hash") or ""
            logger.warning(
                "[sweep] #%d idempotent skip: broadcast already done, "
                "reconciled against chain (tx=%s)",
                sweep_id, tx_hash[:16] if tx_hash else "?",
            )
        else:
            result_raw = await rpc.send_raw_transaction(raw_hex)
            # If send_raw_transaction didn't raise, result_raw is the tx hash
            tx_hash = result_raw if isinstance(result_raw, str) else ""
            await mark_confirmed(_intent_key, tx_hash)

        await _update_sweep(
            status=SweepStatus.completed,
            tx_hash=tx_hash,
            gas_used=gas_limit,
            gas_price_gwei=gas_gwei,
            gas_cost_eth=gas_cost_eth,
            gas_percent=round(gas_pct, 2),
            executed_at=datetime.now(timezone.utc),
        )

        completed_data = {
            **ws_base,
            "tx_hash": tx_hash,
            "gas_gwei": gas_gwei,
            "gas_cost_eth": round(gas_cost_eth, 8),
            "status": "completed",
        }
        if not is_erc20:
            completed_data["net_amount_eth"] = round(tx_value / 1e18, 8)

        if owner:
            await _notify(owner, "sweep_completed", completed_data)

        logger.info(
            "[sweep] #%d on %s: %s %s -> %s | TX: %s",
            sweep_id, chain_name,
            f"{amount_human:.6f}", token_symbol,
            destination[:10], tx_hash[:16] if tx_hash else "?",
        )

        # ── Ledger double-entry recording (non-blocking) ──
        try:
            from app.services.ledger_service import create_payment_entries
            from app.models.ledger_models import Account, Transaction
            from decimal import Decimal
            import uuid as _uuid

            async with db_write_lock():
                async with async_session() as ledger_db:
                    from sqlalchemy import select as _sel

                    src_acc = (await ledger_db.execute(
                        _sel(Account).where(Account.address == source.lower())
                    )).scalar_one_or_none()
                    dst_acc = (await ledger_db.execute(
                        _sel(Account).where(Account.address == destination.lower())
                    )).scalar_one_or_none()

                    if src_acc and dst_acc:
                        tx_obj = Transaction(
                            idempotency_key=f"sweep:{sweep_id}:{tx_hash or _uuid.uuid4()}",
                            tx_type="SWEEP",
                            status="COMPLETED",
                            tx_hash=tx_hash,
                            chain_id=chain_id,
                            reference=f"Sweep #{sweep_id}",
                        )
                        ledger_db.add(tx_obj)
                        await ledger_db.flush()

                        treasury = (await ledger_db.execute(
                            _sel(Account).where(
                                Account.account_type == "treasury",
                                Account.currency == token_symbol,
                            )
                        )).scalar_one_or_none()

                        fee = Decimal("0")
                        await create_payment_entries(
                            session=ledger_db,
                            tx_id=tx_obj.id,
                            sender_account_id=src_acc.id,
                            recipient_account_id=dst_acc.id,
                            treasury_account_id=treasury.id if treasury else dst_acc.id,
                            gross_amount=Decimal(str(amount_wei)) / Decimal(10 ** token_decimals),
                            fee_amount=fee,
                            currency=token_symbol,
                        )
                        await ledger_db.commit()
                        logger.info("[sweep] Ledger recorded for sweep #%d", sweep_id)
                    else:
                        logger.debug("[sweep] Ledger skip: accounts not found for %s / %s", source[:10], destination[:10])
        except Exception as ledger_err:
            logger.warning("[sweep] Ledger recording failed (non-blocking): %s", ledger_err)

        await _release_lock(f"exec:{sweep_id}")
        SWEEP_TOTAL.labels(status="completed", chain_id=str(chain_id)).inc()
        SWEEP_LATENCY.observe(_time.monotonic() - _t0)
        SWEEP_AMOUNT_ETH.observe(amount_human)
        return {"status": "completed", "tx_hash": tx_hash}

    except Exception as e:
        err_msg = str(e)[:200]
        try:
            await _update_sweep(
                status=SweepStatus.failed,
                error_message=err_msg,
            )
        except Exception:
            logger.error("[sweep] #%d failed to update status: %s", sweep_id, err_msg)

        if owner:
            await _notify(owner, "sweep_error", {**ws_base, "error": err_msg, "status": "failed"})

        logger.error("[sweep] #%d failed: %s", sweep_id, err_msg)

        # Critical alert for sweep failure
        try:
            from app.services.alert_service import critical_alert
            await critical_alert(
                f"Sweep #{sweep_id} FAILED\n"
                f"Chain: {chain_id}\nError: {err_msg}"
            )
        except Exception:
            pass

        await _release_lock(f"exec:{sweep_id}")
        SWEEP_TOTAL.labels(status="failed", chain_id=str(chain_id)).inc()
        SWEEP_LATENCY.observe(_time.monotonic() - _t0)
        return {"status": "failed", "error": err_msg}


# ═══════════════════════════════════════════════════════════════
#  SPLIT ROUTING
# ═══════════════════════════════════════════════════════════════

async def _execute_split(
    id1: int,
    id2: int,
    rule: ForwardingRule,
    wei1: int,
    wei2: int,
    owner: Optional[str] = None,
    token_address: Optional[str] = None,
    token_symbol: str = "ETH",
    token_decimals: int = 18,
) -> None:
    """Execute a split sweep: two sequential TXs with a nonce-safety delay."""
    strategy = rule.gas_strategy or GasStrategy.normal
    max_gas = rule.max_gas_percent or 10.0

    r1 = await execute_single_sweep(
        id1, rule.source_wallet, rule.destination_wallet, wei1,
        rule.chain_id, strategy, max_gas, owner,
        token_address, token_symbol, token_decimals,
    )

    # Always attempt second TX (even if first fails, the amounts are independent)
    await asyncio.sleep(2)  # nonce propagation delay

    r2 = await execute_single_sweep(
        id2, rule.source_wallet, rule.split_destination, wei2,
        rule.chain_id, strategy, max_gas, owner,
        token_address, token_symbol, token_decimals,
    )

    # Send unified notification for the split
    details = {
        "sweep_ids": [id1, id2],
        "split_1": r1,
        "split_2": r2,
        "status": "completed" if r1.get("status") == "completed" and r2.get("status") == "completed" else "partial",
    }
    await _send_notification(rule, "sweep_split_completed", details)


# ═══════════════════════════════════════════════════════════════
#  RETRY WITH EXPONENTIAL BACKOFF
# ═══════════════════════════════════════════════════════════════

TRANSIENT_ERRORS = {"nonce too low", "nonce too high", "replacement transaction", "timeout", "connection"}


def _is_transient(error_message: str) -> bool:
    """Check if an error is transient and worth retrying."""
    lower = (error_message or "").lower()
    return any(keyword in lower for keyword in TRANSIENT_ERRORS)


async def _retry_with_backoff(
    sweep_id: int,
    rule: ForwardingRule,
    token_address: Optional[str] = None,
    token_symbol: str = "ETH",
    token_decimals: int = 18,
) -> dict:
    """Retry a failed sweep with exponential backoff."""
    # Read phase (no lock needed)
    async with async_session() as db:
        result = await db.execute(select(SweepLog).where(SweepLog.id == sweep_id))
        sweep = result.scalar_one_or_none()
        if not sweep:
            return {"status": "failed", "error": "Sweep log not found"}

        if sweep.retry_count >= MAX_RETRY_COUNT:
            logger.info("[retry] #%d max retries (%d) reached", sweep_id, MAX_RETRY_COUNT)
            return {"status": "failed", "error": "Max retries exceeded"}

        new_count = sweep.retry_count + 1

    # Write phase (under write lock)
    from app.db.session import db_write_lock
    async with db_write_lock():
        async with async_session() as db:
            await db.execute(
                update(SweepLog).where(SweepLog.id == sweep_id).values(
                    retry_count=new_count,
                    status=SweepStatus.pending,
                )
            )
            await db.commit()

    delay = RETRY_BASE_DELAY * (2 ** (new_count - 1))
    logger.info("[retry] #%d attempt %d/%d — waiting %ds", sweep_id, new_count, MAX_RETRY_COUNT, delay)
    await asyncio.sleep(delay)

    return await execute_single_sweep(
        sweep_id=sweep_id,
        source=sweep.source_wallet,
        destination=sweep.destination_wallet,
        amount_wei=int(sweep.amount_wei),
        chain_id=rule.chain_id,
        strategy=rule.gas_strategy or GasStrategy.normal,
        max_gas_pct=rule.max_gas_percent or 10.0,
        owner=rule.user_id,
        token_address=token_address,
        token_symbol=token_symbol,
        token_decimals=token_decimals,
    )


# ═══════════════════════════════════════════════════════════════
#  QUEUE & ORCHESTRATION
# ═══════════════════════════════════════════════════════════════

async def queue_sweep(
    sweep_id: int,
    rule: ForwardingRule,
    amount: float,
    trigger_tx_hash: Optional[str] = None,
) -> None:
    """
    Main entry point called by the webhook handler.

    Validates all conditions, acquires a distributed lock,
    and dispatches the sweep execution as an async task.
    """
    owner = rule.user_id

    # ── 0. Fail-closed dependency check ───────────────
    # Financial ops MUST NOT proceed without Redis (idempotency)
    # and Postgres (persistence). RPC is checked per-chain.
    try:
        await dependency_guard.require_redis()
        await dependency_guard.require_rpc(chain_id=rule.chain_id)
    except SweepBlockedError as e:
        logger.error(
            "[queue] Sweep BLOCKED for rule #%d: %s",
            rule.id, e,
            extra={"service": "sweep", "rule_id": rule.id},
        )
        raise

    # ── 1. Distributed lock on trigger TX ──────────────
    if trigger_tx_hash:
        if not await _acquire_lock(trigger_tx_hash):
            logger.info("[queue] Duplicate trigger TX %s — skipping", trigger_tx_hash[:16])
            return

    # ── 2. Validate all conditions ─────────────────────
    ok, reason = await validate_all_conditions(rule, rule.token_symbol or "ETH", rule.token_address)
    if not ok:
        logger.info("[queue] Rule #%d skipped: %s", rule.id, reason)
        from app.db.session import db_write_lock
        async with db_write_lock():
            async with async_session() as db:
                await db.execute(
                    update(SweepLog).where(SweepLog.id == sweep_id).values(
                        status=SweepStatus.skipped,
                        error_message=reason[:200] if reason else "Condition not met",
                    )
                )
                await db.commit()

        SWEEP_TOTAL.labels(status="skipped", chain_id=str(rule.chain_id)).inc()
        await _send_notification(rule, "sweep_skipped", {
            "sweep_id": sweep_id,
            "reason": reason,
            "status": "skipped",
        })
        return

    # ── 3. Auto-swap check ─────────────────────────────
    if rule.auto_swap and rule.swap_to_token:
        logger.warning(
            "[queue] Auto-swap requested (rule #%d) but not yet implemented — proceeding with normal transfer",
            rule.id,
        )

    # ── 4. Resolve token params (from registry) ────────
    token_address = rule.token_address
    _token_info = _registry_get_token(rule.chain_id, token_address) if token_address else _registry_get_native(rule.chain_id)
    token_symbol = _token_info.symbol if _token_info else (rule.token_symbol or "ETH")
    token_decimals = _token_info.decimals if _token_info else (
        _get_token_decimals(rule.chain_id, token_address) if token_address else 18
    )

    # ── 5. Convert amount to raw units ─────────────────
    amount_raw = _human_to_token_units(amount, token_decimals)

    # ── 6. Split or single ─────────────────────────────
    if rule.split_enabled and rule.split_destination and rule.split_percent:
        pct1 = rule.split_percent
        pct2 = 100 - pct1

        # Gas estimation + price lookup (outside write lock)
        if not token_address:
            _, _, gas_cost = await estimate_simple_gas_cost(
                rule.chain_id, rule.gas_strategy or GasStrategy.normal,
            )
            total_gas_wei = int(gas_cost * 1e18 * 2)
            net_raw = amount_raw - total_gas_wei
            if net_raw <= 0:
                logger.warning("[queue] Split: amount too small for 2 TX gas on chain %d", rule.chain_id)
                return
        else:
            net_raw = amount_raw

        amt1 = (net_raw * pct1) // 100
        amt2 = net_raw - amt1

        _token_info = _registry_get_token(rule.chain_id, token_address)
        _cg_id = _token_info.coingecko_id if _token_info else ("ethereum" if not token_address else None)
        _human1 = amt1 / (10 ** token_decimals)
        _human2 = amt2 / (10 ** token_decimals)
        _usd1 = await get_usd_value(_cg_id, _human1) if _cg_id else None
        _usd2 = await get_usd_value(_cg_id, _human2) if _cg_id else None

        # DB write (under write lock)
        from app.db.session import db_write_lock as _dwl
        async with _dwl():
            async with async_session() as db:
                log1 = SweepLog(
                    rule_id=rule.id, source_wallet=rule.source_wallet,
                    destination_wallet=rule.destination_wallet, is_split=True,
                    split_index=0, split_percent=pct1,
                    amount_wei=str(amt1), amount_human=_human1,
                    amount_usd=_usd1,
                    token_symbol=token_symbol, status=SweepStatus.pending,
                    trigger_tx_hash=trigger_tx_hash,
                )
                log2 = SweepLog(
                    rule_id=rule.id, source_wallet=rule.source_wallet,
                    destination_wallet=rule.split_destination, is_split=True,
                    split_index=1, split_percent=pct2,
                    amount_wei=str(amt2), amount_human=_human2,
                    amount_usd=_usd2,
                    token_symbol=token_symbol, status=SweepStatus.pending,
                    trigger_tx_hash=trigger_tx_hash,
                )
                db.add(log1)
                db.add(log2)
                await db.flush()
                id1, id2 = log1.id, log2.id
                await db.commit()

        chain_name = CHAIN_NAMES.get(rule.chain_id, str(rule.chain_id))
        logger.info(
            "[queue] Split on %s: %d%% -> %s | %d%% -> %s",
            chain_name, pct1, rule.destination_wallet[:10], pct2, rule.split_destination[:10],
        )
        asyncio.create_task(
            _execute_split(id1, id2, rule, amt1, amt2, owner, token_address, token_symbol, token_decimals)
        )
    else:
        asyncio.create_task(
            execute_single_sweep(
                sweep_id=sweep_id,
                source=rule.source_wallet,
                destination=rule.destination_wallet,
                amount_wei=amount_raw,
                chain_id=rule.chain_id,
                strategy=rule.gas_strategy or GasStrategy.normal,
                max_gas_pct=rule.max_gas_percent or 10.0,
                owner=owner,
                token_address=token_address,
                token_symbol=token_symbol,
                token_decimals=token_decimals,
            )
        )


# ═══════════════════════════════════════════════════════════════
#  RETRY PENDING SWEEPS
# ═══════════════════════════════════════════════════════════════

_DB_RETRY_ATTEMPTS = 5
_DB_RETRY_DELAYS = [0.3, 0.7, 1.5, 3.0, 5.0]


async def process_incoming_tx(
    from_addr: str,
    to_addr: str,
    value: float,
    tx_hash: str,
    asset: str = "ETH",
    token_address: Optional[str] = None,
    token_decimals: int = 18,
    block_num: Optional[str] = None,
) -> int:
    """
    Process an incoming transaction detected by webhook or polling.

    Finds active forwarding rules matching the destination address,
    creates SweepLog entries, and queues sweeps for execution.
    Retries on SQLite "database is locked" with exponential backoff.

    Args:
        from_addr: Sender address
        to_addr: Recipient address (must match a rule's source_wallet)
        value: Human-readable amount (ETH or token units)
        tx_hash: Transaction hash (used for dedup lock)
        asset: Asset symbol from the source (e.g. "ETH", "USDC")
        token_address: ERC-20 contract address (None for native ETH)
        token_decimals: Token decimals (18 for ETH)
        block_num: Block number (hex string, for logging)

    Returns:
        Number of sweeps queued.
    """
    # ── Fail-closed: verify Postgres is reachable before DB writes ──
    try:
        await dependency_guard.require_postgres()
    except SweepBlockedError as e:
        logger.error(
            "[incoming] TX processing BLOCKED: %s (tx=%s)",
            e, tx_hash[:16],
            extra={"service": "sweep", "tx_hash": tx_hash},
        )
        raise

    # ── AML screening (non-blocking on failure) ──────────
    try:
        from app.services.aml_service import screen_transaction
        aml_result = await screen_transaction(from_addr, to_addr, str(int(Decimal(str(value)) * Decimal(10 ** 18))))
        if aml_result["blocked"]:
            logger.warning("AML BLOCKED TX from %s to %s: %s", from_addr[:10], to_addr[:10], aml_result["flags"])
            return 0  # Non processare
    except Exception as e:
        logger.warning("AML screening failed (fail-open): %s", e)

    # ── Retry wrapper for SQLite "database is locked" ────
    from sqlalchemy.exc import OperationalError

    for attempt in range(_DB_RETRY_ATTEMPTS):
        try:
            return await _process_incoming_tx_inner(
                from_addr, to_addr, value, tx_hash, asset,
                token_address, token_decimals, block_num,
            )
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < _DB_RETRY_ATTEMPTS - 1:
                delay = _DB_RETRY_DELAYS[attempt]
                logger.warning(
                    "[incoming] DB locked (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _DB_RETRY_ATTEMPTS, delay, tx_hash[:16],
                )
                await asyncio.sleep(delay)
            else:
                raise
    return 0


async def _process_incoming_tx_inner(
    from_addr: str,
    to_addr: str,
    value: float,
    tx_hash: str,
    asset: str,
    token_address: Optional[str],
    token_decimals: int,
    block_num: Optional[str],
) -> int:
    """Inner implementation of process_incoming_tx (retried by caller on DB lock).

    Three-phase design to minimize SQLite write-lock hold time:
      Phase 1 — reads + external lookups (no lock)
      Phase 2 — dedup check + INSERT + COMMIT (under db_write_lock)
      Phase 3 — queue_sweep + WS broadcast (no lock, after commit)
    """
    from app.api.websocket_routes import feed_manager
    from app.db.session import db_write_lock

    to_lower = to_addr.lower()

    # ── Phase 1: read rules + filter + price lookup (NO write lock) ──
    candidates: list[dict] = []

    async with async_session() as db:
        result = await db.execute(
            select(ForwardingRule).where(
                ForwardingRule.source_wallet == to_lower,
                ForwardingRule.is_active == True,   # noqa: E712
                ForwardingRule.is_paused == False,   # noqa: E712
            )
        )
        rules = result.scalars().all()

    if not rules:
        return 0

    # Resolve token from registry for complete metadata
    token_info: Optional[TokenInfo] = (
        _registry_get_token(rules[0].chain_id, token_address)
        if token_address
        else _registry_get_native(rules[0].chain_id)
    )
    decimals = token_info.decimals if token_info else (token_decimals if token_address else 18)
    amount_wei = int(Decimal(str(value)) * Decimal(10 ** decimals))
    resolved_symbol = token_info.symbol if token_info else asset
    _cg = token_info.coingecko_id if token_info else ("ethereum" if not token_address else None)
    _usd = await get_usd_value(_cg, value) if _cg else None
    _eur = await get_eur_value(_cg, value) if _cg else None

    for rule in rules:
        # ── Token filter: address-based + symbol-based matching ──
        if rule.token_address:
            if not token_address or token_address.lower() != rule.token_address.lower():
                continue
        elif rule.token_filter:
            ok, _reason = _check_token_filter(rule, asset, token_address)
            if not ok:
                logger.debug("[incoming] Rule #%d skipped: %s", rule.id, _reason)
                continue

        # Threshold check
        if value < rule.min_threshold:
            continue

        candidates.append({
            "rule": rule,
            "amount_wei": amount_wei,
            "resolved_symbol": resolved_symbol,
            "cg": _cg,
            "usd": _usd,
            "eur": _eur,
        })

    if not candidates:
        return 0

    # ── Phase 2: dedup + INSERT + COMMIT (under write lock) ──
    created: list[dict] = []

    async with db_write_lock():
        async with async_session() as db:
            for c in candidates:
                rule = c["rule"]
                # DB-level dedup: skip if sweep already exists for this trigger+rule
                existing = await db.execute(
                    select(SweepLog.id).where(
                        SweepLog.trigger_tx_hash == tx_hash,
                        SweepLog.rule_id == rule.id,
                    ).limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    logger.info("[incoming] Duplicate sweep skipped: rule=%d tx=%s", rule.id, tx_hash[:16])
                    continue

                sweep = SweepLog(
                    rule_id=rule.id,
                    source_wallet=rule.source_wallet,
                    destination_wallet=rule.destination_wallet,
                    amount_wei=str(c["amount_wei"]),
                    amount_human=value,
                    amount_display=value,
                    amount_usd=c["eur"] if c["eur"] is not None else c["usd"],
                    token_symbol=c["resolved_symbol"],
                    status=SweepStatus.pending,
                    trigger_tx_hash=tx_hash,
                )
                db.add(sweep)
                await db.flush()
                created.append({
                    "sweep_id": sweep.id,
                    "rule": rule,
                    **c,
                })

            if created:
                await db.commit()

    # ── Phase 3: queue + WS broadcast (after commit, NO write lock) ──
    for item in created:
        rule = item["rule"]
        await queue_sweep(item["sweep_id"], rule, value, trigger_tx_hash=tx_hash)

        await feed_manager.broadcast(rule.user_id, "incoming_detected", {
            "sweep_id": item["sweep_id"],
            "rule_id": rule.id,
            "source_wallet": rule.source_wallet,
            "from_address": from_addr.lower(),
            "amount": value,
            "token": item["resolved_symbol"],
            "token_address": token_address,
            "coingecko_id": item["cg"],
            "amount_eur": item["eur"],
            "trigger_tx": tx_hash,
            "block": block_num,
        })

    if created:
        logger.info(
            "[incoming] %d sweep(s) queued for TX %s -> %s (%.6f %s)",
            len(created), from_addr[:10], to_lower[:10], value, asset,
        )

    return len(created)


# ═══════════════════════════════════════════════════════════════
#  RETRY PENDING SWEEPS
# ═══════════════════════════════════════════════════════════════

async def retry_pending_sweeps() -> int:
    """
    Retry sweeps that failed due to gas or transient errors.
    Called periodically (e.g., via a cron or background task).
    """
    async with async_session() as db:
        result = await db.execute(
            select(SweepLog).where(
                (SweepLog.status == SweepStatus.gas_too_high)
                | (
                    (SweepLog.status == SweepStatus.failed)
                    & (SweepLog.retry_count < MAX_RETRY_COUNT)
                )
            ).order_by(SweepLog.created_at).limit(20)
        )
        sweeps = result.scalars().all()

        retried = 0
        for sweep in sweeps:
            # Only retry transient failures (not permanent ones)
            if sweep.status == SweepStatus.failed and not _is_transient(sweep.error_message):
                continue

            rule_r = await db.execute(
                select(ForwardingRule).where(ForwardingRule.id == sweep.rule_id)
            )
            rule = rule_r.scalar_one_or_none()
            if not rule or not rule.is_active:
                continue

            token_address = rule.token_address
            token_symbol = rule.token_symbol or "ETH"
            token_decimals = _get_token_decimals(rule.chain_id, token_address) if token_address else 18

            asyncio.create_task(
                _retry_with_backoff(sweep.id, rule, token_address, token_symbol, token_decimals)
            )
            retried += 1

        return retried
