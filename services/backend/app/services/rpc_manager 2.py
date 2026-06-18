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

from app.config import get_settings
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
    cb: CircuitBreaker = field(default=None, repr=False)

    def __post_init__(self):
        if self.cb is None:
            self.cb = CircuitBreaker(
                name=f"rpc_{self.name}_{self.chain_id}",
                failure_threshold=3,
                recovery_timeout=15.0,
                half_open_max_calls=1,
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
        data = resp.json()

    if "error" in data:
        raise RuntimeError(f"RPC {method} error: {data['error']}")

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

        # Add Alchemy as highest-priority provider if key is configured
        if alchemy_key:
            alchemy_urls = {
                8453: f"https://base-mainnet.g.alchemy.com/v2/{alchemy_key}",
                84532: f"https://base-sepolia.g.alchemy.com/v2/{alchemy_key}",
                1: f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}",
                42161: f"https://arb-mainnet.g.alchemy.com/v2/{alchemy_key}",
            }
            if chain_id in alchemy_urls:
                self._providers.append(
                    RPCProvider(
                        name="alchemy",
                        url=alchemy_urls[chain_id],
                        chain_id=chain_id,
                        priority=-1,  # highest priority
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
        tasks = [self._check_provider(p) for p in self._providers]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Determine the highest known block across all providers
        blocks = [p.last_block for p in self._providers if p.last_block > 0]
        if not blocks:
            return
        max_block = max(blocks)

        # Mark providers behind by >MAX_BLOCK_LAG as unhealthy
        all_unhealthy = True
        for p in self._providers:
            if p.last_block > 0 and (max_block - p.last_block) <= MAX_BLOCK_LAG:
                p.healthy = True
                all_unhealthy = False
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

        # All unhealthy → force-open all circuit breakers
        if all_unhealthy and blocks:
            logger.critical(
                "ALL RPC providers unhealthy on chain %d — opening circuit breakers",
                self.chain_id,
            )
            for p in self._providers:
                p.cb._transition(p.cb._state.OPEN)

    async def _check_provider(self, provider: RPCProvider) -> None:
        """Check a single provider's block height."""
        try:
            result = await _raw_rpc_call(
                provider.url, "eth_blockNumber", [], timeout=5
            )
            block = int(result, 16)
            provider.last_block = block
            provider.last_check = time.monotonic()
        except Exception as exc:
            logger.debug("Health check failed for %s: %s", provider.name, exc)
            provider.healthy = False

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
                return result
            except CircuitOpenError:
                logger.debug(
                    "Provider %s circuit open — skipping", provider.name
                )
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
                logger.warning(
                    "Provider %s failed for %s: %s", provider.name, method, exc
                )
                last_exc = exc
                continue

        raise RuntimeError(
            f"All RPC providers failed for {method} on chain {self.chain_id}: "
            f"{last_exc}"
        )

    # ── Consensus call (critical reads) ───────────────────

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

        async def _query(provider: RPCProvider) -> tuple[str, Any]:
            try:
                result = await provider.cb.call(
                    _raw_rpc_call, provider.url, method, params, timeout
                )
                return (provider.name, result)
            except Exception as exc:
                return (provider.name, exc)

        results = await asyncio.gather(
            *[_query(p) for p in providers_to_query]
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


async def start_all_managers() -> None:
    """Start health checks for all registered managers."""
    for mgr in _managers.values():
        await mgr.start()


async def stop_all_managers() -> None:
    """Stop all running managers gracefully."""
    for mgr in _managers.values():
        await mgr.stop()
