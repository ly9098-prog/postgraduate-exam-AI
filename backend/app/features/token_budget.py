"""Shared token budget tracker used by OCR/import AI stages.

Production uses Redis-backed daily/monthly counters so all worker processes see
one budget.  Local development can fall back to process-local counters when
Redis is intentionally absent.  The existing public API is preserved.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.time_utils import shanghai_now
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_redis_pool: Any = None
_redis_unavailable_logged = False
_token_usage: dict[str, int | str] = {
    "daily": 0,
    "monthly": 0,
    "daily_date": "",
    "monthly_month": "",
}


def estimate_tokens(text: str) -> int:
    chinese = len(re.findall(r"[一-鿿]", text))
    return int(chinese * 1.3 + (len(text) - chinese) * 0.3)


def _periods() -> tuple[str, str]:
    now = shanghai_now()
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


def _reset_counters_if_needed() -> None:
    today, month = _periods()
    if _token_usage["daily_date"] != today:
        _token_usage["daily"] = 0
        _token_usage["daily_date"] = today
    if _token_usage["monthly_month"] != month:
        _token_usage["monthly"] = 0
        _token_usage["monthly_month"] = month


def _restricted() -> bool:
    if str(settings.APP_ENV).strip().lower() == "production":
        return True
    try:
        return detect_deployment_profile() == DeploymentProfile.CLOUD_API
    except Exception:
        return True


async def _redis():
    global _redis_pool
    if not settings.REDIS_URL:
        return None
    try:
        import redis.asyncio as redis_async

        if _redis_pool is None:
            _redis_pool = redis_async.ConnectionPool.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
                decode_responses=True,
                max_connections=6,
            )
        return redis_async.Redis(connection_pool=_redis_pool)
    except Exception:
        return None


def _keys() -> tuple[str, str]:
    day, month = _periods()
    env = str(settings.APP_ENV or "unknown").strip().lower()
    return (
        f"memograd:{env}:ai:tokens:day:{day}",
        f"memograd:{env}:ai:tokens:month:{month}",
    )


async def _redis_usage() -> tuple[int, int] | None:
    client = await _redis()
    if client is None:
        return None
    day_key, month_key = _keys()
    try:
        values = await client.mget(day_key, month_key)
        return int(values[0] or 0), int(values[1] or 0)
    except Exception as exc:
        logger.debug("shared token budget Redis read failed: %s", exc)
        return None


async def check_token_limit(estimated_tokens: int, config: dict) -> bool:
    global _redis_unavailable_logged
    estimated_tokens = max(0, int(estimated_tokens or 0))
    daily_limit = max(0, int(config.get("daily_token_limit", 50000) or 0))
    monthly_limit = max(0, int(config.get("monthly_token_limit", 1000000) or 0))

    shared = await _redis_usage()
    if shared is not None:
        if _redis_unavailable_logged:
            logger.info("AI token budget resumed: Redis recovered")
            _redis_unavailable_logged = False
        used_daily, used_monthly = shared
        if daily_limit > 0 and used_daily + estimated_tokens > daily_limit:
            return False
        if monthly_limit > 0 and used_monthly + estimated_tokens > monthly_limit:
            return False
        return True

    # Production/cloud deployments require Redis for a shared budget.  Failing
    # closed prevents an infrastructure outage from silently removing cost caps.
    if _restricted():
        if not _redis_unavailable_logged:
            logger.warning("AI token budget paused: Redis is unavailable")
            _redis_unavailable_logged = True
        return False

    async with _lock:
        _reset_counters_if_needed()
        if daily_limit > 0 and int(_token_usage["daily"]) + estimated_tokens > daily_limit:
            return False
        if monthly_limit > 0 and int(_token_usage["monthly"]) + estimated_tokens > monthly_limit:
            return False
        return True


async def record_token_usage(tokens: int) -> None:
    tokens = max(0, int(tokens or 0))
    if tokens <= 0:
        return

    client = await _redis()
    if client is not None:
        day_key, month_key = _keys()
        try:
            pipe = client.pipeline(transaction=True)
            pipe.incrby(day_key, tokens)
            pipe.expire(day_key, 3 * 24 * 3600)
            pipe.incrby(month_key, tokens)
            pipe.expire(month_key, 40 * 24 * 3600)
            await pipe.execute()
            # Keep a process-local mirror for the existing synchronous snapshot.
            async with _lock:
                _reset_counters_if_needed()
                _token_usage["daily"] = int(_token_usage["daily"]) + tokens
                _token_usage["monthly"] = int(_token_usage["monthly"]) + tokens
            return
        except Exception as exc:
            logger.debug("shared token budget Redis increment failed: %s", exc)
            if _restricted():
                # The call already happened, so do not raise and corrupt business
                # state.  Future check_token_limit calls fail closed until Redis
                # recovers; usage should also be available from provider logs.
                return

    async with _lock:
        _reset_counters_if_needed()
        _token_usage["daily"] = int(_token_usage["daily"]) + tokens
        _token_usage["monthly"] = int(_token_usage["monthly"]) + tokens


def get_token_usage_snapshot() -> dict:
    """Return the process-local mirror used by lightweight diagnostics."""
    _reset_counters_if_needed()
    return {
        "daily": int(_token_usage["daily"]),
        "monthly": int(_token_usage["monthly"]),
    }


async def get_shared_token_usage_snapshot() -> dict:
    """Return Redis-shared usage when available, otherwise the local snapshot."""
    shared = await _redis_usage()
    if shared is not None:
        return {"daily": shared[0], "monthly": shared[1], "shared": True}
    local = get_token_usage_snapshot()
    return {**local, "shared": False}


async def close_token_budget() -> None:
    """Close the shared Redis pool during application shutdown."""
    global _redis_pool
    pool = _redis_pool
    _redis_pool = None
    if pool is not None:
        try:
            await pool.aclose()
        except Exception:
            pass
