import hashlib
import json
import logging
import random
from collections.abc import Callable
from functools import wraps
from typing import Any

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.cache")

_COMPARE_AND_DELETE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


class CacheUnavailableError(RuntimeError):
    """Raised when a security-sensitive Redis operation cannot be completed."""


class CacheClient:
    """Redis 缓存客户端封装。

    Redis 不可用时静默降级为进程内缓存，不影响核心功能。
    """

    def __init__(self):
        self._client: Redis | None = None  # noqa: F821
        self._enabled = bool(settings.REDIS_URL)
        self._stats: dict[str, int] = {"hits": 0, "misses": 0}
        # 进程内缓存后备（Redis 不可用时使用）
        self._local: dict[str, tuple[float, Any]] = {}
        self._local_max_size = 512

    # ── 进程内缓存后备 ──

    def _local_get(self, key: str) -> Any | None:
        entry = self._local.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None
        expiry, value = entry
        if expiry is not None and expiry < __import__("time").time():
            self._local.pop(key, None)
            self._stats["misses"] += 1
            return None
        self._stats["hits"] += 1
        return value

    def _local_set(self, key: str, value: Any, ttl: int = 300) -> None:
        if len(self._local) >= self._local_max_size:
            # 简单清理：清空过期条目
            now = __import__("time").time()
            stale = [k for k, (exp, _) in self._local.items() if exp is not None and exp < now]
            for k in stale:
                self._local.pop(k, None)
            # 如果仍然超出容量，放弃缓存此条目
            if len(self._local) >= self._local_max_size:
                return
        expiry = (__import__("time").time() + ttl) if ttl > 0 else None
        self._local[key] = (expiry, value)

    def _local_delete(self, pattern: str) -> int:
        import fnmatch
        removed = 0
        for k in list(self._local.keys()):
            if fnmatch.fnmatch(k, pattern):
                self._local.pop(k, None)
                removed += 1
        return removed

    def _local_clear(self) -> int:
        n = len(self._local)
        self._local.clear()
        return n

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def _ensure_client(self):
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as redis

            self._client = redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=False,
            )
            await self._client.ping()
            logger.info("Redis 连接成功")
        except Exception as e:
            logger.warning("Redis 不可用: %s", e)
            self._client = None
        return self._client

    async def get(self, key: str) -> Any | None:
        if not self._enabled:
            return self._local_get(key)
        try:
            client = await self._ensure_client()
            if client is None:
                return self._local_get(key)
            val = await client.get(key)
            if val:
                self._stats["hits"] += 1
                return json.loads(val)
            self._stats["misses"] += 1
            return None
        except Exception:
            return self._local_get(key)

    async def get_strict(self, key: str) -> Any | None:
        """Get without falling back across processes when Redis is configured."""
        if not self._enabled:
            return self._local_get(key)
        client = await self._ensure_client()
        if client is None:
            raise CacheUnavailableError("Redis unavailable")
        try:
            val = await client.get(key)
            return json.loads(val) if val else None
        except Exception as exc:
            raise CacheUnavailableError("Redis unavailable") from exc

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        if not self._enabled:
            self._local_set(key, value, ttl)
            return
        try:
            client = await self._ensure_client()
            if client is None:
                self._local_set(key, value, ttl)
                return
            await client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            self._local_set(key, value, ttl)

    async def set_strict(self, key: str, value: Any, ttl: int = 300) -> None:
        if not self._enabled:
            self._local_set(key, value, ttl)
            return
        client = await self._ensure_client()
        if client is None:
            raise CacheUnavailableError("Redis unavailable")
        try:
            await client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            raise CacheUnavailableError("Redis unavailable") from exc

    @staticmethod
    def jitter_ttl(base: int = 300, percent: float = 0.1) -> int:
        variance = int(base * percent)
        if variance <= 0:
            return base
        return base + random.randint(-variance, variance)

    async def acquire_lock(self, key: str, value: str, ttl: int = 10) -> bool:
        if not self._enabled:
            # 本地模式：简单的原子化模拟
            now = __import__("time").time()
            entry = self._local.get(key)
            if entry is not None:
                exp, _ = entry
                if exp is None or exp > now:
                    return False
            self._local_set(key, value, ttl)
            return True
        try:
            client = await self._ensure_client()
            if client is None:
                now = __import__("time").time()
                entry = self._local.get(key)
                if entry is not None:
                    exp, _ = entry
                    if exp is None or exp > now:
                        return False
                self._local_set(key, value, ttl)
                return True
            return bool(await client.set(key, value, nx=True, ex=ttl))
        except Exception:
            return False

    async def acquire_lock_strict(self, key: str, value: str, ttl: int = 10) -> bool:
        if not self._enabled:
            return await self.acquire_lock(key, value, ttl)
        client = await self._ensure_client()
        if client is None:
            raise CacheUnavailableError("Redis unavailable")
        try:
            return bool(await client.set(key, value, nx=True, ex=ttl))
        except Exception as exc:
            raise CacheUnavailableError("Redis unavailable") from exc

    async def release_lock(self, key: str, value: str) -> None:
        if not self._enabled:
            entry = self._local.get(key)
            if entry is not None:
                _, stored = entry
                if stored == value:
                    self._local.pop(key, None)
            return
        try:
            client = await self._ensure_client()
            if client is None:
                entry = self._local.get(key)
                if entry is not None:
                    _, stored = entry
                    if stored == value:
                        self._local.pop(key, None)
                return
            # Lua compare-and-delete: atomic, no TOCTOU race
            await client.eval(_COMPARE_AND_DELETE_SCRIPT, 1, key, value)
        except Exception:
            pass

    async def expire(self, key: str, ttl: int) -> bool:
        """Extend TTL for an existing key.

        Does NOT verify ownership — the caller must ensure it is safe
        to extend (e.g. the lock was acquired by this process).
        """
        if not self._enabled:
            return False
        try:
            client = await self._ensure_client()
            if client is None:
                return False
            return bool(await client.expire(key, ttl))
        except Exception:
            return False

    async def increment(self, key: str, *, ttl: int) -> int:
        """Atomically increment a short-lived counter and return its value."""
        if not self._enabled:
            current = self._local_get(key) or 0
            value = int(current) + 1
            self._local_set(key, value, ttl)
            return value
        try:
            client = await self._ensure_client()
            if client is None:
                current = self._local_get(key) or 0
                value = int(current) + 1
                self._local_set(key, value, ttl)
                return value
            value = int(await client.incr(key))
            if value == 1:
                await client.expire(key, ttl)
            return value
        except Exception:
            current = self._local_get(key) or 0
            value = int(current) + 1
            self._local_set(key, value, ttl)
            return value

    async def increment_strict(self, key: str, *, ttl: int) -> int:
        if not self._enabled:
            return await self.increment(key, ttl=ttl)
        client = await self._ensure_client()
        if client is None:
            raise CacheUnavailableError("Redis unavailable")
        script = """
        local value = redis.call('INCR', KEYS[1])
        if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return value
        """
        try:
            return int(await client.eval(script, 1, key, ttl))
        except Exception as exc:
            raise CacheUnavailableError("Redis unavailable") from exc

    async def delete(self, pattern: str) -> int:
        """按模式删除缓存，返回删除的 key 数量。

        Uses SCAN for safe iteration instead of KEYS (which blocks Redis).
        """
        if not self._enabled:
            return self._local_delete(pattern)
        try:
            client = await self._ensure_client()
            if client is None:
                return self._local_delete(pattern)
            return await self._scan_delete(client, pattern)
        except Exception:
            return self._local_delete(pattern)

    async def delete_strict(self, key: str) -> int:
        """Delete one exact security key without cross-process fallback."""
        if not self._enabled:
            return self._local_delete(key)
        client = await self._ensure_client()
        if client is None:
            raise CacheUnavailableError("Redis unavailable")
        try:
            return int(await client.delete(key))
        except Exception as exc:
            raise CacheUnavailableError("Redis unavailable") from exc

    async def _scan_delete(self, client, pattern: str, batch_size: int = 500) -> int:
        """Delete keys matching *pattern* via SCAN iteration.

        Avoids blocking the Redis event loop that KEYS would cause on
        large keyspaces. Iterates in batches of *batch_size*.
        """
        total = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor, match=pattern, count=batch_size,
            )
            if keys:
                total += await client.delete(*keys)
            if cursor == 0:
                break
        return total

    async def delete_namespaced(self, pattern: str) -> int:
        """Delete keys under a namespace-safe pattern.

        Only operates on keys matching the given pattern. Use this for
        API-facing cache clearing instead of bare ``delete()`` to ensure
        namespace isolation is enforced at the call site.
        """
        return await self.delete(pattern)

    async def clear(self) -> int:
        """清空本地缓存。Redis FLUSHDB 已移除——使用 delete_namespaced 代替。

        Never call FLUSHDB — it would clear task queues, JWT blacklists,
        distributed locks, and other system namespaces.
        """
        logger.warning("cache.clear() called — only clears local cache, not Redis")
        return self._local_clear()

    def get_stats(self) -> dict:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = round(self._stats["hits"] / total, 4) if total > 0 else 0.0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": hit_rate,
            "enabled": self._enabled,
        }


cache = CacheClient()


def make_cache_key(prefix: str, *args, **kwargs) -> str:
    """生成稳定的缓存 key。"""
    raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    digest = hashlib.md5(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


def cached(ttl: int = 300, key_prefix: str = ""):
    """缓存装饰器。

    Usage:
        @cached(ttl=600, key_prefix="practice_stats")
        async def get_stats(user_id, subject):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = make_cache_key(key_prefix or func.__name__, *args, **kwargs)
            result = await cache.get(cache_key)
            if result is not None:
                return result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorator
