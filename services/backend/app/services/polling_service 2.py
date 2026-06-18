"""
RSends Backend — Block Polling Fallback Service (CC-06).

Fallback ingestion path when Alchemy webhooks are not configured
or temporarily unavailable.

Every ~2 seconds:
  1. Fetch latest block number via eth_blockNumber
  2. For each new block since last processed:
     a. Fetch block with full TX list
     b. Filter TXs whose ``to`` matches a monitored address
     c. Dispatch matching TXs to Celery process_incoming_tx.delay()
  3. Persist last processed block in Redis (survives restarts)

Alerts (Telegram + CRITICAL log) after 5 consecutive RPC errors.

Supports:
  - ETH native transfers (via block transactions)
  - ERC-20 Transfer events (via eth_getLogs for Transfer topic)

Activation:
  - ALCHEMY_WEBHOOK_SECRET empty  → polling active at boot
  - ALCHEMY_WEBHOOK_SECRET set    → polling disabled (webhook takes over)
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy import select

from app.config import get_settings
from app.services.cache_service import get_redis

logger = logging.getLogger("polling_service")

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

POLL_INTERVAL = 2               # seconds between ticks
DEFAULT_CHAIN_ID = 8453         # Base mainnet
MAX_BLOCKS_PER_TICK = 10        # cap to prevent runaway catch-up
CONSECUTIVE_ERROR_ALERT = 5     # alert threshold

# Redis keys
REDIS_LAST_BLOCK_KEY = "poll:last_block:{chain_id}"
REDIS_ERROR_COUNT_KEY = "poll:errors:{chain_id}"

# keccak256("Transfer(address,address,uint256)")
TRANSFER_EVENT_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


# ═══════════════════════════════════════════════════════════════
#  Redis-backed block tracking
# ═══════════════════════════════════════════════════════════════

async def _get_last_processed_block(chain_id: int) -> Optional[int]:
    """Read last processed block number from Redis."""
    r = await get_redis()
    val = await r.get(REDIS_LAST_BLOCK_KEY.format(chain_id=chain_id))
    return int(val) if val else None


async def _set_last_processed_block(chain_id: int, block_number: int) -> None:
    """Persist last processed block number to Redis."""
    r = await get_redis()
    await r.set(REDIS_LAST_BLOCK_KEY.format(chain_id=chain_id), str(block_number))


async def _increment_error_count(chain_id: int) -> int:
    """Increment consecutive error counter and return new count."""
    r = await get_redis()
    key = REDIS_ERROR_COUNT_KEY.format(chain_id=chain_id)
    count = await r.incr(key)
    await r.expire(key, 300)  # auto-expire after 5 min idle
    return count


async def _reset_error_count(chain_id: int) -> None:
    """Reset consecutive error counter on success."""
    r = await get_redis()
    await r.delete(REDIS_ERROR_COUNT_KEY.format(chain_id=chain_id))


async def _send_error_alert(chain_id: int, error_count: int, last_error: str) -> None:
    """Send alert after CONSECUTIVE_ERROR_ALERT consecutive failures."""
    logger.critical(
        "POLLING ALERT: %d consecutive RPC errors on chain %d — %s",
        error_count, chain_id, last_error,
    )
    try:
        from app.services.notification_service import send_telegram_alert
        await send_telegram_alert(
            f"POLLING: {error_count} consecutive RPC errors "
            f"on chain {chain_id}. Last: {last_error}"
        )
    except Exception:
        pass  # best-effort


# ═══════════════════════════════════════════════════════════════
#  BlockPoller
# ═══════════════════════════════════════════════════════════════

class BlockPoller:
    """Polls new blocks on a single chain, dispatches to Celery.

    Last processed block is stored in Redis so polling survives restarts.
    """

    def __init__(self, chain_id: int = DEFAULT_CHAIN_ID) -> None:
        self.chain_id = chain_id
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ── Lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[poller] Started block polling on chain %d (interval: %ds)",
            self.chain_id, POLL_INTERVAL,
        )

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[poller] Stopped block polling on chain %d", self.chain_id)

    # ── Monitored addresses ─────────────────────────────────

    async def _get_monitored_addresses(self) -> set[str]:
        """Query all distinct source_wallet addresses from active rules."""
        from app.db.session import async_session
        from app.models.forwarding_models import ForwardingRule

        async with async_session() as db:
            result = await db.execute(
                select(ForwardingRule.source_wallet)
                .where(
                    ForwardingRule.is_active == True,   # noqa: E712
                    ForwardingRule.is_paused == False,   # noqa: E712
                    ForwardingRule.chain_id == self.chain_id,
                )
                .distinct()
            )
            return {row[0].lower() for row in result.all()}

    # ── Main loop ───────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stopped."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                error_count = await _increment_error_count(self.chain_id)
                logger.error(
                    "[poller] Tick failed (chain=%d errors=%d): %s",
                    self.chain_id, error_count, exc,
                )
                if error_count >= CONSECUTIVE_ERROR_ALERT:
                    await _send_error_alert(self.chain_id, error_count, str(exc))
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_once(self) -> dict:
        """Execute one polling tick: fetch new blocks, filter, dispatch.

        Returns dict with blocks_processed, txs_dispatched, latest_block.
        """
        from app.services.rpc_manager import get_rpc_manager

        rpc = get_rpc_manager(self.chain_id)

        # ── 1. Get latest block ──────────────────────────────
        latest_hex = await rpc.call("eth_blockNumber", [])
        latest_block = int(latest_hex, 16)

        # ── 2. Determine range from Redis ────────────────────
        last_processed = await _get_last_processed_block(self.chain_id)
        if last_processed is None:
            # First run — start from current block (don't replay history)
            await _set_last_processed_block(self.chain_id, latest_block)
            await _reset_error_count(self.chain_id)
            logger.info("[poller] Initialized at block %d", latest_block)
            return {
                "blocks_processed": 0,
                "txs_dispatched": 0,
                "latest_block": latest_block,
            }

        start_block = last_processed + 1
        if start_block > latest_block:
            return {
                "blocks_processed": 0,
                "txs_dispatched": 0,
                "latest_block": latest_block,
            }

        # Cap to prevent runaway catch-up
        end_block = min(latest_block, start_block + MAX_BLOCKS_PER_TICK - 1)

        # ── 3. Load monitored addresses ──────────────────────
        monitored = await self._get_monitored_addresses()
        if not monitored:
            await _set_last_processed_block(self.chain_id, end_block)
            return {
                "blocks_processed": end_block - start_block + 1,
                "txs_dispatched": 0,
                "latest_block": latest_block,
            }

        # ── 4. Fetch blocks, filter, dispatch ────────────────
        txs_dispatched = 0

        for block_num in range(start_block, end_block + 1):
            block_hex = hex(block_num)
            try:
                block = await rpc.call(
                    "eth_getBlockByNumber", [block_hex, True],
                )
                if not block:
                    continue

                # Native ETH transfers
                txs_dispatched += await self._process_native_transfers(
                    block, monitored,
                )

                # ERC-20 Transfer events
                txs_dispatched += await self._process_erc20_transfers(
                    rpc, block_hex, monitored,
                )

            except Exception as exc:
                logger.warning("[poller] Block %d error: %s", block_num, exc)

        # ── 5. Persist progress, reset error counter ─────────
        await _set_last_processed_block(self.chain_id, end_block)
        await _reset_error_count(self.chain_id)

        if txs_dispatched:
            logger.info(
                "[poller] chain=%d blocks=%d-%d txs_dispatched=%d",
                self.chain_id, start_block, end_block, txs_dispatched,
            )

        return {
            "blocks_processed": end_block - start_block + 1,
            "txs_dispatched": txs_dispatched,
            "latest_block": latest_block,
        }

    # ── Native ETH transfers ────────────────────────────────

    async def _process_native_transfers(
        self, block: dict, monitored: set[str],
    ) -> int:
        """Filter and dispatch native ETH transfers to monitored addresses.

        Returns count of TXs dispatched.
        """
        from app.tasks.sweep_tasks import process_incoming_tx as celery_process_tx

        dispatched = 0
        block_num = block.get("number")

        for tx in block.get("transactions", []):
            to_addr = (tx.get("to") or "").lower()
            if to_addr not in monitored:
                continue

            from_addr = (tx.get("from") or "").lower()
            tx_hash = tx.get("hash", "")
            value_hex = tx.get("value", "0x0")
            value_wei = int(value_hex, 16)

            if value_wei == 0:
                continue

            logger.info(
                "[poller] ETH: %s -> %s | %d wei | tx=%s | block=%s",
                from_addr[:10], to_addr[:10],
                value_wei, tx_hash[:16], block_num,
            )

            payload = {
                "tx_hash": tx_hash,
                "from_address": from_addr,
                "to_address": to_addr,
                "value_wei": str(value_wei),
                "chain_id": self.chain_id,
                "token_address": None,
                "token_symbol": "ETH",
                "block_number": block_num,
            }

            try:
                celery_process_tx.delay(payload)
                dispatched += 1
            except Exception as exc:
                logger.warning(
                    "[poller] Celery dispatch failed for %s: %s",
                    tx_hash[:16], exc,
                )

        return dispatched

    # ── ERC-20 Transfer events ──────────────────────────────

    async def _process_erc20_transfers(
        self, rpc, block_hex: str, monitored: set[str],
    ) -> int:
        """Fetch ERC-20 Transfer events and dispatch matches.

        Uses eth_getLogs with topic filter:
          topic[0] = Transfer event signature
          topic[2] = recipient address (padded to 32 bytes)

        Returns count of TXs dispatched.
        """
        from app.tasks.sweep_tasks import process_incoming_tx as celery_process_tx

        # Pad each monitored address to bytes32 for topic matching
        padded_addrs = [
            "0x" + addr.replace("0x", "").zfill(64) for addr in monitored
        ]

        try:
            logs = await rpc.call(
                "eth_getLogs",
                [{
                    "fromBlock": block_hex,
                    "toBlock": block_hex,
                    "topics": [
                        TRANSFER_EVENT_TOPIC,
                        None,           # topic[1] = from (any)
                        padded_addrs,   # topic[2] = to (our addresses)
                    ],
                }],
            )
        except Exception as exc:
            logger.debug(
                "[poller] ERC-20 log query failed for block %s: %s",
                block_hex, exc,
            )
            return 0

        if not logs:
            return 0

        dispatched = 0

        for log_entry in logs:
            token_contract = (log_entry.get("address") or "").lower()
            topics = log_entry.get("topics", [])
            data = log_entry.get("data", "0x")
            tx_hash = log_entry.get("transactionHash", "")
            log_block = log_entry.get("blockNumber")

            if len(topics) < 3:
                continue

            from_addr = "0x" + topics[1][-40:]
            to_addr = "0x" + topics[2][-40:]

            if to_addr.lower() not in monitored:
                continue

            raw_value = int(data, 16) if data and data != "0x" else 0
            if raw_value == 0:
                continue

            logger.info(
                "[poller] ERC-20: %s -> %s | %d raw | contract=%s | tx=%s",
                from_addr[:10], to_addr[:10],
                raw_value, token_contract[:10], tx_hash[:16],
            )

            payload = {
                "tx_hash": tx_hash,
                "from_address": from_addr.lower(),
                "to_address": to_addr.lower(),
                "value_wei": str(raw_value),
                "chain_id": self.chain_id,
                "token_address": token_contract,
                "token_symbol": "ERC20",
                "block_number": log_block,
            }

            try:
                celery_process_tx.delay(payload)
                dispatched += 1
            except Exception as exc:
                logger.warning(
                    "[poller] Celery dispatch failed for %s: %s",
                    tx_hash[:16], exc,
                )

        return dispatched


# ═══════════════════════════════════════════════════════════════
#  Module-level singleton & startup helper
# ═══════════════════════════════════════════════════════════════

_poller: Optional[BlockPoller] = None


async def start_polling_if_needed() -> Optional[BlockPoller]:
    """Start the block poller if ALCHEMY_WEBHOOK_SECRET is NOT configured.

    Called at application startup (lifespan). If the webhook secret is
    present, polling is skipped — the webhook handler takes over.
    """
    global _poller
    settings = get_settings()

    if settings.alchemy_webhook_secret:
        logger.info(
            "[poller] Alchemy webhook secret configured — polling disabled"
        )
        return None

    if _poller is not None:
        return _poller

    logger.info(
        "[poller] No webhook secret — starting fallback block polling"
    )
    _poller = BlockPoller(chain_id=DEFAULT_CHAIN_ID)
    await _poller.start()
    return _poller


async def stop_polling() -> None:
    """Stop the block poller (called at shutdown)."""
    global _poller
    if _poller:
        await _poller.stop()
        _poller = None
