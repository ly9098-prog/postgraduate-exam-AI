"""WebSocket push service for export task status updates.

Architecture:
- Each user connects via WebSocket with JWT auth.
- The WebSocket handler registers the connection in a user-indexed dict.
- On task status change, the processor publishes to Redis Pub/Sub.
- A **single per-instance** Redis subscriber listens for all users and
  forwards events to the relevant local connections.
- When Redis is unavailable, the miniprogram falls back to polling.

This design avoids the N×N fanout problem: each instance has exactly one
Redis subscriber task (not one per connection), and each message is
forwarded to the correct user's local connections once.

Events are ephemeral — the database remains the source of truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
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

# Max message payload size (bytes)
_MAX_MESSAGE_BYTES = 65_536

# Redis channel prefix
_CHANNEL_PREFIX = "export:task:events:"

# ═══════════════════════════════════════════════════
# Per-instance unified Redis subscriber
# ═══════════════════════════════════════════════════

_redis_subscriber_task: asyncio.Task | None = None
_redis_subscriber_stop = asyncio.Event()


async def _subscribe_all():
    """Single per-instance Redis subscriber for all export events.

    Listens on the export event channel and dispatches each message
    to the correct user's local connections via ``send_to_user``.
    This avoids the N×N fanout problem.
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled:
            logger.debug("Redis not available — skipping per-instance subscriber")
            return

        client = await cache._ensure_client()
        if client is None:
            return

        async with client.pubsub() as pubsub:
            # Subscribe to all export events via a single channel
            channel = f"{_CHANNEL_PREFIX}*"
            await pubsub.psubscribe(channel)

            logger.info("Per-instance Redis subscriber started")

            while not _redis_subscriber_stop.is_set():
                try:
                    msg = await pubsub.get_message(timeout=1.0)
                    if msg and msg["type"] == "pmessage":
                        try:
                            payload = json.loads(msg["data"])
                            _task_id = payload.get("task_id")
                            # Forward to local connections once
                            # The payload already contains user_id from build_status_event
                            user_id = payload.get("user_id")
                            if user_id:
                                await send_to_user(user_id, payload)
                        except (json.JSONDecodeError, KeyError):
                            logger.warning("Invalid Redis pmessage payload")
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(1)

    except Exception:
        logger.debug("Redis subscriber unavailable (polling fallback)")


def start_redis_subscriber():
    """Start the per-instance Redis subscriber if not already running."""
    global _redis_subscriber_task
    if _redis_subscriber_task is None or _redis_subscriber_task.done():
        _redis_subscriber_stop.clear()
        _redis_subscriber_task = asyncio.create_task(_subscribe_all())
        logger.debug("Per-instance Redis subscriber started")


def stop_redis_subscriber():
    """Stop the per-instance Redis subscriber."""
    global _redis_subscriber_task
    if _redis_subscriber_task and not _redis_subscriber_task.done():
        _redis_subscriber_stop.set()
        _redis_subscriber_task.cancel()
        _redis_subscriber_task = None
        logger.debug("Per-instance Redis subscriber stopped")


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

    # Ensure the per-instance subscriber is running
    start_redis_subscriber()
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

    if len(payload) > _MAX_MESSAGE_BYTES:
        logger.warning("WS payload too large (%d bytes) for user %d", len(payload), user_id)
        event = {"type": "export_status", "task_id": event.get("task_id"), "status": event.get("status")}
        payload = json.dumps(event, ensure_ascii=False, default=str)

    for ws in _connections[user_id]:
        try:
            await ws.send_text(payload)
            delivered += 1
        except Exception:
            stale.add(ws)

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

    Includes ``user_id`` for per-instance Redis routing.

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
        "version": task.get("version", 0),
        "downloadable": task.get("status") == "completed",
        "user_id": task.get("user_id"),
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

        if not cache.is_enabled:
            return

        client = await cache._ensure_client()
        if client is None:
            return

        channel = f"{_CHANNEL_PREFIX}{user_id}"
        payload = json.dumps(event, ensure_ascii=False, default=str)
        await client.publish(channel, payload)
    except Exception:
        logger.debug("Redis publish failed (non-fatal)")


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
    2. Send heartbeat probe to detect stale connections.
    3. On disconnect: unregister and clean up.

    Note: Redis events are handled by the per-instance ``_subscribe_all``
    subscriber, not per-connection. This avoids N×N fanout.
    """
    await ws.accept()

    accepted = await register(user_id, ws)
    if not accepted:
        await ws.send_json({"type": "error", "message": "连接数过多"})
        await ws.close()
        return

    try:
        # Heartbeat loop — respond to PING from client
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=_HEARTBEAT_INTERVAL + 5)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except TimeoutError:
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
        unregister(user_id, ws)
