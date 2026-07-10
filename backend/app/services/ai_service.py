import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import deepseek
from app.ai.context import build_error_context
from app.ai.fallback import get_fallback_analysis, get_fallback_advice
from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION, build_error_analysis, build_study_advice
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion

logger = logging.getLogger(__name__)

ERROR_ANALYSIS_TIMEOUT_SECONDS = 25
ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS = 45

# 同进程内生成中锁，防止并发重复调用大模型
_generating: set[int] = set()


def _pick_field(d: dict, candidates: list[str]) -> str:
    """Return the first non-empty string value from a list of candidate keys."""
    for key in candidates:
        val = d.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ""


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
        return {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}

    # 去掉 markdown code fence
    stripped = re.sub(r'^```(?:json)?\s*\n?', '', text)
    stripped = re.sub(r'\n?```\s*$', '', stripped)

    parsed = None
    # 尝试直接 JSON 解析
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试提取第一个 {…}
    if not parsed:
        brace_start = stripped.find('{')
        brace_end = stripped.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            try:
                parsed = json.loads(stripped[brace_start:brace_end + 1])
            except (json.JSONDecodeError, ValueError):
                pass

    if isinstance(parsed, dict):
        result = {
            "mistake_diagnosis": _pick_field(parsed, ["mistake_diagnosis", "error_analysis", "diagnosis", "mistakeDiagnosis", "mistakediagnosis", "错因诊断"]),
            "knowledge_patch": _pick_field(parsed, ["knowledge_patch", "knowledge_weakness", "knowledge", "knowledgePatch", "knowledgepatch", "补漏重点"]),
            "review_task": _pick_field(parsed, ["review_task", "suggestion", "task", "reviewTask", "reviewtask", "reviewask", "复练任务"]),
        }
        # 字段值本身可能是 JSON 字符串，需要递归解包
        for key in result:
            val = result[key]
            if isinstance(val, str) and val.strip().startswith("{"):
                try:
                    inner = json.loads(val)
                    if isinstance(inner, dict):
                        result[key] = _pick_field(inner, ["mistake_diagnosis", "error_analysis", "diagnosis", "mistakeDiagnosis", "mistakediagnosis", "错因诊断", "knowledge_patch", "knowledge", "review_task", "suggestion", "text", "content"])
                except (json.JSONDecodeError, ValueError):
                    pass
        return result

    # 非 JSON：尝试按中文标题切分
    sections = re.split(r'(?:^|\n)(?:(?:错因诊断|补漏重点|复练任务)\s*[：:]\s*)', stripped)
    return {
        "mistake_diagnosis": sections[1].strip() if len(sections) > 1 else stripped,
        "knowledge_patch": sections[2].strip() if len(sections) > 2 else "",
        "review_task": sections[3].strip() if len(sections) > 3 else "",
    }


def is_valid_ai_analysis(content: dict) -> bool:
    return any(str(content.get(k, "")).strip() for k in ["mistake_diagnosis", "knowledge_patch", "review_task"])


def _normalize_ai_analysis(cached: dict) -> dict:
    """Convert any field-name format to canonical snake_case."""
    if not cached:
        return {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}
    # If canonical fields already have content, return as-is
    if str(cached.get("mistake_diagnosis", "")).strip() or str(cached.get("knowledge_patch", "")).strip() or str(cached.get("review_task", "")).strip():
        return cached
    return {
        "mistake_diagnosis": _pick_field(cached, ["mistake_diagnosis", "error_analysis", "diagnosis", "mistakeDiagnosis", "mistakediagnosis", "错因诊断"]),
        "knowledge_patch": _pick_field(cached, ["knowledge_patch", "knowledge_weakness", "knowledge", "knowledgePatch", "knowledgepatch", "补漏重点"]),
        "review_task": _pick_field(cached, ["review_task", "suggestion", "task", "reviewTask", "reviewtask", "reviewask", "复练任务"]),
    }


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
    lock_value = str(user_id)
    try:
        have_lock = await cache.acquire_lock(lock_key, lock_value, ttl=60)
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

        context = build_error_context(wq, q)
        messages = build_error_analysis(
            context["question"], wq.wrong_answer, q.answer
        )

        timeout_sec = ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS if force_regenerate else ERROR_ANALYSIS_TIMEOUT_SECONDS
        try:
            async with asyncio.timeout(timeout_sec):
                result = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
        except asyncio.TimeoutError:
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
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
    """后台预生成错题 AI 分析。独立 session，失败仅记录日志，不抛异常。"""
    import logging
    logger = logging.getLogger(__name__)
    try:
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
    except Exception:
        logger.exception("[prewarm] failed id=%d uid=%d", wrong_question_id, user_id)


async def generate_advice(db: AsyncSession, user_id: int, subject: str | None = None) -> dict:
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

    weak_points = set()
    subject_stats = {}
    recent_wrong = []
    for w in wrong_list:
        q = questions.get(w.question_id)
        if q:
            if q.knowledge_points:
                weak_points.update(q.knowledge_points)
            # Use subject_id as label (subject_ref is noload, always None without selectinload)
            subj_label = str(q.subject_id)
            subject_stats[subj_label] = subject_stats.get(subj_label, 0) + 1
            recent_wrong.append({
                "subject": subj_label,
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
