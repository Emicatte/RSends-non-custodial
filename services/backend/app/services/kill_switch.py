"""Kill switch: global and per-client execution gating.

Redis-backed state for live toggling via admin API without restart.
State is read on every protected call; changes take effect immediately.

Fail-closed: if Redis is unreachable and we can't verify the switch state,
we DENY execution. An attacker causing a Redis outage should NOT be able
to force execution by breaking our ability to check.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_GLOBAL_KILL_KEY = "kill_switch:global"
_CLIENT_KILL_PREFIX = "kill_switch:client:"
_AUTO_STOP_KEY = "kill_switch:auto_stop"

_CHECK_CACHE_TTL = 2

_cache: dict = {}
_cache_expiry: float = 0.0


class KillSwitch:

    @staticmethod
    async def _read_state() -> dict:
        global _cache, _cache_expiry
        now = time.monotonic()
        if now < _cache_expiry:
            return _cache

        from app.services.cache_service import get_redis

        r = await get_redis()
        if r is None:
            logger.warning("Kill switch: Redis unavailable — denying execution")
            return {"redis_available": False}

        try:
            global_flag = await r.get(_GLOBAL_KILL_KEY)
            auto_stop_val = await r.get(_AUTO_STOP_KEY)
            state = {
                "redis_available": True,
                "global_stopped": global_flag in (b"1", "1"),
                "auto_stop": auto_stop_val.decode() if isinstance(auto_stop_val, bytes) else auto_stop_val,
            }
            _cache = state
            _cache_expiry = now + _CHECK_CACHE_TTL
            return state
        except Exception as e:
            logger.warning("Kill switch read failed (fail-closed): %s", e)
            return {"redis_available": False}

    async def can_execute(self, client_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Return (allowed, reason). Fail-closed on any error."""
        state = await self._read_state()

        if not state.get("redis_available"):
            return False, "kill_switch_unverifiable"

        if state.get("global_stopped"):
            return False, "global_kill_switch_active"

        if state.get("auto_stop"):
            return False, f"auto_stop_active:{state['auto_stop']}"

        if client_id:
            from app.services.cache_service import get_redis

            r = await get_redis()
            if r is None:
                return False, "kill_switch_unverifiable"
            try:
                client_flag = await r.get(f"{_CLIENT_KILL_PREFIX}{client_id}")
                if client_flag in (b"1", "1"):
                    return False, f"client_kill_switch_active:{client_id}"
            except Exception as e:
                logger.warning("Kill switch client check failed: %s", e)
                return False, "kill_switch_unverifiable"

        return True, None


kill_switch = KillSwitch()


async def auto_stop(reason: str, ttl_seconds: int = 3600) -> None:
    """Trigger auto-stop with a reason message. Auto-clears after TTL."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        logger.error("Cannot auto-stop: Redis unavailable")
        return
    try:
        await r.set(_AUTO_STOP_KEY, reason, ex=ttl_seconds)
        logger.warning("Auto-stop activated: reason=%s ttl=%ds", reason, ttl_seconds)
    except Exception as e:
        logger.error("Auto-stop failed: %s", e)


async def clear_auto_stop() -> None:
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable")
    await r.delete(_AUTO_STOP_KEY)
    _invalidate_cache()
    logger.info("Auto-stop cleared")


async def set_global_stop(active: bool) -> None:
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable")
    if active:
        await r.set(_GLOBAL_KILL_KEY, "1")
        logger.warning("Global kill switch ACTIVATED")
    else:
        await r.delete(_GLOBAL_KILL_KEY)
        logger.info("Global kill switch deactivated")
    _invalidate_cache()


async def set_client_stop(client_id: str, active: bool) -> None:
    from app.services.cache_service import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable")
    if active:
        await r.set(f"{_CLIENT_KILL_PREFIX}{client_id}", "1")
        logger.warning("Client kill switch ACTIVATED: %s", client_id)
    else:
        await r.delete(f"{_CLIENT_KILL_PREFIX}{client_id}")
        logger.info("Client kill switch deactivated: %s", client_id)


async def get_status() -> dict:
    """Return current kill switch status for admin endpoints."""
    state = await KillSwitch._read_state()
    allowed, reason = await kill_switch.can_execute()
    return {
        "executing_allowed": allowed,
        "reason": reason,
        "global_stopped": state.get("global_stopped", False),
        "auto_stop": state.get("auto_stop"),
        "redis_available": state.get("redis_available", False),
    }


def _invalidate_cache() -> None:
    global _cache_expiry
    _cache_expiry = 0.0
