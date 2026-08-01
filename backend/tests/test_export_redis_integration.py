"""Integration tests for Redis-based export event publishing.

Requires a running Redis server at localhost:6379.
"""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.asyncio

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _check_redis():
    try:
        import redis.asyncio  # noqa: F401 as aioredis
        return True
    except ImportError:
        return False


def _get_redis():
    """Create a direct Redis connection for test use."""
    from redis.asyncio import from_url
    return from_url(_REDIS_URL, socket_connect_timeout=2, decode_responses=False)


@pytest.mark.skipif(not _check_redis(), reason="redis.asyncio not available")
class TestRedisPublishSubscribe:
    """Real Redis Pub/Sub integration for export events."""

    async def test_publish_and_receive_event(self):
        """Publish an event via Redis Pub/Sub and verify it's received."""
        client = await _get_redis()
        try:
            await client.ping()
            channel = "export:task:events:42"
            event = {"type": "export_status", "task_id": 123, "status": "completed", "user_id": 42}

            async with client.pubsub() as pubsub:
                await pubsub.subscribe(channel)
                await client.publish(channel, json.dumps(event))

                msg = None
                for _ in range(20):
                    msg = await pubsub.get_message(timeout=0.1)
                    if msg and msg["type"] == "message":
                        break

                assert msg is not None
                assert msg["type"] == "message"
                payload = json.loads(msg["data"])
                assert payload["task_id"] == 123
                assert payload["status"] == "completed"
        finally:
            await client.aclose()

    async def test_pattern_subscribe(self):
        """Pattern subscription catches per-user channels."""
        client = await _get_redis()
        try:
            await client.ping()

            async with client.pubsub() as pubsub:
                await pubsub.psubscribe("export:task:events:*")

                for uid in [1, 2, 3]:
                    await client.publish(
                        f"export:task:events:{uid}",
                        json.dumps({"type": "export_status", "task_id": uid, "user_id": uid}),
                    )

                received = set()
                for _ in range(30):
                    msg = await pubsub.get_message(timeout=0.1)
                    if msg and msg["type"] == "pmessage":
                        received.add(json.loads(msg["data"])["user_id"])
                    if len(received) >= 3:
                        break

                assert received == {1, 2, 3}
        finally:
            await client.aclose()

    async def test_only_intended_user(self):
        """Events for user A not received by user B's channel subscription."""
        client = await _get_redis()
        try:
            await client.ping()

            async with client.pubsub() as pubsub:
                await pubsub.subscribe("export:task:events:99")

                await client.publish("export:task:events:99",
                                     json.dumps({"user_id": 99}))
                await client.publish("export:task:events:100",
                                     json.dumps({"user_id": 100}))

                received = []
                for _ in range(15):
                    msg = await pubsub.get_message(timeout=0.1)
                    if msg and msg["type"] == "message":
                        received.append(json.loads(msg["data"]))

                assert len(received) == 1
                assert received[0]["user_id"] == 99
        finally:
            await client.aclose()

    async def test_build_status_event_no_sensitive_data(self):
        """build_status_event excludes JWT, internal keys, permanent URLs."""
        from app.services.export.push_service import build_status_event

        event = build_status_event({
            "id": 1, "user_id": 42, "status": "completed",
            "jwt": "should-not-appear", "file_key": "internal/path/file.pdf",
            "storage_backend": "local", "_internal_flag": True,
        })

        for key in ("jwt", "file_key", "storage_backend", "_internal_flag"):
            assert key not in event
        assert event["task_id"] == 1
        assert event["status"] == "completed"

    async def test_redis_unavailable_fallback(self):
        """publish_via_redis silently fails when Redis is down."""
        from app.services.export.push_service import publish_via_redis

        from app.core.cache import cache
        saved_enabled = cache._enabled
        saved_client = cache._client
        try:
            cache._enabled = True
            cache._client = None
            await publish_via_redis(
                {"type": "export_status", "task_id": 1, "status": "completed"},
                user_id=42,
            )
        except Exception:
            pytest.fail("publish_via_redis should not raise when Redis is unavailable")
        finally:
            cache._enabled = saved_enabled
            cache._client = saved_client
