"""AI 学习引擎核心服务。"""

import json
import logging
import random
from datetime import timedelta

logger = logging.getLogger(__name__)

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import chat_with_db_model
from app.ai.fallback import (
    get_fallback_explain,
    get_fallback_mistake_analysis,
    get_fallback_report,
)
from app.ai.prompts_learning import (
    build_explain_prompt,
    build_mistake_analysis_prompt,
    build_report_prompt,
)
from app.core.config import settings
from app.core.time_utils import shanghai_date_utc_range, shanghai_today, utcnow
from app.models.ai_chat import AiChat
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.services.admin_subject_service import resolve_subject_ids
from app.services.knowledge_point_service import load_question_kps

# ============================================================
# Token 用量控制
# ============================================================


async def _check_token_limit(db: AsyncSession, user_id: int, tokens_needed: int = 0) -> bool:
    """检查用户是否超出 token 限额（日 + 月）。返回 True 表示可以继续调用。"""
    daily_limit = settings.AI_DAILY_TOKEN_LIMIT
    monthly_limit = settings.AI_MONTHLY_TOKEN_LIMIT

    if daily_limit <= 0 and monthly_limit <= 0:
        return True

    today_date = shanghai_today()
    today = shanghai_date_utc_range(today_date)[0]
    first_of_month = shanghai_date_utc_range(today_date.replace(day=1))[0]

    # One indexed user/month scan instead of two round-trips.  The monthly
    # predicate bounds the row set; CASE derives the daily subtotal from the
    # same scan.
    result = await db.execute(
        select(
            func.coalesce(
                func.sum(case((AiChat.created_at >= today, AiChat.tokens_used), else_=0)),
                0,
            ),
            func.coalesce(func.sum(AiChat.tokens_used), 0),
        ).where(
            AiChat.user_id == user_id,
            AiChat.created_at >= first_of_month,
        )
    )
    used_today, used_monthly = result.one()

    if daily_limit > 0 and (int(used_today or 0) + tokens_needed) > daily_limit:
        return False
    if monthly_limit > 0 and (int(used_monthly or 0) + tokens_needed) > monthly_limit:
        return False

    return True


async def _record_token_usage(
    db: AsyncSession,
    user_id: int,
    session_type: str,
    user_message: str,
    ai_response: str,
    result: dict,
) -> None:
    """记录 AI 调用 token 用量到 AiChat。"""
    db.add(
        AiChat(
            user_id=user_id,
            session_type=session_type,
            user_message=user_message[:500],
            ai_response=ai_response[:2000],
            tokens_used=result.get("tokens_used", 0),
            model=result.get("model", "unknown"),
            duration_ms=result.get("duration_ms", 0),
        )
    )
    await db.commit()


async def _call_ai(messages: list, db: AsyncSession | None = None) -> dict | None:
    """调用后台配置的 OpenAI-compatible 分析模型，失败返回 None。"""
    if db is None:
        return None
    try:
        return await chat_with_db_model(db, messages, feature="analysis")
    except RuntimeError:
        return None


def _parse_json_response(content: str) -> dict | None:
    """解析 AI 返回的 JSON，支持 markdown code fence。"""
    if not content:
        return None
    # 尝试提取 ```json ... ``` 中的内容
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) > 1 and lines[-1].strip() == "```":
            content = "\n".join(lines[1:-1])
            if content.startswith("json"):
                content = content[4:]
    # 尝试查找 JSON 对象
    brace_start = content.find("{")
    if brace_start == -1:
        return None
    brace_end = content.rfind("}")
    if brace_end == -1:
        return None
    try:
        return json.loads(content[brace_start : brace_end + 1])
    except (json.JSONDecodeError, KeyError):
        return None


# ============================================================
# AI 题目讲解
# ============================================================


