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


async def check_health() -> bool:
    """Health check for SSE Pub/Sub infrastructure.

    Uses Redis PING only — no DB queries. Returns True if Redis is reachable
    and Pub/Sub can operate, False otherwise. This is the minimal connectivity
    check needed for SSE to work.
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled:
            return False

        client = await cache._ensure_client()
        if client is None:
            return False

        await client.ping()
        return True
    except Exception:
        return False


async def publish_event(job_id: str | int, event_type: str, data: dict) -> None:
    """Publish an event to the job's Redis channel.

    Uses the shared cache client to avoid creating a new connection per event.
    Falls back to logging when Redis is unavailable (non-fatal).
    """
    try:
        from app.core.cache import cache

        if not cache.is_enabled:
            return

        client = await cache._ensure_client()
        if client is None:
            return

        channel = f"{_CHANNEL_PREFIX}{job_id}"
        payload = json.dumps(
            {"type": event_type, "data": data}, ensure_ascii=False, default=str
        )
        await client.publish(channel, payload)
    except Exception:
        logger.debug(
            "Pub/Sub publish_event failed for job %s: best-effort, skipping", job_id
        )


async def subscribe_job(
    job_id: str | int,
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

        if not cache.is_enabled:
            raise ConnectionError("No Redis configured")

        client = await cache._ensure_client()
        if client is None:
            raise ConnectionError("Redis client unavailable")

        async with client.pubsub() as pubsub:
            channel = f"{_CHANNEL_PREFIX}{job_id}"
            await pubsub.subscribe(channel)

            deadline = asyncio.get_event_loop().time() + timeout
            # Exponential backoff for get_message timeout.
            # NO DB polling while Pub/Sub is available — DB fallback only after PubSub breaks.
            get_msg_timeout = 1.0  # initial get_message timeout
            max_get_msg_timeout = 5.0  # cap
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await pubsub.get_message(timeout=get_msg_timeout)
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
                            logger.warning("Invalid PubSub message for job %s", job_id)
                        get_msg_timeout = 0.05  # reset after message
                    else:
                        get_msg_timeout = min(
                            get_msg_timeout * 1.5, max_get_msg_timeout
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "PubSub error for job %s, falling back to poll", job_id
                    )
                    break

            await pubsub.unsubscribe(channel)

    except Exception:
        logger.info("PubSub unavailable for job %s, using polling fallback", job_id)

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
                logger.warning("Poll fallback error for job %s", job_id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
