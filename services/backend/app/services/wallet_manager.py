"""
RSends Backend — Hot Wallet Balance Monitor.

Tracks the hot wallet's balance, estimates gas costs, and
triggers refill alerts when balance drops below thresholds.

Methods:
  get_hot_balance()               — current balance in Wei
  check_hot_sufficient(amount)    — True if balance covers amount + buffer
  estimate_sweep_gas(count, mode) — estimate gas cost for a batch sweep
  needs_refill()                  — True if balance < MIN_HOT_BALANCE
  alert_refill()                  — send Telegram/log alert
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from prometheus_client import Gauge

from app.config import get_settings
from app.services.key_manager import get_signer

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Prometheus Metrics
# ═══════════════════════════════════════════════════════════════

HOT_BALANCE_WEI = Gauge(
    "hot_wallet_balance_wei",
    "Hot wallet balance in Wei",
    ["chain_id"],
)
HOT_BALANCE_ETH = Gauge(
    "hot_wallet_balance_eth",
    "Hot wallet balance in ETH",
    ["chain_id"],
)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

WEI_PER_ETH = 10 ** 18
SAFETY_BUFFER_WEI = int(0.01 * WEI_PER_ETH)       # 0.01 ETH gas reserve
DEFAULT_MIN_HOT_BALANCE = int(0.1 * WEI_PER_ETH)   # 0.1 ETH

# Gas estimates (Base L2 — much cheaper than L1)
GAS_PER_ETH_TRANSFER = 21_000
GAS_PER_ERC20_TRANSFER = 65_000
GAS_PER_BATCH_OVERHEAD = 30_000

# ERC-20 transfer function selector
ERC20_TRANSFER_SELECTOR = "a9059cbb"


# ═══════════════════════════════════════════════════════════════
#  WalletManager
# ═══════════════════════════════════════════════════════════════

class WalletManager:
    """Hot wallet balance monitoring and gas estimation.

    Usage::

        wm = WalletManager(chain_id=8453)

        balance = await wm.get_hot_balance()
        if await wm.needs_refill():
            await wm.alert_refill()

        gas_cost = await wm.estimate_sweep_gas(
            recipient_count=5, mode="eth"
        )
        ok = await wm.check_hot_sufficient(gas_cost)
    """

    def __init__(
        self,
        chain_id: int = 8453,
        min_hot_balance: Optional[int] = None,
    ):
        self.chain_id = chain_id
        self.min_hot_balance = min_hot_balance or DEFAULT_MIN_HOT_BALANCE
        self._cached_address: Optional[str] = None
        self._last_alert_time: float = 0.0

    # ── Hot wallet address ────────────────────────────────

    async def _get_address(self) -> str:
        """Get the hot wallet address from the signer."""
        if self._cached_address is None:
            signer = get_signer()
            self._cached_address = await signer.get_address()
        return self._cached_address

    # ── Balance queries ───────────────────────────────────

    async def get_hot_balance(self) -> int:
        """Get current hot wallet balance in Wei.

        Uses consensus RPC call for accuracy.

        Returns:
            Balance in Wei as integer.
        """
        from app.services.rpc_manager import get_rpc_manager

        address = await self._get_address()
        mgr = get_rpc_manager(self.chain_id)

        result = await mgr.consensus_call(
            "eth_getBalance",
            [address, "latest"],
        )

        balance = int(result, 16)

        # Update Prometheus
        HOT_BALANCE_WEI.labels(chain_id=self.chain_id).set(balance)
        HOT_BALANCE_ETH.labels(chain_id=self.chain_id).set(
            balance / WEI_PER_ETH
        )

        return balance

    async def get_hot_nonce(self) -> int:
        """Get current nonce for the hot wallet (consensus read)."""
        from app.services.rpc_manager import get_rpc_manager

        address = await self._get_address()
        mgr = get_rpc_manager(self.chain_id)

        result = await mgr.consensus_call(
            "eth_getTransactionCount",
            [address, "pending"],
        )

        return int(result, 16)

    # ── Sufficiency check ─────────────────────────────────

    async def check_hot_sufficient(self, amount_wei: int) -> bool:
        """Check if hot wallet has enough balance for amount + safety buffer.

        Args:
            amount_wei: Amount needed (gas cost + value) in Wei.

        Returns:
            True if balance >= amount + SAFETY_BUFFER.
        """
        balance = await self.get_hot_balance()
        needed = amount_wei + SAFETY_BUFFER_WEI
        sufficient = balance >= needed

        if not sufficient:
            logger.warning(
                "Hot wallet insufficient: balance=%s needed=%s (amount=%s + buffer=%s)",
                balance,
                needed,
                amount_wei,
                SAFETY_BUFFER_WEI,
            )

        return sufficient

    # ── Gas estimation ────────────────────────────────────

    async def estimate_sweep_gas(
        self,
        recipient_count: int,
        mode: str = "eth",
    ) -> int:
        """Estimate total gas cost in Wei for a sweep batch.

        Args:
            recipient_count: Number of recipients.
            mode: ``"eth"`` for native transfers, ``"erc20"`` for token.

        Returns:
            Estimated gas cost in Wei.
        """
        from app.services.rpc_manager import get_rpc_manager

        mgr = get_rpc_manager(self.chain_id)

        # Get current gas price
        gas_price_hex = await mgr.call("eth_gasPrice", [])
        gas_price = int(gas_price_hex, 16)

        # Calculate total gas units
        if mode == "erc20":
            gas_per_transfer = GAS_PER_ERC20_TRANSFER
        else:
            gas_per_transfer = GAS_PER_ETH_TRANSFER

        total_gas = GAS_PER_BATCH_OVERHEAD + (gas_per_transfer * recipient_count)

        # L2 execution cost with 1.2x safety margin
        l2_cost = int(total_gas * gas_price * 1.2)

        # L1 data fee for OP Stack chains (Base)
        l1_cost = 0
        from app.services.gas_estimator import is_op_stack, estimate_l1_data_fee, \
            CALLDATA_FIXED_BYTES, CALLDATA_PER_RECIPIENT_BYTES
        if is_op_stack(self.chain_id):
            try:
                calldata_bytes = CALLDATA_FIXED_BYTES + CALLDATA_PER_RECIPIENT_BYTES * recipient_count
                l1_cost = await estimate_l1_data_fee(self.chain_id, calldata_bytes)
            except Exception as exc:
                logger.debug("L1 fee estimation failed, using 0: %s", exc)

        total_cost = l2_cost + l1_cost

        logger.debug(
            "Gas estimate: %d recipients x %s = %d gas units, "
            "price=%d gwei, l2=%s l1=%s total=%s ETH",
            recipient_count,
            mode,
            total_gas,
            gas_price // 10**9,
            Decimal(l2_cost) / Decimal(WEI_PER_ETH),
            Decimal(l1_cost) / Decimal(WEI_PER_ETH),
            Decimal(total_cost) / Decimal(WEI_PER_ETH),
        )

        return total_cost

    # ── Refill detection ──────────────────────────────────

    async def needs_refill(self) -> bool:
        """Check if hot wallet balance is below MIN_HOT_BALANCE.

        Returns:
            True if balance < min_hot_balance.
        """
        balance = await self.get_hot_balance()
        return balance < self.min_hot_balance

    # ── Alerts ────────────────────────────────────────────

    async def alert_refill(self) -> None:
        """Send a refill alert via Telegram (if configured) and logging.

        Rate-limited to 1 alert per 10 minutes.
        """
        import time

        now = time.time()
        if now - self._last_alert_time < 600:
            return  # rate limit

        self._last_alert_time = now
        balance = await self.get_hot_balance()
        address = await self._get_address()
        balance_eth = Decimal(balance) / Decimal(WEI_PER_ETH)
        min_eth = Decimal(self.min_hot_balance) / Decimal(WEI_PER_ETH)

        msg = (
            f"Hot wallet needs refill!\n"
            f"Address: {address}\n"
            f"Chain: {self.chain_id}\n"
            f"Balance: {balance_eth:.6f} ETH\n"
            f"Minimum: {min_eth:.6f} ETH"
        )

        logger.critical(msg)

        # Try Telegram notification
        settings = get_settings()
        if settings.telegram_bot_token:
            try:
                await self._send_telegram(msg, settings.telegram_bot_token)
            except Exception as exc:
                logger.error("Telegram alert failed: %s", exc)

    async def _send_telegram(self, message: str, bot_token: str) -> None:
        """Send alert via Telegram bot."""
        import httpx

        # The chat_id would come from config; for now log it
        logger.info("Telegram alert: %s", message[:200])

    # ── Info ──────────────────────────────────────────────

    async def info(self) -> dict:
        """Status summary for health checks."""
        balance = await self.get_hot_balance()
        address = await self._get_address()

        return {
            "address": address,
            "chain_id": self.chain_id,
            "balance_wei": str(balance),
            "balance_eth": str(Decimal(balance) / Decimal(WEI_PER_ETH)),
            "min_balance_wei": str(self.min_hot_balance),
            "needs_refill": balance < self.min_hot_balance,
            "safety_buffer_wei": str(SAFETY_BUFFER_WEI),
        }


# ═══════════════════════════════════════════════════════════════
#  Module Singleton
# ═══════════════════════════════════════════════════════════════

_managers: dict[int, WalletManager] = {}


def get_wallet_manager(chain_id: int = 8453) -> WalletManager:
    """Get or create a WalletManager for the given chain."""
    if chain_id not in _managers:
        _managers[chain_id] = WalletManager(chain_id=chain_id)
    return _managers[chain_id]
