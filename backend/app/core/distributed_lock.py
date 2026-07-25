"""Strict Redis-backed distributed lock with Lua atomic operations.

Provides mutual exclusion for scheduler tasks across multiple worker
instances. Unlike ``cache.acquire_lock``, this module never degrades to
local in-memory locking — production Redis failures are fail-closed.

Lock operations are atomic via Lua scripts. Each lock acquisition
generates a unique owner_token; renew and release verify the token
to prevent stale-writer interference.

Lua scripts:
- ``_LUA_ACQUIRE`` — SET NX with owner_token embedded in the value,
  returns 1 on success, 0 if already held.
- ``_LUA_RENEW`` — compare value (owner_token) → EXPIRE, returns 1
  on success, 0 on owner mismatch (caller should stop).
- ``_LUA_RELEASE`` — compare value (owner_token) → DEL, returns 1
  on success, 0 on owner mismatch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

import redis.asyncio as redis_async
import redis.exceptions as redis_exc

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.distributed-lock")

# Lua: ACQUIRE — SET NX (atomically set if not exist)
# KEYS: [lock_key]
# ARGV: [value_with_token, ttl_sec]
# Returns: 1 on success, 0 if already held
_LUA_ACQUIRE = """
local val = redis.call("SET", KEYS[1], ARGV[1], "NX", "EX", tonumber(ARGV[2]))
if val then return 1 else return 0 end
"""

# Lua: RENEW — compare value, then EXPIRE
# KEYS: [lock_key]
# ARGV: [expected_value, ttl_sec]
# Returns: 1 on success, 0 if mismatch or not exists
_LUA_RENEW = """
local val = redis.call("GET", KEYS[1])
if not val or val ~= ARGV[1] then return 0 end
redis.call("EXPIRE", KEYS[1], tonumber(ARGV[2]))
return 1
"""

# Lua: RELEASE — compare value, then DEL
# KEYS: [lock_key]
# ARGV: [expected_value]
# Returns: 1 on success, 0 if mismatch or not exists
_LUA_RELEASE = """
local val = redis.call("GET", KEYS[1])
if not val or val ~= ARGV[1] then return 0 end
redis.call("DEL", KEYS[1])
return 1
"""


class DistributedLock:
    """Strict distributed lock backed by Redis Lua scripts.

    Never degrades to local in-memory locking when Redis is unavailable.
    In production, all failures are logged but the lock operation returns
    ``False`` (caller skips rather than proceeding without mutual exclusion).

    Usage::

        lock = DistributedLock("my_task_lock")

        # Simple acquire/release
        if await lock.acquire(ttl=60):
            try:
                await do_work()
            finally:
                await lock.release()

        # With automatic renewal
        async with lock.acquire_and_renew(ttl=60, renew_interval=30) as held:
            if held:
                await do_long_work()

    Metrics counters (incremented in-process):
        - acquired, skipped, failed, duration
    """

    def __init__(
        self,
        name: str,
        *,
        redis_url: str | None = None,
        instance_id: str | None = None,
    ) -> None:
        self._name = name
        self._redis_url = redis_url or (settings.REDIS_URL if settings.REDIS_URL else None)
        self._redis_enabled = bool(self._redis_url)
        self._client: redis_async.Redis | None = None
        self._instance_id = instance_id or f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._owner_token: str = ""
        self._lock_key = f"distlock:{name}"
        self._lua_acquire_sha: str | None = None
        self._lua_renew_sha: str | None = None
        self._lua_release_sha: str | None = None

        # Metrics
        self.acquired: int = 0
        self.skipped: int = 0
        self.failed: int = 0
        self.duration_ms: float = 0.0

    async def _get_client(self) -> redis_async.Redis | None:
        if not self._redis_enabled:
            return None
        if self._client is None:
            try:
                self._client = redis_async.from_url(
                    self._redis_url,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    decode_responses=True,
                )
            except Exception as e:
                logger.error("distlock %s: failed to create Redis client: %s", self._name, e)
                return None
        return self._client

    async def _load_scripts(self, client: redis_async.Redis) -> None:
        if self._lua_acquire_sha is not None:
            return
        self._lua_acquire_sha = await client.script_load(_LUA_ACQUIRE)
        self._lua_renew_sha = await client.script_load(_LUA_RENEW)
        self._lua_release_sha = await client.script_load(_LUA_RELEASE)

    async def _reload_scripts(self, client: redis_async.Redis) -> None:
        self._lua_acquire_sha = None
        self._lua_renew_sha = None
        self._lua_release_sha = None
        await self._load_scripts(client)

    def _value(self) -> str:
        """Value stored in Redis: ``{instance_id}:{owner_token}``."""
        return f"{self._instance_id}:{self._owner_token}"

    async def acquire(self, ttl: int = 60) -> bool:
        """Acquire the distributed lock.

        Returns True if the lock was acquired, False if already held
        by another instance or on Redis failure.
        """
        if not self._redis_enabled:
            logger.warning("distlock %s: Redis not configured, lock always fails", self._name)
            self.failed += 1
            return False

        self._owner_token = uuid.uuid4().hex
        client = await self._get_client()
        if client is None:
            self.failed += 1
            return False

        try:
            await self._load_scripts(client)
            result = await client.evalsha(self._lua_acquire_sha, 1, self._lock_key, self._value(), str(ttl))
            if result == 1:
                self.acquired += 1
                logger.debug("distlock %s: acquired (token=%s)", self._name, self._owner_token[:8])
                return True
            self.skipped += 1
            return False
        except redis_exc.NoScriptError:
            try:
                await self._reload_scripts(client)
                result = await client.evalsha(self._lua_acquire_sha, 1, self._lock_key, self._value(), str(ttl))
                if result == 1:
                    self.acquired += 1
                    return True
                self.skipped += 1
                return False
            except Exception as e:
                logger.error("distlock %s: acquire (after reload) error: %s", self._name, e)
                self.failed += 1
                return False
        except Exception as e:
            logger.error("distlock %s: acquire error: %s", self._name, e)
            self.failed += 1
            return False

    async def renew(self, ttl: int = 60) -> bool:
        """Extend the lock TTL.

        Only succeeds if the calling instance still owns the lock
        (owner_token matches). Returns False if lock was lost —
        caller MUST stop work immediately.
        """
        if not self._redis_enabled or not self._owner_token:
            return False

        client = await self._get_client()
        if client is None:
            return False

        try:
            result = await client.evalsha(self._lua_renew_sha, 1, self._lock_key, self._value(), str(ttl))
            if result == 1:
                return True
            logger.warning("distlock %s: renew failed — lock lost (token=%s)", self._name, self._owner_token[:8])
            return False
        except redis_exc.NoScriptError:
            try:
                await self._reload_scripts(client)
                result = await client.evalsha(self._lua_renew_sha, 1, self._lock_key, self._value(), str(ttl))
                return result == 1
            except Exception as e:
                logger.error("distlock %s: renew (after reload) error: %s", self._name, e)
                return False
        except Exception as e:
            logger.error("distlock %s: renew error: %s", self._name, e)
            return False

    async def release(self) -> bool:
        """Release the lock.

        Only succeeds if the calling instance still owns the lock.
        Returns True on release, False if lock was already lost.
        """
        if not self._redis_enabled or not self._owner_token:
            return False

        client = await self._get_client()
        if client is None:
            return False

        try:
            result = await client.evalsha(self._lua_release_sha, 1, self._lock_key, self._value())
            if result == 1:
                logger.debug("distlock %s: released (token=%s)", self._name, self._owner_token[:8])
            self._owner_token = ""
            return result == 1
        except redis_exc.NoScriptError:
            try:
                await self._reload_scripts(client)
                result = await client.evalsha(self._lua_release_sha, 1, self._lock_key, self._value())
                self._owner_token = ""
                return result == 1
            except Exception as e:
                logger.error("distlock %s: release (after reload) error: %s", self._name, e)
                self._owner_token = ""
                return False
        except Exception as e:
            logger.error("distlock %s: release error: %s", self._name, e)
            self._owner_token = ""
            return False

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning("distlock %s: close error: %s", self._name, e)
            self._client = None

    # ── Context manager with auto-renewal ──

    async def _renew_loop(
        self,
        ttl: int,
        renew_interval: float,
        stop_event: asyncio.Event,
    ) -> None:
        """Background task that periodically extends the lock."""
        while not stop_event.is_set():
            try:
                await asyncio.sleep(renew_interval)
                if not await self.renew(ttl=ttl):
                    logger.error(
                        "distlock %s: renewal failed, lock lost after %s",
                        self._name, self._owner_token[:8],
                    )
                    return
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("distlock %s: renew_loop error: %s", self._name, e)

    async def acquire_and_renew(
        self,
        ttl: int = 60,
        renew_interval: float = 30,
    ):
        """Async context manager that acquires the lock and auto-renews it.

        Usage::

            async with lock.acquire_and_renew(ttl=60, renew_interval=30) as held:
                if held:
                    await do_long_work()
        """
        start = time.time()
        acquired = await self.acquire(ttl=ttl)

        if not acquired:
            self.duration_ms += (time.time() - start) * 1000
            yield False
            return

        stop_event = asyncio.Event()
        renewer = asyncio.create_task(
            self._renew_loop(ttl, renew_interval, stop_event),
            name=f"distlock-renew-{self._name}",
        )

        try:
            yield True
        finally:
            stop_event.set()
            renewer.cancel()
            try:
                await renewer
            except asyncio.CancelledError:
                pass
            await self.release()
            self.duration_ms += (time.time() - start) * 1000

    def __del__(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            pass  # Redis client GC is handled by redis-py
