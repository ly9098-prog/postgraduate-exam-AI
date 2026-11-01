import asyncio
import json
import logging
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.answer_grounding import (
    build_answer_grounding,
    build_revision_drift_analysis,
    build_safe_grounded_analysis,
    diagnosis_contradicts_grounding,
    grounding_fact_signature,
    grounding_prompt_payload,
    grounding_verification_payload,
    merge_grounded_diagnosis,
)
from app.ai.client import llm
from app.ai.context import build_error_context
from app.ai.fallback import get_fallback_advice, get_fallback_analysis
from app.ai.gateway import chat_with_db_model, resolve_llm_runtime_config
from app.ai.prompts import (
    AI_ANALYSIS_PROMPT_VERSION,
    build_error_analysis,
    build_study_advice,
    build_visual_evidence_probe,
)
from app.core.config import settings
from app.models.admin import QuestionVersion
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.ai.advice_snapshot import (
    advice_fallback_response,
    advice_success_response,
    build_advice_snapshot,
    parse_advice_content,
)
from app.services.ai.analysis_cache import (
    _analysis_input_signature,
    _analysis_model_signature,
    build_cached_error_analysis_response,
)
from app.services.ai.analysis_content import (
    _ANALYSIS_WRAPPER_KEYS,
    _canonical_answer_check_list,  # noqa: F401 — historical public import
    _canonical_answer_echo,  # noqa: F401 — historical public import
    _coerce_analysis_text,
    _decode_structured_content,
    _extract_analysis_fields,  # noqa: F401 — historical public import
    _extract_answer_check,  # noqa: F401 — historical public import
    _looks_like_structured_analysis_text,  # noqa: F401 — historical public import
    _normalize_ai_analysis,
    _parse_titled_analysis_text,  # noqa: F401 — historical public import
    _pick_field,  # noqa: F401 — historical public import
    _strip_code_fence,  # noqa: F401 — historical public import
    _validate_answer_check,
    is_valid_ai_analysis,
    parse_error_analysis_content,
)
from app.services.ai.analysis_execution import (  # noqa: F401 — historical public import
    begin_analysis_generation,
    finish_analysis_generation,
    prepare_locked_analysis_inputs,
    review_locked_analysis_cache,
)
from app.services.ai.analysis_invocation import (  # noqa: F401 — historical public import
    AnalysisInvocationRequest,
    invoke_prepared_analysis,
)
from app.services.ai.analysis_orchestration import (
    AnalysisOrchestrationRequest,
    execute_locked_analysis,
)
from app.services.ai.analysis_outcomes import (
    build_analysis_usage,
    grounding_repair_outcome,
    valid_analysis_outcome,
    visual_ack_failure_outcome,
)
from app.services.ai.analysis_persistence import (
    persist_repaired_analysis,
    persist_valid_analysis,
)
from app.services.ai.analysis_preparation import (
    AnalysisPreparationRequest,
    prepare_analysis,
)
from app.services.ai.analysis_responses import (
    generation_in_progress_response,
    grounding_repaired_response,
    quota_exceeded_response,
    valid_analysis_response,
    visual_ack_failed_response,
)
from app.services.ai.analysis_result_review import (  # noqa: F401 — historical public import
    resolve_analysis_outcome,
    review_analysis_result,
)
from app.services.ai.prewarm_execution import (
    PrewarmExecutionRequest,
    execute_prewarm,
)
from app.services.ai.provider_exception import classify_ai_provider_exception
from app.services.ai.revision_guard import check_analysis_revision_drift
from app.services.ai.visual_ack_retry import (
    ACK_MAIN_BUDGET_MS,
    retry_visual_ack,
    should_retry_visual_ack,
)
from app.services.ai.visual_cache import (
    MAX_VISUAL_IMAGES,
    _analysis_cache_age_ms,
    _analysis_cache_stale_reason,
    _collect_question_visual_sources,
    _detect_image_mime,
    _extract_structured_visual,
    _image_bytes_to_data_url,
    _iter_url_values,  # noqa: F401 — historical public import
    _question_has_unresolved_visual_slot,
    _visual_evidence_is_valid,
    ai_analysis_generated_at,
    is_ai_analysis_fresh,  # noqa: F401 — historical public import
)
from app.services.ai_learning_service import check_token_limit
from app.services.knowledge_point_service import load_question_kps
from app.services.safe_remote_fetch import request_remote_bytes

