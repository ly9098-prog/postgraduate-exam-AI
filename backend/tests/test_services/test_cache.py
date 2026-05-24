"""Stage 14 缓存 — 单元测试。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.cache import CacheClient, cached, make_cache_key


class TestCacheClient:
    @pytest.mark.asyncio
    async def test_cache_disabled_without_redis_url(self):
        """Redis URL 为空时缓存禁用。"""
        with patch("app.core.cache.settings") as mock_settings:
            mock_settings.REDIS_URL = ""
            client = CacheClient()
            assert client._enabled is False
            result = await client.get("test_key")
            assert result is None
            await client.set("test_key", "value")
            stats = client.get_stats()
            assert stats["enabled"] is False

    @pytest.mark.asyncio
    async def test_cache_get_set(self):
        """基本读写测试。"""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379"
                client = CacheClient()
                # get (miss)
                result = await client.get("key1")
                assert result is None
                assert client._stats["misses"] == 1

                # set
                await client.set("key1", {"data": 123}, ttl=300)
                mock_redis.set.assert_called_once()

                # get (hit)
                import json

                mock_redis.get.return_value = json.dumps({"data": 123})
                result = await client.get("key1")
                assert result == {"data": 123}
                assert client._stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_cache_ttl(self):
        """TTL 参数传递正确。"""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379"
                client = CacheClient()
                await client.set("key", "val", ttl=600)
                call_args = mock_redis.set.call_args
                assert call_args[1]["ex"] == 600

    @pytest.mark.asyncio
    async def test_cache_stats(self):
        """命中统计正确。"""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379"
                client = CacheClient()
                await client.get("k1")  # miss
                await client.get("k2")  # miss
                stats = client.get_stats()
                assert stats["misses"] == 2
                assert stats["hits"] == 0
                assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_redis_unavailable_graceful(self):
        """Redis 连接失败时静默降级。"""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.side_effect = OSError("Connection refused")
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://bad-host:6379"
                client = CacheClient()
                result = await client.get("key")
                assert result is None
                await client.set("key", "val")
                stats = client.get_stats()
                assert stats["enabled"] is False

    @pytest.mark.asyncio
    async def test_cache_delete_pattern(self):
        """按模式删除缓存。"""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.keys.return_value = [b"test:1", b"test:2"]
        mock_redis.delete.return_value = 2

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379"
                client = CacheClient()
                deleted = await client.delete("test:*")
                assert deleted == 2
                mock_redis.keys.assert_called_once_with("test:*")

    @pytest.mark.asyncio
    async def test_cache_clear(self):
        """清空所有缓存。"""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379"
                client = CacheClient()
                await client.clear()
                mock_redis.flushdb.assert_called_once()


def test_make_cache_key_deterministic():
    """相同参数生成相同 key。"""
    k1 = make_cache_key("test", 1, 2, name="x")
    k2 = make_cache_key("test", 1, 2, name="x")
    assert k1 == k2


def test_make_cache_key_different():
    """不同参数生成不同 key。"""
    k1 = make_cache_key("test", 1, 2, name="x")
    k2 = make_cache_key("test", 1, 3, name="x")
    assert k1 != k2


@pytest.mark.asyncio
async def test_cached_decorator():
    """缓存装饰器生效。"""
    from app.core.cache import cache as _global_cache

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.ping = AsyncMock()

    call_count = 0

    @cached(ttl=60, key_prefix="test")
    async def my_func(x: int) -> dict:
        nonlocal call_count
        call_count += 1
        return {"value": x * 2}

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        with patch("app.core.cache.settings") as mock_settings:
            mock_settings.REDIS_URL = "redis://localhost:6379"
            # Reset global cache state to pick up patched redis
            _global_cache._client = None
            _global_cache._enabled = True

            # First call — should execute
            result = await my_func(5)
            assert result == {"value": 10}
            assert call_count == 1

            # Second call — should hit cache
            import json
            mock_redis.get.return_value = json.dumps({"value": 10})
            result = await my_func(5)
            assert result == {"value": 10}
            assert call_count == 1  # Not incremented
