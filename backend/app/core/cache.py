import hashlib
import json
import logging
import random
from functools import wraps
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.cache")


class CacheClient:
    """Redis 缓存客户端封装。

    Redis 不可用时静默降级为进程内缓存，不影响核心功能。
    """

    def __init__(self):
        self._client: redis.Redis | None = None
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
            logger.warning("Redis 不可用，缓存已禁用: %s", e)
            self._enabled = False
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
            current = await client.get(key)
            if isinstance(current, bytes):
                current = current.decode()
            if current == value:
                await client.delete(key)
        except Exception:
            pass

    async def delete(self, pattern: str) -> int:
        """按模式删除缓存，返回删除的 key 数量。"""
        if not self._enabled:
            return self._local_delete(pattern)
        try:
            client = await self._ensure_client()
            if client is None:
                return self._local_delete(pattern)
            keys = await client.keys(pattern)
            if keys:
                return await client.delete(*keys)
            return 0
        except Exception:
            return self._local_delete(pattern)

    async def clear(self) -> int:
        """清空所有缓存（FLUSHDB）。"""
        if not self._enabled:
            return self._local_clear()
        try:
            client = await self._ensure_client()
            if client is None:
                return self._local_clear()
            await client.flushdb()
            return 1
        except Exception:
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