async def ai_explain(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str | None = None,
    is_correct: bool | None = None,
    focus: str = "solution",
) -> dict:
    """AI 题目讲解。"""

    q = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active)
    )
    q = q.scalar_one_or_none()
    if not q:
        raise ValueError("题目不存在")

    kp_map = await load_question_kps(db, [q.id])
    q_kps = kp_map.get(q.id, [])

    # 构造 context
    stem = q.content.get("text", "") if isinstance(q.content, dict) else str(q.content or "")

    messages = build_explain_prompt(
        stem=stem,
        options=q.options,
        answer=q.answer,
        analysis=q.analysis,
        knowledge_points=q_kps,
        user_answer=user_answer,
        is_correct=is_correct,
        focus=focus,
    )

    # 检查 token 限额
    if not await _check_token_limit(db, user_id, 500):
        return {
            "question_id": question_id,
            "explanation": "今日 AI 调用额度已用尽，请明天再试。",
            "solution_steps": [],
            "key_knowledge_points": q_kps,
            "common_mistakes": [],
            "tokens_used": 0,
            "from_fallback": True,
        }

    result = await _call_ai(messages, db)

    if result is None:
        fallback = get_fallback_explain()
        return {
            "question_id": question_id,
            "explanation": fallback["explanation"],
            "solution_steps": [],
            "key_knowledge_points": q_kps,
            "common_mistakes": [],
            "tokens_used": 0,
            "from_fallback": True,
        }

    parsed = _parse_json_response(result["content"])
    if parsed is None:
        parsed = {"explanation": result["content"], "solution_steps": [], "key_knowledge_points": [], "common_mistakes": []}

    await _record_token_usage(
        db, user_id, "ai_explain",
        f"question_id={question_id} focus={focus}",
        result["content"], result,
    )

    return {
        "question_id": question_id,
        "explanation": parsed.get("explanation", ""),
        "solution_steps": parsed.get("solution_steps", []),
        "key_knowledge_points": parsed.get("key_knowledge_points", []),
        "common_mistakes": parsed.get("common_mistakes", []),
        "tokens_used": result["tokens_used"],
        "from_fallback": False,
    }


# ============================================================
# AI 错因分析
# ============================================================


async def ai_analyze_mistake(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    correct_answer: str,
) -> dict:
    """AI 错因分析。"""

    q = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active)
    )
    q = q.scalar_one_or_none()
    if not q:
        raise ValueError("题目不存在")

    stem = q.content.get("text", "") if isinstance(q.content, dict) else str(q.content or "")

    messages = build_mistake_analysis_prompt(
        stem=stem,
        options=q.options,
        correct_answer=correct_answer,
        user_answer=user_answer,
        analysis=q.analysis,
    )

    if not await _check_token_limit(db, user_id, 300):
        return {
            "error_type": "limit_exceeded",
            "error_type_label": "额度用尽",
            "analysis": "今日 AI 调用额度已用尽，请明天再试。",
            "suggestion": "建议自行查看题目解析。",
            "tokens_used": 0,
            "from_fallback": True,
        }

    result = await _call_ai(messages, db)

    if result is None:
        fallback = get_fallback_mistake_analysis()
        return {
            "error_type": fallback["error_type"],
            "error_type_label": fallback["error_type_label"],
            "analysis": fallback["analysis"],
            "suggestion": fallback["suggestion"],
            "tokens_used": 0,
            "from_fallback": True,
        }

    parsed = _parse_json_response(result["content"])
    if parsed is None:
        parsed = {"error_type": "unknown", "analysis": result["content"], "suggestion": ""}

    error_type = parsed.get("error_type", "unknown")
    label_map = {
        "概念理解错误": "概念理解错误",
        "计算错误": "计算错误",
        "审题错误": "审题错误",
        "思路错误": "思路错误",
        "concept_misunderstanding": "概念理解错误",
        "calculation_error": "计算错误",
        "misreading": "审题错误",
        "approach_error": "思路错误",
    }

    await _record_token_usage(
        db, user_id, "mistake_analysis",
        f"question_id={question_id}",
        result["content"], result,
    )

    return {
        "error_type": error_type,
        "error_type_label": label_map.get(error_type, parsed.get("error_type", "未知")),
        "analysis": parsed.get("analysis", ""),
        "suggestion": parsed.get("suggestion", ""),
        "tokens_used": result["tokens_used"],
        "from_fallback": False,
    }


# ============================================================
# 相似题推荐（规则推荐，非 AI）
# ============================================================


