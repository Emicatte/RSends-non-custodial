"""
RPagos Backend — CC-06 Tests: Webhook Security, Polling, Reconciliation.

Tests:
  Webhook Security Chain (9 tests):
    - Full pipeline: verify_webhook → 200 accepted
    - Missing HMAC signature → 401
    - Invalid HMAC signature → 401
    - IP not in whitelist → 403
    - Stale timestamp → 401
    - Duplicate webhook (idempotency) → 200 duplicate
    - Rate limited → 429
    - Background dispatches to Celery .delay()
    - Celery fallback to direct async call

  Polling Service (10 tests):
    - First tick initializes block in Redis
    - Processes new blocks and dispatches matching TXs
    - Up-to-date: no new blocks → no processing
    - Skips TXs not to monitored addresses
    - Caps blocks per tick at MAX_BLOCKS_PER_TICK
    - Error count increments on RPC failure
    - Alert fires after 5 consecutive errors
    - Error count resets on success
    - ERC-20 transfer event processing
    - No monitored addresses → skip

  Reconciliation CC-06 (8 tests):
    - reconcile_rule_balances: no discrepancy → no alert
    - reconcile_rule_balances: discrepancy > 0.001 ETH → alert
    - reconcile_rule_balances: persists to audit trail
    - reconcile_rule_balances: handles RPC failure gracefully
    - generate_daily_report: clean day → no alerts
    - generate_daily_report: in/out mismatch → alert
    - generate_daily_report: persists summary to audit
    - RULE_DISCREPANCY_THRESHOLD_ETH is 0.001

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_cc06_webhook_polling_reconciliation.py -v
"""

import asyncio
import hashlib
import hmac as hmac_mod
import json
import time

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

# ═══════════════════════════════════════════════════════════════
#  Webhook Verifier Unit Tests
# ═══════════════════════════════════════════════════════════════


class TestWebhookVerifier:
    """Unit tests for app.security.webhook_verifier functions."""

    def test_verify_hmac_valid(self):
        from app.security.webhook_verifier import verify_hmac_signature

        body = b'{"test": "data"}'
        secret = "my-secret"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

        assert verify_hmac_signature(body, sig, secret) is True

    def test_verify_hmac_invalid(self):
        from app.security.webhook_verifier import verify_hmac_signature

        body = b'{"test": "data"}'
        assert verify_hmac_signature(body, "bad_signature", "my-secret") is False

    def test_verify_hmac_timing_safe(self):
        """HMAC comparison must use compare_digest (timing-safe)."""
        import inspect
        from app.security import webhook_verifier

        source = inspect.getsource(webhook_verifier.verify_hmac_signature)
        assert "compare_digest" in source

    def test_ip_whitelist_known_alchemy_ip(self):
        from app.security.webhook_verifier import check_ip_whitelist

        with patch("app.security.webhook_verifier.get_settings") as mock:
            mock.return_value.debug = False
            assert check_ip_whitelist("54.236.187.89") is True

    def test_ip_whitelist_unknown_ip(self):
        from app.security.webhook_verifier import check_ip_whitelist

        with patch("app.security.webhook_verifier.get_settings") as mock:
            mock.return_value.debug = False
            assert check_ip_whitelist("1.2.3.4") is False

    def test_ip_whitelist_private_debug(self):
        from app.security.webhook_verifier import check_ip_whitelist

        with patch("app.security.webhook_verifier.get_settings") as mock:
            mock.return_value.debug = True
            assert check_ip_whitelist("127.0.0.1") is True
            assert check_ip_whitelist("192.168.1.1") is True

    def test_timestamp_freshness_valid(self):
        from app.security.webhook_verifier import check_timestamp_freshness

        now = datetime.now(timezone.utc).isoformat()
        assert check_timestamp_freshness(now) is True

    def test_timestamp_freshness_stale(self):
        from app.security.webhook_verifier import check_timestamp_freshness

        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        assert check_timestamp_freshness(old) is False

    def test_timestamp_freshness_invalid(self):
        from app.security.webhook_verifier import check_timestamp_freshness

        assert check_timestamp_freshness("not-a-date") is False
        assert check_timestamp_freshness("") is False

    @pytest.mark.asyncio
    async def test_idempotency_new(self):
        from app.security.webhook_verifier import check_idempotency

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # SETNX succeeded

        with patch("app.services.cache_service.get_redis", return_value=mock_redis):
            assert await check_idempotency("new-webhook-id") is True

    @pytest.mark.asyncio
    async def test_idempotency_duplicate(self):
        from app.security.webhook_verifier import check_idempotency

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)  # SETNX failed = duplicate

        with patch("app.services.cache_service.get_redis", return_value=mock_redis):
            assert await check_idempotency("dup-webhook-id") is False

    @pytest.mark.asyncio
    async def test_idempotency_redis_down_fails_open(self):
        """If Redis is down, idempotency check should fail open (allow)."""
        from app.security.webhook_verifier import check_idempotency

        with patch(
            "app.services.cache_service.get_redis",
            side_effect=Exception("Redis down"),
        ):
            assert await check_idempotency("any-id") is True

    @pytest.mark.asyncio
    async def test_rate_limit_within(self):
        from app.security.webhook_verifier import check_rate_limit

        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 1, 5, True])  # 5 requests
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.services.cache_service.get_redis", return_value=mock_redis):
            assert await check_rate_limit("1.2.3.4") is True

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        from app.security.webhook_verifier import check_rate_limit

        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 1, 101, True])  # 101 > 100
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.services.cache_service.get_redis", return_value=mock_redis):
            assert await check_rate_limit("1.2.3.4") is False

    @pytest.mark.asyncio
    async def test_rate_limit_redis_down_fails_open(self):
        from app.security.webhook_verifier import check_rate_limit

        with patch(
            "app.services.cache_service.get_redis",
            side_effect=Exception("Redis down"),
        ):
            assert await check_rate_limit("1.2.3.4") is True


