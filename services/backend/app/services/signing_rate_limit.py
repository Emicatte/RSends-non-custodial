"""
RSends Backend — Signing Rate Limiter (Redis-backed).

Rate limits for oracle signature requests:
  - Per wallet: max 10 firme/minuto, 50 firme/ora
  - Per IP:     max 20 firme/minuto
  - Globale:    max 100 firme/minuto

Uses Redis INCR + EXPIRE for atomic counting.
If Redis is down → BLOCK all signatures (fail-closed).

Also provides nonce deduplication:
  - Every nonce is stored in Redis with 1h TTL
  - Duplicate nonces are rejected immediately
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Rate limit configuration ─────────────────────────────
WALLET_LIMIT_PER_MINUTE = 10
WALLET_LIMIT_PER_HOUR = 50
IP_LIMIT_PER_MINUTE = 20
GLOBAL_LIMIT_PER_MINUTE = 100

NONCE_TTL = 3600  # 1 hour


async def _get_redis():
    """Get Redis connection. Returns None if unavailable."""
    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        if r is not None:
            await r.ping()
        return r
    except Exception:
        return None


async def check_signing_rate_limit(
    wallet: str,
    ip_address: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Check if a signing request is within rate limits.

    Returns:
        (allowed, denial_reason) — if allowed is False, denial_reason explains why.

    Fail-closed: if Redis is unreachable, signing is BLOCKED.
    """
    r = await _get_redis()
    if r is None:
        return False, "rate_limit_unavailable (Redis down — fail-closed)"

    wallet_lower = wallet.lower()
    pipe = r.pipeline()

    try:
        # ── Per-wallet: minute window ─────────────────────
        wk_min = f"sign_rl:wallet:{wallet_lower}:min"
        pipe.incr(wk_min)
        pipe.expire(wk_min, 60)

        # ── Per-wallet: hour window ───────────────────────
        wk_hr = f"sign_rl:wallet:{wallet_lower}:hr"
        pipe.incr(wk_hr)
        pipe.expire(wk_hr, 3600)

        # ── Per-IP: minute window ─────────────────────────
        if ip_address:
            ik = f"sign_rl:ip:{ip_address}:min"
            pipe.incr(ik)
            pipe.expire(ik, 60)

        # ── Global: minute window ─────────────────────────
        gk = "sign_rl:global:min"
        pipe.incr(gk)
        pipe.expire(gk, 60)

        results = await pipe.execute()

        # Parse results (INCR returns count, EXPIRE returns True)
        wallet_min_count = results[0]  # INCR result
        wallet_hr_count = results[2]   # INCR result (index 2, skip EXPIRE at 1)
        ip_count = results[4] if ip_address else 0  # INCR (index 4, skip EXPIRE at 3)
        global_count = results[6] if ip_address else results[4]  # depends on ip presence

        if not ip_address:
            global_count = results[4]  # INCR for global when no IP commands

        # ── Check limits ──────────────────────────────────
        if wallet_min_count > WALLET_LIMIT_PER_MINUTE:
            return False, f"wallet_rate_limit_minute ({wallet_min_count}/{WALLET_LIMIT_PER_MINUTE})"

        if wallet_hr_count > WALLET_LIMIT_PER_HOUR:
            return False, f"wallet_rate_limit_hour ({wallet_hr_count}/{WALLET_LIMIT_PER_HOUR})"

        if ip_address and ip_count > IP_LIMIT_PER_MINUTE:
            return False, f"ip_rate_limit_minute ({ip_count}/{IP_LIMIT_PER_MINUTE})"

        if global_count > GLOBAL_LIMIT_PER_MINUTE:
            return False, f"global_rate_limit_minute ({global_count}/{GLOBAL_LIMIT_PER_MINUTE})"

        return True, None

    except Exception as e:
        logger.error("Rate limit check failed: %s", e, extra={"service": "signing_rl"})
        return False, f"rate_limit_error ({e})"


async def check_nonce_uniqueness(nonce: str) -> tuple[bool, Optional[str]]:
    """Check if a nonce has already been used (server-side dedup).

    Atomically marks the nonce as used with a 1h TTL.
    Returns (is_unique, reason). If not unique, reason explains why.

    Fail-closed: if Redis is down, nonces are REJECTED.
    """
    r = await _get_redis()
    if r is None:
        return False, "nonce_check_unavailable (Redis down — fail-closed)"

    try:
        nonce_key = f"sign_nonce:{nonce.lower()}"
        is_new = await r.set(nonce_key, "1", nx=True, ex=NONCE_TTL)

        if not is_new:
            return False, f"nonce_already_used ({nonce[:18]}...)"

        return True, None

    except Exception as e:
        logger.error("Nonce check failed: %s", e, extra={"service": "signing_rl"})
        return False, f"nonce_check_error ({e})"
