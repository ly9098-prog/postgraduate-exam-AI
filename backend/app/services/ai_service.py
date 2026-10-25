import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
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
from app.services.ai.analysis_cache import (
    _analysis_input_signature,
    _analysis_model_signature,
    build_cached_error_analysis_response,
)
from app.services.ai.visual_ack_retry import (
    ACK_MAIN_BUDGET_MS,
    retry_visual_ack,
    should_retry_visual_ack,
)
from app.services.ai.analysis_persistence import (
    persist_repaired_analysis,
    persist_valid_analysis,
)
from app.services.ai.advice_snapshot import (
    advice_fallback_response,
    advice_success_response,
    build_advice_snapshot,
    parse_advice_content,
)
from app.services.ai.prewarm_transition import (
    failure_category,
    finish_prewarm_result,
    skipped_not_found,
    superseded_regenerated,
    superseded_revision,
)
from app.services.ai.provider_exception import classify_ai_provider_exception
from app.services.ai.provider_invocation import (
    ProviderInvocationInput,
    invoke_analysis_provider,
)
from app.services.ai.revision_guard import check_analysis_revision_drift
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
from app.core.config import settings
from app.models.admin import QuestionVersion
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.knowledge_point_service import load_question_kps
from app.services.safe_remote_fetch import request_remote_bytes