logger = logging.getLogger(__name__)


def _analysis_timeout_sec(effective_force: bool) -> int:
    return (
        ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS
        if effective_force
        else ERROR_ANALYSIS_TIMEOUT_SECONDS
    )


# 与 ai_learning_service 的同类入口一致：先按预估额度做准入，实际用量事后记入 AiChat。
_ERROR_ANALYSIS_QUOTA_ESTIMATE = 900
_ADVICE_QUOTA_ESTIMATE = 1000


async def _analyze_error_with_lease(
    db: AsyncSession,
    user_id: int,
    preparation: Any,
) -> dict:
    from app.core.cache import cache
    from app.services.ai.analysis_availability import resolve_available_runtime

    runtime, state = await resolve_available_runtime(db)
    if runtime is None:
        return _unavailable_analysis_response(preparation, state)
    prepared = replace(
        preparation,
        runtime=runtime,
        model_signature=_analysis_model_signature(runtime),
    )
    return await execute_locked_analysis(
        _analysis_orchestration_request(db, user_id, prepared, cache)
    )


def _unavailable_analysis_response(preparation: Any, state: dict) -> dict:
    cached = build_any_cached_error_analysis_response(preparation.wrong_question)
    return {
        **(cached or quota_exceeded_response()),
        "error_code": "ai_service_unavailable",
        "retryable": False,
        "cache_preserved": bool(cached),
        "availability": state,
    }


def _analysis_orchestration_request(
    db: AsyncSession,
    user_id: int,
    prepared: Any,
    cache: Any,
) -> AnalysisOrchestrationRequest:
    return AnalysisOrchestrationRequest(
        db=db,
        user_id=user_id,
        wrong_question=prepared.wrong_question,
        question=prepared.question,
        answer_grounding=prepared.answer_grounding,
        stored_visual_sources=prepared.visual_sources,
        requires_visual=prepared.requires_visual,
        knowledge_points=prepared.knowledge_points,
        runtime=prepared.runtime,
        input_signature=prepared.input_signature,
        model_signature=prepared.model_signature,
        effective_force=prepared.force,
        timeout_sec=_analysis_timeout_sec(prepared.force),
        lock_grace_sec=ERROR_ANALYSIS_LOCK_GRACE_SECONDS,
        generating=_generating,
        cache=cache,
        logger=logger,
        **_analysis_orchestration_ports(),
    )


def _analysis_orchestration_ports() -> dict[str, Any]:
    return {
        "prepare_visual_inputs": _prepare_visual_inputs,
        "build_context": build_error_context,
        "build_prompt_grounding": grounding_prompt_payload,
        "build_expected_answer_check": grounding_verification_payload,
        "input_signature_builder": _analysis_input_signature,
        "cached_response": build_cached_error_analysis_response,
        "cache_age": _analysis_cache_age_ms,
        "chat": llm.chat,
        "resolve_runtime": _resolve_healthy_analysis_runtime,
        "quarantine_runtime": _quarantine_analysis_runtime_auth,
        "parse_content": parse_error_analysis_content,
        "validate_content": is_valid_ai_analysis,
        "extract_evidence": _extract_visual_evidence,
        "build_usage": build_analysis_usage,
        "validate_answer_check": _validate_answer_check,
        "diagnosis_contradicts_grounding": diagnosis_contradicts_grounding,
        "evidence_is_valid": _visual_evidence_is_valid,
        "should_retry_visual_ack": should_retry_visual_ack,
        "retry_visual_ack": retry_visual_ack,
        "model_signature_builder": _analysis_model_signature,
        "max_tokens": _ERROR_ANALYSIS_MAX_TOKENS,
        "timeout_guard_sec": ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS,
        "visual_ack_failure": visual_ack_failure_outcome,
        "grounding_repair": grounding_repair_outcome,
        "valid_outcome": valid_analysis_outcome,
    }


