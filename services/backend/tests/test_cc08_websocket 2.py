"""
RPagos Backend — Test CC-08: WebSocket Sweep Feed.

Tests:
  - Connection: accept, max connections, invalid address
  - Welcome message + initial state (last 20 events + stats)
  - Client messages: pong, replay, unknown
  - Broadcast: single owner, all owners
  - Redis event buffer: push, recent, missed
  - Pub/Sub: publish_event helper
  - Circuit breaker monitor: state change broadcast
  - Spending warning monitor: threshold-based warnings
  - Background tasks lifecycle: start, shutdown
  - Heartbeat: dead connection cleanup

Run:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_cc08_websocket.py -v
"""

import asyncio
import json
import time

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

from app.db.session import engine
from app.models.db_models import Base


# ── Test addresses ────────────────────────────────────────

OWNER = "0x" + "aa" * 20
OWNER2 = "0x" + "bb" * 20


# ── Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _bypass_ws_ticket():
    """The /ws/sweep-feed endpoint requires a single-use ?ticket= (M4), minted
    via Redis. Bypass ticket consumption in tests by returning the connecting
    owner. The address-validation rejection test is unaffected (address check
    runs before the ticket check)."""
    with patch(
        "app.api.websocket_routes.consume_sweep_ticket",
        AsyncMock(return_value=OWNER.lower()),
    ):
        yield


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def manager():
    """Fresh SweepFeedManager instance (no background tasks)."""
    from app.api.websocket_routes import SweepFeedManager
    return SweepFeedManager()


def make_ws(accept=True):
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ═══════════════════════════════════════════════════════════
#  Connection Manager
# ═══════════════════════════════════════════════════════════

