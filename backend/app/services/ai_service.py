import ast
import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import deepseek
from app.ai.context import build_error_context
from app.ai.fallback import get_fallback_advice, get_fallback_analysis
from app.ai.prompts import (
    AI_ANALYSIS_PROMPT_VERSION,
    build_error_analysis,
    build_study_advice,
)
from app.core.config import settings
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.knowledge_point_service import load_question_kps

logger = logging.getLogger(__name__)

# 微信小程序请求链路通常只有约 60 秒可用。模型调用必须在该预算内结束，
# 同时不能继续沿用原来的 25 秒硬截断，否则大量本可成功的请求会被误判超时。
_CONFIGURED_AI_TIMEOUT_SECONDS = max(10, int(settings.AI_TIMEOUT or 50))
ERROR_ANALYSIS_TIMEOUT_SECONDS = min(_CONFIGURED_AI_TIMEOUT_SECONDS, 48)
ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS = min(_CONFIGURED_AI_TIMEOUT_SECONDS, 50)
ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS = 2
ERROR_ANALYSIS_LOCK_GRACE_SECONDS = 15

# 同进程内生成中锁，防止并发重复调用大模型
_generating: set[int] = set()


def _pick_field(d: dict, candidates: list[str]) -> str:
    """Return the first non-empty normalized value from candidate keys."""
    for key in candidates:
        if key not in d:
            continue
        val = _coerce_analysis_text(d.get(key))
        if val:
            return val
    return ""


_ANALYSIS_WRAPPER_KEYS = ("content", "data", "result", "analysis", "ai_analysis", "payload")
_ANALYSIS_TEXT_KEYS = ("text", "content", "value", "description")
_DIAGNOSIS_KEYS = ("mistake_diagnosis", "error_analysis", "diagnosis", "mistakeDiagnosis", "mistakediagnosis", "错因诊断")
_KNOWLEDGE_KEYS = ("knowledge_patch", "knowledge_weakness", "knowledge", "knowledgePatch", "knowledgepatch", "补漏重点")
_TASK_KEYS = ("review_task", "suggestion", "task", "reviewTask", "reviewtask", "reviewask", "复练任务")
_EMPTY_ANALYSIS = {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}


def _coerce_analysis_text(value, depth: int = 0) -> str:
    """Normalize common model field shapes (string/list/nested object) to text."""
    if value is None or depth > 6:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_analysis_text(item, depth + 1)
            if text and text not in parts:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in _ANALYSIS_TEXT_KEYS:
            if key in value:
                text = _coerce_analysis_text(value.get(key), depth + 1)
                if text:
                    return text
        # 某些模型会把正文放进只有一个字段的对象中。
        if len(value) == 1:
            return _coerce_analysis_text(next(iter(value.values())), depth + 1)
    return ""


def _extract_analysis_fields(value, depth: int = 0) -> dict:
    if depth > 6 or value is None:
        return dict(_EMPTY_ANALYSIS)

    if isinstance(value, str):
        decoded = _decode_structured_content(value)
        if decoded is not None and not (
            isinstance(decoded, str) and decoded.strip() == value.strip()
        ):
            return _extract_analysis_fields(decoded, depth + 1)
        return _parse_titled_analysis_text(value)

    if isinstance(value, list):
        best = dict(_EMPTY_ANALYSIS)
        best_score = -1
        for item in value:
            candidate = _extract_analysis_fields(item, depth + 1)
            score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
            if score > best_score:
                best = candidate
                best_score = score
        if best_score > 0:
            return best
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    if not isinstance(value, dict):
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    direct = {
        "mistake_diagnosis": _pick_field(value, list(_DIAGNOSIS_KEYS)),
        "knowledge_patch": _pick_field(value, list(_KNOWLEDGE_KEYS)),
        "review_task": _pick_field(value, list(_TASK_KEYS)),
    }
    if is_valid_ai_analysis(direct):
        return direct

    # 优先解包常见响应包装层，再兜底搜索其余嵌套对象。
    nested_values = [value[key] for key in _ANALYSIS_WRAPPER_KEYS if key in value]
    nested_values.extend(v for k, v in value.items() if k not in _ANALYSIS_WRAPPER_KEYS and isinstance(v, (dict, list, str)))
    best = direct
    best_score = 0
    for nested in nested_values:
        candidate = _extract_analysis_fields(nested, depth + 1)
        score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
        if score > best_score:
            best = candidate
            best_score = score
            if score == 3:
                break
    return best


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()


