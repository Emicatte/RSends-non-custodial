"""
RSends Backend — Multi-Tier Spending Policy.

Enforces five layers of spending limits before any sweep executes.

Tiers:
  1. Per-TX         — max 10 ETH per single transaction
  2. Per-Hour       — sliding window, max 25 ETH per source address
  3. Per-Day        — max 50 ETH per source address
  4. Global Daily   — max 500 ETH across all sources combined
  5. Velocity       — max 10 sweeps per source per hour

All amounts are in Wei (str) to preserve uint256 precision.
Redis MULTI ensures atomic check + reserve.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants (all in Wei — 1 ETH = 10^18 Wei)
# ═══════════════════════════════════════════════════════════════

WEI_PER_ETH = 10 ** 18

DEFAULT_PER_TX_LIMIT = 10 * WEI_PER_ETH            # 10 ETH
DEFAULT_PER_HOUR_LIMIT = 25 * WEI_PER_ETH           # 25 ETH per source
DEFAULT_PER_DAY_LIMIT = 50 * WEI_PER_ETH            # 50 ETH per source
DEFAULT_GLOBAL_DAILY_LIMIT = 500 * WEI_PER_ETH      # 500 ETH global
DEFAULT_MAX_SWEEPS_PER_HOUR = 10                      # per source

HOUR_SECONDS = 3600
DAY_SECONDS = 86400


# ═══════════════════════════════════════════════════════════════
#  Data Types
# ═══════════════════════════════════════════════════════════════

@dataclass
class PolicyResult:
    """Result of a spending policy check."""

    allowed: bool
    reason: str
    remaining_wei: str          # remaining allowance in the binding tier
    tier: str                   # which tier was the binding constraint

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "remaining_wei": self.remaining_wei,
            "tier": self.tier,
        }


@dataclass
class SpendingStatus:
    """Current spending status for a source address."""

    source: str
    chain_id: int
    per_hour_spent_wei: str
    per_hour_limit_wei: str
    per_day_spent_wei: str
    per_day_limit_wei: str
    global_daily_spent_wei: str
    global_daily_limit_wei: str
    sweeps_this_hour: int
    max_sweeps_per_hour: int


# ═══════════════════════════════════════════════════════════════
#  Exception
# ═══════════════════════════════════════════════════════════════

class SpendingPolicyError(Exception):
    """Non-limit errors (Redis unavailable, etc.)."""
    pass


# ═══════════════════════════════════════════════════════════════
#  SpendingPolicy
# ═══════════════════════════════════════════════════════════════

class SpendingPolicy:
    """Multi-tier spending limiter backed by Redis.

    Usage::

        policy = SpendingPolicy()

        result = await policy.check_and_reserve(
            source="0xAbC...",
            amount_wei="5000000000000000000",  # 5 ETH
            chain_id=8453,
        )

        if not result.allowed:
            raise TooMuchSpending(result.reason)

        try:
            await execute_sweep(...)
        except Exception:
            # TX failed — release the reserved amount
            await policy.release(source, amount_wei, chain_id)
    """

    def __init__(
        self,
        per_tx_limit: int = DEFAULT_PER_TX_LIMIT,
        per_hour_limit: int = DEFAULT_PER_HOUR_LIMIT,
        per_day_limit: int = DEFAULT_PER_DAY_LIMIT,
        global_daily_limit: int = DEFAULT_GLOBAL_DAILY_LIMIT,
        max_sweeps_per_hour: int = DEFAULT_MAX_SWEEPS_PER_HOUR,
    ):
        self.per_tx_limit = per_tx_limit
        self.per_hour_limit = per_hour_limit
        self.per_day_limit = per_day_limit
        self.global_daily_limit = global_daily_limit
        self.max_sweeps_per_hour = max_sweeps_per_hour

    # ── Keys ──────────────────────────────────────────────

    @staticmethod
    def _hour_key(source: str, chain_id: int) -> str:
        return f"spend:hour:{chain_id}:{source.lower()}"

    @staticmethod
    def _day_key(source: str, chain_id: int) -> str:
        return f"spend:day:{chain_id}:{source.lower()}"

    @staticmethod
    def _global_key(chain_id: int) -> str:
        return f"spend:global:{chain_id}"

    @staticmethod
    def _velocity_key(source: str, chain_id: int) -> str:
        return f"spend:vel:{chain_id}:{source.lower()}"

    # ── Check + Reserve (atomic via Redis MULTI) ──────────

    async def check_and_reserve(
        self,
        source: str,
        amount_wei: str,
        chain_id: int,
    ) -> PolicyResult:
        """Check all tiers and atomically reserve the amount if allowed.

        Args:
            source: Source wallet address.
            amount_wei: Amount in Wei as string.
            chain_id: EVM chain ID.

        Returns:
            PolicyResult with allowed=True/False and details.
        """
        amount = int(amount_wei)

        # ── Tier 1: Per-TX limit (no Redis needed) ────────
        if amount > self.per_tx_limit:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Amount {amount_wei} exceeds per-TX limit "
                    f"of {self.per_tx_limit} Wei"
                ),
                remaining_wei=str(self.per_tx_limit),
                tier="per_tx",
            )

        # ── Tiers 2-5: Redis-backed checks ───────────────
        try:
            return await self._check_redis(source, amount, chain_id)
        except Exception as exc:
            # Redis down — fail closed (deny) for safety
            logger.error("Spending policy Redis error — denying: %s", exc)
            return PolicyResult(
                allowed=False,
                reason=f"Spending policy unavailable: {exc}",
                remaining_wei="0",
                tier="error",
            )

    async def _check_redis(
        self,
        source: str,
        amount: int,
        chain_id: int,
    ) -> PolicyResult:
        """Redis-backed multi-tier check with MULTI/EXEC for atomicity."""
        from app.services.cache_service import get_redis

        r = await get_redis()
        now = time.time()

        hour_key = self._hour_key(source, chain_id)
        day_key = self._day_key(source, chain_id)
        global_key = self._global_key(chain_id)
        vel_key = self._velocity_key(source, chain_id)

        # ── Read current state ────────────────────────────
        pipe = r.pipeline()
        pipe.zrangebyscore(hour_key, now - HOUR_SECONDS, "+inf", withscores=True)
        pipe.zrangebyscore(day_key, now - DAY_SECONDS, "+inf", withscores=True)
        pipe.zrangebyscore(global_key, now - DAY_SECONDS, "+inf", withscores=True)
        pipe.zrangebyscore(vel_key, now - HOUR_SECONDS, "+inf")
        state = await pipe.execute()

        hour_entries = state[0]
        day_entries = state[1]
        global_entries = state[2]
        vel_entries = state[3]

        hour_spent = sum(int(float(member.split(":")[0])) for member, _ in hour_entries)
        day_spent = sum(int(float(member.split(":")[0])) for member, _ in day_entries)
        global_spent = sum(int(float(member.split(":")[0])) for member, _ in global_entries)
        sweep_count = len(vel_entries)

        # ── Tier 2: Per-Hour ──────────────────────────────
        if hour_spent + amount > self.per_hour_limit:
            remaining = max(0, self.per_hour_limit - hour_spent)
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Hourly limit exceeded for {source}: "
                    f"spent={hour_spent}, requested={amount}, "
                    f"limit={self.per_hour_limit}"
                ),
                remaining_wei=str(remaining),
                tier="per_hour",
            )

        # ── Tier 3: Per-Day ───────────────────────────────
        if day_spent + amount > self.per_day_limit:
            remaining = max(0, self.per_day_limit - day_spent)
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Daily limit exceeded for {source}: "
                    f"spent={day_spent}, requested={amount}, "
                    f"limit={self.per_day_limit}"
                ),
                remaining_wei=str(remaining),
                tier="per_day",
            )

        # ── Tier 4: Global Daily ──────────────────────────
        if global_spent + amount > self.global_daily_limit:
            remaining = max(0, self.global_daily_limit - global_spent)
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Global daily limit exceeded on chain {chain_id}: "
                    f"spent={global_spent}, requested={amount}, "
                    f"limit={self.global_daily_limit}"
                ),
                remaining_wei=str(remaining),
                tier="global_daily",
            )

        # ── Tier 5: Velocity ─────────────────────────────
        if sweep_count >= self.max_sweeps_per_hour:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Velocity limit: {sweep_count} sweeps this hour "
                    f"for {source} (max {self.max_sweeps_per_hour})"
                ),
                remaining_wei=str(max(0, self.per_hour_limit - hour_spent)),
                tier="velocity",
            )

        # ── All tiers passed — atomically reserve ─────────
        member = f"{amount}:{now}"
        reserve_pipe = r.pipeline(transaction=True)
        # Add to hourly window
        reserve_pipe.zadd(hour_key, {member: now})
        reserve_pipe.expire(hour_key, HOUR_SECONDS + 60)
        # Add to daily window
        reserve_pipe.zadd(day_key, {member: now})
        reserve_pipe.expire(day_key, DAY_SECONDS + 60)
        # Add to global daily window
        global_member = f"{amount}:{now}:{source.lower()}"
        reserve_pipe.zadd(global_key, {global_member: now})
        reserve_pipe.expire(global_key, DAY_SECONDS + 60)
        # Velocity counter
        reserve_pipe.zadd(vel_key, {str(now): now})
        reserve_pipe.expire(vel_key, HOUR_SECONDS + 60)
        # Cleanup expired entries
        reserve_pipe.zremrangebyscore(hour_key, 0, now - HOUR_SECONDS)
        reserve_pipe.zremrangebyscore(day_key, 0, now - DAY_SECONDS)
        reserve_pipe.zremrangebyscore(global_key, 0, now - DAY_SECONDS)
        reserve_pipe.zremrangebyscore(vel_key, 0, now - HOUR_SECONDS)
        await reserve_pipe.execute()

        remaining = min(
            self.per_hour_limit - hour_spent - amount,
            self.per_day_limit - day_spent - amount,
            self.global_daily_limit - global_spent - amount,
        )

        logger.info(
            "Spending reserved: source=%s amount=%s chain=%d remaining=%s",
            source,
            amount,
            chain_id,
            remaining,
        )

        return PolicyResult(
            allowed=True,
            reason="OK",
            remaining_wei=str(max(0, remaining)),
            tier="none",
        )

    # ── Release (for failed TX) ───────────────────────────

    async def release(
        self,
        source: str,
        amount_wei: str,
        chain_id: int,
    ) -> bool:
        """Release a previously reserved amount (e.g. TX failed).

        Removes the most recent matching entry from each window.
        Returns True if successfully released.
        """
        try:
            from app.services.cache_service import get_redis

            r = await get_redis()
            amount = int(amount_wei)

            hour_key = self._hour_key(source, chain_id)
            day_key = self._day_key(source, chain_id)
            global_key = self._global_key(chain_id)
            vel_key = self._velocity_key(source, chain_id)

            # Find and remove the most recent entry matching this amount
            prefix = f"{amount}:"
            for key in (hour_key, day_key):
                members = await r.zrangebyscore(key, "-inf", "+inf")
                for m in reversed(members):
                    if m.startswith(prefix):
                        await r.zrem(key, m)
                        break

            # Global key has a different format
            g_prefix = f"{amount}:"
            g_members = await r.zrangebyscore(global_key, "-inf", "+inf")
            for m in reversed(g_members):
                if m.startswith(g_prefix) and source.lower() in m:
                    await r.zrem(global_key, m)
                    break

            # Remove one velocity entry
            vel_members = await r.zrangebyscore(vel_key, "-inf", "+inf")
            if vel_members:
                await r.zrem(vel_key, vel_members[-1])

            logger.info(
                "Spending released: source=%s amount=%s chain=%d",
                source,
                amount_wei,
                chain_id,
            )
            return True

        except Exception as exc:
            logger.error("Failed to release spending reservation: %s", exc)
            return False

    # ── Status query ──────────────────────────────────────

    async def get_status(
        self,
        source: str,
        chain_id: int,
    ) -> SpendingStatus:
        """Get current spending status for a source address."""
        try:
            from app.services.cache_service import get_redis

            r = await get_redis()
            now = time.time()

            pipe = r.pipeline()
            pipe.zrangebyscore(
                self._hour_key(source, chain_id),
                now - HOUR_SECONDS, "+inf",
                withscores=True,
            )
            pipe.zrangebyscore(
                self._day_key(source, chain_id),
                now - DAY_SECONDS, "+inf",
                withscores=True,
            )
            pipe.zrangebyscore(
                self._global_key(chain_id),
                now - DAY_SECONDS, "+inf",
                withscores=True,
            )
            pipe.zrangebyscore(
                self._velocity_key(source, chain_id),
                now - HOUR_SECONDS, "+inf",
            )
            state = await pipe.execute()

            hour_spent = sum(
                int(float(m.split(":")[0])) for m, _ in state[0]
            )
            day_spent = sum(
                int(float(m.split(":")[0])) for m, _ in state[1]
            )
            global_spent = sum(
                int(float(m.split(":")[0])) for m, _ in state[2]
            )

            return SpendingStatus(
                source=source,
                chain_id=chain_id,
                per_hour_spent_wei=str(hour_spent),
                per_hour_limit_wei=str(self.per_hour_limit),
                per_day_spent_wei=str(day_spent),
                per_day_limit_wei=str(self.per_day_limit),
                global_daily_spent_wei=str(global_spent),
                global_daily_limit_wei=str(self.global_daily_limit),
                sweeps_this_hour=len(state[3]),
                max_sweeps_per_hour=self.max_sweeps_per_hour,
            )

        except Exception as exc:
            logger.error("Failed to get spending status: %s", exc)
            return SpendingStatus(
                source=source,
                chain_id=chain_id,
                per_hour_spent_wei="0",
                per_hour_limit_wei=str(self.per_hour_limit),
                per_day_spent_wei="0",
                per_day_limit_wei=str(self.per_day_limit),
                global_daily_spent_wei="0",
                global_daily_limit_wei=str(self.global_daily_limit),
                sweeps_this_hour=0,
                max_sweeps_per_hour=self.max_sweeps_per_hour,
            )


# ═══════════════════════════════════════════════════════════════
#  Module Singleton
# ═══════════════════════════════════════════════════════════════

_policy: Optional[SpendingPolicy] = None


def get_spending_policy() -> SpendingPolicy:
    """Get or create the global spending policy instance."""
    global _policy
    if _policy is None:
        _policy = SpendingPolicy()
    return _policy