# 第三方 Relay / reasoning 模型可能健康地超过 50 秒，因此服务端不能继续
# 使用旧的 48/50 秒硬截断。微信小程序 wx.request 本身最多约 60 秒，所以
# 客户端仍保持 <60 秒的单次请求，并在超时后轮询持久化结果；同时会补投一个
# 后台 recovery 任务，防止反向代理/客户端断连真的中止原始生成。
# Keep the provider budget independent from the mini-program transport budget:
# the backend may wait longer for a healthy compatible model, while the client
# switches to persistence polling/recovery before the platform request ceiling.
_CONFIGURED_AI_TIMEOUT_SECONDS = max(
    10,
    int(
        getattr(settings, "AI_ERROR_ANALYSIS_TIMEOUT_SEC", 0)
        or settings.AI_TIMEOUT
        or 150
    ),
)
ERROR_ANALYSIS_TIMEOUT_SECONDS = _CONFIGURED_AI_TIMEOUT_SECONDS
ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS = _CONFIGURED_AI_TIMEOUT_SECONDS
ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS = 3
ERROR_ANALYSIS_LOCK_GRACE_SECONDS = 15

# 同进程内生成中锁，防止并发重复调用大模型
_generating: set[int] = set()

# A bad credential is a configuration failure, not a transient provider outage.
# Quarantine the exact model-config revision briefly so one invalid key does not
# make every newly-created wrong question hit the provider and emit another 401.
# The fingerprint changes when the encrypted credential changes, so an admin key
# update becomes eligible immediately instead of waiting for this TTL.
_ANALYSIS_AUTH_QUARANTINE_SECONDS = 15 * 60
_ANALYSIS_RUNTIME_RESOLUTION_LIMIT = 16


def _analysis_auth_quarantine_key(runtime) -> str | None:
    if runtime is None or runtime.model_config_id is None:
        return None
    fingerprint = str(getattr(runtime, "config_fingerprint", "") or "legacy")
    return f"ai:analysis:auth_failed:{runtime.model_config_id}:{fingerprint}"


async def _is_analysis_runtime_auth_quarantined(runtime) -> bool:
    key = _analysis_auth_quarantine_key(runtime)
    if not key:
        return False
    from app.core.cache import cache
    from app.services.ai.model_health import public_state, read_health

    try:
        health = await read_health(runtime)
    except Exception:
        logger.warning("ai.analysis.health_read_failed", exc_info=True)
        return True
    if health:
        return not public_state(health)["enabled"]

    return bool(await cache.get(key))


async def _quarantine_analysis_runtime_auth(runtime) -> None:
    key = _analysis_auth_quarantine_key(runtime)
    if not key:
        return
    from app.core.cache import cache

    await cache.set(
        key,
        {
            "model_config_id": runtime.model_config_id,
            "provider": runtime.provider,
            "model_name": runtime.model_name,
        },
        ttl=_ANALYSIS_AUTH_QUARANTINE_SECONDS,
    )


async def _resolve_healthy_analysis_runtime(
    db: AsyncSession,
    *,
    excluded_model_config_ids: set[int] | None = None,
):
    excluded = {int(item) for item in (excluded_model_config_ids or set())}
    for _ in range(_ANALYSIS_RUNTIME_RESOLUTION_LIMIT):
        runtime = await resolve_llm_runtime_config(
            db,
            feature="analysis",
            exclude_model_config_ids=excluded,
        )
        if runtime is None:
            return None
        model_id = runtime.model_config_id
        if model_id is None:
            return runtime
        if not await _is_analysis_runtime_auth_quarantined(runtime):
            return runtime
        excluded.add(int(model_id))
        logger.info(
            "ai.error_analysis.model_skipped model_config_id=%s provider=%s model=%s reason=auth_quarantined",
            model_id,
            runtime.provider,
            runtime.model_name,
        )
    return None


# Vision context is deliberately bounded to control upload/token cost. The model
# call itself may legitimately outlive one mini-program HTTP request; client-side
# recovery/polling handles that transport limit.
_MAX_VISUAL_IMAGES = MAX_VISUAL_IMAGES
_MAX_VISUAL_SOURCE_BYTES = 6 * 1024 * 1024
_VISUAL_FETCH_TIMEOUT_SECONDS = 6.0

# wrong-detail is a short, structured response task. Keep its output bounded.
# Persisted question images are already resized to <=1200px by compress_image,
# so the OpenAI-compatible message can stay vendor-neutral without model-specific
# image extensions such as max_pixels/detail tuning.
_ERROR_ANALYSIS_MAX_TOKENS = 800
# The primary visual analysis can occasionally return all three pedagogical
# fields correctly while omitting only ``visual_evidence``.  A tiny same-model
# probe repairs that protocol-level omission without re-running the full answer.


