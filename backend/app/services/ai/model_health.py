"""Shared, revision-scoped health state for wrong-detail model calls."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.core.cache import CacheUnavailableError, cache
from app.services.ai.provider_exception import classify_ai_provider_exception

SUCCESS_TTL = 30
PROBE_TIMEOUT = 60
CHECKING_RETRY_MS = 2000
HARD_FAILURE_COOLDOWN = 300
TRANSIENT_COOLDOWNS = (30, 60, 120, 300)
STATE_TTL = 86400

MESSAGES = {
    "checking": "正在检查 AI 服务",
    "quota": "AI 服务额度不足，暂不可用",
    "configuration": "AI 服务配置或权限异常，等待管理员处理",
    "transient": "AI 服务暂时繁忙，请稍后重试",
    "unconfigured": "AI 服务尚未配置，请联系管理员",
    "status_unavailable": "暂时无法确认 AI 服务状态，请稍后重试",
    "user_quota": "今日 AI 使用额度已用尽，可先查看已有解析",
}


def health_key(runtime: Any) -> str:
    return (
        f"ai:analysis:health:{getattr(runtime, 'model_config_id', None)}:"
        f"{getattr(runtime, 'config_fingerprint', '') or 'legacy'}"
    )


def public_state(record: dict | None, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    record = record or {}
    status = str(record.get("status") or "checking")
    reason = str(record.get("reason") or "checking")
    enabled = status == "available" and float(record.get("next_probe_at", 0)) > now
    if status == "available" and not enabled:
        status, reason = "checking", "checking"
    retry_after_ms = max(1000, int((record.get("next_probe_at", now + 2) - now) * 1000))
    if status == "checking":
        retry_after_ms = min(retry_after_ms, CHECKING_RETRY_MS)
    return {
        "status": status,
        "enabled": enabled,
        "reason": "" if enabled else reason,
        "message": "" if enabled else MESSAGES.get(reason, MESSAGES["transient"]),
        "retry_after_ms": retry_after_ms,
    }


async def read_health(runtime: Any) -> dict | None:
    record = await cache.get_strict(health_key(runtime))
    return record if isinstance(record, dict) else None


async def _mutate(runtime: Any, change: Callable[[dict], dict | None]) -> dict | None:
    key = health_key(runtime)
    lock_key, owner = f"{key}:mutex", uuid.uuid4().hex
    for _ in range(25):
        if await cache.acquire_lock_strict(lock_key, owner, ttl=15):
            break
        await asyncio.sleep(0.02)
    else:
        raise CacheUnavailableError("Model health state is busy")
    try:
        previous = await read_health(runtime) or {}
        updated = change(previous)
        if updated is not None:
            await cache.set_strict(key, updated, ttl=STATE_TTL)
        return updated
    finally:
        await cache.release_lock(lock_key, owner)


async def claim_probe(runtime: Any, *, force: bool = False) -> tuple[dict, str | None]:
    now, token = time.time(), uuid.uuid4().hex
    claimed = False

    def change(previous: dict) -> dict:
        nonlocal claimed
        if (
            previous.get("status") == "checking"
            and previous.get("next_probe_at", 0) > now
        ):
            return previous
        if not force and previous.get("next_probe_at", 0) > now:
            return previous
        claimed = True
        return {
            "status": "checking",
            "reason": "checking",
            "probe_token": token,
            "failures": previous.get("failures", 0),
            "next_probe_at": now + PROBE_TIMEOUT + 5,
        }

    record = await _mutate(runtime, change)
    return record or {}, token if claimed else None


def _failed_record(previous: dict, reason: str) -> dict:
    failures = int(previous.get("failures", 0)) + 1
    delay = (
        HARD_FAILURE_COOLDOWN
        if reason in {"quota", "configuration"}
        else TRANSIENT_COOLDOWNS[min(failures - 1, len(TRANSIENT_COOLDOWNS) - 1)]
    )
    return {
        "status": "unavailable",
        "reason": reason,
        "failures": failures,
        "next_probe_at": time.time() + delay,
    }


async def finish_probe(runtime: Any, token: str, result: dict) -> bool:
    def change(previous: dict) -> dict | None:
        # A real request failure supersedes an older in-flight probe.
        if previous.get("probe_token") != token:
            return None
        if result.get("success"):
            record = {
                "status": "available",
                "reason": "",
                "failures": 0,
                "next_probe_at": time.time() + SUCCESS_TTL,
            }
        else:
            status = result.get("status")
            reason = (
                "quota"
                if status == "quota_error"
                else "configuration"
                if status in {"auth_error", "model_not_found"}
                else "transient"
            )
            record = _failed_record(previous, reason)
        record["test_result"] = {
            key: result[key]
            for key in ("success", "status", "latency_ms", "model_returned")
            if key in result
        }
        return record

    return await _mutate(runtime, change) is not None


async def record_failure(runtime: Any, exc: Exception) -> None:
    if runtime is None or getattr(runtime, "model_config_id", None) is None:
        return
    code, _, _ = classify_ai_provider_exception(exc, visual=False)
    reasons = {
        "ai_provider_auth_failed": "configuration",
        "ai_provider_quota_exceeded": "quota",
        "ai_provider_model_not_found": "configuration",
        "ai_provider_rate_limited": "transient",
        "ai_provider_transient": "transient",
    }
    reason = "transient" if isinstance(exc, TimeoutError) else reasons.get(code)
    # Question-specific format, vision and context errors do not quarantine a model.
    if reason is not None:
        await _mutate(runtime, lambda previous: _failed_record(previous, reason))