async def recommend_similar_questions(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    count: int = 5,
) -> dict:
    """推荐相似题目（向量优先 + 规则兜底）。"""

    # ── 向量优先 ──
    try:
        from app.services import vector_retrieval_service

        vector_result = await vector_retrieval_service.search_similar_questions(
            db=db,
            user_id=user_id,
            question_id=question_id,
            count=count,
            exclude_answered=True,
        )
        if vector_result.get("enabled") and vector_result.get("recommendations"):
            return {
                "source_question_id": question_id,
                "recommendations": vector_result["recommendations"],
                "strategy": "vector_plus_rule",
                "tokens_used": 0,
            }
    except Exception:
        logger.warning("向量推荐异常，回退到规则推荐", exc_info=True)

    # ── 规则推荐（原有逻辑） ──

    q = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active)
    )
    q = q.scalar_one_or_none()
    if not q:
        raise ValueError("题目不存在")

    # 获取用户已做过的题目 ID
    answered_result = await db.execute(
        select(PracticeRecord.question_id).where(PracticeRecord.user_id == user_id)
    )
    answered_ids = {row[0] for row in answered_result.all()}
    answered_ids.add(question_id)  # 排除自身

    # 同 subject 候选
    candidates_result = await db.execute(
        select(Question).where(
            Question.subject_id.in_(await resolve_subject_ids(db, q.subject_id)),
            Question.is_active,
            Question.review_status == "approved",
        )
    )
    candidates = candidates_result.scalars().all()

    kp_map = await load_question_kps(db, [q.id] + [c.id for c in candidates])
    source_kps = set(kp_map.get(q.id, []))

    # 按知识点重叠度 + 难度匹配打分排序
    scored = []
    for c in candidates:
        if c.id in answered_ids:
            continue
        c_kps = set(kp_map.get(c.id, []))
        kp_overlap = len(source_kps & c_kps)
        difficulty_match = 1 if c.difficulty == q.difficulty else 0
        score = kp_overlap * 2 + difficulty_match
        if score > 0:
            scored.append((score, c))

    # 按分数降序排列，取前 N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:count]

    # 随机打乱前 N 的结果
    random.shuffle(top)

    recommendations = []
    for _, c in top:
        kps = kp_map.get(c.id, [])
        match_reasons = []
        if set(kps) & source_kps:
            match_reasons.append("同知识点")
        if c.difficulty == q.difficulty:
            match_reasons.append("同难度")
        if not match_reasons:
            match_reasons.append("同科目")

        stem = c.content.get("text", "") if isinstance(c.content, dict) else str(c.content or "")

        recommendations.append({
            "question_id": c.id,
            "subject_id": c.subject_id,
            "subject_code": c.subject_ref.code if c.subject_ref else "",
            "subject_name": c.subject_ref.name if c.subject_ref else "",
            "question_type": c.question_type,
            "stem": stem[:200],
            "knowledge_points": kps,
            "match_reason": " + ".join(match_reasons),
        })

    return {
        "source_question_id": question_id,
        "recommendations": recommendations,
        "strategy": "rule_based",
        "tokens_used": 0,
    }


# ============================================================
# AI 学习报告
# ============================================================