class PrewarmAnalysisError(RuntimeError):
    """Typed prewarm failure used by queue/local runners for retry policy.

    ``analyze_error`` intentionally returns a structured fallback response to
    synchronous mini-program requests so the UI can degrade gracefully. A
    background prewarm, however, must not count that fallback as a successful
    cache warm. This exception converts the structured fallback back into queue
    semantics without changing the public API behavior.
    """

    def __init__(
        self,
        error_code: str,
        *,
        retryable: bool,
        model: str = "fallback",
        detail: str = "",
    ) -> None:
        self.error_code = str(error_code or "ai_analysis_failed")
        self.retryable = bool(retryable)
        self.model = str(model or "fallback")
        self.detail = str(detail or "")
        message = (
            self.error_code if not self.detail else f"{self.error_code}: {self.detail}"
        )
        super().__init__(message)


def _classify_ai_provider_exception(
    exc: Exception, *, visual: bool
) -> tuple[str, bool, str]:
    return classify_ai_provider_exception(exc, visual=visual)


def _prewarm_failure_from_result(result: dict) -> PrewarmAnalysisError:
    model = str(result.get("model") or "fallback")
    error_code = str(result.get("error_code") or "")
    retryable = result.get("retryable")

    if not error_code:
        defaults = {
            "generating": ("generation_in_progress", True),
            "timeout": ("ai_provider_timeout", True),
            "vision_input_missing": ("vision_input_missing", False),
            "vision_unavailable": ("vision_unavailable", False),
            "vision_parse_failed": ("vision_parse_failed", False),
            "parse_failed": ("ai_response_parse_failed", True),
            "fallback": ("ai_analysis_failed", True),
        }
        error_code, default_retryable = defaults.get(
            model, ("ai_analysis_failed", True)
        )
        if retryable is None:
            retryable = default_retryable

    return PrewarmAnalysisError(
        error_code,
        retryable=bool(retryable),
        model=model,
    )


def _read_local_public_asset(url: str) -> tuple[bytes, str] | None:
    """Read our own /static asset without doing an SSRF-prone HTTP round trip."""
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    path = unquote(parsed.path if parsed.scheme else raw.split("?", 1)[0])
    public_base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    if parsed.scheme and public_base and not raw.startswith(public_base + "/"):
        return None
    if not path.startswith("/static/"):
        return None

    # services/ai_service.py lives under <repo>/app/services in production.
    repo_root = Path(__file__).resolve().parents[2]
    static_root = (repo_root / "static").resolve()
    candidate = (repo_root / path.lstrip("/")).resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    size = candidate.stat().st_size
    if size < 1 or size > _MAX_VISUAL_SOURCE_BYTES:
        return None
    data = candidate.read_bytes()
    return data, _detect_image_mime(data)


