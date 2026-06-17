"""
RSends Backend — Circuit Breaker Service (Redis-backed).

States:
  CLOSED    → normal operation, failures are counted
  OPEN      → service assumed down, calls fail-fast
  HALF_OPEN → recovery probe: limited calls to test service

OPEN triggers (any one is sufficient):
  - Error rate > 5% in a 5-minute sliding window (min 20 calls)
  - 3+ consecutive failures (configurable)
  - Manual trigger via force_open(reason)

Redis Lua scripts guarantee atomic state transitions.
Falls back to in-memory state when Redis is unavailable.

Backward-compatible: existing consumers (cache_service, sweep_service,
external_health) continue to work unchanged via the call() method.

Provides:
  - CircuitBreaker class (per-service, Redis-backed)
  - @circuit_breaker(name=...) decorator for async functions
  - Global registry for health monitoring
  - Prometheus metrics: state, failures, successes
  - Async API: check(), record_success(), record_failure(),
    force_open(), force_close(), get_state()
"""

import asyncio
import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  Prometheus Metrics
# ═══════════════════════════════════════════════════════════════

CB_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["service"],
)
CB_FAILURES = Counter(
    "circuit_breaker_failures_total",
    "Total circuit breaker failures",
    ["service"],
)
CB_SUCCESSES = Counter(
    "circuit_breaker_successes_total",
    "Total circuit breaker successes",
    ["service"],
)
CB_STATE_TRANSITIONS = Counter(
    "circuit_breaker_transitions_total",
    "Total circuit breaker state transitions",
    ["service", "from_state", "to_state"],
)


# ═══════════════════════════════════════════════════════════════
#  Circuit Breaker States
# ═══════════════════════════════════════════════════════════════

class CBState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    @property
    def metric_value(self) -> int:
        return {"closed": 0, "open": 1, "half_open": 2}[self.value]


# ═══════════════════════════════════════════════════════════════
#  Circuit Breaker Exception
# ═══════════════════════════════════════════════════════════════

class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. Retry after {retry_after:.1f}s"
        )


class SweepBlockedError(Exception):
    """Raised when a financial operation is blocked due to critical dependency failure.

    Fail-closed: sweep, transfer, and execution operations MUST NOT proceed
    when Redis or Postgres are unavailable, as this could lead to duplicate
    executions or data inconsistency.
    """

    def __init__(self, dependency: str, reason: str = ""):
        self.dependency = dependency
        self.reason = reason
        super().__init__(
            f"Financial operation BLOCKED: {dependency} unavailable"
            + (f" — {reason}" if reason else "")
        )


# ═══════════════════════════════════════════════════════════════
#  Redis Lua Scripts (atomic state transitions)
# ═══════════════════════════════════════════════════════════════

# Script 1: Check if a call is allowed
_LUA_CHECK_ALLOWED = """
-- KEYS[1] = cb:{name}:state
-- KEYS[2] = cb:{name}:last_fail
-- KEYS[3] = cb:{name}:ho_calls
-- ARGV[1] = now (seconds, float)
-- ARGV[2] = recovery_timeout (seconds)
-- ARGV[3] = half_open_max_calls
-- Returns: {allowed (0|1), state_str, old_state_str}

local state = redis.call('GET', KEYS[1]) or 'closed'
local now = tonumber(ARGV[1])
local recovery = tonumber(ARGV[2])
local ho_max = tonumber(ARGV[3])

if state == 'open' then
    local last_fail = tonumber(redis.call('GET', KEYS[2]) or '0')
    if (now - last_fail) >= recovery then
        redis.call('SET', KEYS[1], 'half_open')
        redis.call('SET', KEYS[3], '0')
        return {1, 'half_open', 'open'}
    end
    return {0, 'open', 'open'}
elseif state == 'half_open' then
    local ho_calls = tonumber(redis.call('GET', KEYS[3]) or '0')
    if ho_calls >= ho_max then
        return {0, 'half_open', 'half_open'}
    end
    redis.call('INCR', KEYS[3])
    return {1, 'half_open', 'half_open'}
end
return {1, 'closed', 'closed'}
"""

