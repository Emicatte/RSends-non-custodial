"""
RSends Backend — RPC Manager (Multi-Provider Failover + Consensus).

Features:
  - Multiple RPC providers per chain with priority ordering
  - Critical reads (balance, nonce): query 2/3 providers, use majority
  - Non-critical reads: primary with sequential fallback
  - Writes: primary only — never broadcast the same TX to multiple RPCs
  - Background health check every 30 s: mark unhealthy if >5 blocks behind
  - All providers unhealthy → circuit breaker OPEN
  - Per-provider circuit breakers + Prometheus metrics
"""

import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from prometheus_client import Counter as PromCounter, Gauge, Histogram

from app.config import ALCHEMY_RPC_URL_TEMPLATES, get_settings
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Prometheus Metrics
# ═══════════════════════════════════════════════════════════════

RPC_CALLS = PromCounter(
    "rpc_calls_total",
    "Total JSON-RPC calls",
    ["chain_id", "provider", "method", "status"],
)
RPC_LATENCY = Histogram(
    "rpc_latency_seconds",
    "JSON-RPC call duration",
    ["chain_id", "provider"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)
RPC_BLOCK_HEIGHT = Gauge(
    "rpc_block_height",
    "Latest block number per provider",
    ["chain_id", "provider"],
)
RPC_HEALTHY = Gauge(
    "rpc_provider_healthy",
    "Provider health (1=healthy, 0=unhealthy)",
    ["chain_id", "provider"],
)

# ═══════════════════════════════════════════════════════════════
#  Provider Configuration
# ═══════════════════════════════════════════════════════════════

@dataclass
class RPCProvider:
    """Single RPC endpoint with health tracking."""

    name: str
    url: str
    chain_id: int
    priority: int = 0                  # lower = higher priority
    healthy: bool = True
    last_block: int = 0
    last_check: float = 0.0
    # Consecutive call failures seen by RPCManager.call, and a one-shot latch
    # so losing a provider is announced exactly once instead of once per call.
    consecutive_failures: int = 0
    lost: bool = False
    cb: CircuitBreaker = field(default=None, repr=False)

    def __post_init__(self):
        if self.cb is None:
            self.cb = CircuitBreaker(
                name=f"rpc_{self.name}_{self.chain_id}",
                failure_threshold=3,
                recovery_timeout=15.0,
                half_open_max_calls=1,
                # A deterministic request rejection is not a provider fault:
                # counting it opened the circuit on a healthy provider every
                # ~16s, forever (Alchemy getLogs range limit, 2026-07-14).
                excluded_exceptions=(PermanentRPCError,),
            )


# Default provider configurations per chain
_DEFAULT_PROVIDERS: dict[int, list[dict]] = {
    8453: [
        {"name": "base_primary", "url": "https://mainnet.base.org", "priority": 0},
        {"name": "base_llama", "url": "https://base.llamarpc.com", "priority": 1},
        {"name": "base_1rpc", "url": "https://1rpc.io/base", "priority": 2},
    ],
    84532: [
        {"name": "base_sepolia", "url": "https://sepolia.base.org", "priority": 0},
    ],
    1: [
        {"name": "eth_llama", "url": "https://eth.llamarpc.com", "priority": 0},
        {"name": "eth_1rpc", "url": "https://1rpc.io/eth", "priority": 1},
        {"name": "eth_ankr", "url": "https://rpc.ankr.com/eth", "priority": 2},
    ],
    42161: [
        {"name": "arb_primary", "url": "https://arb1.arbitrum.io/rpc", "priority": 0},
        {"name": "arb_1rpc", "url": "https://1rpc.io/arb", "priority": 1},
    ],
}

# Max block delta before marking a provider as unhealthy
MAX_BLOCK_LAG = 5

# Health check interval
HEALTH_CHECK_INTERVAL = 30  # seconds

# Request timeout
REQUEST_TIMEOUT = 10  # seconds


# ═══════════════════════════════════════════════════════════════
#  Low-level RPC call
# ═══════════════════════════════════════════════════════════════

class PermanentRPCError(RuntimeError):
    """Deterministic request rejection (invalid params, getLogs range too
    large, …): retrying the SAME request will fail identically, so it must
    not count as a provider-availability failure — the circuit breaker
    excludes it (see RPCProvider). Another provider MAY still accept the
    request, so RPCManager.call keeps rotating on it."""


# Heuristic classification of JSON-RPC errors that are properties of the
# REQUEST, not of the provider's availability. Small and documented on
# purpose — extend only with error shapes observed in the wild.
# -32600 invalid request / -32602 invalid params: both deterministic —
# Alchemy rejects an oversized getLogs range with -32600 in production
# (observed 2026-07-14), which previously fed the breaker as if transient.
_PERMANENT_ERROR_CODES = {-32600, -32602}
_PERMANENT_ERROR_PATTERNS = (
    "block range",      # Alchemy free tier: "up to a 10 block range"
    "too large",
    "exceed",
    "invalid param",
)
# Rate limiting / quota exhaustion codes. These are AVAILABILITY faults, not
# properties of the request: the same call succeeds on another provider right
# now, and on this one once the window resets. Classifying them permanent is
# what turned Alchemy's monthly-quota 429 into a silent outage (2026-08-22) —
# permanent errors are excluded from the circuit breaker, so the quota-dead
# provider was never marked down, never alerted, and kept costing a wasted
# round-trip on every single call for days.
_TRANSIENT_ERROR_CODES = {429, -32005, -32029}

# Overrides checked FIRST: error shapes that carry a permanent code/pattern but
# are actually transient. A getLogs toBlock briefly beyond the serving
# backend's head (tip race / cross-provider head divergence) arrives as -32602
# "block range extends beyond current head block" (observed Base Sepolia
# 2026-07) yet self-heals as soon as the lagging node catches up. The
# quota/throttle wordings are here because they all contain "exceed", which the
# permanent patterns below match for a completely different reason (the
# getLogs range limit).
_TRANSIENT_OVERRIDE_PATTERNS = (
    "beyond current head",
    "rate limit",          # "rate limit exceeded", "request rate limited"
    "capacity",            # "Monthly capacity limit exceeded" (Alchemy)
    "compute unit",        # "exceeded its compute units per second capacity"
    "quota",
    "request count",       # "daily request count exceeded"
    "too many requests",
    "throttl",             # throttled / throttling
)


def _is_permanent_rpc_error(error: dict) -> bool:
    message = str(error.get("message", "")).lower()
    if error.get("code") in _TRANSIENT_ERROR_CODES:
        return False
    if any(p in message for p in _TRANSIENT_OVERRIDE_PATTERNS):
        return False
    if error.get("code") in _PERMANENT_ERROR_CODES:
        return True
    return any(p in message for p in _PERMANENT_ERROR_PATTERNS)


async def _raw_rpc_call(
    url: str,
    method: str,
    params: list,
    timeout: int = REQUEST_TIMEOUT,
) -> Any:
    """Execute a single JSON-RPC call. Returns the ``result`` field."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=timeout,
        )
        try:
            data = resp.json()
        except ValueError:  # includes json.JSONDecodeError
            data = None

    if not isinstance(data, dict):
        # A vendor edge (429 page, 5xx, maintenance HTML) answered instead of
        # the node. Availability fault — and the status has to be in the
        # message, or the log line is a bare JSONDecodeError naming nothing.
        raise RuntimeError(
            f"RPC {method} got a non-JSON response (HTTP {resp.status_code}): "
            f"{resp.text[:200]!r}"
        )

    if "error" in data:
        if resp.status_code == 429 or resp.status_code >= 500:
            # The transport already said "throttled" / "broken": that verdict
            # outranks any wording heuristic on the error body.
            raise RuntimeError(
                f"RPC {method} HTTP {resp.status_code}: {data['error']}"
            )
        if _is_permanent_rpc_error(data["error"]):
            raise PermanentRPCError(f"RPC {method} rejected: {data['error']}")
        raise RuntimeError(f"RPC {method} error: {data['error']}")

    if resp.status_code >= 400:
        raise RuntimeError(
            f"RPC {method} HTTP {resp.status_code} with no JSON-RPC error object"
        )

    return data.get("result")


# ═══════════════════════════════════════════════════════════════
#  RPCManager
# ═══════════════════════════════════════════════════════════════

class RPCManager:
    """Multi-provider RPC manager with failover and consensus reads.

    Usage::

        mgr = RPCManager(chain_id=8453)
        await mgr.start()

        # Critical read (balance, nonce) — queries majority of providers
        balance = await mgr.consensus_call("eth_getBalance", [addr, "latest"])

        # Non-critical read — primary with fallback
        block = await mgr.call("eth_getBlockByNumber", ["latest", False])

        # Write (primary only — NEVER send same TX to multiple RPCs)
        tx_hash = await mgr.send_raw_transaction(signed_tx_hex)

        await mgr.stop()
    """

    def __init__(self, chain_id: int = 8453):
        self.chain_id = chain_id
        self._providers: list[RPCProvider] = []
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

        # Initialise providers
        settings = get_settings()
        alchemy_key = settings.alchemy_api_key

        # Add Alchemy as highest-priority provider if key is configured.
        # The chain→URL table lives in config.ALCHEMY_RPC_URL_TEMPLATES so that
        # validate_settings' provider-coverage check reads the same keys.
        if alchemy_key and chain_id in ALCHEMY_RPC_URL_TEMPLATES:
            self._providers.append(
                RPCProvider(
                    name="alchemy",
                    url=ALCHEMY_RPC_URL_TEMPLATES[chain_id].format(key=alchemy_key),
                    chain_id=chain_id,
                    priority=-1,  # highest priority
                )
            )

        # Add config-driven extra providers (RPC_PROVIDERS_JSON) BEFORE the
        # public defaults: with the default priority 0 the stable sort keeps
        # them ahead of the equal-priority publics, i.e. between Alchemy (-1)
        # and the best-effort public fallbacks. Adding a second paid vendor
        # at mainnet is one env edit, zero code.
        for cfg in settings.rpc_extra_providers.get(chain_id, []):
            self._providers.append(
                RPCProvider(
                    name=cfg["name"],
                    url=cfg["url"],
                    chain_id=chain_id,
                    priority=cfg["priority"],
                )
            )

        # Add default public providers
        for cfg in _DEFAULT_PROVIDERS.get(chain_id, []):
            self._providers.append(
                RPCProvider(
                    name=cfg["name"],
                    url=cfg["url"],
                    chain_id=chain_id,
                    priority=cfg["priority"],
                )
            )

        # Sort by priority (lower = first)
        self._providers.sort(key=lambda p: p.priority)

    # ── Lifecycle ─────────────────────────────────────────

    async def start(self) -> None:
        """Start background health checks."""
        if self._running:
            return
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info(
            "RPCManager started: chain=%d providers=%d",
            self.chain_id,
            len(self._providers),
        )

    async def stop(self) -> None:
        """Stop background health checks gracefully."""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        logger.info("RPCManager stopped: chain=%d", self.chain_id)

    # ── Health check loop ─────────────────────────────────

    async def _health_loop(self) -> None:
        """Check provider health every HEALTH_CHECK_INTERVAL seconds."""
        while self._running:
            try:
                await self._check_all_providers()
            except Exception as exc:
                logger.error("Health check cycle failed: %s", exc)
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    async def _check_all_providers(self) -> None:
        """Query each provider for latest block number and update health."""
        if not self._providers:
            return  # unconfigured chain: nothing to probe (vacuous "all failed")
        results = await asyncio.gather(
            *(self._check_provider(p) for p in self._providers),
            return_exceptions=True,
        )
        # Positionally aligned with self._providers — load-bearing below: a
        # provider that did NOT answer this cycle must never be re-marked
        # healthy off the stale last_block its failed probe left behind.
        probe_ok = [r is True for r in results]

        if not any(probe_ok):
            # Every probe failed this cycle (network/vendor outage). Mark all
            # providers unhealthy (truthful gauges) and fail LOUD — but do NOT
            # touch the circuit breakers: call() already tries every provider
            # as a last resort when none is healthy, so a forced-open
            # fail-fast window would only delay recovery. (The previous
            # force-open branch here was unreachable: it keyed on block lag,
            # and the provider holding max_block always has lag 0.)
            for p in self._providers:
                p.healthy = False
                RPC_HEALTHY.labels(
                    chain_id=self.chain_id, provider=p.name
                ).set(0)
                RPC_BLOCK_HEIGHT.labels(
                    chain_id=self.chain_id, provider=p.name
                ).set(p.last_block)
            logger.critical(
                "ALL RPC provider health probes failed on chain %d "
                "(%d providers) — payment detection is degraded until one recovers",
                self.chain_id, len(self._providers),
            )
            self._fire_all_down_alert()
            return

        # Determine the highest known block across all providers
        blocks = [p.last_block for p in self._providers if p.last_block > 0]
        if not blocks:
            return
        max_block = max(blocks)

        # Mark providers behind by >MAX_BLOCK_LAG as unhealthy
        for p, answered in zip(self._providers, probe_ok):
            if not answered:
                # _check_provider already set healthy=False; keep it that way.
                # Its last_block is stale, so the lag arm below would happily
                # resurrect a provider that is down right now (it only takes
                # the tip having advanced by <= MAX_BLOCK_LAG since its last
                # good probe) and call() would route to it.
                p.healthy = False
            elif p.last_block > 0 and (max_block - p.last_block) <= MAX_BLOCK_LAG:
                p.healthy = True
            elif p.last_block > 0:
                p.healthy = False
                logger.warning(
                    "Provider %s unhealthy: block=%d (max=%d, lag=%d)",
                    p.name, p.last_block, max_block, max_block - p.last_block,
                )

            RPC_HEALTHY.labels(
                chain_id=self.chain_id, provider=p.name
            ).set(1 if p.healthy else 0)
            RPC_BLOCK_HEIGHT.labels(
                chain_id=self.chain_id, provider=p.name
            ).set(p.last_block)

    async def _check_provider(self, provider: RPCProvider) -> bool:
        """Check a single provider's block height. True on a successful probe."""
        try:
            result = await _raw_rpc_call(
                provider.url, "eth_blockNumber", [], timeout=5
            )
            block = int(result, 16)
            provider.last_block = block
            provider.last_check = time.monotonic()
            return True
        except Exception as exc:
            logger.debug("Health check failed for %s: %s", provider.name, exc)
            provider.healthy = False
            return False

    def _fire_all_down_alert(self) -> None:
        """Best-effort RPC_DOWN alert (always at least a log line in
        alert_service; Telegram/webhook when configured). Cooldown in
        alert_service keeps the 30s loop from paging every cycle. Never
        raises — alerting must not break the health loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            from app.services.alert_service import AlertType, fire_alert

            loop.create_task(fire_alert(
                AlertType.RPC_DOWN,
                f"ALL RPC provider health probes failed on chain "
                f"{self.chain_id} ({len(self._providers)} providers)",
                {"chain_id": self.chain_id,
                 "providers": [p.name for p in self._providers]},
            ))
        except Exception:
            pass

    # ── Provider loss (fail loud) ─────────────────────────

    def _mark_provider_lost(self, provider: RPCProvider, reason: str) -> None:
        """Announce, ONCE, that a provider is no longer serving.

        The 2026-08-22 outage was not caused by a single endpoint failing — it
        was caused by nobody knowing that the other provider had been
        quota-dead for days. A provider dropping out has to be as loud as an
        outage, or the failover silently degrades to no failover at all.
        Latched, so a dead provider produces one ERROR + one alert, not one
        per call.
        """
        if provider.lost:
            return
        provider.lost = True
        remaining = [p.name for p in self._providers if not p.lost]
        logger.error(
            "RPC provider %s LOST on chain %d (%s) — %d of %d providers still "
            "serving (%s)",
            provider.name, self.chain_id, reason,
            len(remaining), len(self._providers),
            ", ".join(remaining) or "NONE",
        )
        self._fire_provider_lost_alert(provider, reason, remaining)

    def _fire_provider_lost_alert(
        self, provider: RPCProvider, reason: str, remaining: list[str]
    ) -> None:
        """Best-effort RPC_DOWN alert. Never raises — alerting must not break
        the call path (mirrors _fire_all_down_alert)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            from app.services.alert_service import AlertType, fire_alert

            loop.create_task(fire_alert(
                AlertType.RPC_DOWN,
                f"RPC provider '{provider.name}' lost on chain "
                f"{self.chain_id} ({reason}) — {len(remaining)} of "
                f"{len(self._providers)} providers still serving",
                {"chain_id": self.chain_id,
                 "provider": provider.name,
                 "reason": reason[:200],
                 "remaining": remaining},
            ))
        except Exception:
            pass

    def _note_provider_success(self, provider: RPCProvider) -> None:
        if provider.lost:
            provider.lost = False
            logger.warning(
                "RPC provider %s RECOVERED on chain %d",
                provider.name, self.chain_id,
            )
        provider.consecutive_failures = 0

    def _note_provider_failure(self, provider: RPCProvider, reason: str) -> None:
        provider.consecutive_failures += 1
        if provider.consecutive_failures >= provider.cb.failure_threshold:
            self._mark_provider_lost(provider, reason)

    # ── Healthy providers ─────────────────────────────────

    def _healthy_providers(self) -> list[RPCProvider]:
        """Return healthy providers sorted by priority."""
        return [p for p in self._providers if p.healthy]

    # ── Standard call (primary + fallback) ────────────────

    async def call(
        self,
        method: str,
        params: list,
        timeout: int = REQUEST_TIMEOUT,
    ) -> Any:
        """Execute an RPC call with failover.

        Tries the primary (highest-priority healthy) provider first,
        then falls back to other healthy providers sequentially.
        """
        healthy = self._healthy_providers()
        if not healthy:
            healthy = self._providers  # try all as last resort

        last_exc: Optional[Exception] = None
        all_permanent = True  # becomes False on any transient/availability error

        for provider in healthy:
            t0 = time.monotonic()
            try:
                result = await provider.cb.call(
                    _raw_rpc_call, provider.url, method, params, timeout
                )
                elapsed = time.monotonic() - t0
                RPC_LATENCY.labels(
                    chain_id=self.chain_id, provider=provider.name
                ).observe(elapsed)
                RPC_CALLS.labels(
                    chain_id=self.chain_id,
                    provider=provider.name,
                    method=method,
                    status="ok",
                ).inc()
                self._note_provider_success(provider)
                return result
            except CircuitOpenError:
                logger.debug(
                    "Provider %s circuit open — skipping", provider.name
                )
                # The breaker opened (possibly on another code path): the
                # provider is out of rotation — say so once.
                self._mark_provider_lost(provider, "circuit breaker OPEN")
                continue
            except Exception as exc:
                elapsed = time.monotonic() - t0
                RPC_LATENCY.labels(
                    chain_id=self.chain_id, provider=provider.name
                ).observe(elapsed)
                RPC_CALLS.labels(
                    chain_id=self.chain_id,
                    provider=provider.name,
                    method=method,
                    status="error",
                ).inc()
                if isinstance(exc, PermanentRPCError):
                    # Request rejected deterministically (not counted by the
                    # breaker) — another provider may accept it, keep rotating.
                    logger.warning(
                        "Provider %s rejected %s (permanent request error): %s",
                        provider.name, method, exc,
                    )
                else:
                    all_permanent = False
                    logger.warning(
                        "Provider %s failed for %s: %s", provider.name, method, exc
                    )
                    self._note_provider_failure(provider, str(exc)[:200])
                last_exc = exc
                continue

        if all_permanent and isinstance(last_exc, PermanentRPCError):
            # EVERY provider rejected the request deterministically: retrying
            # the same call cannot succeed. Propagate the classification so
            # callers (the indexer's stall detection) can surface it as a
            # config/range error to FIX instead of a fault to retry forever.
            raise PermanentRPCError(
                f"All RPC providers rejected {method} on chain "
                f"{self.chain_id} (permanent request error): {last_exc}"
            ) from last_exc

        raise RuntimeError(
            f"All RPC providers failed for {method} on chain {self.chain_id}: "
            f"{last_exc}"
        )

    # ── Consensus call (critical reads) ───────────────────

    async def poll_providers(
        self,
        method: str,
        params: list,
        timeout: int = REQUEST_TIMEOUT,
        providers: Optional[list[RPCProvider]] = None,
    ) -> list[tuple[str, Any]]:
        """Ask several providers the SAME question concurrently and report each
        answer verbatim, `(provider_name, result_or_Exception)`.

        This is the fan-out `consensus_call` has always done, exposed on its own
        because agreement is sometimes the answer a caller needs rather than the
        majority value. `consensus_call` collapses divergence (it logs and
        returns the primary's result), so a caller that must distinguish "every
        provider says the same thing" from "the providers disagree" cannot use
        it directly — see `router_registry._empty_is_unanimous`.

        Defaults to EVERY configured provider, not the healthy subset: a
        provider excluded for being unhealthy is exactly the one whose answer
        would change the verdict.
        """
        targets = self._providers if providers is None else providers

        async def _query(provider: RPCProvider) -> tuple[str, Any]:
            try:
                result = await provider.cb.call(
                    _raw_rpc_call, provider.url, method, params, timeout
                )
                return (provider.name, result)
            except Exception as exc:
                return (provider.name, exc)

        return list(await asyncio.gather(*[_query(p) for p in targets]))

    async def consensus_call(
        self,
        method: str,
        params: list,
        min_agree: int = 2,
        timeout: int = REQUEST_TIMEOUT,
    ) -> Any:
        """Query multiple providers and return the majority result.

        Used for critical reads (balance, nonce) where correctness
        matters more than latency.

        Args:
            method: JSON-RPC method.
            params: Method parameters.
            min_agree: Minimum number of providers that must agree.
            timeout: Per-provider timeout.

        Returns:
            The result that the majority of providers agree on.
        """
        healthy = self._healthy_providers()
        if len(healthy) < min_agree:
            healthy = self._providers[:3]

        # Query up to 3 providers concurrently
        providers_to_query = healthy[:3]

        results = await self.poll_providers(
            method, params, timeout=timeout, providers=providers_to_query
        )

        # Collect successful results
        successes: list[tuple[str, Any]] = []
        for name, result in results:
            if isinstance(result, Exception):
                logger.warning("Consensus: %s failed: %s", name, result)
            else:
                successes.append((name, result))

        if not successes:
            raise RuntimeError(
                f"Consensus call failed: all providers returned errors "
                f"for {method} on chain {self.chain_id}"
            )

        # If only one succeeded, return it (degraded mode)
        if len(successes) == 1:
            logger.warning(
                "Consensus degraded: only 1/%d providers responded for %s",
                len(providers_to_query),
                method,
            )
            return successes[0][1]

        # Find majority result
        # Serialise results to strings for comparison
        result_strs: list[tuple[str, str, Any]] = []
        for name, result in successes:
            result_strs.append((name, str(result), result))

        counter = Counter(rs[1] for rs in result_strs)
        majority_str, count = counter.most_common(1)[0]

        if count >= min_agree:
            # Return the first result matching the majority
            for _, rs, raw in result_strs:
                if rs == majority_str:
                    return raw

        # No majority — log divergence and return primary's result
        logger.warning(
            "Consensus divergence for %s: %s",
            method,
            {name: rs for name, rs, _ in result_strs},
        )
        return successes[0][1]

    # ── Write (primary only) ──────────────────────────────

    async def send_raw_transaction(self, raw_tx_hex: str) -> str:
        """Send a signed transaction to the PRIMARY provider only.

        NEVER broadcasts the same TX to multiple RPCs to avoid
        nonce conflicts and double-spending.

        Returns:
            Transaction hash.
        """
        primary = self._providers[0] if self._providers else None
        if primary is None:
            raise RuntimeError(f"No RPC providers for chain {self.chain_id}")

        result = await primary.cb.call(
            _raw_rpc_call,
            primary.url,
            "eth_sendRawTransaction",
            [raw_tx_hex],
        )

        RPC_CALLS.labels(
            chain_id=self.chain_id,
            provider=primary.name,
            method="eth_sendRawTransaction",
            status="ok",
        ).inc()

        return result

    # ── Info ──────────────────────────────────────────────

    def info(self) -> dict:
        """Return manager status for health checks."""
        return {
            "chain_id": self.chain_id,
            "providers": [
                {
                    "name": p.name,
                    "healthy": p.healthy,
                    "last_block": p.last_block,
                    "circuit_state": p.cb.state.value,
                }
                for p in self._providers
            ],
        }


# ═══════════════════════════════════════════════════════════════
#  Singleton Registry
# ═══════════════════════════════════════════════════════════════

_managers: dict[int, RPCManager] = {}


def get_rpc_manager(chain_id: int = 8453) -> RPCManager:
    """Get or create an RPCManager for the given chain."""
    if chain_id not in _managers:
        _managers[chain_id] = RPCManager(chain_id=chain_id)
    return _managers[chain_id]


# ═══════════════════════════════════════════════════════════════
#  Chain identity — PROVEN, not declared (F1)
# ═══════════════════════════════════════════════════════════════

class ChainIdentityError(RuntimeError):
    """The chain could not be proven, or was disproven.

    Raised when NO configured provider could be reached, when a provider that
    DID answer answered with the wrong chain id or an unparseable one, and when
    no provider is configured at all. There is deliberately no "probably fine"
    branch: an unproven chain is not a safe chain.

    Not raised merely because one provider is unreachable — that is a statement
    about a vendor, not about the network. See `assert_chain_identity`.
    """


# Proof is immutable — a node that served chain X at boot cannot start serving
# chain Y under the same URL without being a different node. Cached per
# (provider_url, chain_id) for the process lifetime. ONLY successes are ever
# recorded here; a failure leaves no trace, so a later call re-probes and fails
# again rather than inheriting a pass.
_CHAIN_ID_VERIFIED: set[tuple[str, int]] = set()


async def assert_chain_identity(chain_id: int, timeout: int = REQUEST_TIMEOUT) -> None:
    """Prove, via `eth_chainId`, that the providers for `chain_id` serve
    `chain_id`. Raise `ChainIdentityError` if the chain cannot be proven, or is
    disproven by any provider that answers.

    The chain is PROVEN once at least one configured provider returns
    `chain_id`. A provider that cannot be reached is logged at WARNING and
    skipped: its silence is a fact about that vendor, not about the network.
    The original guard collapsed the two, so one vendor's HTTP 429 killed a
    boot that a second, healthy, correctly-configured vendor could have carried
    (incident 2026-08-28 — a dual-provider deployment failing as though it were
    single-provider).

    Every provider is still probed, and any that ANSWERS must answer correctly:
    a wrong answer is worse than no answer, and stays fatal even when a sibling
    provider proves the chain. Stopping at the first proof would leave a
    wrong-chain node dormant until failover adopted it, with no further check
    anywhere downstream — the chain id keys the cursor, the test/live
    environment stamp and the on-chain invoice id, none of which re-derives it
    from the network.

    Why provider health is not enough: `_check_provider` asks `eth_blockNumber`
    and compares lag BETWEEN the providers of the same declared chain. A whole
    provider set on the wrong network agrees with itself and is marked healthy.

    This function reads no configuration and has no off switch, by design — see
    `tests/test_chain_identity_guard.py::test_no_configuration_surface_can_disable_chain_identity`.
    """
    providers = list(get_rpc_manager(chain_id)._providers)
    if not providers:
        raise ChainIdentityError(
            f"chain {chain_id}: no RPC provider is configured, so the chain "
            f"cannot be proven. Refusing to operate on an unproven chain."
        )

    proven: list[str] = []
    unreachable: list[str] = []

    for p in providers:
        if (p.url, chain_id) in _CHAIN_ID_VERIFIED:
            proven.append(p.name)
            continue

        try:
            raw = await _raw_rpc_call(p.url, "eth_chainId", [], timeout=timeout)
        except Exception as exc:
            # Availability fault. Skipped, never cached — the next call
            # re-probes it, so a recovering provider is re-proven and a
            # wrong-chain one it might be replaced by is still caught.
            logger.warning(
                "[chain-identity] chain %d: provider %s (%s) could not be asked "
                "for eth_chainId (%r) — SKIPPED. An unreachable provider proves "
                "nothing either way; another provider must prove this chain.",
                chain_id, p.name, p.url, exc,
            )
            unreachable.append(f"{p.name} ({exc!r})")
            continue

        if not isinstance(raw, str):
            raise ChainIdentityError(
                f"chain {chain_id}: provider {p.name} ({p.url}) answered "
                f"eth_chainId with {raw!r}, which is not a hex string."
            )
        try:
            observed = int(raw, 16)
        except ValueError as exc:
            raise ChainIdentityError(
                f"chain {chain_id}: provider {p.name} ({p.url}) answered "
                f"eth_chainId with {raw!r}, which is not parseable as hex."
            ) from exc

        if observed != chain_id:
            raise ChainIdentityError(
                f"chain {chain_id}: provider {p.name} ({p.url}) serves chain "
                f"{observed}, not {chain_id}. Indexing it would key the cursor, "
                f"the environment stamp and the invoice id to the wrong network."
            )

        # Recorded only after the proof succeeded.
        _CHAIN_ID_VERIFIED.add((p.url, chain_id))
        proven.append(p.name)

    if not proven:
        raise ChainIdentityError(
            f"chain {chain_id}: NO configured provider could be reached, so the "
            f"chain is unproven — refusing to operate. Tried: "
            f"{'; '.join(unreachable)}."
        )

    if unreachable:
        logger.warning(
            "[chain-identity] chain %d proven by %s, with %d provider(s) "
            "unreachable (%s). Payment detection is running WITHOUT its full "
            "failover set.",
            chain_id, ", ".join(proven), len(unreachable), ", ".join(unreachable),
        )


async def verify_chain_identity_for_boot(chain_ids: list[int]) -> None:
    """Boot guard: prove every configured chain, or refuse to start.

    Raises `SystemExit`, matching `router_registry.verify_enabled_tokens_onchain`
    — the existing convention for "a boot fact was wrong, do not serve traffic".
    No chains configured is a no-op; it must not invent a default chain to check.
    """
    for chain_id in chain_ids:
        try:
            await assert_chain_identity(chain_id)
        except ChainIdentityError as exc:
            raise SystemExit(f"[chain-identity] FATAL {exc}") from exc
        logger.info("[chain-identity] chain %d proven on every provider", chain_id)


def log_provider_inventory(chain_ids: list[int]) -> None:
    """State the RPC failover list per chain at boot, and WARN when a chain has
    no redundancy.

    Redundancy that exists only in a config comment is indistinguishable from
    redundancy that does not exist. Print the list on every boot so a
    single-provider chain is a fact in the log, not something to be inferred
    after an outage.
    """
    for chain_id in chain_ids:
        mgr = get_rpc_manager(chain_id)
        names = [p.name for p in mgr._providers]
        logger.info(
            "RPC providers chain=%d (%d): %s",
            chain_id, len(names), ", ".join(names) or "NONE",
        )
        if len(names) < 2:
            logger.warning(
                "RPC chain %d has NO REDUNDANCY: %d provider(s) configured "
                "(%s) — a single vendor outage stops payment detection on this "
                "chain. Add a second vendor via RPC_PROVIDERS_JSON "
                "(see DEPLOY_RUNBOOK).",
                chain_id, len(names), ", ".join(names) or "none",
            )


async def start_all_managers() -> None:
    """Start health checks for all registered managers."""
    for mgr in _managers.values():
        await mgr.start()


async def start_health_checks(chain_ids: list[int]) -> None:
    """Instantiate managers for the given chains, then start every registered
    manager's health loop.

    The instantiation step is load-bearing: the registry is populated lazily
    (the indexer only calls get_rpc_manager inside its first tick), so calling
    start_all_managers() alone at lifespan startup would iterate an EMPTY
    registry and silently start nothing — the footgun that kept this layer
    inert since it was written."""
    for chain_id in chain_ids:
        get_rpc_manager(chain_id)
    await start_all_managers()


async def stop_all_managers() -> None:
    """Stop all running managers gracefully."""
    for mgr in _managers.values():
        await mgr.stop()