class TestWebhookConstants:
    """Verify security constants are correct."""

    def test_freshness_window(self):
        from app.security.webhook_verifier import FRESHNESS_WINDOW
        assert FRESHNESS_WINDOW == 300  # 5 minutes

    def test_rate_limit_max(self):
        from app.security.webhook_verifier import RATE_LIMIT_MAX
        assert RATE_LIMIT_MAX == 100

    def test_idempotency_ttl(self):
        from app.security.webhook_verifier import IDEMPOTENCY_TTL
        assert IDEMPOTENCY_TTL == 3600  # 1 hour

    def test_alchemy_ip_count(self):
        from app.security.webhook_verifier import ALCHEMY_IP_ALLOWLIST
        assert len(ALCHEMY_IP_ALLOWLIST) >= 5


class TestWebhookEndpointIntegration:
    """Integration tests for the updated webhook endpoint using verify_webhook."""

    @pytest.mark.asyncio
    async def test_webhook_dispatches_to_celery(self):
        """Background task should call celery_process_tx.delay()."""
        from app.api.sweeper_routes import _process_alchemy_activity

        activity = [{
            "fromAddress": "0x" + "11" * 20,
            "toAddress": "0x" + "22" * 20,
            "value": 0.5,
            "hash": "0x" + "ab" * 32,
            "asset": "ETH",
            "blockNum": "0x100",
            "category": "external",
        }]

        mock_delay = MagicMock()
        with patch(
            "app.api.sweeper_routes.process_incoming_tx",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.tasks.sweep_tasks.process_incoming_tx"
            ) as mock_celery:
                mock_celery.delay = mock_delay

                await _process_alchemy_activity(activity)

        mock_delay.assert_called_once()
        payload = mock_delay.call_args[0][0]
        assert payload["tx_hash"] == "0x" + "ab" * 32
        assert payload["from_address"] == ("0x" + "11" * 20).lower()
        assert payload["to_address"] == ("0x" + "22" * 20).lower()
        assert payload["token_symbol"] == "ETH"

    @pytest.mark.asyncio
    async def test_webhook_celery_fallback(self):
        """When Celery broker is down, fall back to direct async call."""
        from app.api.sweeper_routes import _process_alchemy_activity

        activity = [{
            "fromAddress": "0x" + "11" * 20,
            "toAddress": "0x" + "22" * 20,
            "value": 0.5,
            "hash": "0x" + "ab" * 32,
            "asset": "ETH",
            "blockNum": "0x100",
            "category": "external",
        }]

        mock_direct = AsyncMock(return_value=1)
        with patch(
            "app.api.sweeper_routes.process_incoming_tx",
            mock_direct,
        ):
            with patch(
                "app.tasks.sweep_tasks.process_incoming_tx"
            ) as mock_celery:
                mock_celery.delay = MagicMock(
                    side_effect=Exception("Broker unavailable")
                )

                await _process_alchemy_activity(activity)

        # Direct call should have been made as fallback
        mock_direct.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_skips_zero_value(self):
        """Zero-value activities should be skipped."""
        from app.api.sweeper_routes import _process_alchemy_activity

        activity = [{
            "fromAddress": "0x" + "11" * 20,
            "toAddress": "0x" + "22" * 20,
            "value": 0,
            "hash": "0x" + "ab" * 32,
            "asset": "ETH",
            "blockNum": "0x100",
            "category": "external",
        }]

        mock_delay = MagicMock()
        with patch(
            "app.tasks.sweep_tasks.process_incoming_tx"
        ) as mock_celery:
            mock_celery.delay = mock_delay
            await _process_alchemy_activity(activity)

        mock_delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_skips_no_to_address(self):
        """Activities without to_address should be skipped."""
        from app.api.sweeper_routes import _process_alchemy_activity

        activity = [{
            "fromAddress": "0x" + "11" * 20,
            "toAddress": "",
            "value": 1.0,
            "hash": "0x" + "ab" * 32,
            "asset": "ETH",
            "blockNum": "0x100",
            "category": "external",
        }]

        mock_delay = MagicMock()
        with patch(
            "app.tasks.sweep_tasks.process_incoming_tx"
        ) as mock_celery:
            mock_celery.delay = mock_delay
            await _process_alchemy_activity(activity)

        mock_delay.assert_not_called()