async def _visual_source_to_data_url(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("data:image/"):
        # Existing data URLs are accepted only when bounded and syntactically
        # simple. They will still be decoded/re-encoded by the caller when they
        # originate from uploads; this branch is for stored question content.
        if len(raw) <= (_MAX_VISUAL_SOURCE_BYTES * 2):
            return raw
        return None

    local = await asyncio.to_thread(_read_local_public_asset, raw)
    if local is not None:
        data, content_type = local
        try:
            return _image_bytes_to_data_url(data, content_type=content_type)
        except Exception:
            return None

    if not raw.startswith(("https://", "http://")):
        return None
    try:
        remote = await asyncio.to_thread(
            request_remote_bytes,
            raw,
            max_bytes=_MAX_VISUAL_SOURCE_BYTES,
            timeout=_VISUAL_FETCH_TIMEOUT_SECONDS,
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            follow_redirects=True,
            max_redirects=2,
            require_2xx=True,
            headers={"Accept": "image/*"},
        )
        return _image_bytes_to_data_url(remote.data, content_type=remote.content_type)
    except Exception:
        logger.warning("ai.error_analysis.visual_fetch_failed url=%s", raw[:180])
        return None


async def _prepare_visual_inputs(question: Question) -> tuple[list[str], dict]:
    """Load visual inputs only from the persisted question record.

    wrong-detail does not accept user-supplied screenshots. The question image
    stored in the database/object storage is the single source of truth for
    questions that actually contain raster visuals.  Text-only questions
    legitimately return an empty image list and continue through the text path;
    callers only fail when a declared visual asset cannot be resolved.
    """
    sources = _collect_question_visual_sources(question)
    data_urls: list[str] = []

    if sources:
        resolved = await asyncio.gather(
            *(
                _visual_source_to_data_url(source)
                for source in sources[:_MAX_VISUAL_IMAGES]
            ),
            return_exceptions=False,
        )
        for data_url in resolved:
            if len(data_urls) >= _MAX_VISUAL_IMAGES:
                break
            if data_url and data_url not in data_urls:
                data_urls.append(data_url)

    return data_urls, {
        "declared_source_count": len(sources),
        "loaded_count": len(data_urls),
        "structured_visual": _extract_structured_visual(question.content),
    }


def _extract_visual_evidence(raw: str) -> str:
    decoded = _decode_structured_content(raw or "")

    def find(value, depth: int = 0) -> str:
        if depth > 5:
            return ""
        if isinstance(value, dict):
            for key in ("visual_evidence", "visualEvidence", "image_evidence"):
                if key in value:
                    return _coerce_analysis_text(value.get(key), depth + 1)
            for key in _ANALYSIS_WRAPPER_KEYS:
                if key in value:
                    found = find(value.get(key), depth + 1)
                    if found:
                        return found
        elif isinstance(value, list):
            for item in value:
                found = find(item, depth + 1)
                if found:
                    return found
        return ""

    return find(decoded)


def build_any_cached_error_analysis_response(wq) -> dict | None:
    """
    Return any cached AI analysis regardless of prompt version freshness.
    Used as fallback when force_regenerate fails — preserves old content
    even if the cache was generated with an older prompt version.
    """
    if not isinstance(wq.ai_analysis, dict) or not wq.ai_analysis:
        return None
    content = _normalize_ai_analysis(wq.ai_analysis)
    if not is_valid_ai_analysis(content):
        return None
    meta = (wq.ai_analysis or {}).get("_meta") or {}
    return {
        "content": content,
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache_preserved",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": True,
        "visual_input_count": int(meta.get("visual_input_count") or 0),
        "visual_evidence": meta.get("visual_evidence") or None,
        "generated_at": ai_analysis_generated_at(wq.ai_analysis),
    }


async def evaluate_cached_error_analysis(
    db: AsyncSession,
    wq: WrongQuestion,
    q: Question,
    *,
    knowledge_points: list[str] | None = None,
) -> dict:
    """Evaluate whether ``wrong_questions.ai_analysis`` is safe to show directly.

    The wrong-detail endpoint embeds cached AI content in its initial payload,
    so it must use the same freshness rules as ``analyze_error``. Returning a
    stale cache here would make prewarm/version invalidation ineffective because
    the mini-program could render the old content before calling the AI endpoint.
    """
    if not isinstance(wq.ai_analysis, dict) or not wq.ai_analysis:
        return {"status": "empty", "analysis": None, "reason": "empty"}

    visual_sources = _collect_question_visual_sources(q)
    requires_visual = bool(visual_sources) or _question_has_unresolved_visual_slot(q)
    if requires_visual and not visual_sources:
        return {"status": "stale", "analysis": None, "reason": "visual_input_missing"}

    if knowledge_points is None:
        question_id = int(getattr(q, "id", 0) or wq.question_id or 0)
        kp_map = await load_question_kps(db, [question_id])
        knowledge_points = kp_map.get(question_id, [])
    runtime = await _resolve_healthy_analysis_runtime(db)
    input_signature = _analysis_input_signature(
        wq, q, knowledge_points, visual_sources=visual_sources
    )
    model_signature = _analysis_model_signature(runtime)
    reason = _analysis_cache_stale_reason(
        wq.ai_analysis,
        requires_visual=requires_visual,
        expected_input_signature=input_signature,
        expected_model_signature=model_signature,
    )
    if reason is not None:
        logger.info(
            "ai.error_analysis.detail_cache_stale wq_id=%d user_id=%d reason=%s",
            wq.id,
            wq.user_id,
            reason,
        )
        return {"status": "stale", "analysis": None, "reason": reason}
    age_ms = _analysis_cache_age_ms(wq.ai_analysis)
    logger.info(
        "ai.error_analysis.detail_cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
        wq.id,
        wq.user_id,
        age_ms,
        ((wq.ai_analysis or {}).get("_meta") or {}).get("model") or "unknown",
    )
    return {
        "status": "ready",
        "analysis": _normalize_ai_analysis(wq.ai_analysis),
        "reason": None,
        "age_ms": age_ms,
    }


async def analyze_error(
    db: AsyncSession,
    user_id: int,
    wrong_question_id: int,
    force_regenerate: bool = False,
) -> dict:
    preparation = await prepare_analysis(
        AnalysisPreparationRequest(
            db=db,
            user_id=user_id,
            wrong_question_id=wrong_question_id,
            force_regenerate=force_regenerate,
            logger=logger,
            load_runtime=_resolve_healthy_analysis_runtime,
            build_grounding=build_answer_grounding,
            revision_guard=check_analysis_revision_drift,
            collect_visual_sources=_collect_question_visual_sources,
            has_visual_slot=_question_has_unresolved_visual_slot,
            load_knowledge_points=load_question_kps,
            input_signature=_analysis_input_signature,
            model_signature=_analysis_model_signature,
            cached_response=build_cached_error_analysis_response,
            cache_age=_analysis_cache_age_ms,
            stale_reason=_analysis_cache_stale_reason,
        )
    )
    if preparation.response is not None:
        return preparation.response

    if not await check_token_limit(db, user_id, _ERROR_ANALYSIS_QUOTA_ESTIMATE):
        return quota_exceeded_response()

    return await _analyze_error_with_lease(db, user_id, preparation)


async def prewarm_wrong_question_analysis(
    wrong_question_id: int,
    user_id: int,
    *,
    expected_revision: str | None = None,
    force_regenerate: bool = False,
    baseline_generated_at: str | None = None,
) -> dict:
    """Pre-generate one wrong-question analysis using queue-friendly semantics.

    The synchronous ``analyze_error`` API returns fallback payloads on provider
    failures so the mini-program can degrade gracefully. A prewarm job must not
    treat those payloads as a successful warm, otherwise monitoring reports a
    false positive and the next detail-page open still has no valid cache.

    Success/cache-hit/superseded cases return an outcome dict. Structured
    fallback results are converted to :class:`PrewarmAnalysisError`, carrying a
    stable ``error_code`` plus whether the durable/local worker may retry.
    """
    from app.ai.prewarm_revision import build_prewarm_revision
    from app.core.database import async_session

    return await execute_prewarm(
        PrewarmExecutionRequest(
            wrong_question_id=wrong_question_id,
            user_id=user_id,
            expected_revision=expected_revision,
            force_regenerate=force_regenerate,
            baseline_generated_at=baseline_generated_at,
            logger=logger,
            async_session=async_session,
            build_revision=build_prewarm_revision,
            generated_at=ai_analysis_generated_at,
            analyze_error=analyze_error,
            failure_factory=_prewarm_failure_from_result,
        )
    )


async def generate_advice(
    db: AsyncSession, user_id: int, subject_id: int | None = None
) -> dict:
    runtime = await resolve_llm_runtime_config(db, feature="analysis")

    if runtime is None:
        return advice_fallback_response(get_fallback_advice())

    if not await check_token_limit(db, user_id, _ADVICE_QUOTA_ESTIMATE):
        return advice_fallback_response(get_fallback_advice())

    # Collect user's wrong question stats
    conditions = [WrongQuestion.user_id == user_id, WrongQuestion.is_active]
    result = await db.execute(select(WrongQuestion).where(*conditions).limit(10))
    wrong_list = result.scalars().all()

    snapshot = await build_advice_snapshot(db, wrong_list)
    subject_stats = snapshot["subject_stats"]

    messages = build_study_advice(
        [{"subject": k, "count": v} for k, v in subject_stats.items()],
        snapshot["weak_points"],
        snapshot["recent_wrong"],
    )

    try:
        result = await chat_with_db_model(db, messages, feature="analysis")
        if result is None:
            raise RuntimeError("AI分析模型未配置")
    except Exception:
        return advice_fallback_response(get_fallback_advice())

    parsed = parse_advice_content(result["content"])

    db.add(
        AiChat(
            user_id=user_id,
            session_type="study_advice",
            user_message=str(subject_stats),
            ai_response=result["content"],
            tokens_used=result["tokens_used"],
            model=result["model"],
            duration_ms=result["duration_ms"],
        )
    )
    await db.commit()

    return advice_success_response(parsed, result)
