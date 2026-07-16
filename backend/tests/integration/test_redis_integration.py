"""Redis integration tests — requires ``--run-integration``.

Verifies Redis connectivity and cache operations used by the app.
"""

import pytest


pytestmark = pytest.mark.integration


class TestRedisConnectivity:
    """Basic Redis connectivity and CRUD."""

    @pytest.mark.asyncio
    async def test_ping(self, redis_session):
        await redis_session.ping()

    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_session):
        await redis_session.set("test_key", "hello_redis")
        value = await redis_session.get("test_key")
        assert value == "hello_redis"

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, redis_session):
        await redis_session.set("ttl_key", "expires", ex=60)
        ttl = await redis_session.ttl("ttl_key")
        assert 0 < ttl <= 60

    @pytest.mark.asyncio
    async def test_delete(self, redis_session):
        await redis_session.set("del_key", "will_be_deleted")
        await redis_session.delete("del_key")
        value = await redis_session.get("del_key")
        assert value is None

    @pytest.mark.asyncio
    async def test_key_pattern_scan(self, redis_session):
        await redis_session.set("scan:a:1", "v1")
        await redis_session.set("scan:a:2", "v2")
        await redis_session.set("scan:b:1", "v3")
        cursor = 0
        keys = []
        while True:
            cursor, batch = await redis_session.scan(cursor=cursor, match="scan:a:*")
            keys.extend(batch)
            if cursor == 0:
                break
        assert "scan:a:1" in keys
        assert "scan:a:2" in keys
        assert "scan:b:1" not in keys


class TestCacheClientIntegration:
    """Test the app's CacheClient against real Redis."""

    @pytest.mark.asyncio
    async def test_cache_get_set(self, redis_session):
        """CacheClient.set → CacheClient.get round-trip."""
        from app.core.cache import CacheClient

        cache = CacheClient()
        test_key = f"integration_test:{__name__}"

        # Force client to use real Redis
        await cache.set(test_key, {"msg": "cached_value"}, ttl=30)
        result = await cache.get(test_key)
        assert result is not None
        assert result["msg"] == "cached_value"

        await cache.delete(test_key)
        gone = await cache.get(test_key)
        assert gone is None

    @pytest.mark.asyncio
    async def test_cache_lock_acquire_release(self, redis_session):
        """CacheClient.acquire_lock → release_lock."""
        from app.core.cache import CacheClient

        cache = CacheClient()
        lock_key = f"integration_lock:{__name__}"

        acquired = await cache.acquire_lock(lock_key, ttl=10)
        assert acquired is True

        # Second acquire should fail (already locked)
        re_acquired = await cache.acquire_lock(lock_key, ttl=10)
        assert re_acquired is False

        released = await cache.release_lock(lock_key)
        assert released is True

        # After release, can acquire again
        re_acquired2 = await cache.acquire_lock(lock_key, ttl=10)
        assert re_acquired2 is True
        await cache.release_lock(lock_key)
