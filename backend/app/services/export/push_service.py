"""WebSocket push service for export task status updates.

Architecture:
- Each user connects via WebSocket with JWT auth.
- The WebSocket handler registers the connection in a user-indexed dict.
- On task status change, the processor publishes to Redis Pub/Sub.
- All WebSocket instances subscribe to the Redis channel and forward
  events to the relevant user's connections.
- When Redis is unavailable, the miniprogram falls back to polling.

This enables real-time task status updates in single- and multi-instance
deployments. Events are ephemeral — the database remains the source of truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("postgraduate-ai.export-push")

# ── Connection registry ──
# Maps user_id -> set of WebSocket connections
_connections: dict[int, set[WebSocket]] = {}

# Per-user connection limit
_MAX_CONNECTIONS_PER_USER = 5

# Heartbeat interval (seconds)
_HEARTBEAT_INTERVAL = 25

# Redis channel prefix
_CHANNEL_PREFIX = "export:task:events:"


# ═══════════════════════════════════════════════════
# Connection management
# ═══════════════════════════════════════════════════


async def register(user_id: int, ws: WebSocket) -> bool:
    """Register a WebSocket connection for a user.

    Enforces per-user connection limits. Returns True if accepted.
    """
    if user_id not in _connections:
        _connections[user_id] = set()

    if len(_connections[user_id]) >= _MAX_CONNECTIONS_PER_USER:
        logger.warning("Connection limit reached for user %d", user_id)
        return False

    _connections[user_id].add(ws)
    logger.debug("WebSocket registered for user %d (total: %d)", user_id, len(_connections[user_id]))
    return True


def unregister(user_id: int, ws: WebSocket) -> None:
    """Remove a WebSocket connection."""
    if user_id in _connections:
        _connections[user_id].discard(ws)
        if not _connections[user_id]:
            del _connections[user_id]
    logger.debug("WebSocket unregistered for user %d", user_id)


async def send_to_user(user_id: int, event: dict) -> int:
    """Send an event to all connections of a user.

    Returns the number of successfully delivered connections.
    Cleans up stale connections.
    """
    if user_id not in _connections:
        return 0

    stale: set[WebSocket] = set()
    delivered = 0
    payload = json.dumps(event, ensure_ascii=False, default=str)

    for ws in _connections[user_id]:
        try:
            await ws.send_text(payload)
            delivered += 1
        except Exception:
            stale.add(ws)

    # Clean up stale connections
    if stale:
        _connections[user_id] -= stale
        if not _connections[user_id]:
            del _connections[user_id]

    return delivered


async def send_to_all(event: dict) -> int:
    """Send an event to all connected users. Returns delivered count."""
    total = 0
    for user_id in list(_connections.keys()):
        total += await send_to_user(user_id, event)
    return total


def get_active_connections() -> int:
    """Return total active WebSocket connections across all users."""
    return sum(len(conns) for conns in _connections.values())


# ═══════════════════════════════════════════════════
# Event building
# ═══════════════════════════════════════════════════


def build_status_event(task: dict) -> dict:
    """Build the status event payload from a task dict.

    The payload excludes sensitive data (JWT, permanent URLs, internal keys).
    """
    return {
        "type": "export_status",
        "task_id": task.get("id"),
        "status": task.get("status"),
        "file_format": task.get("file_format"),
        "success_count": task.get("success_count"),
        "skip_count": task.get("skip_count"),
        "error_message": task.get("error_message"),
        "completed_at": _serialize_dt(task.get("completed_at")),
        "expires_at": _serialize_dt(task.get("expires_at")),
        "updated_at": _serialize_dt(task.get("updated_at")),
        "downloadable": task.get("status") == "completed",
    }


def _serialize_dt(val: Any) -> str | None:
    """Serialize a datetime to ISO string or return None."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ═══════════════════════════════════════════════════
# Redis Pub/Sub integration
# ═══════════════════════════════════════════════════


async def publish_via_redis(event: dict, user_id: int) -> None:
    """Publish an event to Redis so other instances can forward it.

    This is a best-effort operation. If Redis is unavailable the event
    is still delivered to local connections.
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled():
            return

        client = await cache._ensure_client()
        if client is None:
            return

        channel = f"{_CHANNEL_PREFIX}{user_id}"
        payload = json.dumps(event, ensure_ascii=False, default=str)
        await client.publish(channel, payload)
    except Exception:
        logger.debug("Redis publish failed (non-fatal)")


async def listen_redis_for_user(
    user_id: int,
    on_event: Callable,
    stop_event: asyncio.Event,
) -> None:
    """Listen for Redis Pub/Sub events for a specific user.

    Runs in a background task per connection. Forwarded events are
    delivered to the on_event callback.
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled():
            return

        client = await cache._ensure_client()
        if client is None:
            return

        async with client.pubsub() as pubsub:
            channel = f"{_CHANNEL_PREFIX}{user_id}"
            await pubsub.subscribe(channel)

            while not stop_event.is_set():
                try:
                    msg = await pubsub.get_message(timeout=1.0)
                    if msg and msg["type"] == "message":
                        try:
                            payload = json.loads(msg["data"])
                            await on_event(payload)
                        except json.JSONDecodeError:
                            logger.warning("Invalid Redis message for user %d", user_id)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(1)

            await pubsub.unsubscribe(channel)

    except Exception:
        logger.debug("Redis listener unavailable for user %d (polling fallback)", user_id)


# ═══════════════════════════════════════════════════
# WebSocket handler
# ═══════════════════════════════════════════════════


async def handle_export_ws(ws: WebSocket, user_id: int) -> None:
    """Main WebSocket handler for export status subscriptions.

    Args:
        ws: The FastAPI WebSocket connection.
        user_id: The authenticated user's ID (verified before calling).

    Flow:
    1. Accept the connection and register it.
    2. Start heartbeat + Redis listener in background tasks.
    3. Forward incoming Redis events to the WS.
    4. On disconnect: unregister and clean up.
    """
    await ws.accept()

    accepted = await register(user_id, ws)
    if not accepted:
        await ws.send_json({"type": "error", "message": "连接数过多"})
        await ws.close()
        return

    stop_event = asyncio.Event()
    redis_task = asyncio.create_task(
        listen_redis_for_user(
            user_id,
            lambda ev: send_to_user(user_id, ev),
            stop_event,
        )
    )

    try:
        # Heartbeat loop — respond to PING from client
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=_HEARTBEAT_INTERVAL + 5)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # No message received — send a heartbeat probe
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
            except json.JSONDecodeError:
                pass  # ignore malformed messages

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for user %d", user_id)
    except Exception as e:
        logger.warning("WebSocket error for user %d: %s", user_id, e)
    finally:
        stop_event.set()
        redis_task.cancel()
        try:
            await redis_task
        except asyncio.CancelledError:
            pass
        unregister(user_id, ws)