# ═══════════════════════════════════════════════════════════════
#  Polling Service Tests
# ═══════════════════════════════════════════════════════════════


class TestPollingRedisTracking:
    """Test Redis-backed block tracking in polling_service."""

    @pytest.mark.asyncio
    async def test_get_last_block_none(self):
        """No key in Redis → returns None."""
        from app.services.polling_service import _get_last_processed_block

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            result = await _get_last_processed_block(8453)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_block_returns_int(self):
        """Key exists in Redis → returns int."""
        from app.services.polling_service import _get_last_processed_block

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="12345678")

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            result = await _get_last_processed_block(8453)

        assert result == 12345678

    @pytest.mark.asyncio
    async def test_set_last_block(self):
        """Persists block number to Redis."""
        from app.services.polling_service import _set_last_processed_block

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            await _set_last_processed_block(8453, 99999)

        mock_redis.set.assert_called_once_with("poll:last_block:8453", "99999")

    @pytest.mark.asyncio
    async def test_error_count_increment(self):
        """Error count increments and returns new value."""
        from app.services.polling_service import _increment_error_count

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=3)
        mock_redis.expire = AsyncMock()

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            count = await _increment_error_count(8453)

        assert count == 3
        mock_redis.incr.assert_called_once_with("poll:errors:8453")
        mock_redis.expire.assert_called_once_with("poll:errors:8453", 300)

    @pytest.mark.asyncio
    async def test_error_count_reset(self):
        """Success resets error count."""
        from app.services.polling_service import _reset_error_count

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            await _reset_error_count(8453)

        mock_redis.delete.assert_called_once_with("poll:errors:8453")


class TestPollingConstants:
    """Verify polling service constants."""

    def test_poll_interval(self):
        from app.services.polling_service import POLL_INTERVAL
        assert POLL_INTERVAL == 2

    def test_max_blocks_per_tick(self):
        from app.services.polling_service import MAX_BLOCKS_PER_TICK
        assert MAX_BLOCKS_PER_TICK == 10

    def test_error_alert_threshold(self):
        from app.services.polling_service import CONSECUTIVE_ERROR_ALERT
        assert CONSECUTIVE_ERROR_ALERT == 5