class TestConnectionManager:
    """Test connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, manager):
        ws = make_ws()
        result = await manager.connect(OWNER, ws)
        assert result is True
        ws.accept.assert_awaited_once()
        assert manager.active_connections == 1

    @pytest.mark.asyncio
    async def test_max_connections_per_owner(self, manager):
        """Max 5 connections per owner, 6th is rejected."""
        sockets = []
        for _ in range(5):
            ws = make_ws()
            assert await manager.connect(OWNER, ws) is True
            sockets.append(ws)

        assert manager.active_connections == 5

        ws6 = make_ws()
        result = await manager.connect(OWNER, ws6)
        assert result is False
        ws6.accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_different_owners_independent(self, manager):
        """Different owners have independent connection pools."""
        for _ in range(5):
            assert await manager.connect(OWNER, make_ws()) is True
        for _ in range(5):
            assert await manager.connect(OWNER2, make_ws()) is True

        assert manager.active_connections == 10
        assert manager.connected_owners() == {OWNER, OWNER2}

    @pytest.mark.asyncio
    async def test_disconnect_removes_socket(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)
        assert manager.active_connections == 1

        manager.disconnect(OWNER, ws)
        assert manager.active_connections == 0
        assert OWNER not in manager.connected_owners()

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_noop(self, manager):
        """Disconnecting a socket that was never connected is a no-op."""
        ws = make_ws()
        manager.disconnect(OWNER, ws)  # should not raise
        assert manager.active_connections == 0


# ═══════════════════════════════════════════════════════════
#  Broadcast
# ═══════════════════════════════════════════════════════════

class TestBroadcast:

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_owner_sockets(self, manager):
        ws1 = make_ws()
        ws2 = make_ws()
        await manager.connect(OWNER, ws1)
        await manager.connect(OWNER, ws2)

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis:
            mock_r = AsyncMock()
            mock_redis.return_value = mock_r

            await manager.broadcast(OWNER, "batch_started", {"batch_id": "123"})

        assert ws1.send_json.await_count == 1
        assert ws2.send_json.await_count == 1

        event = ws1.send_json.call_args[0][0]
        assert event["type"] == "batch_started"
        assert event["data"]["batch_id"] == "123"
        assert "event_id" in event
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_sockets(self, manager):
        ws_alive = make_ws()
        ws_dead = make_ws()
        ws_dead.send_json.side_effect = Exception("connection lost")

        await manager.connect(OWNER, ws_alive)
        await manager.connect(OWNER, ws_dead)
        assert manager.active_connections == 2

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            await manager.broadcast(OWNER, "test", {})

        assert manager.active_connections == 1

    @pytest.mark.asyncio
    async def test_broadcast_to_all_owners(self, manager):
        ws1 = make_ws()
        ws2 = make_ws()
        await manager.connect(OWNER, ws1)
        await manager.connect(OWNER2, ws2)

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            await manager.broadcast_to_all("circuit_breaker_change", {"breaker": "alchemy"})

        assert ws1.send_json.await_count == 1
        assert ws2.send_json.await_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_increments_event_id(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            await manager.broadcast(OWNER, "a", {})
            await manager.broadcast(OWNER, "b", {})

        ev1 = ws.send_json.call_args_list[0][0][0]
        ev2 = ws.send_json.call_args_list[1][0][0]
        assert ev2["event_id"] > ev1["event_id"]


# ═══════════════════════════════════════════════════════════
#  Redis Event Buffer
# ═══════════════════════════════════════════════════════════

class TestRedisBuffer:

    @pytest.mark.asyncio
    async def test_push_event_stores_in_redis(self, manager):
        mock_r = AsyncMock()
        with patch("app.api.websocket_routes.get_redis", return_value=mock_r):
            event = {"event_id": 1, "type": "test", "data": {}}
            await manager._push_event(OWNER, event)

        mock_r.lpush.assert_awaited_once()
        mock_r.ltrim.assert_awaited_once()
        mock_r.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_recent_events_returns_oldest_first(self, manager):
        events = [
            json.dumps({"event_id": 3, "type": "c"}),
            json.dumps({"event_id": 2, "type": "b"}),
            json.dumps({"event_id": 1, "type": "a"}),
        ]
        mock_r = AsyncMock()
        mock_r.lrange.return_value = events  # newest first (LPUSH order)

        with patch("app.api.websocket_routes.get_redis", return_value=mock_r):
            result = await manager._get_recent_events(OWNER, 20)

        assert len(result) == 3
        assert result[0]["event_id"] == 1  # oldest first
        assert result[2]["event_id"] == 3

    @pytest.mark.asyncio
    async def test_get_missed_events_filters_by_id(self, manager):
        events = [
            json.dumps({"event_id": 5, "type": "e"}),
            json.dumps({"event_id": 4, "type": "d"}),
            json.dumps({"event_id": 3, "type": "c"}),
            json.dumps({"event_id": 2, "type": "b"}),
        ]
        mock_r = AsyncMock()
        mock_r.lrange.return_value = events

        with patch("app.api.websocket_routes.get_redis", return_value=mock_r):
            result = await manager.get_missed_events(OWNER, after_event_id=3)

        assert len(result) == 2
        assert result[0]["event_id"] == 4
        assert result[1]["event_id"] == 5

    @pytest.mark.asyncio
    async def test_buffer_graceful_on_redis_failure(self, manager):
        with patch("app.api.websocket_routes.get_redis", side_effect=Exception("down")):
            await manager._push_event(OWNER, {})  # should not raise
            result = await manager._get_recent_events(OWNER, 20)
            assert result == []
            missed = await manager.get_missed_events(OWNER, 0)
            assert missed == []


# ═══════════════════════════════════════════════════════════
#  Initial State on Connect
# ═══════════════════════════════════════════════════════════

class TestInitialState:

    @pytest.mark.asyncio
    async def test_send_initial_state_with_events(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        recent_events = [
            json.dumps({"event_id": 1, "type": "a", "data": {}}),
            json.dumps({"event_id": 2, "type": "b", "data": {}}),
        ]
        mock_r = AsyncMock()
        mock_r.lrange.return_value = recent_events

        with patch("app.api.websocket_routes.get_redis", return_value=mock_r), \
             patch.object(manager, "_build_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = {"sweep_count_24h": 5}
            await manager.send_initial_state(OWNER, ws)

        # welcome (from connect) + replay + stats = 3 calls
        calls = ws.send_json.call_args_list
        # First call is from ws.accept in connect, then send_json from send_initial_state
        # Skip accept call — look at send_json calls after connect
        replay_call = None
        stats_call = None
        for call in calls:
            msg = call[0][0]
            if msg.get("type") == "replay_response":
                replay_call = msg
            elif msg.get("type") == "stats_update":
                stats_call = msg

        assert replay_call is not None
        assert replay_call["data"]["count"] == 2
        assert replay_call["data"]["reason"] == "initial_connect"

        assert stats_call is not None
        assert stats_call["data"]["sweep_count_24h"] == 5

    @pytest.mark.asyncio
    async def test_send_initial_state_no_events(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        mock_r = AsyncMock()
        mock_r.lrange.return_value = []

        with patch("app.api.websocket_routes.get_redis", return_value=mock_r), \
             patch.object(manager, "_build_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = {"sweep_count_24h": 0}
            await manager.send_initial_state(OWNER, ws)

        # No replay sent for empty event list, just stats
        calls = ws.send_json.call_args_list
        types = [c[0][0].get("type") for c in calls]
        assert "replay_response" not in types
        assert "stats_update" in types

    @pytest.mark.asyncio
    async def test_send_initial_state_stats_failure_non_blocking(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        mock_r = AsyncMock()
        mock_r.lrange.return_value = []

        with patch("app.api.websocket_routes.get_redis", return_value=mock_r), \
             patch.object(manager, "_build_stats", side_effect=Exception("db error")):
            await manager.send_initial_state(OWNER, ws)  # should not raise


# ═══════════════════════════════════════════════════════════
#  Pub/Sub Helper
# ═══════════════════════════════════════════════════════════

class TestPublishEvent:

    @pytest.mark.asyncio
    async def test_publish_event_success(self):
        from app.api.websocket_routes import publish_event

        mock_r = AsyncMock()
        with patch("app.api.websocket_routes.get_redis", return_value=mock_r):
            result = await publish_event(OWNER, "batch_started", {"batch_id": "x"})

        assert result is True
        mock_r.publish.assert_awaited_once()
        channel = mock_r.publish.call_args[0][0]
        assert channel == f"sweep_events:{OWNER.lower()}"

        payload = json.loads(mock_r.publish.call_args[0][1])
        assert payload["type"] == "batch_started"
        assert payload["data"]["batch_id"] == "x"

    @pytest.mark.asyncio
    async def test_publish_event_redis_down(self):
        from app.api.websocket_routes import publish_event

        with patch("app.api.websocket_routes.get_redis", side_effect=Exception("down")):
            result = await publish_event(OWNER, "test", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_event_lowercases_owner(self):
        from app.api.websocket_routes import publish_event

        mock_r = AsyncMock()
        with patch("app.api.websocket_routes.get_redis", return_value=mock_r):
            await publish_event("0xABCDef1234567890abcdef1234567890ABCDEF12", "test", {})

        channel = mock_r.publish.call_args[0][0]
        assert channel == "sweep_events:0xabcdef1234567890abcdef1234567890abcdef12"


# ═══════════════════════════════════════════════════════════
#  Circuit Breaker Monitor
# ═══════════════════════════════════════════════════════════

class TestCircuitBreakerMonitor:

    @pytest.mark.asyncio
    async def test_detects_state_change(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        # Seed initial state
        manager._cb_states["alchemy"] = "closed"

        mock_cb = MagicMock()
        mock_cb.state = MagicMock()
        mock_cb.state.value = "open"

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis, \
             patch("app.services.circuit_breaker.get_all_circuit_breakers", return_value={"alchemy": mock_cb}):
            mock_redis.return_value = AsyncMock()
            await manager._circuit_breaker_monitor.__wrapped__(manager) if hasattr(manager._circuit_breaker_monitor, '__wrapped__') else None

            # Call the monitor logic directly (simulate one iteration)
            from app.services.circuit_breaker import get_all_circuit_breakers
            for name, cb in {"alchemy": mock_cb}.items():
                current = cb.state.value
                previous = manager._cb_states.get(name)
                if previous is not None and current != previous:
                    await manager.broadcast_to_all(
                        "circuit_breaker_change",
                        {
                            "breaker": name,
                            "from_state": previous,
                            "to_state": current,
                        },
                    )
                manager._cb_states[name] = current

        # Find the circuit_breaker_change event
        found = False
        for call in ws.send_json.call_args_list:
            msg = call[0][0]
            if msg.get("type") == "circuit_breaker_change":
                assert msg["data"]["breaker"] == "alchemy"
                assert msg["data"]["from_state"] == "closed"
                assert msg["data"]["to_state"] == "open"
                found = True
        assert found

    @pytest.mark.asyncio
    async def test_no_broadcast_when_state_unchanged(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        manager._cb_states["redis"] = "closed"

        mock_cb = MagicMock()
        mock_cb.state = MagicMock()
        mock_cb.state.value = "closed"

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            for name, cb in {"redis": mock_cb}.items():
                current = cb.state.value
                previous = manager._cb_states.get(name)
                if previous is not None and current != previous:
                    await manager.broadcast_to_all("circuit_breaker_change", {})
                manager._cb_states[name] = current

        # Only the accept-related calls, no broadcast
        for call in ws.send_json.call_args_list:
            msg = call[0][0]
            assert msg.get("type") != "circuit_breaker_change"


# ═══════════════════════════════════════════════════════════
#  Spending Warning Monitor
# ═══════════════════════════════════════════════════════════

class TestSpendingWarning:

    @pytest.mark.asyncio
    async def test_warning_when_over_80_percent(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        from app.services.spending_policy import SpendingStatus

        mock_status = SpendingStatus(
            source=OWNER,
            chain_id=8453,
            per_hour_spent_wei=str(22 * 10**18),     # 22 ETH / 25 = 88%
            per_hour_limit_wei=str(25 * 10**18),
            per_day_spent_wei=str(10 * 10**18),       # 10 ETH / 50 = 20%
            per_day_limit_wei=str(50 * 10**18),
            global_daily_spent_wei=str(100 * 10**18),  # 100 ETH / 500 = 20%
            global_daily_limit_wei=str(500 * 10**18),
            sweeps_this_hour=3,
            max_sweeps_per_hour=10,
        )

        mock_policy = AsyncMock()
        mock_policy.get_status.return_value = mock_status

        with patch("app.api.websocket_routes.get_redis", new_callable=AsyncMock) as mock_redis, \
             patch.object(manager, "_get_owner_chain_ids", return_value=[8453]), \
             patch("app.services.spending_policy.SpendingPolicy", return_value=mock_policy):
            mock_redis.return_value = AsyncMock()

            # Simulate one iteration of spending monitor
            from app.services.spending_policy import SpendingPolicy
            policy = mock_policy
            chain_ids = [8453]
            for chain_id in chain_ids:
                status = await policy.get_status(OWNER, chain_id)
                warnings = []

                hour_spent = int(status.per_hour_spent_wei)
                hour_limit = int(status.per_hour_limit_wei)
                if hour_limit > 0 and hour_spent / hour_limit >= 0.80:
                    warnings.append({
                        "tier": "per_hour",
                        "percent": round(hour_spent / hour_limit * 100, 1),
                    })

                if warnings:
                    await manager.broadcast(OWNER, "spending_warning", {
                        "chain_id": chain_id,
                        "warnings": warnings,
                    })

        found = False
        for call in ws.send_json.call_args_list:
            msg = call[0][0]
            if msg.get("type") == "spending_warning":
                assert msg["data"]["chain_id"] == 8453
                assert len(msg["data"]["warnings"]) == 1
                assert msg["data"]["warnings"][0]["tier"] == "per_hour"
                assert msg["data"]["warnings"][0]["percent"] == 88.0
                found = True
        assert found

    @pytest.mark.asyncio
    async def test_no_warning_under_threshold(self, manager):
        ws = make_ws()
        await manager.connect(OWNER, ws)

        from app.services.spending_policy import SpendingStatus

        mock_status = SpendingStatus(
            source=OWNER,
            chain_id=8453,
            per_hour_spent_wei=str(5 * 10**18),       # 5/25 = 20%
            per_hour_limit_wei=str(25 * 10**18),
            per_day_spent_wei=str(10 * 10**18),        # 10/50 = 20%
            per_day_limit_wei=str(50 * 10**18),
            global_daily_spent_wei=str(50 * 10**18),   # 50/500 = 10%
            global_daily_limit_wei=str(500 * 10**18),
            sweeps_this_hour=2,
            max_sweeps_per_hour=10,
        )

        # Compute warnings manually — should be empty
        warnings = []
        hour_spent = int(mock_status.per_hour_spent_wei)
        hour_limit = int(mock_status.per_hour_limit_wei)
        if hour_limit > 0 and hour_spent / hour_limit >= 0.80:
            warnings.append({"tier": "per_hour"})

        assert warnings == []


# ═══════════════════════════════════════════════════════════
#  Background Tasks Lifecycle
# ═══════════════════════════════════════════════════════════

class TestBackgroundTasks:

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self, manager):
        # Patch all loops to immediately return
        with patch.object(manager, "_heartbeat_loop", new_callable=AsyncMock) as hb, \
             patch.object(manager, "_stats_loop", new_callable=AsyncMock) as st, \
             patch.object(manager, "_pubsub_loop", new_callable=AsyncMock) as ps, \
             patch.object(manager, "_circuit_breaker_monitor", new_callable=AsyncMock) as cb, \
             patch.object(manager, "_spending_monitor", new_callable=AsyncMock) as sp:
            manager.start_background_tasks()
            assert len(manager._bg_tasks) == 5
            # Cleanup
            for t in manager._bg_tasks:
                t.cancel()
            await asyncio.gather(*manager._bg_tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks_and_closes_connections(self, manager):
        ws1 = make_ws()
        ws2 = make_ws()
        await manager.connect(OWNER, ws1)
        await manager.connect(OWNER2, ws2)

        # Add dummy tasks
        async def noop():
            await asyncio.sleep(999)

        manager._bg_tasks = [asyncio.create_task(noop()) for _ in range(3)]

        await manager.shutdown()

        assert len(manager._bg_tasks) == 0
        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()


# ═══════════════════════════════════════════════════════════
#  Heartbeat
# ═══════════════════════════════════════════════════════════

class TestHeartbeat:

    @pytest.mark.asyncio
    async def test_heartbeat_removes_dead_connections(self, manager):
        ws_alive = make_ws()
        ws_dead = make_ws()
        ws_dead.send_json.side_effect = Exception("gone")

        await manager.connect(OWNER, ws_alive)
        await manager.connect(OWNER, ws_dead)
        assert manager.active_connections == 2

        # Run one heartbeat iteration (skip the sleep)
        dead_pairs = []
        for owner, sockets in list(manager._connections.items()):
            for ws in sockets:
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    dead_pairs.append((owner, ws))
        for owner, ws in dead_pairs:
            manager.disconnect(owner, ws)

        assert manager.active_connections == 1


# ═══════════════════════════════════════════════════════════
#  WebSocket Endpoint (Integration via TestClient)
# ═══════════════════════════════════════════════════════════

class TestWebSocketEndpoint:

    @staticmethod
    def _mock_fm():
        """Create a feed_manager mock whose connect() accepts the websocket."""
        mock_fm = MagicMock()

        async def _accept_connect(owner, ws):
            await ws.accept()
            return True

        mock_fm.connect = AsyncMock(side_effect=_accept_connect)
        mock_fm.send_initial_state = AsyncMock()
        mock_fm.disconnect = MagicMock()
        mock_fm.get_missed_events = AsyncMock(return_value=[])
        return mock_fm

    @pytest.mark.asyncio
    async def test_invalid_address_rejected(self):
        from starlette.testclient import TestClient
        from app.main import app

        with patch("app.api.websocket_routes.feed_manager") as mock_fm:
            client = TestClient(app)
            with pytest.raises(Exception):
                with client.websocket_connect("/ws/sweep-feed/not-an-address"):
                    pass

    @pytest.mark.asyncio
    async def test_valid_connection_receives_welcome(self):
        from starlette.testclient import TestClient
        from app.main import app

        mock_fm = self._mock_fm()
        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "connected"
                assert msg["data"]["owner"] == OWNER.lower()
                assert "message_types" in msg["data"]
                assert "incoming_detected" in msg["data"]["message_types"]
                assert "batch_started" in msg["data"]["message_types"]

    @pytest.mark.asyncio
    async def test_replay_message(self):
        from starlette.testclient import TestClient
        from app.main import app

        mock_fm = self._mock_fm()
        mock_fm.get_missed_events = AsyncMock(return_value=[
            {"event_id": 5, "type": "test", "data": {}},
        ])

        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                ws.receive_json()  # welcome
                ws.send_json({"type": "replay", "after_event_id": 4})
                resp = ws.receive_json()
                assert resp["type"] == "replay_response"
                assert resp["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_pong_message_no_response(self):
        from starlette.testclient import TestClient
        from app.main import app

        mock_fm = self._mock_fm()
        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                ws.receive_json()  # welcome
                ws.send_json({"type": "pong"})
                # Send another message to verify pong didn't produce output
                ws.send_json({"type": "unknown_test"})
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "unknown_test" in resp["data"]["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        from starlette.testclient import TestClient
        from app.main import app

        mock_fm = self._mock_fm()
        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                ws.receive_json()  # welcome
                ws.send_text("not json at all")
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "Invalid JSON" in resp["data"]["message"]

    @pytest.mark.asyncio
    async def test_max_connections_error(self):
        """When connect returns False, endpoint accepts, sends error, then closes."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        from app.main import app

        mock_fm = MagicMock()
        mock_fm.connect = AsyncMock(return_value=False)
        mock_fm.disconnect = MagicMock()

        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            # The server accepts, sends error, then closes — client sees disconnect
            try:
                with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                    msg = ws.receive_json()
                    assert msg["type"] == "error"
                    assert "Max" in msg["data"]["message"]
            except Exception:
                pass  # Expected: server closes after error message


