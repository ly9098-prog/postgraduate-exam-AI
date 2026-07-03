import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import deepseek
from app.ai.context import build_error_context
from app.ai.fallback import get_fallback_analysis, get_fallback_advice
from app.ai.prompts import build_error_analysis, build_study_advice
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion

ERROR_ANALYSIS_TIMEOUT_SECONDS = 25

# 同进程内生成中锁，防止并发重复调用大模型
_generating: set[int] = set()


async def analyze_error(
    db: AsyncSession, user_id: int, wrong_question_id: int
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

    # Check cache — convert old format to new field names
    if wq.ai_analysis and isinstance(wq.ai_analysis, dict):
        cached = wq.ai_analysis
        if "mistake_diagnosis" not in cached:
            cached = {
                "mistake_diagnosis": cached.get("error_analysis", ""),
                "knowledge_patch": cached.get("knowledge_weakness", ""),
                "review_task": cached.get("suggestion", ""),
            }
        return {
            "content": cached,
            "from_cache": True,
            "from_fallback": False,
            "tokens_used": 0,
            "model": "cache",
            "duration_ms": 0,
        }

    # 并发保护：防止同一道题重复调用大模型
    wq_pk = wq.id
    if wq_pk in _generating:
        # 已在生成中，返回临时状态，前端会展示 fallback 提示
        return {
            "content": {"mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看", "knowledge_patch": "", "review_task": ""},
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
        }
    _generating.add(wq_pk)
    try:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db, feature="analysis")

        if not creds:
            fallback = get_fallback_analysis()
            return {
                "content": fallback,
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 0,
            }

        api_key, base_url, model_name = creds

        context = build_error_context(wq, q)
        messages = build_error_analysis(
            context["question"], wq.wrong_answer, q.answer
        )

        try:
            async with asyncio.timeout(ERROR_ANALYSIS_TIMEOUT_SECONDS):
                result = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
        except Exception:
            fallback = get_fallback_analysis()
            return {
                "content": fallback,
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": ERROR_ANALYSIS_TIMEOUT_SECONDS * 1000,
            }

        try:
            parsed = json.loads(result["content"])
        except (json.JSONDecodeError, KeyError):
            parsed = {"mistake_diagnosis": result["content"], "knowledge_patch": "", "review_task": ""}

        # 附加元信息
        parsed["_meta"] = {
            "model": result.get("model", model_name or ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": "v1",
            "from_fallback": False,
        }

        # 持久化到 wrong_questions.ai_analysis（非 fallback 才保存）
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

        return {
            "content": parsed,
            "from_cache": False,
            "from_fallback": False,
            "tokens_used": result["tokens_used"],
            "model": result["model"],
            "duration_ms": result["duration_ms"],
        }
    finally:
        _generating.discard(wq_pk)


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
            # 已有缓存则跳过
            if wq.ai_analysis and isinstance(wq.ai_analysis, dict) and len(wq.ai_analysis) > 0:
                logger.info("[prewarm] already cached id=%d uid=%d", wrong_question_id, user_id)
                return
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
