"""
RSends Backend — single-use WebSocket authorization tickets (M4).

Browser WebSockets cannot send custom auth headers, so the sweep-feed WS
(`/ws/sweep-feed/{owner}`) cannot use the normal wallet-auth headers. Instead
the client first mints a short-lived, single-use ticket via an HTTP route
guarded by @require_wallet_auth (so the owner is the *verified* wallet), then
connects with `?ticket=`. The WS consumes the ticket atomically and checks the
bound owner matches the requested feed.

Why this is safe even though the ticket rides in the URL: it is random
(token_urlsafe), bound to one owner, expires in 30s, and is single-use
(consumed with GETDEL on first connect) — a leaked/logged ticket is inert.

Fail-closed: if Redis is unavailable, no ticket is minted / no ticket
validates, so the WS cannot be authorized.
"""

import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

_TICKET_PREFIX = "ws_sweep_ticket:"
TICKET_TTL_SECONDS = 30


async def _redis():
    try:
        from app.services.cache_service import get_redis

        return await get_redis()
    except Exception:
        return None


async def mint_sweep_ticket(owner: str) -> Optional[str]:
    """Mint a single-use ticket bound to `owner`. Returns None if Redis is down."""
    r = await _redis()
    if r is None:
        return None
    try:
        ticket = secrets.token_urlsafe(24)
        await r.set(f"{_TICKET_PREFIX}{ticket}", owner.lower(), ex=TICKET_TTL_SECONDS)
        return ticket
    except Exception as e:
        logger.warning("mint_sweep_ticket failed: %s", e)
        return None


async def consume_sweep_ticket(ticket: Optional[str]) -> Optional[str]:
    """Atomically consume a ticket; return the bound owner (lowercase) or None.

    Single-use: the key is deleted on read (GETDEL), so a replay finds nothing.
    """
    if not ticket:
        return None
    r = await _redis()
    if r is None:
        return None
    key = f"{_TICKET_PREFIX}{ticket}"
    try:
        owner = await r.getdel(key)
    except Exception:
        # Fallback for clients without GETDEL: GET then DEL (best-effort).
        try:
            pipe = r.pipeline()
            pipe.get(key)
            pipe.delete(key)
            owner = (await pipe.execute())[0]
        except Exception as e:
            logger.warning("consume_sweep_ticket failed: %s", e)
            return None
    if owner is None:
        return None
    if isinstance(owner, (bytes, bytearray)):
        owner = owner.decode()
    return owner.lower()