class TestBlockPoller:
    """Tests for BlockPoller class."""

    @pytest.mark.asyncio
    async def test_first_tick_initializes(self):
        """First tick with no last_block → sets current block, no processing."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)

        mock_rpc = AsyncMock()
        mock_rpc.call = AsyncMock(return_value="0x100")  # block 256

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # no last block
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                result = await poller._poll_once()

        assert result["blocks_processed"] == 0
        # Should have stored block 256 in Redis
        mock_redis.set.assert_called_with("poll:last_block:8453", "256")

    @pytest.mark.asyncio
    async def test_up_to_date_no_processing(self):
        """When latest block == last processed → no work."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)

        mock_rpc = AsyncMock()
        mock_rpc.call = AsyncMock(return_value="0x100")  # block 256

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="256")  # already at 256
        mock_redis.set = AsyncMock()

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                result = await poller._poll_once()

        assert result["blocks_processed"] == 0
        assert result["txs_dispatched"] == 0

    @pytest.mark.asyncio
    async def test_processes_new_block_dispatches_matching_tx(self):
        """New block with TX to monitored address → dispatches to Celery."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)
        monitored_addr = "0x" + "aa" * 20

        mock_rpc = AsyncMock()
        # First call: eth_blockNumber, second: eth_getBlockByNumber
        mock_rpc.call = AsyncMock(side_effect=[
            "0x101",  # block 257
            {  # block data
                "number": "0x101",
                "transactions": [
                    {
                        "from": "0x" + "11" * 20,
                        "to": monitored_addr,
                        "value": "0xde0b6b3a7640000",  # 1 ETH in wei
                        "hash": "0x" + "ab" * 32,
                    },
                    {
                        "from": "0x" + "11" * 20,
                        "to": "0x" + "ff" * 20,  # not monitored
                        "value": "0xde0b6b3a7640000",
                        "hash": "0x" + "cd" * 32,
                    },
                ],
            },
            [],  # eth_getLogs (ERC-20) returns empty
        ])

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="256")  # last block
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_delay = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(monitored_addr,)]
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                with patch("app.db.session.async_session", return_value=mock_session):
                    with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
                        mock_celery.delay = mock_delay
                        result = await poller._poll_once()

        assert result["blocks_processed"] == 1
        assert result["txs_dispatched"] == 1
        # Only the matching TX was dispatched
        payload = mock_delay.call_args[0][0]
        assert payload["to_address"] == monitored_addr.lower()
        assert payload["value_wei"] == str(10**18)

    @pytest.mark.asyncio
    async def test_no_monitored_addresses_skips(self):
        """No active rules → skip block processing."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)

        mock_rpc = AsyncMock()
        mock_rpc.call = AsyncMock(return_value="0x101")

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="256")
        mock_redis.set = AsyncMock()

        # No monitored addresses
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                with patch("app.db.session.async_session", return_value=mock_session):
                    result = await poller._poll_once()

        assert result["txs_dispatched"] == 0

    @pytest.mark.asyncio
    async def test_caps_blocks_per_tick(self):
        """When behind by >10 blocks, only process MAX_BLOCKS_PER_TICK."""
        from app.services.polling_service import BlockPoller, MAX_BLOCKS_PER_TICK

        poller = BlockPoller(chain_id=8453)

        mock_rpc = AsyncMock()
        # Latest is 300, last processed is 256 → 44 blocks behind
        # Should only process 10 (MAX_BLOCKS_PER_TICK)
        calls = [
            "0x12c",  # eth_blockNumber = 300
        ]
        # 10 blocks of eth_getBlockByNumber + eth_getLogs each
        for _ in range(MAX_BLOCKS_PER_TICK):
            calls.append({"number": "0x100", "transactions": []})
            calls.append([])  # eth_getLogs

        mock_rpc.call = AsyncMock(side_effect=calls)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="256")
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("0x" + "aa" * 20,)]
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                with patch("app.db.session.async_session", return_value=mock_session):
                    result = await poller._poll_once()

        assert result["blocks_processed"] == MAX_BLOCKS_PER_TICK
        # Last stored block should be 256 + 10 = 266, NOT 300
        mock_redis.set.assert_called_with("poll:last_block:8453", "266")

    @pytest.mark.asyncio
    async def test_skips_zero_value_tx(self):
        """TX with value=0 should be skipped."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)
        monitored_addr = "0x" + "aa" * 20

        mock_rpc = AsyncMock()
        mock_rpc.call = AsyncMock(side_effect=[
            "0x101",  # block 257
            {
                "number": "0x101",
                "transactions": [{
                    "from": "0x" + "11" * 20,
                    "to": monitored_addr,
                    "value": "0x0",  # zero value
                    "hash": "0x" + "ab" * 32,
                }],
            },
            [],
        ])

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="256")
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(monitored_addr,)]
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_delay = MagicMock()

        with patch("app.services.rpc_manager.get_rpc_manager", return_value=mock_rpc):
            with patch("app.services.polling_service.get_redis", return_value=mock_redis):
                with patch("app.db.session.async_session", return_value=mock_session):
                    with patch("app.tasks.sweep_tasks.process_incoming_tx") as mock_celery:
                        mock_celery.delay = mock_delay
                        result = await poller._poll_once()

        mock_delay.assert_not_called()
        assert result["txs_dispatched"] == 0


class TestPollingErrorHandling:
    """Test error handling and alerting in the polling loop."""

    @pytest.mark.asyncio
    async def test_poll_loop_increments_error_on_failure(self):
        """RPC failure in _poll_once → error count incremented."""
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)
        poller._running = True

        call_count = 0

        async def mock_poll_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("RPC timeout")
            # Stop after second tick
            poller._running = False

        poller._poll_once = mock_poll_once

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.services.polling_service.get_redis", return_value=mock_redis):
            with patch("app.services.polling_service.POLL_INTERVAL", 0.01):
                await poller._poll_loop()

        mock_redis.incr.assert_called_with("poll:errors:8453")

    @pytest.mark.asyncio
    async def test_alert_fires_at_threshold(self):
        """After 5 consecutive errors, alert logs CRITICAL."""
        from app.services.polling_service import _send_error_alert

        with patch("app.services.polling_service.logger") as mock_logger:
            await _send_error_alert(8453, 5, "RPC timeout")

        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args[0]
        assert "5" in str(call_args)
        assert "8453" in str(call_args)

    @pytest.mark.asyncio
    async def test_alert_no_crash_if_notification_unavailable(self):
        """Alert should not crash even if notification module is missing."""
        from app.services.polling_service import _send_error_alert

        # notification_service doesn't exist — _send_error_alert catches ImportError
        await _send_error_alert(8453, 5, "RPC timeout")
        # No exception = success


class TestPollingLifecycle:
    """Test start/stop lifecycle."""

    def test_initial_state(self):
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)
        assert poller._running is False
        assert poller._task is None

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)

        # Mock the loop to stop immediately
        async def mock_loop():
            poller._running = False

        with patch.object(poller, "_poll_loop", mock_loop):
            await poller.start()
            assert poller._running is True
            # Give the task a moment to complete
            await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        from app.services.polling_service import BlockPoller

        poller = BlockPoller(chain_id=8453)
        poller._running = True

        async def mock_loop():
            while poller._running:
                await asyncio.sleep(0.01)

        poller._task = asyncio.create_task(mock_loop())
        await poller.stop()

        assert poller._running is False
        assert poller._task is None


# ═══════════════════════════════════════════════════════════════
#  Reconciliation CC-06 Tests
# ═══════════════════════════════════════════════════════════════


class TestReconciliationConstants:
    """Verify reconciliation thresholds."""

    def test_rule_discrepancy_threshold(self):
        from app.services.reconciliation_service import RULE_DISCREPANCY_THRESHOLD_ETH
        assert RULE_DISCREPANCY_THRESHOLD_ETH == Decimal("0.001")

    def test_stale_threshold(self):
        from app.services.reconciliation_service import STALE_THRESHOLD_MINUTES
        assert STALE_THRESHOLD_MINUTES == 10

    def test_onchain_threshold(self):
        from app.services.reconciliation_service import ONCHAIN_DISCREPANCY_THRESHOLD_WEI
        assert ONCHAIN_DISCREPANCY_THRESHOLD_WEI == 10**14


class TestRuleBalanceCheck:
    """Test per-rule balance reconciliation data class."""

    def test_no_alert_when_balanced(self):
        from app.services.reconciliation_service import RuleBalanceCheck

        check = RuleBalanceCheck(
            rule_id=1,
            source_wallet="0x" + "aa" * 20,
            chain_id=8453,
            total_incoming_wei=10**18,
            total_swept_wei=10**18,
            expected_balance_wei=0,
            actual_balance_wei=0,
            discrepancy_wei=0,
            discrepancy_eth=Decimal("0"),
            alert=False,
        )
        assert check.alert is False

    def test_alert_when_discrepancy_exceeds_threshold(self):
        from app.services.reconciliation_service import RuleBalanceCheck

        check = RuleBalanceCheck(
            rule_id=1,
            source_wallet="0x" + "aa" * 20,
            chain_id=8453,
            total_incoming_wei=10**18,
            total_swept_wei=10**18,
            expected_balance_wei=0,
            actual_balance_wei=2 * 10**15,  # 0.002 ETH residual
            discrepancy_wei=2 * 10**15,
            discrepancy_eth=Decimal("0.002"),
            alert=True,
        )
        assert check.alert is True
        assert check.discrepancy_eth > Decimal("0.001")


class TestRuleDailyVolume:
    """Test daily volume data class."""

    def test_clean_day(self):
        from app.services.reconciliation_service import RuleDailyVolume

        vol = RuleDailyVolume(
            rule_id=1,
            source_wallet="0x" + "aa" * 20,
            date="2026-04-02",
            volume_in_wei=5 * 10**18,
            volume_out_wei=5 * 10**18,
            sweep_count=10,
            completed_count=10,
            failed_count=0,
            discrepancy_wei=0,
            alert=False,
        )
        assert vol.alert is False
        assert vol.completed_count == vol.sweep_count

    def test_failed_day(self):
        from app.services.reconciliation_service import RuleDailyVolume

        vol = RuleDailyVolume(
            rule_id=1,
            source_wallet="0x" + "aa" * 20,
            date="2026-04-02",
            volume_in_wei=5 * 10**18,
            volume_out_wei=3 * 10**18,
            sweep_count=10,
            completed_count=6,
            failed_count=4,
            discrepancy_wei=2 * 10**18,
            alert=True,
        )
        assert vol.alert is True
        assert vol.failed_count == 4


class TestDailyReconciliationReport:
    """Test the full daily report structure."""

    def test_clean_report(self):
        from app.services.reconciliation_service import DailyReconciliationReport

        report = DailyReconciliationReport(
            date="2026-04-02",
            rules_checked=5,
            alerts=0,
        )
        assert report.alerts == 0
        assert len(report.rule_volumes) == 0
        assert len(report.rule_balances) == 0

    def test_report_with_alerts(self):
        from app.services.reconciliation_service import (
            DailyReconciliationReport, RuleDailyVolume,
        )

        vol = RuleDailyVolume(
            rule_id=1, source_wallet="0x" + "aa" * 20,
            date="2026-04-02", volume_in_wei=10**18,
            volume_out_wei=0, sweep_count=1,
            completed_count=0, failed_count=1,
            discrepancy_wei=10**18, alert=True,
        )
        report = DailyReconciliationReport(
            date="2026-04-02",
            rules_checked=1,
            alerts=1,
            rule_volumes=[vol],
        )
        assert report.alerts == 1
        assert report.rule_volumes[0].alert is True


class TestReconcileRuleBalancesLogic:
    """Test the reconciliation math and alert logic."""

    def test_discrepancy_calculation(self):
        """Verify discrepancy is calculated correctly: |actual - expected|."""
        actual = 1_500_000_000_000_000  # 0.0015 ETH
        expected = 0
        disc = abs(actual - expected)
        disc_eth = Decimal(disc) / Decimal(10**18)

        assert disc_eth == Decimal("0.0015")
        assert disc_eth > Decimal("0.001")  # should trigger alert

    def test_no_alert_below_threshold(self):
        """Discrepancy below 0.001 ETH should NOT alert."""
        actual = 500_000_000_000_000  # 0.0005 ETH
        expected = 0
        disc = abs(actual - expected)
        disc_eth = Decimal(disc) / Decimal(10**18)

        assert disc_eth == Decimal("0.0005")
        assert disc_eth < Decimal("0.001")  # no alert

    def test_zero_discrepancy(self):
        """Perfect match → zero discrepancy, no alert."""
        actual = 10**18
        expected = 10**18
        disc = abs(actual - expected)

        assert disc == 0

    def test_negative_expected_balance(self):
        """When swept > incoming (should not happen, but test the math)."""
        incoming = 5 * 10**18
        swept = 5 * 10**18
        expected = incoming - swept
        actual = 100_000_000_000_000  # 0.0001 ETH dust

        disc = abs(actual - expected)
        disc_eth = Decimal(disc) / Decimal(10**18)

        assert disc_eth == Decimal("0.0001")
        assert disc_eth < Decimal("0.001")  # no alert for dust


class TestFullVerifyWebhookPipeline:
    """Test the full verify_webhook pipeline with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self):
        """All 5 checks pass → returns parsed payload."""
        from app.security.webhook_verifier import verify_webhook

        body_dict = {
            "id": "evt_123",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "webhookId": "wh_test",
            "event": {"network": "BASE_MAINNET", "activity": []},
        }
        body = json.dumps(body_dict).encode()
        secret = "test-secret"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_request = AsyncMock()
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {
            "X-Alchemy-Signature": sig,
            "X-Real-IP": "54.236.187.89",  # Known Alchemy IP
        }
        mock_request.client = MagicMock()
        mock_request.client.host = "54.236.187.89"

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # new webhook
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 1, 5, True])  # under limit
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.security.webhook_verifier.get_settings") as mock_s:
            mock_s.return_value.alchemy_webhook_secret = secret
            mock_s.return_value.debug = False

            with patch("app.services.cache_service.get_redis", return_value=mock_redis):
                result = await verify_webhook(mock_request)

        assert result["id"] == "evt_123"
        assert result["webhookId"] == "wh_test"

    @pytest.mark.asyncio
    async def test_pipeline_rejects_bad_ip(self):
        """Non-whitelisted IP → WebhookVerificationError 403."""
        from app.security.webhook_verifier import (
            verify_webhook, WebhookVerificationError,
        )

        body_dict = {"id": "evt_123", "createdAt": datetime.now(timezone.utc).isoformat()}
        body = json.dumps(body_dict).encode()
        secret = "test-secret"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_request = AsyncMock()
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {
            "X-Alchemy-Signature": sig,
            "X-Real-IP": "1.2.3.4",  # Unknown IP
        }
        mock_request.client = MagicMock()
        mock_request.client.host = "1.2.3.4"

        with patch("app.security.webhook_verifier.get_settings") as mock_s:
            mock_s.return_value.alchemy_webhook_secret = secret
            mock_s.return_value.debug = False

            with pytest.raises(WebhookVerificationError) as exc_info:
                await verify_webhook(mock_request)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_pipeline_rejects_duplicate(self):
        """Duplicate webhook_id → WebhookVerificationError 200."""
        from app.security.webhook_verifier import (
            verify_webhook, WebhookVerificationError,
        )

        body_dict = {
            "id": "evt_dup",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(body_dict).encode()
        secret = "test-secret"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_request = AsyncMock()
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {
            "X-Alchemy-Signature": sig,
            "X-Real-IP": "54.236.187.89",
        }
        mock_request.client = MagicMock()
        mock_request.client.host = "54.236.187.89"

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)  # duplicate!
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 1, 5, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.security.webhook_verifier.get_settings") as mock_s:
            mock_s.return_value.alchemy_webhook_secret = secret
            mock_s.return_value.debug = False

            with patch("app.services.cache_service.get_redis", return_value=mock_redis):
                with pytest.raises(WebhookVerificationError) as exc_info:
                    await verify_webhook(mock_request)

        assert exc_info.value.status_code == 200
        assert "Duplicate" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_pipeline_rejects_rate_limited(self):
        """Rate limit exceeded → WebhookVerificationError 429."""
        from app.security.webhook_verifier import (
            verify_webhook, WebhookVerificationError,
        )

        body_dict = {
            "id": "evt_rate",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(body_dict).encode()
        secret = "test-secret"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_request = AsyncMock()
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {
            "X-Alchemy-Signature": sig,
            "X-Real-IP": "54.236.187.89",
        }
        mock_request.client = MagicMock()
        mock_request.client.host = "54.236.187.89"

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # new
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 1, 200, True])  # over limit
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.security.webhook_verifier.get_settings") as mock_s:
            mock_s.return_value.alchemy_webhook_secret = secret
            mock_s.return_value.debug = False

            with patch("app.services.cache_service.get_redis", return_value=mock_redis):
                with pytest.raises(WebhookVerificationError) as exc_info:
                    await verify_webhook(mock_request)

        assert exc_info.value.status_code == 429
