"""
RSends Backend — Alchemy Webhook Verifier.

Five-layer verification for incoming Alchemy webhooks:
  1. HMAC-SHA256 body signature  (ALCHEMY_WEBHOOK_SECRET)
  2. IP whitelist               (known Alchemy ranges)
  3. Timestamp freshness        (< 5 min)
  4. Idempotency via Redis      (webhook_id, TTL 1 h)
  5. Rate limit                 (max 100/min per source IP)
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import Request

from app.config import get_settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

# Known Alchemy webhook egress IPs (update when Alchemy publishes new ranges)
ALCHEMY_IP_ALLOWLIST: frozenset[str] = frozenset({
    "54.236.187.89",
    "54.209.70.28",
    "54.82.6.97",
    "54.198.90.86",
    "3.213.24.108",
})

# Private/loopback prefixes accepted in DEBUG mode
_PRIVATE_PREFIXES = (
    "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
    "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.", "192.168.", "127.",
)

FRESHNESS_WINDOW = 300      # 5 minutes
IDEMPOTENCY_TTL = 3600      # 1 hour
RATE_LIMIT_MAX = 100         # max webhooks per window
RATE_LIMIT_WINDOW = 60       # 1 minute


# ═══════════════════════════════════════════════════════════════
#  Exception
# ═══════════════════════════════════════════════════════════════

class WebhookVerificationError(Exception):
    """Webhook verification failed."""

    def __init__(self, reason: str, status_code: int = 401):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


# ═══════════════════════════════════════════════════════════════
#  1. HMAC-SHA256 Signature
# ═══════════════════════════════════════════════════════════════

def verify_hmac_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 of the raw body against the provided signature.

    Uses ``hmac.compare_digest`` to prevent timing attacks.
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


# ═══════════════════════════════════════════════════════════════
#  2. IP Whitelist
# ═══════════════════════════════════════════════════════════════

def check_ip_whitelist(client_ip: str) -> bool:
    """Check whether the client IP belongs to Alchemy's known ranges.

    In DEBUG mode, private/loopback IPs are also accepted.
    """
    settings = get_settings()

    if settings.debug:
        if any(client_ip.startswith(p) for p in _PRIVATE_PREFIXES):
            return True
        if client_ip in ("::1", "localhost"):
            return True

    return client_ip in ALCHEMY_IP_ALLOWLIST


# ═══════════════════════════════════════════════════════════════
#  3. Timestamp Freshness
# ═══════════════════════════════════════════════════════════════

def check_timestamp_freshness(timestamp_str: str) -> bool:
    """Return True if the timestamp is within FRESHNESS_WINDOW seconds."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return False

    age = abs((datetime.now(timezone.utc) - ts).total_seconds())
    return age <= FRESHNESS_WINDOW


# ═══════════════════════════════════════════════════════════════
#  4. Idempotency (Redis SETNX — FAIL-CLOSED)
# ═══════════════════════════════════════════════════════════════

async def check_idempotency(webhook_id: str) -> bool:
    """Check whether this webhook_id has already been processed.

    FAIL-CLOSED: If Redis is down, returns False and raises 503.
    Alchemy will retry the webhook when Redis recovers.

    Returns:
        True if NEW (not seen before) — proceed with processing.
        False if DUPLICATE or REDIS DOWN — skip/reject.

    Raises:
        WebhookVerificationError(503) if Redis is unavailable.
    """
    from app.services.idempotency_service import check_and_mark

    is_new, reason = await check_and_mark(webhook_id)

    if is_new:
        return True

    if reason == "duplicate":
        return False

    # Redis unavailable or error → fail-closed with 503
    raise WebhookVerificationError(
        f"Idempotency check unavailable: {reason}",
        status_code=503,
    )


# ═══════════════════════════════════════════════════════════════
#  5. Rate Limit (sliding window)
# ═══════════════════════════════════════════════════════════════

async def check_rate_limit(source: str) -> bool:
    """Sliding-window rate limiter per source IP.

    Returns True if within limit (max 100/min).
    """
    try:
        from app.services.cache_service import get_redis

        r = await get_redis()
        key = f"wh:rl:{source}"
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, RATE_LIMIT_WINDOW * 2)
        results = await pipe.execute()

        count = results[2]
        return count <= RATE_LIMIT_MAX
    except Exception as exc:
        logger.warning("Webhook rate-limit check failed (allowing): %s", exc)
        return True


# ═══════════════════════════════════════════════════════════════
#  Full Verification Pipeline
# ═══════════════════════════════════════════════════════════════

def _extract_client_ip(request: Request) -> str:
    """Extract the real client IP (validated via trusted proxy)."""
    from app.security.trusted_proxy import get_real_client_ip

    return get_real_client_ip(request)


async def verify_webhook(request: Request) -> dict:
    """Run all five verification layers on an incoming webhook.

    Order:
      1. HMAC signature
      2. IP whitelist
      3. Timestamp freshness
      4. Idempotency (dedupe)
      5. Rate limit

    Returns:
        Parsed webhook payload (dict).

    Raises:
        WebhookVerificationError: On any check failure.
    """
    settings = get_settings()

    if not settings.alchemy_webhook_secret:
        raise WebhookVerificationError(
            "Webhook secret not configured", status_code=500
        )

    body = await request.body()

    # ── 1. HMAC ────────────────────────────────────────────
    signature = request.headers.get("X-Alchemy-Signature", "")
    if not signature:
        raise WebhookVerificationError("Missing X-Alchemy-Signature header")

    if not verify_hmac_signature(body, signature, settings.alchemy_webhook_secret):
        logger.warning("Webhook HMAC verification failed")
        raise WebhookVerificationError("Invalid webhook signature")

    # ── 2. IP whitelist ────────────────────────────────────
    client_ip = _extract_client_ip(request)
    if not check_ip_whitelist(client_ip):
        logger.warning("Webhook from non-whitelisted IP: %s", client_ip)
        raise WebhookVerificationError("IP not in allowlist", status_code=403)

    # ── 3. Parse body ──────────────────────────────────────
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise WebhookVerificationError("Invalid JSON body", status_code=400)

    # ── 4. Timestamp freshness ─────────────────────────────
    created_at = payload.get("createdAt", "")
    if created_at and not check_timestamp_freshness(created_at):
        logger.warning("Webhook timestamp stale: %s", created_at)
        raise WebhookVerificationError("Webhook timestamp too old")

    # ── 5. Idempotency ─────────────────────────────────────
    webhook_id = payload.get("id", "")
    if webhook_id:
        is_new = await check_idempotency(webhook_id)
        if not is_new:
            logger.info("Duplicate webhook ignored: %s", webhook_id)
            # Return 200 to ACK so Alchemy doesn't retry
            raise WebhookVerificationError("Duplicate webhook", status_code=200)

    # ── 6. Rate limit ──────────────────────────────────────
    if not await check_rate_limit(client_ip):
        logger.warning("Webhook rate-limited: %s", client_ip)
        raise WebhookVerificationError("Rate limited", status_code=429)

    logger.info(
        "Webhook verified: id=%s ip=%s",
        webhook_id or "n/a",
        client_ip,
    )
    return payload
