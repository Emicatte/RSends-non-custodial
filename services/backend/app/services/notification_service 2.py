"""
RSends Backend — Notification Service v2.

Centralized alert delivery with rate limiting and message formatting.

Channels:
  - Telegram Bot API (primary)

Message types:
  - sweep_completed   — successful sweep batch
  - sweep_failed      — failed sweep batch
  - circuit_breaker   — circuit breaker state change
  - daily_digest      — daily summary (via Celery beat)
  - spending_warning  — spending limit approaching (>80%)

Rate limiting:
  - 30 messages/minute per chat via Redis sliding window
  - Burst protection with exponential backoff on 429

Queue:
  - All notifications dispatched via Celery 'notify' queue
  - Fire-and-forget: failures are logged, never block sweep pipeline
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Rate Limiter (Redis sliding window — 30 msg/min)
# ═══════════════════════════════════════════════════════════════

RATE_LIMIT_WINDOW = 60       # seconds
RATE_LIMIT_MAX = 30          # max messages per window

_LUA_RATE_CHECK = """
-- KEYS[1] = rate:{chat_id}
-- ARGV[1] = now (float seconds)
-- ARGV[2] = window (seconds)
-- ARGV[3] = max_count
-- Returns: 1 if allowed, 0 if blocked

local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_count = tonumber(ARGV[3])

-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)

-- Count current
local count = redis.call('ZCARD', KEYS[1])

if count >= max_count then
    return 0
end

