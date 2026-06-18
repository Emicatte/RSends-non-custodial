"""
RSend Backend — Payment WebSocket Hub.

Real-time payment status notifications for checkout pages.

Endpoint:
  WS /ws/payment/{intent_id}
    → Client connects while waiting for payment
    → Server pushes events: payment.completed, payment.expired
    → Ping/pong every 30s for keepalive
    → Auto-disconnect after 30 minutes

Connection manager:
  In-memory dict {intent_id: set[WebSocket]}
  Called by transaction_matcher and expire_pending_intents
  to push events to all connected checkout clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

payment_ws_router = APIRouter()

# ═══════════════════════════════════════════════════════════════
#  Connection Manager
# ═══════════════════════════════════════════════════════════════

MAX_CONNS_PER_INTENT = 10
MAX_CONNECTION_DURATION = 30 * 60  # 30 minutes
HEARTBEAT_INTERVAL = 30  # seconds


class PaymentConnectionManager:
    """Manages WebSocket connections per payment intent."""

    def __init__(self) -> None:
        # intent_id → set of (websocket, connected_at)
        self._connections: dict[str, set[tuple[WebSocket, float]]] = defaultdict(set)
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    async def connect(self, intent_id: str, ws: WebSocket) -> bool:
        """Accept and register a WebSocket connection. Returns False if limit exceeded."""
        if len(self._connections[intent_id]) >= MAX_CONNS_PER_INTENT:
            return False

        await ws.accept()
        self._connections[intent_id].add((ws, time.time()))
        logger.info(
            "Payment WS connected: intent=%s (total=%d for this intent)",
            intent_id, len(self._connections[intent_id]),
        )
        return True

    def disconnect(self, intent_id: str, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        conns = self._connections.get(intent_id)
        if not conns:
            return
        to_remove = {entry for entry in conns if entry[0] is ws}
        conns -= to_remove
        if not conns:
            del self._connections[intent_id]
        logger.debug("Payment WS disconnected: intent=%s", intent_id)

    async def broadcast(self, intent_id: str, event: dict[str, Any]) -> int:
        """
        Send an event to all clients watching this intent_id.
        Returns the number of clients notified.
        """
        conns = self._connections.get(intent_id)
        if not conns:
            return 0

        message = json.dumps(event, default=str)
        sent = 0
        dead: list[tuple[WebSocket, float]] = []

        for entry in list(conns):
            ws, _ = entry
            try:
                await ws.send_text(message)
                sent += 1
            except Exception:
                dead.append(entry)

        for entry in dead:
            conns.discard(entry)
        if not conns:
            self._connections.pop(intent_id, None)

        if sent > 0:
            logger.info(
                "Payment WS broadcast: intent=%s event=%s sent_to=%d",
                intent_id, event.get("event"), sent,
            )
        return sent

    def start_heartbeat(self) -> None:
        """Start the background heartbeat loop."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def shutdown(self) -> None:
        """Cancel heartbeat and close all connections."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        for intent_id, conns in list(self._connections.items()):
            for ws, _ in list(conns):
                try:
                    await ws.close(code=1001, reason="server_shutdown")
                except Exception:
                    pass
            conns.clear()
        self._connections.clear()
        logger.info("Payment WS manager shut down")

    async def _heartbeat_loop(self) -> None:
        """Ping all connections every 30s, evict stale/expired ones."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.time()

                for intent_id in list(self._connections.keys()):
                    conns = self._connections.get(intent_id)
                    if not conns:
                        continue

                    dead: list[tuple[WebSocket, float]] = []
                    for entry in list(conns):
                        ws, connected_at = entry

                        # Auto-disconnect after MAX_CONNECTION_DURATION
                        if now - connected_at > MAX_CONNECTION_DURATION:
                            try:
                                await ws.send_json({
                                    "event": "timeout",
                                    "message": "Connection expired after 30 minutes",
                                })
                                await ws.close(code=1000, reason="max_duration")
                            except Exception:
                                pass
                            dead.append(entry)
                            continue

                        # Ping
                        try:
                            await ws.send_json({"event": "ping"})
                        except Exception:
                            dead.append(entry)

                    for entry in dead:
                        conns.discard(entry)
                    if not conns:
                        self._connections.pop(intent_id, None)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Payment WS heartbeat error")


# Singleton
payment_manager = PaymentConnectionManager()


# ═══════════════════════════════════════════════════════════════
#  Public API — called by transaction_matcher / expire task
# ═══════════════════════════════════════════════════════════════

async def notify_payment_completed(intent_id: str, tx_hash: str) -> int:
    """Notify all checkout clients that payment was received."""
    return await payment_manager.broadcast(intent_id, {
        "event": "payment.completed",
        "tx_hash": tx_hash,
    })


async def notify_payment_expired(intent_id: str) -> int:
    """Notify all checkout clients that the intent expired."""
    return await payment_manager.broadcast(intent_id, {
        "event": "payment.expired",
    })


# ═══════════════════════════════════════════════════════════════
#  WebSocket Endpoint
# ═══════════════════════════════════════════════════════════════

@payment_ws_router.websocket("/ws/payment/{intent_id}")
async def payment_feed(websocket: WebSocket, intent_id: str):
    """
    WebSocket endpoint for checkout pages to receive real-time payment updates.

    Events sent to client:
      {"event": "connected", "intent_id": "..."}
      {"event": "payment.completed", "tx_hash": "0x..."}
      {"event": "payment.expired"}
      {"event": "ping"}       — client should reply {"type": "pong"}
      {"event": "timeout"}    — connection closing after 30 min
    """
    # Validate intent_id format (UUID-like)
    if not intent_id or len(intent_id) > 128:
        await websocket.close(code=4001, reason="invalid_intent_id")
        return

    if not await payment_manager.connect(intent_id, websocket):
        await websocket.accept()
        await websocket.send_json({
            "event": "error",
            "message": f"Max {MAX_CONNS_PER_INTENT} connections per payment",
        })
        await websocket.close(code=4002, reason="max_connections")
        return

    # Welcome message
    await websocket.send_json({
        "event": "connected",
        "intent_id": intent_id,
        "heartbeat_interval_sec": HEARTBEAT_INTERVAL,
        "max_duration_sec": MAX_CONNECTION_DURATION,
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "pong":
                # Heartbeat response — noop
                continue
            # Ignore unknown messages silently

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        payment_manager.disconnect(intent_id, websocket)