logger = logging.getLogger(__name__)

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
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == user_id,
        )
    )
    wq = wq_result.scalar_one_or_none()
    if not wq:
        raise ValueError("错题记录不存在")

    # AI advice is rendered next to wrong-book detail, so the teaching context
    # follows the current question-bank projection that the learner sees. The
    # immutable wrong-attempt revision is still checked as a safety boundary:
    # if option/answer semantics changed, an old answer key must never be
    # reinterpreted against the new projection.
    q_result = await db.execute(select(Question).where(Question.id == wq.question_id))
    q = q_result.scalar_one_or_none()
    if q is None:
        raise ValueError("题目不存在")

    current_answer_grounding = build_answer_grounding(
        question_type=getattr(q, "question_type", None),
        content=q.content,
        options=q.options,
        correct_answer=q.answer,
        user_answer=wq.wrong_answer,
    )
    revision_guard_response = await check_analysis_revision_drift(
        db, wrong_question=wq, question=q
    )
    if revision_guard_response is not None:
        return revision_guard_response

    stored_visual_sources = _collect_question_visual_sources(q)
    requires_visual = bool(
        stored_visual_sources
    ) or _question_has_unresolved_visual_slot(q)
    # Pure text questions are valid and continue through the normal analysis
    # path.  Fail fast only when the question schema explicitly declares a
    # visual element but the persisted asset URL is missing.
    if requires_visual and not stored_visual_sources:
        logger.info(
            "ai.error_analysis.image_missing wq_id=%d question_id=%d reason=declared_visual_without_source",
            wq.id,
            q.id,
        )
        return {
            "content": get_fallback_analysis(),
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "vision_input_missing",
            "duration_ms": 0,
            "force_regenerated": False,
            "cache_preserved": False,
            "visual_input_count": 0,
            "error_code": "vision_input_missing",
            "retryable": False,
        }

    kp_map = await load_question_kps(db, [int(q.id)])
    knowledge_points = kp_map.get(int(q.id), [])
    # Resolve the currently selected analysis model before the cache decision.
    # This is a cheap DB lookup compared with an LLM call and lets a model
    # configuration change invalidate old advice deterministically.
    runtime = await _resolve_healthy_analysis_runtime(db)
    input_signature = _analysis_input_signature(
        wq, q, knowledge_points, visual_sources=stored_visual_sources
    )
    model_signature = _analysis_model_signature(runtime)

    effective_force = bool(force_regenerate)

    if not effective_force:
        cached = build_cached_error_analysis_response(
            wq,
            requires_visual=requires_visual,
            expected_input_signature=input_signature,
            expected_model_signature=model_signature,
        )
        if cached is not None:
            logger.info(
                "ai.error_analysis.cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
                wq.id,
                user_id,
                _analysis_cache_age_ms(wq.ai_analysis),
                ((wq.ai_analysis or {}).get("_meta") or {}).get("model") or "unknown",
            )
            return cached
        stale_reason = _analysis_cache_stale_reason(
            wq.ai_analysis,
            requires_visual=requires_visual,
            expected_input_signature=input_signature,
            expected_model_signature=model_signature,
        )
        logger.info(
            "ai.error_analysis.cache_miss wq_id=%d user_id=%d reason=%s",
            wq.id,
            user_id,
            stale_reason or "unknown",
        )
    else:
        logger.info(
            "force regenerate error analysis wq_id=%d user_id=%d",
            wq.id,
            user_id,
        )

    timeout_sec = (
        ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS
        if effective_force
        else ERROR_ANALYSIS_TIMEOUT_SECONDS
    )

    wq_pk = wq.id
    if wq_pk in _generating:
        return {
            "content": {
                "mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看",
                "knowledge_patch": "",
                "review_task": "",
            },
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
            "error_code": "generation_in_progress",
            "retryable": True,
        }
    _generating.add(wq_pk)

    from app.core.cache import cache

    lock_key = f"ai:error_analysis:{wq_pk}"
    lock_value = f"{user_id}:{uuid.uuid4().hex}"
    lock_ttl = timeout_sec + ERROR_ANALYSIS_LOCK_GRACE_SECONDS
    try:
        have_lock = await cache.acquire_lock(lock_key, lock_value, ttl=lock_ttl)
    except Exception:
        _generating.discard(wq_pk)
        raise
    if not have_lock and cache.is_enabled:
        _generating.discard(wq_pk)
        return {
            "content": {
                "mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看",
                "knowledge_patch": "",
                "review_task": "",
            },
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
            "error_code": "generation_in_progress",
            "retryable": True,
        }

    try:
        await db.refresh(wq)
        # The same wrong-question row can be updated while this request waits
        # for the cross-process generation lock. Recompute the digest so a
        # just-written cache is only reused if it matches the latest answer.
        input_signature = _analysis_input_signature(
            wq, q, knowledge_points, visual_sources=stored_visual_sources
        )
        if not effective_force:
            cached = build_cached_error_analysis_response(
                wq,
                requires_visual=requires_visual,
                expected_input_signature=input_signature,
                expected_model_signature=model_signature,
            )
            if cached is not None:
                logger.info(
                    "ai.error_analysis.cache_hit_after_lock wq_id=%d user_id=%d age_ms=%s",
                    wq.id,
                    user_id,
                    _analysis_cache_age_ms(wq.ai_analysis),
                )
                return cached

        image_data_urls, visual_meta = await _prepare_visual_inputs(q)
        structured_visual = str(visual_meta.get("structured_visual") or "")

        # If the question really contains a raster visual, every declared asset
        # failing to load is a hard failure.  A genuine text-only question has
        # zero images by design and should continue with a text LLM request.
        if requires_visual and not image_data_urls:
            logger.info(
                "ai.error_analysis.image_load_failed wq_id=%d question_id=%d declared_sources=%d",
                wq.id,
                q.id,
                int(visual_meta.get("declared_source_count") or 0),
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "vision_input_missing",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": 0,
                "error_code": "vision_input_missing",
                "retryable": False,
            }

        # Wrong-detail AI analysis must always use the same DB-configured
        # analysis LLM as the original text-only flow. Images are passed
        # directly to that model as multimodal message content; OCR/VL model
        # routing is intentionally not used here.
        if runtime is None:
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "vision_unavailable" if image_data_urls else "fallback",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
                "error_code": "ai_model_unconfigured",
                "retryable": False,
            }

        context = build_error_context(wq, q, knowledge_points)
        context["question"]["structured_visual"] = structured_visual
        answer_grounding = current_answer_grounding
        prompt_grounding = grounding_prompt_payload(answer_grounding)
        expected_answer_check = grounding_verification_payload(answer_grounding)
        # Persist only compact deterministic facts in the audit snapshot. They
        # contain no model reasoning and make future incident review reproducible.
        context["answer_grounding"] = prompt_grounding

        # Text and multimodal calls get the same provider budget. The mini-program
        # cannot hold one wx.request open for this entire duration; it times out
        # earlier and recovers the committed result through polling/recovery.
        model_timeout_sec = timeout_sec

        def _failure_response(
            *,
            error_code: str,
            retryable: bool,
            failure_model: str,
            duration_ms: int = 0,
        ) -> dict:
            old_cache = build_cached_error_analysis_response(
                wq,
                requires_visual=requires_visual,
                expected_input_signature=input_signature,
                expected_model_signature=model_signature,
            )
            if effective_force and old_cache is not None:
                old_cache["force_regenerated"] = False
                old_cache["cache_preserved"] = True
                old_cache["error_code"] = error_code
                old_cache["retryable"] = retryable
                return old_cache
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": failure_model,
                "duration_ms": duration_ms,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
                "error_code": error_code,
                "retryable": retryable,
            }

        # Keep provider selection and its one auth-failure failover beside the
        # cache/persistence contract so model selection remains observable.
        invocation = await invoke_analysis_provider(
            ProviderInvocationInput(
                db=db,
                runtime=runtime,
                chat=llm.chat,
                logger=logger,
                wrong_question_id=wq.id,
                force=effective_force,
                visual=bool(image_data_urls),
                question=context["question"],
                wrong_answer=wq.wrong_answer,
                correct_answer=q.answer,
                image_data_urls=image_data_urls,
                answer_grounding=prompt_grounding,
                model_timeout_sec=model_timeout_sec,
                max_tokens=_ERROR_ANALYSIS_MAX_TOKENS,
                timeout_guard_sec=ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS,
                resolve_runtime=_resolve_healthy_analysis_runtime,
                quarantine_runtime=_quarantine_analysis_runtime_auth,
                failure_response=_failure_response,
            )
        )
        result = invocation.result
        runtime = invocation.runtime
        model_signature = _analysis_model_signature(runtime)

        raw_content = result.get("content", "")
        parsed = parse_error_analysis_content(raw_content)
        parsed_valid = is_valid_ai_analysis(parsed)
        visual_evidence = (
            _extract_visual_evidence(raw_content) if image_data_urls else ""
        )
        visual_ack_retried = False
        visual_ack_retry_ms = 0
        total_tokens_used = int(result.get("tokens_used") or 0)
        total_duration_ms = int(result.get("duration_ms") or 0)

        grounding_valid = False
        grounding_guard_reason = "analysis_invalid"
        actual_answer_check = None
        if parsed_valid:
            grounding_valid, grounding_guard_reason, actual_answer_check = (
                _validate_answer_check(raw_content, expected_answer_check)
            )
            if grounding_valid:
                contradicts, contradiction_reason = diagnosis_contradicts_grounding(
                    parsed.get("mistake_diagnosis", ""), answer_grounding
                )
                if contradicts:
                    grounding_valid = False
                    grounding_guard_reason = (
                        contradiction_reason or "diagnosis_contradiction"
                    )

        if image_data_urls and not _visual_evidence_is_valid(visual_evidence):
            # A surprisingly common model-protocol failure is: the answer itself
            # clearly uses the image, all three analysis fields are valid, but the
            # model omitted the acknowledgement field.  Do one tiny SAME analysis
            # model visual probe instead of discarding an otherwise good answer.
            # No OCR/VL routing is introduced.
            if should_retry_visual_ack(
                parsed_valid=parsed_valid,
                grounding_valid=grounding_valid,
                duration_ms=total_duration_ms,
            ):
                ack = await retry_visual_ack(
                    image_data_urls,
                    runtime=runtime,
                    source_model=str(result.get("model") or ""),
                    wrong_question_id=wq.id,
                    current_evidence=visual_evidence,
                    chat=llm.chat,
                    extract_evidence=_extract_visual_evidence,
                )
                visual_ack_retried = ack.retried
                visual_ack_retry_ms = ack.retry_ms
                total_duration_ms += ack.retry_ms
                total_tokens_used += ack.tokens_used_delta
                visual_evidence = ack.evidence

        if image_data_urls and not _visual_evidence_is_valid(visual_evidence):
            evidence_text = str(visual_evidence or "").strip()
            ack_missing = not evidence_text
            error_code = "vision_ack_missing" if ack_missing else "vision_parse_failed"
            retryable = bool(ack_missing)
            logger.info(
                "ai.error_analysis.visual_ack_failed wq_id=%s model=%s evidence=%r "
                "retried=%s error_code=%s retryable=%s",
                wq.id,
                result.get("model"),
                evidence_text[:120],
                visual_ack_retried,
                error_code,
                retryable,
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "model": "vision_parse_failed",
                "tokens_used": total_tokens_used,
                "duration_ms": total_duration_ms,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
                "error_code": error_code,
                "retryable": retryable,
            }

        if not parsed_valid:
            resp = {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "model": "parse_failed",
                "tokens_used": 0,
                "duration_ms": 0,
                "visual_input_count": len(image_data_urls),
                "error_code": "ai_response_parse_failed",
                "retryable": True,
            }
            if effective_force:
                resp["force_regenerated"] = False
                resp["cache_preserved"] = False
            logger.info(
                "ai.error_analysis.empty wq_id=%s force=%s model=parse_failed",
                wq.id,
                effective_force,
            )
            return resp

        if not grounding_valid:
            # Fail closed: never persist/display an LLM response whose answer
            # facts disagree with deterministic server-side grading.  A compact
            # deterministic repair is still useful to the learner and prevents
            # repeated paid calls on every page open. Manual regeneration can
            # replace it once the configured model follows the contract.
            safe, generated_at = await persist_repaired_analysis(
                db,
                wrong_question=wq,
                user_id=user_id,
                context=context,
                result=result,
                answer_grounding=answer_grounding,
                visual_evidence=visual_evidence,
                visual_ack_retried=visual_ack_retried,
                visual_ack_retry_ms=visual_ack_retry_ms,
                image_count=len(image_data_urls),
                input_signature=input_signature,
                model_signature=model_signature,
                expected_answer_check=expected_answer_check,
                grounding_guard_reason=grounding_guard_reason,
                actual_answer_check=actual_answer_check,
                tokens_used=total_tokens_used,
                duration_ms=total_duration_ms,
                effective_force=effective_force,
                runtime=runtime,
            )
            logger.warning(
                "ai.error_analysis.grounding_repaired wq_id=%s force=%s model=%s reason=%s "
                "expected=%s actual=%s",
                wq.id,
                effective_force,
                result.get("model"),
                grounding_guard_reason,
                expected_answer_check,
                actual_answer_check,
            )
            return {
                "content": safe,
                "from_cache": False,
                "from_fallback": False,
                "tokens_used": total_tokens_used,
                "model": "grounding_guard",
                "duration_ms": total_duration_ms,
                "force_regenerated": effective_force,
                "visual_input_count": len(image_data_urls),
                "visual_evidence": visual_evidence or None,
                "input_mode": "vision" if image_data_urls else "text",
                "generated_at": generated_at,
                "grounding_repaired": True,
            }

        # The answer-difference sentence is always server generated. The model
        # contributes only the pedagogical reason after that authoritative fact.
        generated_at = await persist_valid_analysis(
            db,
            wrong_question=wq,
            user_id=user_id,
            context=context,
            result=result,
            parsed=parsed,
            answer_grounding=answer_grounding,
            visual_evidence=visual_evidence,
            visual_ack_retried=visual_ack_retried,
            visual_ack_retry_ms=visual_ack_retry_ms,
            image_count=len(image_data_urls),
            input_signature=input_signature,
            model_signature=model_signature,
            expected_answer_check=expected_answer_check,
            effective_force=effective_force,
            tokens_used=total_tokens_used,
            duration_ms=total_duration_ms,
            runtime=runtime,
        )

        logger.info(
            "ai.error_analysis.result wq_id=%s force=%s model=%s input_mode=%s visual_count=%s "
            "visual_evidence_valid=%s parsed_valid=%s compatibility=%s max_tokens=%s "
            "visual_ack_retried=%s visual_ack_retry_ms=%s "
            "fields=%s duration_ms=%s",
            wq.id,
            effective_force,
            result.get("model"),
            "vision" if image_data_urls else "text",
            len(image_data_urls),
            _visual_evidence_is_valid(visual_evidence) if image_data_urls else None,
            parsed_valid,
            result.get("compatibility_profile") or "default",
            _ERROR_ANALYSIS_MAX_TOKENS,
            visual_ack_retried,
            visual_ack_retry_ms,
            {
                k: bool(parsed.get(k))
                for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]
            },
            total_duration_ms,
        )

        return {
            "content": parsed,
            "from_cache": False,
            "from_fallback": False,
            "tokens_used": total_tokens_used,
            "model": result.get("model", ""),
            "duration_ms": total_duration_ms,
            "force_regenerated": effective_force,
            "visual_input_count": len(image_data_urls),
            "visual_evidence": visual_evidence or None,
            "input_mode": "vision" if image_data_urls else "text",
            "generated_at": parsed["_meta"]["generated_at"],
        }
    finally:
        _generating.discard(wq_pk)
        if have_lock:
            try:
                await cache.release_lock(lock_key, lock_value)
            except Exception:
                pass


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
    from app.core.database import async_session

    async with async_session() as bg_db:
        wq_result = await bg_db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id == wrong_question_id,
                WrongQuestion.user_id == user_id,
            )
        )
        wq = wq_result.scalar_one_or_none()
        if not wq:
            logger.info(
                "[prewarm] skipped_not_found id=%d uid=%d",
                wrong_question_id,
                user_id,
            )
            return skipped_not_found()

        if expected_revision:
            from app.ai.prewarm_revision import build_prewarm_revision

            current_revision = build_prewarm_revision(
                review_count=wq.review_count,
                wrong_answer=wq.wrong_answer,
            )
            if current_revision != expected_revision:
                logger.info(
                    "[prewarm] superseded id=%d uid=%d expected_revision=%s current_revision=%s",
                    wrong_question_id,
                    user_id,
                    expected_revision,
                    current_revision,
                )
                return superseded_revision()

        # A recovery task is queued only after the mini-program transport times
        # out. The original HTTP handler may still finish successfully. For force
        # regeneration, skip the backup call when a new persisted generation has
        # already replaced the baseline; otherwise the recovery task would cause a
        # second paid regeneration after the first one eventually completed.
        if force_regenerate and baseline_generated_at is not None:
            current_generated_at = ai_analysis_generated_at(wq.ai_analysis) or ""
            if current_generated_at != str(baseline_generated_at or ""):
                logger.info(
                    "[prewarm] recovery_superseded id=%d uid=%d baseline=%s current=%s",
                    wrong_question_id,
                    user_id,
                    baseline_generated_at or "empty",
                    current_generated_at or "empty",
                )
                return superseded_regenerated()

        result = await analyze_error(
            bg_db,
            user_id,
            wrong_question_id,
            force_regenerate=force_regenerate,
        )

        return finish_prewarm_result(
            result,
            wrong_question_id=wrong_question_id,
            user_id=user_id,
            expected_revision=expected_revision,
            logger=logger,
            failure_factory=_prewarm_failure_from_result,
        )


async def generate_advice(
    db: AsyncSession, user_id: int, subject_id: int | None = None
) -> dict:
    runtime = await resolve_llm_runtime_config(db, feature="analysis")

    if runtime is None:
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