def _decode_structured_content(raw: str):
    """Decode JSON/Python-literal model output, including text around the object."""
    text = _strip_code_fence((raw or "").strip())
    if not text:
        return None

    starts = [0]
    starts.extend(i for i, ch in enumerate(text) if i > 0 and ch in "{[")
    decoder = json.JSONDecoder()
    for start in starts:
        candidate = text[start:].lstrip()
        if not candidate:
            continue
        try:
            value, _ = decoder.raw_decode(candidate)
            return value
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            value = ast.literal_eval(candidate)
            if isinstance(value, (dict, list, str)):
                return value
        except (SyntaxError, ValueError):
            pass
    return None


def _parse_titled_analysis_text(text: str) -> dict:
    stripped = _strip_code_fence(text)
    heading_re = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?(?:[-*]\s*)?"
        r"(?:\*\*)?\s*(错因诊断|补漏重点|复练任务)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*"
    )
    matches = list(heading_re.finditer(stripped))
    if not matches:
        return {"mistake_diagnosis": stripped, "knowledge_patch": "", "review_task": ""}

    result = dict(_EMPTY_ANALYSIS)
    key_map = {"错因诊断": "mistake_diagnosis", "补漏重点": "knowledge_patch", "复练任务": "review_task"}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        result[key_map[match.group(1)]] = stripped[match.end():end].strip()
    return result


def parse_error_analysis_content(raw: str) -> dict:
    """
    鲁棒解析 AI 返回内容，兼容：
    1. 标准 JSON
    2. ```json ... ``` 代码块
    3. JSON 前后有解释文字
    4. 字段名不完全一致（snake_case / camelCase / 全小写 / 中文）
    5. 字段值为 JSON 字符串（自动解包）
    6. 非 JSON 但包含三段式中文文本
    返回结构：{mistake_diagnosis, knowledge_patch, review_task}
    """
    text = (raw or '').strip()
    if not text:
        return dict(_EMPTY_ANALYSIS)
    decoded = _decode_structured_content(text)
    return _extract_analysis_fields(decoded if decoded is not None else text)


def is_valid_ai_analysis(content: dict) -> bool:
    return any(str(content.get(k, "")).strip() for k in ["mistake_diagnosis", "knowledge_patch", "review_task"])


def _normalize_ai_analysis(cached: dict) -> dict:
    """Convert any field-name format to canonical snake_case."""
    return _extract_analysis_fields(cached) if cached else dict(_EMPTY_ANALYSIS)


def is_ai_analysis_fresh(ai_analysis: dict | None) -> bool:
    """Check whether the cached AI analysis is still valid for the current prompt version."""
    if not isinstance(ai_analysis, dict) or len(ai_analysis) == 0:
        return False
    cached_version = (ai_analysis.get("_meta") or {}).get("version", "")
    return cached_version == AI_ANALYSIS_PROMPT_VERSION


def build_cached_error_analysis_response(wq) -> dict | None:
    """If the wrong question has a fresh cached AI analysis, return it; otherwise None."""
    if not is_ai_analysis_fresh(wq.ai_analysis):
        return None
    return {
        "content": _normalize_ai_analysis(wq.ai_analysis),
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache",
        "duration_ms": 0,
    }


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
    return {
        "content": content,
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache_preserved",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": True,
    }


