"""Connect saved Admin model tests to the same revision-scoped health state."""

from __future__ import annotations

import asyncio
import hmac
import logging
import time

from app.ai.gateway import LLMRuntimeConfig
from app.core.cache import CacheUnavailableError
from app.services.ai import analysis_availability, model_health

logger = logging.getLogger(__name__)


async def saved_runtime(db, model_id: int) -> LLMRuntimeConfig | None:
    candidates = await analysis_availability.list_analysis_candidates(db)
    for runtime in candidates:
        if runtime.model_config_id is not None and int(runtime.model_config_id) == int(
            model_id
        ):
            return runtime
    return None


async def probe_saved_model(db, model_id: int) -> None:
    try:
        runtime = await saved_runtime(db, model_id)
        if runtime is not None:
            await analysis_availability.request_probe(runtime, force=True)
    except CacheUnavailableError:
        # A committed Admin edit must not fail because health storage is down.
        logger.warning(
            "ai.analysis.admin_probe_health_store_unavailable model_config_id=%s",
            model_id,
        )
    except Exception:
        logger.warning(
            "ai.analysis.admin_probe_failed model_config_id=%s",
            model_id,
            exc_info=True,
        )


async def test_matching_saved_model(
    db,
    model_id,
    *,
    base_url,
    api_key,
    model_name,
    provider,
    features,
) -> dict | None:
    if db is None or model_id is None:
        return None
    runtime = await saved_runtime(db, model_id)
    if runtime is None or not _matches(
        runtime,
        base_url,
        api_key,
        model_name,
        provider,
        features,
    ):
        return None
    try:
        await analysis_availability.request_probe(runtime, force=True)
        return await _wait_for_test(runtime)
    except CacheUnavailableError:
        return {
            "success": False,
            "status": "network_error",
            "latency_ms": 0,
            "message": model_health.MESSAGES["status_unavailable"],
        }


def _matches(runtime, base_url, key, name, provider, features) -> bool:
    return (
        runtime.base_url.rstrip("/") == base_url.rstrip("/")
        and hmac.compare_digest(runtime.api_key, key)
        and runtime.model_name == name
        and (provider or runtime.provider) == runtime.provider
        and set(features) == set(runtime.capabilities)
    )


async def _wait_for_test(runtime) -> dict:
    started = time.monotonic()
    deadline = started + model_health.PROBE_TIMEOUT + 1
    while time.monotonic() < deadline:
        try:
            record = await model_health.read_health(runtime) or {}
        except CacheUnavailableError:
            return {
                "success": False,
                "status": "network_error",
                "latency_ms": 0,
                "message": model_health.MESSAGES["status_unavailable"],
            }
        if record.get("status") != "checking":
            result = record.get("test_result") or {
                "success": False,
                "status": "unknown_error",
                "latency_ms": 0,
            }
            return {
                **result,
                "message": (
                    "连接成功，模型响应正常"
                    if result.get("success")
                    else model_health.public_state(record)["message"]
                ),
            }
        await asyncio.sleep(0.1)
    return {
        "success": False,
        "status": "timeout",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "message": "连接模型超时，请稍后重试",
    }
