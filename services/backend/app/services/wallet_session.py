"""
Wallet-auth HMAC sessions (H4 — anti-replay).

A wallet proves key possession ONCE (EIP-191 signature) to obtain a short-lived
session secret, then authenticates each request with a SINGLE-USE HMAC over
(nonce:timestamp) keyed by that secret. The secret lives only in Redis and the
client's in-memory cache — it is never transmitted on subsequent requests, so a
captured per-request MAC cannot be reused (nonce is single-use) or forged.

Storage: Redis key `wallet_session:{id}` → {"address","secret"}, TTL 15 min.
Fail-closed: if Redis is unavailable, sessions can't be created/looked up and
authentication fails.
"""

import json
import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_TTL = 900  # 15 minutes
_PREFIX = "wallet_session:"


async def create_wallet_session(address: str) -> tuple[str, str]:
    """Create a session for `address`. Returns (session_id, session_secret).

    Raises RuntimeError if Redis is unavailable (fail-closed).
    """
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot create wallet session")

    session_id = secrets.token_urlsafe(24)
    session_secret = secrets.token_hex(32)  # 256-bit HMAC key
    await r.set(
        _PREFIX + session_id,
        json.dumps({"address": address.lower(), "secret": session_secret}),
        ex=SESSION_TTL,
    )
    logger.info("Wallet session created for %s", address.lower())
    return session_id, session_secret


async def get_wallet_session(session_id: str) -> Optional[dict]:
    """Return {"address","secret"} for a session, or None if missing/expired/Redis-down."""
    from app.services.cache_service import get_redis

    if not session_id:
        return None
    r = await get_redis()
    if r is None:
        return None
    raw = await r.get(_PREFIX + session_id)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        return json.loads(raw)
    except Exception:
        return None


async def revoke_wallet_session(session_id: str) -> None:
    """Best-effort session revocation."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is not None and session_id:
        try:
            await r.delete(_PREFIX + session_id)
        except Exception as exc:
            logger.warning("Wallet session revoke failed: %s", exc)