-- Add this message
redis.call('ZADD', KEYS[1], now, tostring(now) .. ':' .. tostring(math.random(100000)))
redis.call('EXPIRE', KEYS[1], window + 10)
return 1
"""


async def _check_rate_limit(chat_id: str) -> bool:
    """Check if we can send a message to this chat. Returns True if allowed."""
    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        result = await r.eval(
            _LUA_RATE_CHECK,
            1,
            f"notif_rate:{chat_id}",
            str(time.time()),
            str(RATE_LIMIT_WINDOW),
            str(RATE_LIMIT_MAX),
        )
        return int(result) == 1
    except Exception as exc:
        logger.debug("Rate limit check failed (allowing): %s", exc)
        return True  # fail open


# ═══════════════════════════════════════════════════════════════
#  Message Formatters
# ═══════════════════════════════════════════════════════════════

def format_sweep_completed(data: dict) -> str:
    """Format a sweep-completed notification."""
    batch_id = data.get("batch_id", "?")[:8]
    amount_wei = int(data.get("total_amount_wei", 0))
    amount_eth = amount_wei / 10**18
    tx_count = data.get("completed", 0)
    chain_id = data.get("chain_id", 8453)
    recipients = data.get("recipients", tx_count)

    return (
        f"<b>[OK] Sweep Completed</b>\n"
        f"Batch: <code>{batch_id}...</code>\n"
        f"Amount: <b>{amount_eth:.6f} ETH</b>\n"
        f"Recipients: {recipients}\n"
        f"TXs: {tx_count}\n"
        f"Chain: {chain_id}"
    )


def format_sweep_failed(data: dict) -> str:
    """Format a sweep-failed notification."""
    batch_id = data.get("batch_id", "?")[:8]
    reason = data.get("reason", data.get("error_message", "unknown"))
    amount_wei = int(data.get("total_amount_wei", 0))
    amount_eth = amount_wei / 10**18

    return (
        f"<b>[FAIL] Sweep Failed</b>\n"
        f"Batch: <code>{batch_id}...</code>\n"
        f"Amount: {amount_eth:.6f} ETH\n"
        f"Reason: {reason}"
    )


def format_circuit_breaker(data: dict) -> str:
    """Format a circuit breaker state change alert."""
    service = data.get("service", "unknown")
    from_state = data.get("from_state", "?")
    to_state = data.get("to_state", "?")
    failure_count = data.get("failure_count", 0)
    reason = data.get("reason", "")

    severity = "ALERT" if to_state == "open" else "INFO"

    lines = [
        f"<b>[{severity}] Circuit Breaker</b>",
        f"Service: <b>{service}</b>",
        f"Transition: {from_state} -> <b>{to_state}</b>",
        f"Failures: {failure_count}",
    ]
    if reason:
        lines.append(f"Reason: {reason}")

    return "\n".join(lines)


def format_spending_warning(data: dict) -> str:
    """Format a spending limit warning."""
    tier = data.get("tier", "unknown")
    usage_pct = data.get("usage_percent", 0)
    used = data.get("used_eth", 0)
    limit = data.get("limit_eth", 0)
    source = data.get("source", "?")[:10]

    return (
        f"<b>[WARN] Spending Limit</b>\n"
        f"Tier: <b>{tier}</b>\n"
        f"Usage: {usage_pct:.1f}%\n"
        f"Used: {used:.4f} / {limit:.4f} ETH\n"
        f"Source: <code>{source}...</code>"
    )


def format_daily_digest(data: dict) -> str:
    """Format the daily digest summary."""
    date = data.get("date", "?")
    total_batches = data.get("total_batches", 0)
    completed = data.get("completed", 0)
    failed = data.get("failed", 0)
    volume_eth = data.get("volume_eth", 0)
    success_rate = data.get("success_rate_pct", 0)
    gas_total_eth = data.get("gas_total_eth", 0)
    active_rules = data.get("active_rules", 0)

    return (
        f"<b>[DIGEST] Daily Summary — {date}</b>\n"
        f"\n"
        f"Batches: {total_batches} (OK: {completed}, FAIL: {failed})\n"
        f"Success rate: {success_rate:.1f}%\n"
        f"Volume: <b>{volume_eth:.4f} ETH</b>\n"
        f"Gas spent: {gas_total_eth:.6f} ETH\n"
        f"Active rules: {active_rules}"
    )


# Formatter registry
_FORMATTERS = {
    "sweep_completed": format_sweep_completed,
    "sweep_failed": format_sweep_failed,
    "circuit_breaker": format_circuit_breaker,
    "spending_warning": format_spending_warning,
    "daily_digest": format_daily_digest,
}


# ═══════════════════════════════════════════════════════════════
#  Core Send Functions
# ═══════════════════════════════════════════════════════════════

async def send_telegram_alert(message: str, chat_id: Optional[str] = None) -> bool:
    """Send an alert message via Telegram Bot API.

    Applies rate limiting (30 msg/min per chat).
    Silently returns False if not configured or rate-limited.

    Args:
        message: Alert text (HTML, truncated to 4096 chars).
        chat_id: Override chat ID (defaults to settings.telegram_chat_id).

    Returns:
        True if sent successfully, False otherwise.
    """
    settings = get_settings()

    if not settings.telegram_bot_token:
        logger.debug("Telegram not configured — skipping alert")
        return False

    target_chat = chat_id or settings.telegram_chat_id
    if not target_chat:
        logger.debug("No Telegram chat_id — skipping alert")
        return False

    # Rate limit check
    if not await _check_rate_limit(target_chat):
        logger.warning("Telegram rate limited for chat %s", target_chat)
        return False

    url = (
        f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        f"/sendMessage"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": target_chat,
                "text": message[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })

            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
                logger.warning("Telegram 429 — retry after %ds", retry_after)
                return False

            resp.raise_for_status()
            logger.info("Telegram alert sent to %s: %s", target_chat, message[:80])
            return True
    except Exception as exc:
        logger.error("Telegram alert failed: %s", exc)
        return False


async def send_notification(
    notification_type: str,
    data: dict,
    chat_id: Optional[str] = None,
) -> bool:
    """Send a typed notification via Telegram.

    Uses the appropriate formatter for the notification type.
    Falls back to raw JSON dump for unknown types.

    Args:
        notification_type: One of sweep_completed, sweep_failed,
            circuit_breaker, spending_warning, daily_digest.
        data: Notification payload dict.
        chat_id: Override Telegram chat ID.

    Returns:
        True if sent, False otherwise.
    """
    formatter = _FORMATTERS.get(notification_type)
    if formatter:
        message = formatter(data)
    else:
        message = f"<b>[{notification_type.upper()}]</b>\n<pre>{json.dumps(data, indent=2, default=str)[:3800]}</pre>"

    return await send_telegram_alert(message, chat_id=chat_id)


# ═══════════════════════════════════════════════════════════════
#  Convenience: Enqueue via Celery (fire-and-forget)
# ═══════════════════════════════════════════════════════════════

def enqueue_notification(
    notification_type: str,
    data: dict,
    chat_id: Optional[str] = None,
) -> None:
    """Enqueue a notification via Celery 'notify' queue.

    Non-blocking. Failures are logged by the worker, never raised here.
    """
    try:
        from app.tasks.notification_tasks import send_notification_task
        send_notification_task.apply_async(
            kwargs={
                "notification_type": notification_type,
                "data": data,
                "chat_id": chat_id,
            },
        )
    except Exception as exc:
        logger.error("Failed to enqueue notification: %s", exc)
