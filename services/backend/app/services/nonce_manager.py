"""
RSends Backend — Nonce Manager (Redis-backed Atomic Nonce Management).

Provides atomic nonce allocation for the hot wallet using Redis.
Prevents nonce collisions across multiple Celery workers.

Methods:
  initialize(chain_id)        — sync nonce from chain via RPC consensus
  get_next(chain_id)          — Redis INCR, returns next nonce atomically
  reserve_range(chain_id, n)  — Redis INCRBY, returns (start, end) range
  sync_from_chain(chain_id)   — re-sync from chain if chain > Redis
  get_current(chain_id)       — read current nonce without incrementing

Redis key: nonce:{chain_id}:{address}
Lock key:  nonce:lock:{chain_id}:{address}

The lock prevents race conditions during sync_from_chain while
get_next/reserve_range remain lock-free (atomic INCR).
"""

import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Lock timeout for sync operations
SYNC_LOCK_TIMEOUT = 10  # seconds
SYNC_LOCK_BLOCKING_TIMEOUT = 15  # seconds


class NonceError(Exception):
    """Nonce management error."""
    pass


class NonceManager:
    """Redis-based atomic nonce manager for EVM hot wallets.

    Usage::

        nm = NonceManager(chain_id=8453)

        # First time: sync from chain
        await nm.initialize()

        # Get next nonce for a transaction
        nonce = await nm.get_next()

        # Reserve a range for batch transactions
        start, end = await nm.reserve_range(5)
        # nonces: start, start+1, ..., end

        # Periodic re-sync from chain
        await nm.sync_from_chain()
    """

    def __init__(self, chain_id: int = 8453):
        self.chain_id = chain_id
        self._address: Optional[str] = None

    # ── Keys ──────────────────────────────────────────────

    def _nonce_key(self, address: str) -> str:
        return f"nonce:{self.chain_id}:{address.lower()}"

    def _lock_key(self, address: str) -> str:
        return f"nonce:lock:{self.chain_id}:{address.lower()}"

    # ── Address resolution ────────────────────────────────

    async def _get_address(self) -> str:
        if self._address is None:
            from app.services.key_manager import get_signer
            signer = get_signer()
            self._address = await signer.get_address()
        return self._address

    # ── Redis access ──────────────────────────────────────

    @staticmethod
    async def _get_redis():
        from app.services.cache_service import get_redis
        return await get_redis()

    # ── Initialize ────────────────────────────────────────

    async def initialize(self) -> int:
        """Sync nonce from chain and set in Redis.

        Queries the chain for the current transaction count (pending)
        using RPC consensus, then sets the Redis nonce key.

        Returns:
            The nonce value set in Redis.
        """
        address = await self._get_address()
        chain_nonce = await self._get_chain_nonce(address)

        r = await self._get_redis()
        key = self._nonce_key(address)

        # Only set if Redis doesn't have a value yet, or chain is ahead
        current = await r.get(key)
        if current is None or int(current) < chain_nonce:
            await r.set(key, chain_nonce)
            logger.info(
                "Nonce initialized: chain=%d address=%s nonce=%d",
                self.chain_id, address, chain_nonce,
            )
            return chain_nonce

        current_val = int(current)
        logger.info(
            "Nonce already initialized: chain=%d address=%s "
            "redis=%d chain=%d (keeping redis value)",
            self.chain_id, address, current_val, chain_nonce,
        )
        return current_val

    # ── Get Next (atomic INCR) ────────────────────────────

    async def get_next(self) -> int:
        """Atomically get the next nonce and increment the counter.

        Uses Redis INCR which is atomic across all workers.
        The returned value is the nonce to use (pre-increment value).

        Returns:
            The nonce to use for the next transaction.

        Raises:
            NonceError: If Redis is unavailable or nonce not initialized.
        """
        address = await self._get_address()
        r = await self._get_redis()
        key = self._nonce_key(address)

        # Check if initialized
        exists = await r.exists(key)
        if not exists:
            raise NonceError(
                f"Nonce not initialized for {address} on chain {self.chain_id}. "
                f"Call initialize() first."
            )

        # INCR returns the value AFTER increment.
        # We want the pre-increment value as the nonce.
        # So we INCR and subtract 1.
        new_val = await r.incr(key)
        nonce = new_val - 1

        logger.debug(
            "Nonce allocated: chain=%d address=%s nonce=%d",
            self.chain_id, address, nonce,
        )
        return nonce

    # ── Reserve Range (atomic INCRBY) ─────────────────────

    async def reserve_range(self, count: int) -> tuple[int, int]:
        """Atomically reserve a range of nonces for batch operations.

        Uses Redis INCRBY which is atomic across all workers.

        Args:
            count: Number of nonces to reserve (must be >= 1).

        Returns:
            (start_nonce, end_nonce) — inclusive range.
            E.g., reserve_range(5) might return (10, 14).

        Raises:
            NonceError: If count < 1, Redis unavailable, or not initialized.
        """
        if count < 1:
            raise NonceError(f"reserve_range count must be >= 1, got {count}")

        address = await self._get_address()
        r = await self._get_redis()
        key = self._nonce_key(address)

        exists = await r.exists(key)
        if not exists:
            raise NonceError(
                f"Nonce not initialized for {address} on chain {self.chain_id}. "
                f"Call initialize() first."
            )

        # INCRBY returns the value AFTER the increment
        new_val = await r.incrby(key, count)
        start = new_val - count
        end = new_val - 1

        logger.info(
            "Nonce range reserved: chain=%d address=%s range=[%d, %d] count=%d",
            self.chain_id, address, start, end, count,
        )
        return start, end

    # ── Sync from Chain ───────────────────────────────────

    async def sync_from_chain(self) -> int:
        """Re-sync nonce from chain with lock to prevent races.

        Queries the chain nonce via RPC consensus. If the chain nonce
        is higher than Redis (e.g., transactions confirmed externally),
        updates Redis to match.

        Uses a Redis lock to prevent concurrent syncs.

        Returns:
            The nonce value after sync.
        """
        address = await self._get_address()
        r = await self._get_redis()
        lock_key = self._lock_key(address)
        nonce_key = self._nonce_key(address)

        # Acquire lock (prevents concurrent syncs)
        lock = r.lock(
            lock_key,
            timeout=SYNC_LOCK_TIMEOUT,
            blocking_timeout=SYNC_LOCK_BLOCKING_TIMEOUT,
        )

        acquired = await lock.acquire()
        if not acquired:
            # Another worker is syncing — read current value
            current = await r.get(nonce_key)
            if current is not None:
                return int(current)
            raise NonceError(
                f"Could not acquire sync lock and no nonce set for "
                f"{address} on chain {self.chain_id}"
            )

        try:
            chain_nonce = await self._get_chain_nonce(address)
            current = await r.get(nonce_key)
            current_val = int(current) if current is not None else 0

            if chain_nonce > current_val:
                await r.set(nonce_key, chain_nonce)
                logger.warning(
                    "Nonce sync: chain ahead — chain=%d address=%s "
                    "redis=%d -> chain=%d",
                    self.chain_id, address, current_val, chain_nonce,
                )
                return chain_nonce

            logger.debug(
                "Nonce sync: redis current — chain=%d address=%s "
                "redis=%d chain=%d",
                self.chain_id, address, current_val, chain_nonce,
            )
            return current_val

        finally:
            await lock.release()

    # ── Read Current ──────────────────────────────────────

    async def get_current(self) -> int:
        """Read the current nonce value without incrementing.

        Returns:
            Current nonce value in Redis.

        Raises:
            NonceError: If not initialized.
        """
        address = await self._get_address()
        r = await self._get_redis()
        key = self._nonce_key(address)

        val = await r.get(key)
        if val is None:
            raise NonceError(
                f"Nonce not initialized for {address} on chain {self.chain_id}"
            )
        return int(val)

    # ── Chain nonce query ─────────────────────────────────

    async def _get_chain_nonce(self, address: str) -> int:
        """Query chain for current nonce via RPC consensus."""
        from app.services.rpc_manager import get_rpc_manager

        mgr = get_rpc_manager(self.chain_id)
        result = await mgr.consensus_call(
            "eth_getTransactionCount",
            [address, "pending"],
        )
        return int(result, 16)

    # ── Info / State ─────────────────────────────────────

    async def info(self) -> dict:
        """Status for health checks."""
        address = await self._get_address()
        r = await self._get_redis()
        key = self._nonce_key(address)
        val = await r.get(key)

        return {
            "chain_id": self.chain_id,
            "address": address,
            "redis_nonce": int(val) if val is not None else None,
            "initialized": val is not None,
        }

    async def get_state(self) -> dict:
        """Full state for monitoring/debugging.

        Returns dict with:
            redis_nonce:   current nonce counter in Redis (next to allocate)
            chain_latest:  confirmed nonce (eth_getTransactionCount 'latest')
            chain_pending: pending nonce (eth_getTransactionCount 'pending')
            gap:           redis_nonce - chain_pending (positive = reserved but unconfirmed)
        """
        from app.services.rpc_manager import get_rpc_manager

        address = await self._get_address()
        r = await self._get_redis()
        key = self._nonce_key(address)
        mgr = get_rpc_manager(self.chain_id)

        redis_val = await r.get(key)
        redis_nonce = int(redis_val) if redis_val is not None else None

        latest_raw = await mgr.consensus_call(
            "eth_getTransactionCount", [address, "latest"],
        )
        pending_raw = await mgr.consensus_call(
            "eth_getTransactionCount", [address, "pending"],
        )
        chain_latest = int(latest_raw, 16)
        chain_pending = int(pending_raw, 16)

        gap = (redis_nonce - chain_pending) if redis_nonce is not None else None

        return {
            "redis_nonce": redis_nonce,
            "chain_latest": chain_latest,
            "chain_pending": chain_pending,
            "gap": gap,
        }


# ═══════════════════════════════════════════════════════════════
#  Module Singleton
# ═══════════════════════════════════════════════════════════════

_managers: dict[int, NonceManager] = {}


def get_nonce_manager(chain_id: int = 8453) -> NonceManager:
    """Get or create a NonceManager for the given chain."""
    if chain_id not in _managers:
        _managers[chain_id] = NonceManager(chain_id=chain_id)
    return _managers[chain_id]
