"""掌握度服务 — 用户知识点掌握度计算与更新。"""
import logging
from datetime import datetime, timedelta
from math import log1p

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import utcnow
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState

logger = logging.getLogger(__name__)


def calculate_mastery_score(
    attempt_count: int,
    correct_count: int,
    wrong_count: int,
    last_wrong_at: datetime | None = None,
    last_practiced_at: datetime | None = None,
) -> float:
    """计算掌握度分数 [0, 1]。

    规则:
    - base_accuracy = correct_count / attempt_count
    - attempt_factor = min(1.0, log1p(attempt_count) / log1p(10))
    - penalty = 0.15 if 最近一次是错题 else 0
    - mastery_score = clamp(base_accuracy * 0.75 + attempt_factor * 0.25 - penalty, 0, 1)
    """
    if attempt_count == 0:
        return 0.0

    base_accuracy = correct_count / attempt_count
    attempt_factor = min(1.0, log1p(attempt_count) / log1p(10))

    # 如果最近一次是错题（last_wrong_at == last_practiced_at），加 penalty
    penalty = 0.0
    if last_wrong_at and last_practiced_at and last_wrong_at >= last_practiced_at:
        penalty = 0.15

    score = base_accuracy * 0.75 + attempt_factor * 0.25 - penalty
    return max(0.0, min(1.0, round(score, 4)))


def classify_weakness_level(mastery_score: float, attempt_count: int) -> str:
    """根据掌握度和尝试次数分类薄弱程度。"""
    if attempt_count == 0:
        return "unknown"
    if mastery_score < 0.45:
        return "weak"
    if mastery_score < 0.75:
        return "medium"
    return "strong"


async def update_user_knowledge_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
) -> dict:
    """答题后更新相关知识点掌握度。

    返回: {"updated": int, "created": int}
    """
    now = utcnow()

    # 1. 查找题目的知识点映射
    result = await db.execute(
        select(QuestionKnowledgePoint, KnowledgePoint)
        .join(KnowledgePoint, QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id)
        .where(QuestionKnowledgePoint.question_id == question_id)
    )
    mappings = result.all()

    # 2. 如果没有映射，尝试从 question.knowledge_points JSON 临时同步
    if not mappings:
        q_result = await db.execute(
            select(Question).options(selectinload(Question.subject_ref)).where(Question.id == question_id)
        )
        question = q_result.scalar_one_or_none()
        if question and question.knowledge_points:
            try:
                from app.services.knowledge_point_service import (
                    sync_question_knowledge_points,
                )
                await sync_question_knowledge_points(db, question, source="auto")
                # 重新查映射
                result = await db.execute(
                    select(QuestionKnowledgePoint, KnowledgePoint)
                    .join(KnowledgePoint, QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id)
                    .where(QuestionKnowledgePoint.question_id == question_id)
                )
                mappings = result.all()
            except Exception:
                logger.warning("auto-sync KP for qid=%d failed", question_id, exc_info=True)

    if not mappings:
        return {"updated": 0, "created": 0}

    # 获取题目 subject
    subject_result = await db.execute(
        select(Subject.code).select_from(Question)
        .join(Subject, Question.subject_id == Subject.id)
        .where(Question.id == question_id)
    )
    subject = subject_result.scalar_one_or_none()
    if not subject:
        return {"updated": 0, "created": 0}

    updated = 0
    created = 0

    for qkp, kp in mappings:
        # 查找或创建 UserKnowledgeState
        state_result = await db.execute(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.knowledge_point_id == kp.id,
            )
        )
        state = state_result.scalar_one_or_none()

        if not state:
            state = UserKnowledgeState(
                user_id=user_id,
                subject=subject,
                knowledge_point_id=kp.id,
                attempt_count=0,
                correct_count=0,
                wrong_count=0,
                accuracy=0.0,
                mastery_score=0.0,
                weakness_level="unknown",
            )
            db.add(state)
            await db.flush()
            created += 1

        # 更新统计
        state.attempt_count += 1
        if is_correct:
            state.correct_count += 1
        else:
            state.wrong_count += 1
            state.last_wrong_at = now

        state.accuracy = (
            state.correct_count / state.attempt_count
            if state.attempt_count > 0
            else 0.0
        )
        state.mastery_score = calculate_mastery_score(
            state.attempt_count,
            state.correct_count,
            state.wrong_count,
            state.last_wrong_at,
            now,
        )
        state.weakness_level = classify_weakness_level(
            state.mastery_score, state.attempt_count
        )
        state.last_practiced_at = now
        updated += 1

    await db.flush()
    return {"updated": updated, "created": created}


