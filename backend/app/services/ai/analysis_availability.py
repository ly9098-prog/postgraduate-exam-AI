"""On-demand model probes and admission for wrong-detail AI features."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.ai.gateway import LLMRuntimeConfig, resolve_llm_runtime_config
from app.core.background_tasks import create_background_task
from app.core.cache import CacheUnavailableError
from app.services.ai import model_health

logger = logging.getLogger(__name__)


class AnalysisUnavailableError(RuntimeError):
    def __init__(self, state: dict) -> None:
        self.state = state
        super().__init__(state["message"])


def unavailable_state(reason: str) -> dict:
    return {
        "status": "unavailable",
        "enabled": False,
        "reason": reason,
        "message": model_health.MESSAGES[reason],
        "retry_after_ms": 30000,
    }


def availability_retryable(state: dict) -> bool:
    return state.get("reason") in {"checking", "transient", "status_unavailable"}


async def _probe(runtime: Any, token: str) -> None:
    from app.services.ai import connection_probe

    try:
        async with asyncio.timeout(model_health.PROBE_TIMEOUT):
            result = await connection_probe.probe_chat_connection(
                runtime.base_url,
                runtime.api_key,
                runtime.model_name,
                provider=runtime.provider,
            )
    except asyncio.CancelledError:
        await _finish_safely(runtime, token, {"success": False, "status": "timeout"})
        raise
    except Exception:
        logger.warning("ai.analysis.probe_failed", exc_info=True)
        result = {"success": False, "status": "network_error"}
    await _finish_safely(runtime, token, result)


async def _finish_safely(runtime: Any, token: str, result: dict) -> None:
    try:
        await model_health.finish_probe(runtime, token, result)
    except CacheUnavailableError:
        logger.warning("ai.analysis.health_store_unavailable")


async def request_probe(runtime: Any, *, force: bool = False) -> dict:
    record, token = await model_health.claim_probe(runtime, force=force)
    if token:
        create_background_task(_probe(runtime, token), name="analysis-model-probe")
    return record


async def list_analysis_candidates(
    db: Any,
    excluded: set[int] | None = None,
) -> list[LLMRuntimeConfig]:
    """Return the same ordered candidates used by analysis and Admin probes."""
    candidates = []
    seen = set(excluded or set())
    for _ in range(16):
        runtime = await resolve_llm_runtime_config(
            db,
            feature="analysis",
            exclude_model_config_ids=seen,
        )
        if runtime is None:
            break
        if runtime.model_config_id is None:
            break
        model_id = int(runtime.model_config_id)
        if model_id in seen:
            break
        seen.add(model_id)
        candidates.append(runtime)
    return candidates


async def resolve_available_runtime(
    db: Any,
    *,
    excluded_model_config_ids: set[int] | None = None,
) -> tuple[LLMRuntimeConfig | None, dict]:
    try:
        return await _resolve_available(db, excluded_model_config_ids or set())
    except CacheUnavailableError:
        return None, unavailable_state("status_unavailable")


async def _resolve_available(db: Any, excluded: set[int]) -> tuple[Any, dict]:
    candidates = await list_analysis_candidates(db, excluded)
    if not candidates:
        return None, unavailable_state("unconfigured")
    records = [
        (runtime, await model_health.read_health(runtime)) for runtime in candidates
    ]
    now = time.time()
    for runtime, record in records:
        if model_health.public_state(record, now=now)["enabled"]:
            if record.get("next_probe_at", 0) <= now:
                await request_probe(runtime)
            return runtime, model_health.public_state(record, now=now)
    # Probe one eligible candidate at a time, retaining warm healthy fallbacks.
    pending = next(
        (
            record
            for _, record in records
            if record
            and record.get("status") == "checking"
            and record.get("next_probe_at", 0) > now
        ),
        None,
    )
    if pending:
        return None, model_health.public_state(pending)
    for runtime, record in records:
        if not record or record.get("next_probe_at", 0) <= now:
            return None, model_health.public_state(await request_probe(runtime))
    states = [model_health.public_state(record) for _, record in records]
    state = dict(states[0])
    state["retry_after_ms"] = min(item["retry_after_ms"] for item in states)
    return None, state


async def require_available_runtime(db: Any) -> LLMRuntimeConfig:
    runtime, state = await resolve_available_runtime(db)
    if runtime is None:
        raise AnalysisUnavailableError(state)
    return runtime


async def require_runtime_verified(runtime: Any) -> None:
    try:
        record = await model_health.read_health(runtime)
        if model_health.public_state(record)["enabled"]:
            return
        state = model_health.public_state(await request_probe(runtime))
    except CacheUnavailableError:
        state = unavailable_state("status_unavailable")
    raise AnalysisUnavailableError(state)


async def availability_for_user(db: Any, user_id: int) -> dict:
    from app.services.ai_learning_service import check_token_limit

    if not await check_token_limit(db, user_id, 900):
        return unavailable_state("user_quota")
    _, state = await resolve_available_runtime(db)
    return state


async def note_failure(runtime: Any, exc: Exception) -> None:
    try:
        await model_health.record_failure(runtime, exc)
    except CacheUnavailableError:
        logger.warning("ai.analysis.health_store_unavailable")


async def note_success(runtime: Any, *, started_at: float) -> None:
    try:
        await model_health.record_success(runtime, started_at=started_at)
    except CacheUnavailableError:
        logger.warning("ai.analysis.health_store_unavailable")
