"""Redis Pub/Sub helper for SSE event streaming.

Replaces polling-based batch image progress tracking with Redis Pub/Sub.
Falls back to polling when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

logger = logging.getLogger("postgraduate-ai.pubsub")

_CHANNEL_PREFIX = "sse:job:"


async def publish_event(job_id: int, event_type: str, data: dict) -> None:
    """Publish an event to the job's Redis channel.

    Uses the shared cache client to avoid creating a new connection per event.
    Falls back to logging when Redis is unavailable (non-fatal).
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled():
            return

        client = await cache._ensure_client()
        if client is None:
            return

        channel = f"{_CHANNEL_PREFIX}{job_id}"
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
        await client.publish(channel, payload)
    except Exception:
        pass  # Pub/Sub is best-effort


async def subscribe_job(
    job_id: int,
    on_event: Callable,
    on_done: Callable,
    poll_fn: Callable | None = None,
    poll_interval: float = 2.0,
    timeout: float = 3600,
) -> None:
    """Subscribe to a job's Redis channel, or poll as fallback.

    Uses the shared cache client to avoid creating a new connection.

    Args:
        job_id: The job to subscribe to.
        on_event: Called with (event_type, data) for each event.
        on_done: Called when a terminal event is received.
        poll_fn: Fallback polling function (async, returns events list).
        poll_interval: Seconds between polls when using fallback.
        timeout: Max subscription duration in seconds.
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled():
            raise ConnectionError("No Redis configured")

        client = await cache._ensure_client()
        if client is None:
            raise ConnectionError("Redis client unavailable")

        async with client.pubsub() as pubsub:
            channel = f"{_CHANNEL_PREFIX}{job_id}"
            await pubsub.subscribe(channel)

            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await pubsub.get_message(
                        timeout=poll_interval if poll_fn else 1.0,
                    )
                    if msg and msg["type"] == "message":
                        try:
                            payload = json.loads(msg["data"])
                            event_type = payload.get("type", "trace")
                            event_data = payload.get("data", {})
                            await on_event(event_type, event_data)
                            if event_type == "done":
                                await on_done()
                                return
                        except json.JSONDecodeError:
                            logger.warning("Invalid PubSub message for job %d", job_id)

                    # When no message and poll_fn available, use fallback
                    if poll_fn and msg is None:
                        events = await poll_fn()
                        if events:
                            for ev in events:
                                await on_event(ev.get("type", "trace"), ev.get("data", {}))
                                if ev.get("type") == "done":
                                    await on_done()
                                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("PubSub error for job %d, falling back to poll", job_id)
                    break

            await pubsub.unsubscribe(channel)

    except Exception:
        logger.info("PubSub unavailable for job %d, using polling fallback", job_id)

    # Fallback: call poll_fn periodically with exponential backoff
    if poll_fn is not None:
        deadline = asyncio.get_event_loop().time() + timeout
        backoff = poll_interval
        max_backoff = min(30.0, poll_interval * 16)
        while asyncio.get_event_loop().time() < deadline:
            try:
                events = await poll_fn()
                if events:
                    # Reset backoff on successful poll with data
                    backoff = poll_interval
                    for ev in events:
                        await on_event(ev.get("type", "trace"), ev.get("data", {}))
                        if ev.get("type") == "done":
                            await on_done()
                            return
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Poll fallback error for job %d", job_id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