async def get_user_weak_knowledge_points(
    db: AsyncSession,
    user_id: int,
    subject: str,
    limit: int = 5,
) -> list[dict]:
    """获取用户薄弱知识点。

    优先从 user_knowledge_states 读取，数据不足时 fallback 到近 30 天 PracticeRecord。
    """
    # 1. 从 UserKnowledgeState 查找
    subject_cond = or_(
        UserKnowledgeState.subject == subject,
        UserKnowledgeState.subject.like(f"{subject}-%"),
    )
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            subject_cond,
            UserKnowledgeState.attempt_count > 0,
        )
        .order_by(
            UserKnowledgeState.mastery_score.asc(),
            UserKnowledgeState.attempt_count.desc(),
        )
        .limit(limit * 2)
    )
    rows = result.all()

    weak_points = []
    for state, kp_name in rows:
        if state.weakness_level in ("weak", "medium"):
            weak_points.append({
                "knowledge_point_id": state.knowledge_point_id,
                "name": kp_name,
                "mastery_score": state.mastery_score,
                "accuracy": state.accuracy,
                "attempt_count": state.attempt_count,
                "weakness_level": state.weakness_level,
            })
        if len(weak_points) >= limit:
            break

    if weak_points:
        return weak_points

    # 2. Fallback: 近 30 天 PracticeRecord 统计
    logger.info("user_knowledge_states 无足够数据，fallback 到 PracticeRecord 统计")
    return await _fallback_weak_kps(db, user_id, subject, limit)


async def _fallback_weak_kps(
    db: AsyncSession,
    user_id: int,
    subject: str,
    limit: int = 5,
) -> list[dict]:
    """Fallback: 从近 30 天做题记录统计薄弱知识点。"""
    cutoff = utcnow() - timedelta(days=30)
    subject_cond = or_(
        PracticeRecord.subject == subject,
        PracticeRecord.subject.like(f"{subject}-%"),
    )

    result = await db.execute(
        select(PracticeRecord, Question.knowledge_points)
        .join(Question, PracticeRecord.question_id == Question.id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            subject_cond,
        )
    )
    rows = result.all()

    if not rows:
        return []

    kp_stats: dict[str, dict] = {}
    for record, kps_json in rows:
        kps = kps_json or []
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "correct": 0}
            kp_stats[kp]["total"] += 1
            if record.is_correct:
                kp_stats[kp]["correct"] += 1

    weak = []
    for kp_name, stats in kp_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        if total >= 2:
            accuracy = correct / total
            if accuracy < 0.65:
                weak.append({
                    "knowledge_point_id": None,
                    "name": kp_name,
                    "mastery_score": round(accuracy * 0.75, 4),
                    "accuracy": round(accuracy, 4),
                    "attempt_count": total,
                    "weakness_level": "weak" if accuracy < 0.45 else "medium",
                })

    weak.sort(key=lambda x: (x["accuracy"], -x["attempt_count"]))
    return weak[:limit]


async def get_user_knowledge_states(
    db: AsyncSession,
    user_id: int,
    subject: str,
) -> list[dict]:
    """获取用户某科目下所有知识点掌握状态。"""
    subject_cond = or_(
        UserKnowledgeState.subject == subject,
        UserKnowledgeState.subject.like(f"{subject}-%"),
    )
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            subject_cond,
        )
        .order_by(KnowledgePoint.name)
    )
    rows = result.all()

    return [
        {
            "knowledge_point_id": state.knowledge_point_id,
            "name": kp_name,
            "subject": state.subject,
            "attempt_count": state.attempt_count,
            "correct_count": state.correct_count,
            "wrong_count": state.wrong_count,
            "accuracy": round(state.accuracy, 4),
            "mastery_score": round(state.mastery_score, 4),
            "weakness_level": state.weakness_level,
            "last_practiced_at": state.last_practiced_at.isoformat() if state.last_practiced_at else None,
            "last_wrong_at": state.last_wrong_at.isoformat() if state.last_wrong_at else None,
        }
        for state, kp_name in rows
    ]