async def analyze_error(
    db: AsyncSession, user_id: int, wrong_question_id: int,
    force_regenerate: bool = False,
) -> dict:
    wq = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == user_id,
        )
    )
    wq = wq.scalar_one_or_none()
    if not wq:
        raise ValueError("错题记录不存在")

    q = await db.execute(
        select(Question).where(Question.id == wq.question_id)
    )
    q = q.scalar_one_or_none()
    if not q:
        raise ValueError("题目不存在")

    # Check cache — 版本不匹配时跳过缓存以重新生成
    if not force_regenerate:
        cached = build_cached_error_analysis_response(wq)
        if cached is not None:
            return cached
    else:
        import logging
        logging.getLogger(__name__).info(
            "force regenerate error analysis wq_id=%d user_id=%d", wq.id, user_id,
        )

    timeout_sec = ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS if force_regenerate else ERROR_ANALYSIS_TIMEOUT_SECONDS

    # 分布式锁：防止并发重复调用大模型（跨进程）
    # 先用进程内集合做快速检测，再用 Redis 分布式锁
    wq_pk = wq.id
    if wq_pk in _generating:
        return {
            "content": {"mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看", "knowledge_patch": "", "review_task": ""},
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
        }
    _generating.add(wq_pk)

    from app.core.cache import cache
    lock_key = f"ai:error_analysis:{wq_pk}"
    # 必须使用每次请求唯一的 owner token。仅用 user_id 时，旧请求可能误删
    # 同一用户后续请求重新获取的锁。
    lock_value = f"{user_id}:{uuid.uuid4().hex}"
    lock_ttl = timeout_sec + ERROR_ANALYSIS_LOCK_GRACE_SECONDS
    try:
        have_lock = await cache.acquire_lock(lock_key, lock_value, ttl=lock_ttl)
    except Exception:
        # acquire_lock 异常时清除进程内锁，防止泄漏
        _generating.discard(wq_pk)
        raise
    if not have_lock and cache.is_enabled:
        # Redis 不可用时降级到进程内锁；Redis 可用但锁已被占则返回 generating
        _generating.discard(wq_pk)
        return {
            "content": {"mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看", "knowledge_patch": "", "review_task": ""},
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
        }

    try:
        # 获取锁后二次检查缓存（另一个进程可能刚写入）
        await db.refresh(wq)
        if not force_regenerate:
            cached = build_cached_error_analysis_response(wq)
            if cached is not None:
                _generating.discard(wq_pk)
                return cached

        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db, feature="analysis")

        if not creds:
            # force_regenerate 失败时有旧缓存则返回旧缓存
            old_cache = build_any_cached_error_analysis_response(wq)
            if old_cache and force_regenerate:
                _generating.discard(wq_pk)
                return old_cache
            # 无旧缓存时才返回 fallback
            _generating.discard(wq_pk)
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
            }

        api_key, base_url, model_name = creds

        kp_map = await load_question_kps(db, [q.id])
        context = build_error_context(wq, q, kp_map.get(q.id, []))
        messages = build_error_analysis(
            context["question"], wq.wrong_answer, q.answer
        )

        try:
            # deepseek.chat 内部是阻塞 HTTP 在线程池中执行。把相同的超时显式传入
            # 底层 socket，避免只取消 await、但后台线程仍继续占用资源并丢失结果。
            async with asyncio.timeout(timeout_sec + ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS):
                result = await deepseek.chat(
                    messages,
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout_sec,
                )
        except TimeoutError:
            old_cache = build_any_cached_error_analysis_response(wq)
            logger.warning(
                "ai.error_analysis.timeout wq_id=%s force=%s timeout_sec=%s has_old_cache=%s",
                wq.id, force_regenerate, timeout_sec, bool(old_cache),
            )
            if old_cache and force_regenerate:
                _generating.discard(wq_pk)
                return old_cache
            resp = {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "timeout",
                "duration_ms": timeout_sec * 1000,
                "force_regenerated": False,
                "cache_preserved": False,
            }
            return resp
        except Exception as e:
            old_cache = build_any_cached_error_analysis_response(wq)
            logger.exception(
                "ai.error_analysis.exception wq_id=%s force=%s err=%s has_old_cache=%s",
                wq.id, force_regenerate, repr(e), bool(old_cache),
            )
            if old_cache and force_regenerate:
                _generating.discard(wq_pk)
                return old_cache
            resp = {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 25000,
                "force_regenerated": False,
                "cache_preserved": False,
            }
            return resp

        raw_content = result.get("content", "")
        parsed = parse_error_analysis_content(raw_content)
        parsed_valid = is_valid_ai_analysis(parsed)

        if not parsed_valid:
            old_cache = build_any_cached_error_analysis_response(wq)
            if old_cache and force_regenerate:
                _generating.discard(wq_pk)
                return old_cache
            # 无有效内容且无旧缓存：返回 fallback，不保存
            fallback = get_fallback_analysis()
            resp = {
                "content": fallback,
                "from_cache": False,
                "from_fallback": True,
                "model": "parse_failed",
                "tokens_used": 0,
                "duration_ms": 0,
            }
            if force_regenerate:
                resp["force_regenerated"] = False
                resp["cache_preserved"] = False
            logger.info(
                "ai.error_analysis.empty wq_id=%s force=%s model=parse_failed",
                wq.id, force_regenerate,
            )
            return resp

        # 附加元信息
        parsed["_meta"] = {
            "model": result.get("model", model_name or ""),
            "generated_at": datetime.now(UTC).isoformat(),
            "version": AI_ANALYSIS_PROMPT_VERSION,
            "from_fallback": False,
            "force_regenerated": force_regenerate,
        }

        # 持久化到 wrong_questions.ai_analysis（仅有效非 fallback 才保存）
        wq.ai_analysis = parsed
        await db.commit()

        # Log chat
        db.add(AiChat(
            user_id=user_id,
            session_type="error_analysis",
            user_message=str(context["question"]),
            ai_response=result["content"],
            context_snapshot=context,
            tokens_used=result["tokens_used"],
            model=result["model"],
            duration_ms=result["duration_ms"],
        ))
        await db.commit()

        logger.info(
            "ai.error_analysis.result wq_id=%s force=%s model=%s from_fallback=%s parsed_valid=%s fields=%s duration_ms=%s",
            wq.id, force_regenerate, result.get("model"), False, parsed_valid,
            {k: bool(parsed.get(k)) for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]},
            result.get("duration_ms"),
        )

        return {
            "content": parsed,
            "from_cache": False,
            "from_fallback": False,
            "tokens_used": result.get("tokens_used", 0),
            "model": result.get("model", model_name or ""),
            "duration_ms": result.get("duration_ms", 0),
            "force_regenerated": force_regenerate,
        }
    finally:
        _generating.discard(wq_pk)
        if have_lock:
            try:
                await cache.release_lock(lock_key, lock_value)
            except Exception:
                pass