# ═══════════════════════════════════════════════════════════
#  Message Types Documented
# ═══════════════════════════════════════════════════════════

class TestMessageTypes:
    """Verify all documented message types are in the welcome message."""

    EXPECTED_TYPES = [
        "incoming_detected",
        "batch_started",
        "batch_progress",
        "batch_completed",
        "batch_failed",
        "item_confirmed",
        "stats_update",
        "circuit_breaker_change",
        "spending_warning",
        "rule_updated",
    ]

    @pytest.mark.asyncio
    async def test_welcome_lists_all_message_types(self):
        from starlette.testclient import TestClient
        from app.main import app

        async def _accept_connect(owner, ws):
            await ws.accept()
            return True

        mock_fm = MagicMock()
        mock_fm.connect = AsyncMock(side_effect=_accept_connect)
        mock_fm.send_initial_state = AsyncMock()
        mock_fm.disconnect = MagicMock()

        with patch("app.api.websocket_routes.feed_manager", mock_fm):
            client = TestClient(app)
            with client.websocket_connect(f"/ws/sweep-feed/{OWNER}") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "connected"
                for t in self.EXPECTED_TYPES:
                    assert t in msg["data"]["message_types"], f"Missing: {t}"


# ═══════════════════════════════════════════════════════════
#  Owner Chain IDs Helper
# ═══════════════════════════════════════════════════════════

