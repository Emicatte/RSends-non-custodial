"""
RSends Backend — WebSocket Sweep Feed (Command Center)

WS /ws/sweep-feed/{owner_address}

Connection:
  - Max 5 connections per owner
  - Heartbeat every 15s (server→client ping, expects pong)
  - Auto-cleanup of dead connections
  - On connect: last 20 events from Redis buffer + current stats

Message types (server → client):
  - incoming_detected    — TX in entrata rilevata (webhook/polling)
  - batch_started        — sweep batch avviato
  - batch_progress       — avanzamento batch (item N/M)
  - batch_completed      — batch completato con successo
  - batch_failed         — batch fallito
  - item_confirmed       — singolo item confermato on-chain
  - stats_update         — ogni 30s con gas/volume/count
  - circuit_breaker_change — cambio stato circuit breaker
  - spending_warning     — soglia spending raggiunta (>80%)
  - rule_updated         — regola modificata/creata/eliminata

Client → server:
  - {"type": "replay", "after_event_id": <int>}  — richiedi eventi persi
  - {"type": "pong"}                              — risposta a ping

Redis Pub/Sub:
  - Subscribe to "sweep_events:{owner}" pattern
  - Buffer last 50 events per owner in Redis list
  - Other services publish via `publish_event()` helper
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import case, func, select

from app.db.session import async_session
from app.models.forwarding_models import ForwardingRule, SweepLog, SweepStatus
from app.services.cache_service import get_redis
from app.services.ws_ticket import consume_sweep_ticket

logger = logging.getLogger(__name__)

ws_router = APIRouter()

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_CONNS_PER_OWNER = 5
EVENT_BUFFER_SIZE = 50
REPLAY_ON_CONNECT = 20
REDIS_EVENTS_KEY = "ws:events:{owner}"
REDIS_EVENT_TTL = 3600  # 1h
PUBSUB_CHANNEL_PREFIX = "sweep_events"
SPENDING_WARNING_THRESHOLD = 0.80  # 80%


# ═══════════════════════════════════════════════════════════
#  Pub/Sub Helper — used by other services to push events
# ═══════════════════════════════════════════════════════════

async def publish_event(owner: str, event_type: str, data: dict) -> bool:
    """Publish an event to Redis Pub/Sub for a specific owner.

    Other services (sweep_service, webhook handler, etc.) call this
    to push events into the WebSocket feed without importing the manager.

    Args:
        owner: Owner address (will be lowercased).
        event_type: One of the documented message types.
        data: Event payload dict.

    Returns:
        True if published, False if Redis unavailable.
    """
    try:
        r = await get_redis()
        channel = f"{PUBSUB_CHANNEL_PREFIX}:{owner.lower()}"
        message = json.dumps({
            "type": event_type,
            "data": data,
        }, default=str)
        await r.publish(channel, message)
        return True
    except Exception:
        logger.debug("Failed to publish event to %s", owner, exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════
#  Connection Manager
# ═══════════════════════════════════════════════════════════

class SweepFeedManager:
    """Gestisce connessioni WebSocket per owner_address."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._event_counter: int = int(time.time() * 1000)
        self._bg_tasks: list[asyncio.Task] = []
        self._cb_states: dict[str, str] = {}  # circuit breaker state cache

    # ── Lifecycle ───────────────────────────────────────

    def start_background_tasks(self) -> None:
        self._bg_tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._bg_tasks.append(asyncio.create_task(self._stats_loop()))
        self._bg_tasks.append(asyncio.create_task(self._pubsub_loop()))
        self._bg_tasks.append(asyncio.create_task(self._circuit_breaker_monitor()))
        self._bg_tasks.append(asyncio.create_task(self._spending_monitor()))
        logger.info(
            "SweepFeedManager started %d background tasks",
            len(self._bg_tasks),
        )

    async def shutdown(self) -> None:
        for task in self._bg_tasks:
            task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
        # Chiudi tutte le connessioni
        for owner, sockets in list(self._connections.items()):
            for ws in sockets:
                try:
                    await ws.close(code=1001, reason="server_shutdown")
                except Exception:
                    pass
            sockets.clear()
        logger.info("SweepFeedManager shut down, all connections closed")

    # ── Connect / Disconnect ────────────────────────────

    async def connect(self, owner: str, ws: WebSocket) -> bool:
        if len(self._connections[owner]) >= MAX_CONNS_PER_OWNER:
            return False
        await ws.accept()
        self._connections[owner].append(ws)
        return True

    def disconnect(self, owner: str, ws: WebSocket) -> None:
        conns = self._connections.get(owner, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(owner, None)

    @property
    def active_connections(self) -> int:
        return sum(len(v) for v in self._connections.values())

    def connected_owners(self) -> set[str]:
        return set(self._connections.keys())

    # ── On-Connect: send recent events + stats ──────────

    async def send_initial_state(self, owner: str, ws: WebSocket) -> None:
        """Send last N events from Redis buffer + current stats on connect."""
        # Recent events
        recent = await self._get_recent_events(owner, REPLAY_ON_CONNECT)
        if recent:
            await ws.send_json({
                "type": "replay_response",
                "data": {
                    "events": recent,
                    "count": len(recent),
                    "reason": "initial_connect",
                },
            })

        # Current stats
        try:
            stats = await self._build_stats(owner)
            self._event_counter += 1
            await ws.send_json({
                "event_id": self._event_counter,
                "type": "stats_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": stats,
            })
        except Exception:
            pass  # Stats failure non-blocking

    # ── Broadcast ───────────────────────────────────────

    async def broadcast(
        self,
        owner: str,
        event_type: str,
        data: dict,
    ) -> None:
        """Invia evento a tutti i client dell'owner e salva in Redis buffer."""
        self._event_counter += 1
        event = {
            "event_id": self._event_counter,
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        # Salva in Redis per replay
        await self._push_event(owner, event)

        # Invia a tutte le connessioni dell'owner
        dead: list[WebSocket] = []
        for ws in self._connections.get(owner, []):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(owner, ws)

    async def broadcast_to_all(self, event_type: str, data: dict) -> None:
        """Broadcast a TUTTI gli owner connessi (es. gas price update globale)."""
        for owner in list(self._connections.keys()):
            await self.broadcast(owner, event_type, data)

    # ── Redis Event Buffer ──────────────────────────────

    async def _push_event(self, owner: str, event: dict) -> None:
        try:
            r = await get_redis()
            key = REDIS_EVENTS_KEY.format(owner=owner)
            await r.lpush(key, json.dumps(event, default=str))
            await r.ltrim(key, 0, EVENT_BUFFER_SIZE - 1)
            await r.expire(key, REDIS_EVENT_TTL)
        except Exception:
            pass  # Redis down — eventi non bufferizzati, non bloccare

    async def _get_recent_events(
        self, owner: str, count: int
    ) -> list[dict]:
        """Get the N most recent events from Redis buffer (oldest first)."""
        try:
            r = await get_redis()
            key = REDIS_EVENTS_KEY.format(owner=owner)
            raw_list = await r.lrange(key, 0, count - 1)
            events = []
            for raw in reversed(raw_list):  # LPUSH → più recente è a indice 0
                events.append(json.loads(raw))
            return events
        except Exception:
            return []

    async def get_missed_events(
        self, owner: str, after_event_id: int
    ) -> list[dict]:
        """Ritorna eventi con event_id > after_event_id (per reconnect)."""
        try:
            r = await get_redis()
            key = REDIS_EVENTS_KEY.format(owner=owner)
            raw_list = await r.lrange(key, 0, EVENT_BUFFER_SIZE - 1)
            events = []
            for raw in reversed(raw_list):  # LPUSH → più recente è a indice 0
                ev = json.loads(raw)
                if ev.get("event_id", 0) > after_event_id:
                    events.append(ev)
            return events
        except Exception:
            return []

    # ── Background: Heartbeat (15s) ─────────────────────

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            ping = {"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()}
            dead_pairs: list[tuple[str, WebSocket]] = []
            for owner, sockets in list(self._connections.items()):
                for ws in sockets:
                    try:
                        await ws.send_json(ping)
                    except Exception:
                        dead_pairs.append((owner, ws))
            for owner, ws in dead_pairs:
                self.disconnect(owner, ws)

    # ── Background: Stats (30s) ─────────────────────────

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            owners = list(self._connections.keys())
            if not owners:
                continue

            for owner in owners:
                if owner not in self._connections:
                    continue
                try:
                    stats = await self._build_stats(owner)
                    await self.broadcast(owner, "stats_update", stats)
                except Exception:
                    pass

    async def _build_stats(self, owner: str) -> dict:
        """Costruisci stats 24h per un owner."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        async with async_session() as db:
            # Rule IDs dell'owner
            rule_ids_q = select(ForwardingRule.id).where(
                ForwardingRule.user_id == owner
            )

            result = await db.execute(
                select(
                    func.count().label("sweep_count_24h"),
                    func.count().filter(
                        SweepLog.status == SweepStatus.completed
                    ).label("completed_24h"),
                    func.coalesce(func.sum(SweepLog.amount_human), 0).label("volume_eth_24h"),
                    func.coalesce(
                        func.sum(
                            case(
                                (SweepLog.amount_usd.isnot(None), SweepLog.amount_usd),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("volume_usd_24h"),
                    func.coalesce(
                        func.sum(
                            case(
                                (SweepLog.gas_cost_eth.isnot(None), SweepLog.gas_cost_eth),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("gas_spent_24h"),
                ).where(
                    SweepLog.rule_id.in_(rule_ids_q),
                    SweepLog.created_at >= cutoff,
                )
            )
            row = result.one()

            # Active rules count
            active_q = await db.execute(
                select(func.count()).select_from(ForwardingRule).where(
                    ForwardingRule.user_id == owner,
                    ForwardingRule.is_active == True,   # noqa: E712
                    ForwardingRule.is_paused == False,   # noqa: E712
                )
            )
            active_rules = active_q.scalar()

        # Gas price corrente via RPC
        gas_gwei = await self._fetch_gas_price()

        return {
            "sweep_count_24h": row.sweep_count_24h,
            "completed_24h": row.completed_24h,
            "volume_eth_24h": round(float(row.volume_eth_24h), 6),
            "volume_usd_24h": round(float(row.volume_usd_24h), 2),
            "gas_spent_eth_24h": round(float(row.gas_spent_24h), 8),
            "current_gas_gwei": gas_gwei,
            "active_rules": active_rules,
            "connected_clients": len(self._connections.get(owner, [])),
        }

    async def _fetch_gas_price(self) -> Optional[float]:
        """Fetch gas price corrente da Base RPC."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://mainnet.base.org",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_gasPrice",
                        "params": [],
                    },
                    timeout=5,
                )
                gas_wei = int(res.json().get("result", "0x0"), 16)
                return round(gas_wei / 1e9, 4)
        except Exception:
            return None

    # ── Background: Redis Pub/Sub Listener ──────────────

    async def _pubsub_loop(self) -> None:
        """Subscribe to sweep_events:* pattern, forward to WS clients."""
        backoff = 1
        while True:
            try:
                r = await get_redis()
                pubsub = r.pubsub()
                await pubsub.psubscribe(f"{PUBSUB_CHANNEL_PREFIX}:*")
                logger.info("Pub/Sub listener subscribed to %s:*", PUBSUB_CHANNEL_PREFIX)
                backoff = 1  # reset on successful connect

                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue

                    channel = message["channel"]
                    # channel = "sweep_events:0xabc..."
                    owner = channel.split(":", 1)[1] if ":" in channel else None
                    if not owner:
                        continue

                    # Only forward if owner has connected clients
                    if owner not in self._connections:
                        continue

                    try:
                        payload = json.loads(message["data"])
                        event_type = payload.get("type", "unknown")
                        data = payload.get("data", {})
                        await self.broadcast(owner, event_type, data)
                    except (json.JSONDecodeError, TypeError):
                        logger.debug("Invalid Pub/Sub message on %s", channel)

            except asyncio.CancelledError:
                # Graceful shutdown
                try:
                    await pubsub.punsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
                raise
            except Exception:
                logger.warning(
                    "Pub/Sub listener error, reconnecting in %ds",
                    backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # ── Background: Circuit Breaker Monitor ─────────────

    async def _circuit_breaker_monitor(self) -> None:
        """Check circuit breaker states every 10s, broadcast changes."""
        while True:
            await asyncio.sleep(10)
            if not self._connections:
                continue

            try:
                from app.services.circuit_breaker import get_all_circuit_breakers

                for name, cb in get_all_circuit_breakers().items():
                    current = cb.state.value
                    previous = self._cb_states.get(name)

                    if previous is not None and current != previous:
                        logger.info(
                            "Circuit breaker '%s' changed: %s -> %s",
                            name, previous, current,
                        )
                        await self.broadcast_to_all(
                            "circuit_breaker_change",
                            {
                                "breaker": name,
                                "from_state": previous,
                                "to_state": current,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )

                    self._cb_states[name] = current

            except Exception:
                pass

    # ── Background: Spending Warning Monitor ────────────

    async def _spending_monitor(self) -> None:
        """Check spending levels every 60s, warn owners approaching limits."""
        while True:
            await asyncio.sleep(60)
            owners = list(self._connections.keys())
            if not owners:
                continue

            try:
                from app.services.spending_policy import SpendingPolicy

                policy = SpendingPolicy()

                for owner in owners:
                    if owner not in self._connections:
                        continue

                    try:
                        # Get rules to determine chain_id
                        chain_ids = await self._get_owner_chain_ids(owner)

                        for chain_id in chain_ids:
                            status = await policy.get_status(owner, chain_id)

                            warnings = []
                            hour_spent = int(status.per_hour_spent_wei)
                            hour_limit = int(status.per_hour_limit_wei)
                            if hour_limit > 0 and hour_spent / hour_limit >= SPENDING_WARNING_THRESHOLD:
                                warnings.append({
                                    "tier": "per_hour",
                                    "spent_wei": status.per_hour_spent_wei,
                                    "limit_wei": status.per_hour_limit_wei,
                                    "percent": round(hour_spent / hour_limit * 100, 1),
                                })

                            day_spent = int(status.per_day_spent_wei)
                            day_limit = int(status.per_day_limit_wei)
                            if day_limit > 0 and day_spent / day_limit >= SPENDING_WARNING_THRESHOLD:
                                warnings.append({
                                    "tier": "per_day",
                                    "spent_wei": status.per_day_spent_wei,
                                    "limit_wei": status.per_day_limit_wei,
                                    "percent": round(day_spent / day_limit * 100, 1),
                                })

                            global_spent = int(status.global_daily_spent_wei)
                            global_limit = int(status.global_daily_limit_wei)
                            if global_limit > 0 and global_spent / global_limit >= SPENDING_WARNING_THRESHOLD:
                                warnings.append({
                                    "tier": "global_daily",
                                    "spent_wei": status.global_daily_spent_wei,
                                    "limit_wei": status.global_daily_limit_wei,
                                    "percent": round(global_spent / global_limit * 100, 1),
                                })

                            vel_ratio = status.sweeps_this_hour / status.max_sweeps_per_hour if status.max_sweeps_per_hour > 0 else 0
                            if vel_ratio >= SPENDING_WARNING_THRESHOLD:
                                warnings.append({
                                    "tier": "velocity",
                                    "sweeps_this_hour": status.sweeps_this_hour,
                                    "max_sweeps_per_hour": status.max_sweeps_per_hour,
                                    "percent": round(vel_ratio * 100, 1),
                                })

                            if warnings:
                                await self.broadcast(
                                    owner,
                                    "spending_warning",
                                    {
                                        "chain_id": chain_id,
                                        "warnings": warnings,
                                    },
                                )

                    except Exception:
                        pass

            except Exception:
                pass

    async def _get_owner_chain_ids(self, owner: str) -> list[int]:
        """Get distinct chain_ids from owner's active rules."""
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(ForwardingRule.chain_id).distinct().where(
                        ForwardingRule.user_id == owner,
                        ForwardingRule.is_active == True,  # noqa: E712
                    )
                )
                return [row[0] for row in result.all() if row[0] is not None]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════

feed_manager = SweepFeedManager()


# ═══════════════════════════════════════════════════════════
#  WebSocket Endpoint
# ═══════════════════════════════════════════════════════════

@ws_router.websocket("/ws/sweep-feed/{owner_address}")
async def sweep_feed(websocket: WebSocket, owner_address: str):
    owner = owner_address.lower()

    # Valida indirizzo
    if not ETH_ADDR_RE.match(owner_address):
        await websocket.close(code=4001, reason="invalid_address")
        return

    # ── Authorization (M4): single-use ticket proving ownership ──
    # Browser WS can't send auth headers, so the client mints a ticket via the
    # wallet-authed POST /api/v1/forwarding/sweep-ticket and passes ?ticket=.
    # The ticket is single-use, 30s TTL, and bound to the verified owner.
    ticket = websocket.query_params.get("ticket")
    ticket_owner = await consume_sweep_ticket(ticket)
    if ticket_owner is None or ticket_owner != owner:
        await websocket.close(code=4003, reason="unauthorized")
        return

    # Limite connessioni
    if not await feed_manager.connect(owner, websocket):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "data": {"message": f"Max {MAX_CONNS_PER_OWNER} connections per address"},
        })
        await websocket.close(code=4002, reason="max_connections")
        return

    # Welcome message
    await websocket.send_json({
        "type": "connected",
        "data": {
            "owner": owner,
            "buffer_size": EVENT_BUFFER_SIZE,
            "heartbeat_interval_sec": 15,
            "stats_interval_sec": 30,
            "message_types": [
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
            ],
        },
    })

    # Send initial state: recent events + current stats
    await feed_manager.send_initial_state(owner, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Invalid JSON"},
                })
                continue

            msg_type = msg.get("type")

            if msg_type == "pong":
                # Heartbeat response — noop
                continue

            elif msg_type == "replay":
                # Client vuole eventi persi dopo riconnessione
                after_id = msg.get("after_event_id", 0)
                if not isinstance(after_id, (int, float)):
                    after_id = 0
                missed = await feed_manager.get_missed_events(owner, int(after_id))
                await websocket.send_json({
                    "type": "replay_response",
                    "data": {
                        "events": missed,
                        "count": len(missed),
                    },
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"},
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        feed_manager.disconnect(owner, websocket)