# Script 2: Record success/failure and check for state transitions
_LUA_RECORD_RESULT = """
-- KEYS[1] = cb:{name}:state
-- KEYS[2] = cb:{name}:failures (consecutive)
-- KEYS[3] = cb:{name}:last_fail (timestamp)
-- KEYS[4] = cb:{name}:window (sorted set: sliding-window calls)
-- ARGV[1] = result_type ("success" | "failure")
-- ARGV[2] = now (seconds, float)
-- ARGV[3] = failure_threshold (consecutive)
-- ARGV[4] = error_rate_threshold (0.05 = 5%)
-- ARGV[5] = error_rate_window (seconds)
-- ARGV[6] = min_calls_for_rate
-- Returns: {new_state, old_state, transitioned (0|1)}

local result = ARGV[1]
local now = tonumber(ARGV[2])
local fail_threshold = tonumber(ARGV[3])
local rate_threshold = tonumber(ARGV[4])
local rate_window = tonumber(ARGV[5])
local min_calls = tonumber(ARGV[6])

local old_state = redis.call('GET', KEYS[1]) or 'closed'

-- Track in sliding window (member = "now:result", score = now)
local member = tostring(now) .. ':' .. result
redis.call('ZADD', KEYS[4], now, member)
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now - rate_window)

if result == 'success' then
    redis.call('SET', KEYS[2], '0')
    if old_state == 'half_open' then
        redis.call('SET', KEYS[1], 'closed')
        redis.call('DEL', KEYS[3])
        return {'closed', old_state, 1}
    end
    return {old_state, old_state, 0}
end

-- Failure path
local failures = redis.call('INCR', KEYS[2])
redis.call('SET', KEYS[3], tostring(now))

if old_state == 'half_open' then
    redis.call('SET', KEYS[1], 'open')
    return {'open', old_state, 1}
end

-- Check consecutive failures
if failures >= fail_threshold then
    redis.call('SET', KEYS[1], 'open')
    return {'open', old_state, 1}
end

-- Check error rate in sliding window
local all_entries = redis.call('ZRANGEBYSCORE', KEYS[4], now - rate_window, '+inf')
local total = #all_entries
if total >= min_calls then
    local errors = 0
    for _, entry in ipairs(all_entries) do
        if string.find(entry, ':failure') then
            errors = errors + 1
        end
    end
    if (errors / total) > rate_threshold then
        redis.call('SET', KEYS[1], 'open')
        return {'open', old_state, 1}
    end
end

return {old_state, old_state, 0}
"""

# Script 3: Force state change
_LUA_FORCE_STATE = """
-- KEYS[1] = cb:{name}:state
-- KEYS[2] = cb:{name}:failures
-- KEYS[3] = cb:{name}:last_fail
-- KEYS[4] = cb:{name}:ho_calls
-- ARGV[1] = new_state
-- ARGV[2] = now
-- Returns: {new_state, old_state}

local old_state = redis.call('GET', KEYS[1]) or 'closed'
local new_state = ARGV[1]
local now = ARGV[2]

redis.call('SET', KEYS[1], new_state)

if new_state == 'closed' then
    redis.call('SET', KEYS[2], '0')
    redis.call('DEL', KEYS[3])
    redis.call('SET', KEYS[4], '0')
elseif new_state == 'open' then
    redis.call('SET', KEYS[3], now)
end

return {new_state, old_state}
"""


# ═══════════════════════════════════════════════════════════════
#  Redis Helpers (lazy connection)
# ═══════════════════════════════════════════════════════════════