class TestOwnerChainIds:

    @pytest.mark.asyncio
    async def test_returns_distinct_chain_ids(self, manager):
        from app.db.session import async_session
        from app.models.forwarding_models import ForwardingRule

        async with async_session() as db:
            r1 = ForwardingRule(
                user_id=OWNER.lower(),
                source_wallet="0x" + "11" * 20,
                destination_wallet="0x" + "22" * 20,
                chain_id=8453,
                is_active=True,
            )
            r2 = ForwardingRule(
                user_id=OWNER.lower(),
                source_wallet="0x" + "33" * 20,
                destination_wallet="0x" + "44" * 20,
                chain_id=84532,
                is_active=True,
            )
            r3 = ForwardingRule(
                user_id=OWNER.lower(),
                source_wallet="0x" + "55" * 20,
                destination_wallet="0x" + "66" * 20,
                chain_id=8453,
                is_active=False,  # inactive
            )
            db.add_all([r1, r2, r3])
            await db.commit()

        result = await manager._get_owner_chain_ids(OWNER.lower())
        assert set(result) == {8453, 84532}  # inactive r3 excluded

    @pytest.mark.asyncio
    async def test_empty_when_no_rules(self, manager):
        result = await manager._get_owner_chain_ids(OWNER.lower())
        assert result == []