async def generate_learning_report(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    days: int = 7,
) -> dict:
    """生成 AI 学习报告。"""
    from app.models.admin import Subject

    subj = await db.get(Subject, subject_id)
    subject_code = subj.code if subj else ""
    subject_name = subj.name if subj else ""
    subject_payload = {
        "subject_id": subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
    }

    since = utcnow() - timedelta(days=days)

    # 查询该时间段内用户的做题记录
    records_result = await db.execute(
        select(
            PracticeRecord.question_id,
            PracticeRecord.is_correct,
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.subject_id == subject_id,
            PracticeRecord.answered_at >= since,
        ).order_by(PracticeRecord.answered_at.desc())
    )
    # Read only the per-answer fields used by the report.  Full ORM hydration is
    # intentionally avoided so retired PracticeRecord batch columns can never
    # become an implicit dependency of this path.
    records = records_result.all()

    total = len(records)
    if total == 0:
        return {
            **subject_payload,
            "period_days": days,
            "total_answered": 0,
            "accuracy": 0.0,
            "weak_points": [],
            "strong_points": [],
            "learning_suggestions": ["暂无做题记录，建议开始练习。"],
            "tokens_used": 0,
            "from_fallback": True,
        }

    correct = sum(1 for r in records if r.is_correct)
    accuracy = correct / total if total > 0 else 0.0

    # 获取涉及题目的知识点
    qids = list({r.question_id for r in records})
    q_map = await load_question_kps(db, qids)

    # 按知识点聚合正确率
    kp_stats: dict[str, dict] = {}
    for r in records:
        kps = q_map.get(r.question_id) or []
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"correct": 0, "total": 0}
            kp_stats[kp]["total"] += 1
            if r.is_correct:
                kp_stats[kp]["correct"] += 1

    kp_list = []
    for kp, stats in kp_stats.items():
        kp_list.append({
            "knowledge_point": kp,
            "accuracy": stats["correct"] / stats["total"] if stats["total"] > 0 else 0,
            "correct": stats["correct"],
            "total": stats["total"],
        })
    kp_list.sort(key=lambda x: x["accuracy"])

    # 数据太少时不调用 AI
    if total < 5:
        weak = [{
            "knowledge_point": kp["knowledge_point"],
            "accuracy": kp["accuracy"],
            "suggestion": "数据不足，继续练习以获取更准确的建议",
        } for kp in [k for k in kp_list if k["accuracy"] < 0.6][:3]]
        strong = [{
            "knowledge_point": kp["knowledge_point"],
            "accuracy": kp["accuracy"],
            "suggestion": "继续保持",
        } for kp in [k for k in kp_list if k["accuracy"] >= 0.85][:3]]
        return {
            "subject_id": subject_id,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "period_days": days,
            "total_answered": total,
            "accuracy": accuracy,
            "weak_points": weak,
            "strong_points": strong,
            "learning_suggestions": ["数据较少，建议积累更多练习记录后再查看 AI 报告。"],
            "tokens_used": 0,
            "from_fallback": False,
        }

    # 调用 AI 生成报告
    messages = build_report_prompt(subject_code, days, total, accuracy, kp_list)

    if not await _check_token_limit(db, user_id, 1000):
        # 限额内用规则生成
        weak = [{
            "knowledge_point": kp["knowledge_point"],
            "accuracy": kp["accuracy"],
            "suggestion": "建议重点复习该知识点",
        } for kp in [k for k in kp_list if k["accuracy"] < 0.6][:5]]
        strong = [{
            "knowledge_point": kp["knowledge_point"],
            "accuracy": kp["accuracy"],
            "suggestion": "继续保持",
        } for kp in [k for k in kp_list if k["accuracy"] >= 0.85][:3]]
        return {
            "subject_id": subject_id,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "period_days": days,
            "total_answered": total,
            "accuracy": accuracy,
            "weak_points": weak,
            "strong_points": strong,
            "learning_suggestions": [
                f"薄弱知识点有 {len(weak)} 个，建议每天重点练习",
                "尝试做更多同类题目的变体练习",
            ],
            "tokens_used": 0,
            "from_fallback": True,
        }

    result = await _call_ai(messages, db)

    if result is None:
        fallback = get_fallback_report()
        return {
            "subject_id": subject_id,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "period_days": days,
            "total_answered": total,
            "accuracy": accuracy,
            "weak_points": fallback.get("weak_points", []),
            "strong_points": fallback.get("strong_points", []),
            "learning_suggestions": fallback.get("learning_suggestions", []),
            "tokens_used": 0,
            "from_fallback": True,
        }

    parsed = _parse_json_response(result["content"])
    if parsed is None:
        parsed = {"weak_points": [], "strong_points": [], "learning_suggestions": [result["content"]]}

    await _record_token_usage(
        db, user_id, "learning_report",
        f"subject_id={subject_id} days={days}",
        result["content"], result,
    )

    weak_points = []
    for wp in parsed.get("weak_points", []):
        weak_points.append({
            "knowledge_point": wp.get("knowledge_point", ""),
            "accuracy": float(wp.get("accuracy", 0)),
            "suggestion": wp.get("suggestion", ""),
        })

    strong_points = []
    for sp in parsed.get("strong_points", []):
        strong_points.append({
            "knowledge_point": sp.get("knowledge_point", ""),
            "accuracy": float(sp.get("accuracy", 0)),
            "suggestion": sp.get("suggestion", ""),
        })

    return {
        "subject_id": subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "period_days": days,
        "total_answered": total,
        "accuracy": accuracy,
        "weak_points": weak_points,
        "strong_points": strong_points,
        "learning_suggestions": parsed.get("learning_suggestions", []),
        "tokens_used": result["tokens_used"],
        "from_fallback": False,
    }