async def prewarm_wrong_question_analysis(
    wrong_question_id: int, user_id: int,
) -> None:
    """后台预生成错题 AI 分析。独立 session。

    Exceptions propagate to the durable worker, which handles retry/dead-letter
    via the failing task's fail_v2 path. The function itself does NOT catch
    exceptions to allow proper retry semantics.
    """
    import logging
    logger = logging.getLogger(__name__)
    from app.core.database import async_session
    async with async_session() as bg_db:
        wq = await bg_db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id == wrong_question_id,
                WrongQuestion.user_id == user_id,
            )
        )
        wq = wq.scalar_one_or_none()
        if not wq:
            logger.info("[prewarm] wrong_question not found id=%d uid=%d", wrong_question_id, user_id)
            return
        # 已有 fresh 缓存则跳过（版本不匹配时触发重新生成）
        if is_ai_analysis_fresh(wq.ai_analysis):
            logger.info("[prewarm] fresh cache exists id=%d uid=%d", wrong_question_id, user_id)
            return
        if wq.ai_analysis and not is_ai_analysis_fresh(wq.ai_analysis):
            logger.info("[prewarm] stale cache (version mismatch) id=%d uid=%d", wrong_question_id, user_id)
        # 复用现有 analyze_error 逻辑
        result = await analyze_error(bg_db, user_id, wrong_question_id)
        logger.info(
            "[prewarm] done id=%d uid=%d from_cache=%s from_fallback=%s",
            wrong_question_id, user_id,
            result.get("from_cache"), result.get("from_fallback"),
        )


async def generate_advice(db: AsyncSession, user_id: int, subject_id: int | None = None) -> dict:
    from app.services.model_config_resolver import ensure_db_model_configured
    creds = await ensure_db_model_configured(db, feature="analysis")

    api_key = creds[0] if creds else None
    base_url = creds[1] if creds else None
    model_name = creds[2] if creds else None

    if not (api_key or deepseek.is_available()):
        return {
            "content": get_fallback_advice(),
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "fallback",
            "duration_ms": 0,
        }

    # Collect user's wrong question stats
    conditions = [WrongQuestion.user_id == user_id]
    result = await db.execute(
        select(WrongQuestion).where(*conditions).limit(10)
    )
    wrong_list = result.scalars().all()

    qids = [w.question_id for w in wrong_list]
    questions = {}
    if qids:
        qr = await db.execute(
            select(Question).where(Question.id.in_(qids))
        )
        questions = {q.id: q for q in qr.scalars().all()}
    kp_map = await load_question_kps(db, qids)

    weak_points = set()
    subject_stats = {}
    recent_wrong = []
    for w in wrong_list:
        q = questions.get(w.question_id)
        if q:
            weak_points.update(kp_map.get(q.id, []))
            # Use subject_id as label (subject_ref is noload, always None without selectinload)
            subj_label = str(q.subject_id)
            subject_stats[subj_label] = subject_stats.get(subj_label, 0) + 1
            recent_wrong.append({
                "subject_id": q.subject_id,
                "error_type": w.error_type,
                "wrong_answer": w.wrong_answer,
                "correct_answer": q.answer,
            })

    messages = build_study_advice(
        [{"subject": k, "count": v} for k, v in subject_stats.items()],
        list(weak_points),
        recent_wrong,
    )

    try:
        result = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
    except Exception:
        fallback = get_fallback_advice()
        return {
            "content": fallback,
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "fallback",
            "duration_ms": 0,
        }

    try:
        parsed = json.loads(result["content"])
    except (json.JSONDecodeError, KeyError):
        parsed = {"overall_assessment": result["content"]}

    db.add(AiChat(
        user_id=user_id,
        session_type="study_advice",
        user_message=str(subject_stats),
        ai_response=result["content"],
        tokens_used=result["tokens_used"],
        model=result["model"],
        duration_ms=result["duration_ms"],
    ))
    await db.commit()

    return {
        "content": parsed,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": result["tokens_used"],
        "model": result["model"],
        "duration_ms": result["duration_ms"],
    }