async def _get_redis():
    """Get Redis connection, or None if unavailable."""
    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        await r.ping()
        return r
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  Circuit Breaker Class
# ═══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Async circuit breaker with Redis-backed state and in-memory fallback.

    OPEN triggers:
      - error_rate > error_rate_threshold in error_rate_window (min 20 calls)
      - consecutive failures >= failure_threshold
      - manual force_open()

    Usage::

        cb = CircuitBreaker("alchemy_rpc")
        result = await cb.call(my_async_func, arg1, arg2)

    Or via new async API::

        if await cb.check():
            try:
                result = await do_work()
                await cb.record_success()
            except Exception as e:
                await cb.record_failure(e)
                raise
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        excluded_exceptions: tuple[type[Exception], ...] = (),
        error_rate_threshold: float = 0.05,
        error_rate_window: int = 300,
        min_calls_for_rate: int = 20,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions
        self.error_rate_threshold = error_rate_threshold
        self.error_rate_window = error_rate_window
        self.min_calls_for_rate = min_calls_for_rate

        # ── In-memory state (always maintained as fallback) ──
        self._state = CBState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._force_reason: str = ""

        # ── Redis key prefix ──
        self._prefix = f"cb:{name}"

        # ── Register globally ──
        _registry[name] = self
        CB_STATE.labels(service=name).set(0)

    # ── Redis keys ────────────────────────────────────────

    @property
    def _k_state(self) -> str:
        return f"{self._prefix}:state"

    @property
    def _k_failures(self) -> str:
        return f"{self._prefix}:failures"

    @property
    def _k_last_fail(self) -> str:
        return f"{self._prefix}:last_fail"

    @property
    def _k_ho_calls(self) -> str:
        return f"{self._prefix}:ho_calls"

    @property
    def _k_window(self) -> str:
        return f"{self._prefix}:window"

    # ══════════════════════════════════════════════════════
    #  NEW ASYNC API
    # ══════════════════════════════════════════════════════

    async def check(self) -> bool:
        """Check if the circuit allows a call.

        Returns True if allowed, False (or raises CircuitOpenError) if not.
        Automatically transitions OPEN → HALF_OPEN when recovery timeout
        has elapsed.
        """
        r = await _get_redis()
        if r is not None:
            return await self._check_redis(r)
        return self._check_memory()

    async def record_success(self) -> None:
        """Record a successful call. Transitions HALF_OPEN → CLOSED."""
        CB_SUCCESSES.labels(service=self.name).inc()
        self._success_count += 1

        r = await _get_redis()
        if r is not None:
            await self._record_redis(r, "success")
        else:
            self._record_memory_success()

    async def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record a failed call.

        May transition to OPEN if threshold or error rate is exceeded.
        """
        CB_FAILURES.labels(service=self.name).inc()

        r = await _get_redis()
        if r is not None:
            await self._record_redis(r, "failure")
        else:
            self._record_memory_failure(exc)

    async def force_open(self, reason: str = "") -> None:
        """Manually open the circuit breaker.

        Args:
            reason: Human-readable reason for the manual trigger.
        """
        self._force_reason = reason
        now = time.monotonic()

        r = await _get_redis()
        if r is not None:
            result = await r.eval(
                _LUA_FORCE_STATE,
                4,
                self._k_state, self._k_failures, self._k_last_fail, self._k_ho_calls,
                "open",
                str(now),
            )
            old_state = result[1] if result else "unknown"
        else:
            old_state = self._state.value

        self._transition(CBState.OPEN)
        self._last_failure_time = now

        logger.warning(
            "Circuit breaker '%s' FORCE OPENED: %s (was %s)",
            self.name, reason or "manual", old_state,
        )

        # Fire critical alert (best-effort, non-blocking)
        try:
            from app.services.alert_service import critical_alert
            import asyncio
            asyncio.ensure_future(critical_alert(
                f"Circuit breaker '{self.name}' OPENED\n"
                f"Reason: {reason or 'manual'}\n"
                f"Previous state: {old_state}"
            ))
        except Exception:
            pass

    async def force_close(self) -> None:
        """Manually close the circuit breaker and reset counters."""
        self._force_reason = ""

        r = await _get_redis()
        if r is not None:
            await r.eval(
                _LUA_FORCE_STATE,
                4,
                self._k_state, self._k_failures, self._k_last_fail, self._k_ho_calls,
                "closed",
                str(time.monotonic()),
            )

        self._transition(CBState.CLOSED)
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0

        logger.info("Circuit breaker '%s' FORCE CLOSED", self.name)

    async def get_state(self) -> CBState:
        """Get the current circuit state (from Redis if available)."""
        r = await _get_redis()
        if r is not None:
            state_str = await r.get(self._k_state)
            if state_str and state_str in ("closed", "open", "half_open"):
                return CBState(state_str)
        return self.state  # fallback to in-memory

    # ── Redis implementation ──────────────────────────────

    async def _check_redis(self, r) -> bool:
        """Lua-atomic check whether a call is allowed."""
        now = time.monotonic()
        result = await r.eval(
            _LUA_CHECK_ALLOWED,
            3,
            self._k_state, self._k_last_fail, self._k_ho_calls,
            str(now),
            str(self.recovery_timeout),
            str(self.half_open_max_calls),
        )

        allowed = int(result[0])
        new_state_str = result[1]
        old_state_str = result[2]

        # Sync in-memory state
        new_state = CBState(new_state_str)
        if new_state != self._state:
            self._transition(new_state)

        if old_state_str != new_state_str:
            self._log_transition(old_state_str, new_state_str)

        if not allowed:
            retry_after = self.recovery_timeout - (now - self._last_failure_time)
            raise CircuitOpenError(self.name, max(0, retry_after))

        return True

    async def _record_redis(self, r, result_type: str) -> None:
        """Lua-atomic record of success/failure with state transition."""
        now = time.monotonic()
        result = await r.eval(
            _LUA_RECORD_RESULT,
            4,
            self._k_state, self._k_failures, self._k_last_fail, self._k_window,
            result_type,
            str(now),
            str(self.failure_threshold),
            str(self.error_rate_threshold),
            str(self.error_rate_window),
            str(self.min_calls_for_rate),
        )

        new_state_str = result[0]
        old_state_str = result[1]
        transitioned = int(result[2])

        # Sync in-memory state
        new_state = CBState(new_state_str)
        if new_state != self._state:
            self._transition(new_state)

        if transitioned:
            self._log_transition(old_state_str, new_state_str)

        # Keep in-memory counters in sync
        if result_type == "success":
            if new_state == CBState.CLOSED:
                self._failure_count = 0
        else:
            self._failure_count += 1
            self._last_failure_time = now

    # ── In-memory implementation (fallback) ───────────────

    def _check_memory(self) -> bool:
        """In-memory check (non-atomic, single-process only)."""
        state = self.state  # triggers OPEN → HALF_OPEN check

        if state == CBState.OPEN:
            retry_after = self.recovery_timeout - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitOpenError(self.name, max(0, retry_after))

        if state == CBState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                raise CircuitOpenError(self.name, self.recovery_timeout)
            self._half_open_calls += 1

        return True

    def _record_memory_success(self) -> None:
        if self._state == CBState.HALF_OPEN:
            self._transition(CBState.CLOSED)
            self._failure_count = 0

    def _record_memory_failure(self, exc: Optional[Exception] = None) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CBState.HALF_OPEN:
            self._transition(CBState.OPEN)
            logger.warning(
                "Circuit breaker '%s': probe failed, back to OPEN (%s)",
                self.name, exc,
            )
        elif self._failure_count >= self.failure_threshold:
            self._transition(CBState.OPEN)
            logger.warning(
                "Circuit breaker '%s': threshold reached (%d failures), OPEN (%s)",
                self.name, self._failure_count, exc,
            )

    # ══════════════════════════════════════════════════════
    #  BACKWARD-COMPATIBLE API
    # ══════════════════════════════════════════════════════

    @property
    def state(self) -> CBState:
        """Synchronous state getter (in-memory, triggers OPEN→HALF_OPEN)."""
        if self._state == CBState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._transition(CBState.HALF_OPEN)
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute func through the circuit breaker.

        Backward-compatible wrapper used by cache_service, sweep_service.
        """
        async with self._lock:
            try:
                await self.check()
            except CircuitOpenError:
                raise

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, self.excluded_exceptions):
                raise
            await self.record_failure(exc)
            raise
        else:
            await self.record_success()
            return result

    def reset(self) -> None:
        """Reset the circuit breaker to CLOSED state (for testing)."""
        self._state = CBState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0
        self._force_reason = ""
        CB_STATE.labels(service=self.name).set(0)

    def info(self) -> dict:
        """Return circuit breaker status for health checks."""
        state = self.state  # triggers OPEN → HALF_OPEN check
        return {
            "name": self.name,
            "state": state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "error_rate_threshold": self.error_rate_threshold,
            "force_reason": self._force_reason,
        }

    # ── State transition helper ───────────────────────────

    def _transition(self, new_state: CBState) -> None:
        """Update in-memory state + Prometheus gauge."""
        old = self._state
        self._state = new_state
        CB_STATE.labels(service=self.name).set(new_state.metric_value)

        if old != new_state:
            CB_STATE_TRANSITIONS.labels(
                service=self.name,
                from_state=old.value,
                to_state=new_state.value,
            ).inc()

            if new_state == CBState.HALF_OPEN:
                self._half_open_calls = 0

    def _log_transition(self, old_str: str, new_str: str) -> None:
        """Log state transition for audit trail + fire alert."""
        if old_str == new_str:
            return

        log_fn = logger.warning if new_str == "open" else logger.info
        log_fn(
            "Circuit breaker '%s': %s -> %s",
            self.name,
            old_str,
            new_str,
            extra={
                "circuit_breaker": self.name,
                "from_state": old_str,
                "to_state": new_str,
                "failure_count": self._failure_count,
                "force_reason": self._force_reason,
            },
        )

        # Fire alert on significant transitions (best-effort, non-blocking)
        self._fire_transition_alert(old_str, new_str)

    def _fire_transition_alert(self, old_str: str, new_str: str) -> None:
        """Fire alert on OPEN (problem) or CLOSED (recovery) transitions."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop — skip alerting

        try:
            from app.services.alert_service import fire_alert, AlertType

            context = {
                "breaker": self.name,
                "failures": self._failure_count,
                "transition": f"{old_str} -> {new_str}",
            }

            if new_str == "open":
                # Determine alert type from breaker name
                if "sign" in self.name or "kms" in self.name:
                    alert_type = AlertType.SIGNING_DOWN
                elif "rpc" in self.name:
                    alert_type = AlertType.RPC_DOWN
                elif "redis" in self.name:
                    alert_type = AlertType.REDIS_DOWN
                else:
                    alert_type = AlertType.SIGNING_DOWN

                loop.create_task(fire_alert(
                    alert_type,
                    f"Circuit breaker OPEN for {self.name}: "
                    f"{self._failure_count} consecutive failures",
                    context,
                ))
            elif new_str == "closed" and old_str in ("open", "half_open"):
                loop.create_task(fire_alert(
                    AlertType.CB_RECOVERY,
                    f"Circuit breaker RECOVERED for {self.name}",
                    context,
                ))
        except Exception:
            pass  # alerting must never break the circuit breaker


# ═══════════════════════════════════════════════════════════════
#  Global Registry
# ═══════════════════════════════════════════════════════════════

_registry: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """Get a circuit breaker by name."""
    return _registry.get(name)


def get_all_circuit_breakers() -> dict[str, CircuitBreaker]:
    """Get all registered circuit breakers."""
    return dict(_registry)


# ═══════════════════════════════════════════════════════════════
#  Decorator
# ═══════════════════════════════════════════════════════════════

def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    fallback: Optional[Callable] = None,
    excluded_exceptions: tuple[type[Exception], ...] = (),
    error_rate_threshold: float = 0.05,
    error_rate_window: int = 300,
) -> Callable:
    """Decorator that wraps an async function with a circuit breaker.

    Usage::

        @circuit_breaker(name="alchemy_rpc", fallback=my_fallback)
        async def call_alchemy(...): ...

    If the circuit is OPEN and a fallback is provided, the fallback
    is called instead of raising CircuitOpenError.
    """
    # Reuse existing CB if already registered with this name
    cb = _registry.get(name)
    if cb is None:
        cb = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
            excluded_exceptions=excluded_exceptions,
            error_rate_threshold=error_rate_threshold,
            error_rate_window=error_rate_window,
        )

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await cb.call(func, *args, **kwargs)
            except CircuitOpenError:
                if fallback is not None:
                    logger.warning(
                        "Circuit '%s' OPEN — using fallback for %s",
                        name, func.__name__,
                    )
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    return fallback(*args, **kwargs)
                raise

        wrapper._circuit_breaker = cb  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════
#  Dependency Guard — Fail-Closed for Financial Operations
#
#  Policy:
#    Financial ops (sweep, transfer, execution):
#      → Redis down  → BLOCK (no fallback — cannot guarantee idempotency)
#      → Postgres down → BLOCK (no data persistence)
#      → RPC down (per-chain) → BLOCK that chain only
#
#    Read ops (balance, portfolio, status):
#      → graceful degradation with cached data (existing behavior)
# ═══════════════════════════════════════════════════════════════

class DependencyGuard:
    """Pre-flight check for critical dependencies before financial operations.

    Usage::

        guard = DependencyGuard()

        # Before any sweep/transfer/execution:
        await guard.require_redis()          # raises SweepBlockedError if down
        await guard.require_postgres()       # raises SweepBlockedError if down
        await guard.require_rpc(chain_id=8453)  # raises SweepBlockedError if down
        await guard.require_all(chain_id=8453)  # checks all three
    """

    async def require_redis(self) -> None:
        """Fail-closed: raises SweepBlockedError if Redis is unreachable."""
        try:
            from app.services.cache_service import get_redis
            r = await get_redis()
            if r is None:
                raise SweepBlockedError("redis", "not configured")
            await asyncio.wait_for(r.ping(), timeout=2.0)
        except SweepBlockedError:
            raise
        except asyncio.TimeoutError:
            raise SweepBlockedError("redis", "ping timeout (>2s)")
        except Exception as e:
            raise SweepBlockedError("redis", str(e)[:200])

    async def require_postgres(self) -> None:
        """Fail-closed: raises SweepBlockedError if Postgres is unreachable."""
        try:
            from app.db.session import engine
            from sqlalchemy import text
            async with engine.connect() as conn:
                await asyncio.wait_for(
                    conn.execute(text("SELECT 1")),
                    timeout=3.0,
                )
        except SweepBlockedError:
            raise
        except asyncio.TimeoutError:
            raise SweepBlockedError("postgres", "query timeout (>3s)")
        except Exception as e:
            raise SweepBlockedError("postgres", str(e)[:200])

    async def require_rpc(self, chain_id: int = 8453) -> None:
        """Fail-closed: raises SweepBlockedError if RPC for chain is unreachable.

        Uses a per-chain circuit breaker. If the CB is OPEN for this chain,
        the operation is blocked immediately without attempting an RPC call.
        """
        cb_name = f"rpc_{chain_id}"
        cb = get_circuit_breaker(cb_name)
        if cb is not None and cb.state == CBState.OPEN:
            raise SweepBlockedError(
                f"rpc (chain {chain_id})",
                f"circuit breaker '{cb_name}' is OPEN",
            )

        try:
            from app.services.rpc_manager import get_rpc_manager
            rpc = get_rpc_manager(chain_id)
            await asyncio.wait_for(
                rpc.call("eth_blockNumber", []),
                timeout=5.0,
            )
        except SweepBlockedError:
            raise
        except asyncio.TimeoutError:
            raise SweepBlockedError(
                f"rpc (chain {chain_id})", "eth_blockNumber timeout (>5s)"
            )
        except Exception as e:
            raise SweepBlockedError(f"rpc (chain {chain_id})", str(e)[:200])

    async def require_all(self, chain_id: int = 8453) -> None:
        """Check all critical dependencies for a financial operation.

        Raises SweepBlockedError on the first failure.
        """
        await self.require_postgres()
        await self.require_redis()
        await self.require_rpc(chain_id)


# Singleton instance
dependency_guard = DependencyGuard()
