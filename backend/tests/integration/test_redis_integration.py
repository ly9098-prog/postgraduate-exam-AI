"""Redis integration tests — requires ``--run-integration``.

Verifies Redis connectivity and cache operations used by the app.
Creates Redis client inline per test to avoid pytest-asyncio 1.3.0
"attached to a different loop" error with conftest fixtures.
"""

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/1")


@pytest.fixture
def redis_url():
    """Return the test Redis URL. Tests create their own client."""
    return TEST_REDIS_URL


class TestRedisConnectivity:
    """Basic Redis connectivity and CRUD."""

    @pytest.mark.asyncio
    async def test_ping(self, redis_url):
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()

    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_url):
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.set("test_key", "hello_redis")
        value = await r.get("test_key")
        assert value == "hello_redis"
        await r.delete("test_key")
        await r.aclose()

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, redis_url):
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.set("ttl_key", "expires", ex=60)
        ttl = await r.ttl("ttl_key")
        assert 0 < ttl <= 60
        await r.delete("ttl_key")
        await r.aclose()

    @pytest.mark.asyncio
    async def test_delete(self, redis_url):
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.set("del_key", "will_be_deleted")
        await r.delete("del_key")
        value = await r.get("del_key")
        assert value is None
        await r.aclose()

    @pytest.mark.asyncio
    async def test_key_pattern_scan(self, redis_url):
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.set("scan:a:1", "v1")
        await r.set("scan:a:2", "v2")
        await r.set("scan:b:1", "v3")
        cursor = 0
        keys = []
        while True:
            cursor, batch = await r.scan(cursor=cursor, match="scan:a:*")
            keys.extend(batch)
            if cursor == 0:
                break
        assert "scan:a:1" in keys
        assert "scan:a:2" in keys
        assert "scan:b:1" not in keys
        # Cleanup
        await r.delete("scan:a:1", "scan:a:2", "scan:b:1")
        await r.aclose()


class TestCacheClientIntegration:
    """Test the app's CacheClient against real Redis."""

    @pytest.mark.asyncio
    async def test_cache_get_set(self, redis_url):
        """CacheClient.set → CacheClient.get round-trip."""
        from app.core.cache import CacheClient

        cache = CacheClient()
        test_key = f"integration_test:cache_get_set"

        await cache.set(test_key, {"msg": "cached_value"}, ttl=30)
        result = await cache.get(test_key)
        assert result is not None
        assert result["msg"] == "cached_value"

        await cache.delete(test_key)
        gone = await cache.get(test_key)
        assert gone is None

    @pytest.mark.asyncio
    async def test_cache_lock_acquire_release(self, redis_url):
        """CacheClient.acquire_lock → release_lock."""
        from app.core.cache import CacheClient

        cache = CacheClient()
        lock_key = f"integration_lock:test_redis"
        lock_value = "test_value_123"

        acquired = await cache.acquire_lock(lock_key, lock_value, ttl=10)
        assert acquired is True

        # Second acquire should fail (already locked)
        re_acquired = await cache.acquire_lock(lock_key, "other_value", ttl=10)
        assert re_acquired is False

        released = await cache.release_lock(lock_key, lock_value)
        assert released is None

        # After release, can acquire again
        re_acquired2 = await cache.acquire_lock(lock_key, lock_value, ttl=10)
        assert re_acquired2 is True
        await cache.release_lock(lock_key, lock_value)
