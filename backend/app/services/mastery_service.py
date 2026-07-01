"""掌握度服务 — 用户知识点掌握度计算与更新。

V3: 增量更新模型。mastery_score 范围 0-100，初始 50（未知状态）。
答对加分、答错扣分，结合难度修正和连续错误修正。
confidence 随 answer_count 增加，低置信度时不做过强判断。
"""
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

# ── V3 掌握度阈值 ──
MASTERY_WEAK_THRESHOLD = 40
MASTERY_NORMAL_THRESHOLD = 70
MASTERY_GOOD_THRESHOLD = 85
MASTERY_INITIAL_SCORE = 50.0


# ── V3 核心工具函数 ──


def normalize_knowledge_points(raw: object) -> list[str]:
    """规范化知识点列表。

    支持多种输入格式：None、字符串、list[str]、list[dict]。
    去重但保留顺序，去除空字符串。
    """
    if not raw:
        return []

    items = raw if isinstance(raw, list) else [raw]
    result: list[str] = []
    seen: set[str] = set()

    for item in items:
        name = None
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("label")

        if not name:
            continue
        name = str(name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)

    return result


def compute_mastery_delta(
    is_correct: bool,
    used_time: int | None = None,
    difficulty: int | None = None,
    recent_wrong_count: int = 0,
) -> float:
    """计算掌握度变化量。

    基础：答对 +6，答错 -12（错题扣更多，更能暴露薄弱点）。
    难度修正：难题(d>=4)答对额外 +3，简单题(d<=2)答错额外 -4。
    连续错误修正：recent_wrong_count >= 2 时额外 -3。
    """
    if is_correct:
        delta = 6.0
    else:
        delta = -12.0

    # 难度修正
    if difficulty is not None:
        if is_correct and difficulty >= 4:
            delta += 3.0
        elif not is_correct and difficulty <= 2:
            delta -= 4.0

    # 近期连续错误修正
    if not is_correct and recent_wrong_count >= 2:
        delta -= 3.0

    return delta


def clamp_mastery_score(score: float) -> float:
    """将掌握度限制在 [0, 100] 范围内。"""
    return max(0.0, min(100.0, score))


def compute_confidence(answer_count: int) -> float:
    """计算置信度。answer_count / 10，上限 1.0。

    0 次 → 0.0，1 次 → 0.1，5 次 → 0.5，10+ 次 → 1.0。
    """
    return min(1.0, max(0.0, answer_count / 10.0))


def get_mastery_label(mastery_score: float, confidence: float) -> str:
    """根据掌握度和置信度返回状态标签。

    低置信度(<0.3)时返回 possible_* 或 observing，避免过度判断。
    """
    if confidence < 0.3:
        if mastery_score < MASTERY_WEAK_THRESHOLD:
            return "possible_weak"
        if mastery_score >= MASTERY_GOOD_THRESHOLD:
            return "possible_mastered"
        return "observing"

    if mastery_score < MASTERY_WEAK_THRESHOLD:
        return "weak"
    if mastery_score < MASTERY_NORMAL_THRESHOLD:
        return "normal"
    if mastery_score < MASTERY_GOOD_THRESHOLD:
        return "good"
    return "mastered"


# ── 旧版兼容（保留供外部调用） ──


def calculate_mastery_score(
    attempt_count: int,
    correct_count: int,
    wrong_count: int,
    last_wrong_at: datetime | None = None,
    last_practiced_at: datetime | None = None,
) -> float:
    """计算掌握度分数 [0, 1]。旧版兼容接口。"""
    if attempt_count == 0:
        return 0.0

    base_accuracy = correct_count / attempt_count
    attempt_factor = min(1.0, log1p(attempt_count) / log1p(10))

    penalty = 0.0
    if last_wrong_at and last_practiced_at and last_wrong_at >= last_practiced_at:
        penalty = 0.15

    score = base_accuracy * 0.75 + attempt_factor * 0.25 - penalty
    return max(0.0, min(1.0, round(score, 4)))


def classify_weakness_level(mastery_score: float, attempt_count: int) -> str:
    """根据掌握度和尝试次数分类薄弱程度。旧版兼容接口。"""
    if attempt_count == 0:
        return "unknown"
    if mastery_score < 0.45:
        return "weak"
    if mastery_score < 0.75:
        return "medium"
    return "strong"


# ── V3 核心：答题后更新知识点掌握度 ──


async def update_user_knowledge_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    used_time: int | None = None,
) -> dict:
    """答题后更新相关知识点掌握度（V3 增量模型）。

    流程：
    1. 查找题目的知识点映射（QuestionKnowledgePoint → KnowledgePoint）。
    2. 如果没有映射，尝试从 question.knowledge_points JSON 自动同步。
    3. 遍历每个知识点，创建或更新 UserKnowledgeState。
    4. 使用 compute_mastery_delta 计算增量，更新 mastery_score。
    5. 更新 confidence、recent_* 系列统计。

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

    # 2. 如果没有映射，尝试从 question.knowledge_points JSON 自动同步
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

    # 获取题目 subject 和 difficulty
    subject_result = await db.execute(
        select(Subject.code, Question.difficulty).select_from(Question)
        .join(Subject, Question.subject_id == Subject.id)
        .where(Question.id == question_id)
    )
    row = subject_result.one_or_none()
    if not row:
        return {"updated": 0, "created": 0}
    subject = row[0]
    difficulty = row[1]

    updated = 0
    created = 0

    for _qkp, kp in mappings:
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
                mastery_score=MASTERY_INITIAL_SCORE,
                weakness_level="observing",
                confidence=0.0,
                recent_answer_count=0,
                recent_correct_count=0,
                recent_wrong_count=0,
            )
            db.add(state)
            await db.flush()
            created += 1

        # V3: 计算掌握度增量
        old_recent_wrong = state.recent_wrong_count or 0
        delta = compute_mastery_delta(
            is_correct=is_correct,
            used_time=used_time,
            difficulty=difficulty,
            recent_wrong_count=old_recent_wrong,
        )

        # 更新统计
        state.attempt_count = (state.attempt_count or 0) + 1
        if is_correct:
            state.correct_count = (state.correct_count or 0) + 1
            state.recent_correct_count = (state.recent_correct_count or 0) + 1
            state.recent_wrong_count = 0
        else:
            state.wrong_count = (state.wrong_count or 0) + 1
            state.recent_wrong_count = (state.recent_wrong_count or 0) + 1
            state.recent_correct_count = 0
            state.last_wrong_at = now

        state.recent_answer_count = (state.recent_answer_count or 0) + 1
        state.accuracy = (
            state.correct_count / state.attempt_count
            if state.attempt_count > 0
            else 0.0
        )

        # V3: 增量更新 mastery_score (0-100)
        state.mastery_score = clamp_mastery_score(
            (state.mastery_score or MASTERY_INITIAL_SCORE) + delta
        )

        # V3: 更新 confidence
        state.confidence = compute_confidence(state.attempt_count)

        # V3: 更新 weakness_level（使用新标签体系）
        state.weakness_level = get_mastery_label(state.mastery_score, state.confidence)

        # V3: 记录最近答题信息
        state.last_is_correct = is_correct
        state.last_answer_time_seconds = used_time
        state.last_practiced_at = now
        updated += 1

    await db.flush()
    return {"updated": updated, "created": created}


# ── 查询接口 ──


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
        # V3: 使用新阈值判断薄弱（mastery_score < 70 即 weak 或 normal）
        if state.mastery_score < MASTERY_NORMAL_THRESHOLD:
            weak_points.append({
                "knowledge_point_id": state.knowledge_point_id,
                "name": kp_name,
                "mastery_score": state.mastery_score,
                "confidence": state.confidence,
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
                    "mastery_score": round(accuracy * 100, 2),
                    "confidence": round(min(1.0, total / 10.0), 2),
                    "accuracy": round(accuracy, 4),
                    "attempt_count": total,
                    "weakness_level": "weak" if accuracy < 0.45 else "normal",
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
            "mastery_score": round(state.mastery_score, 2),
            "confidence": round(state.confidence, 2),
            "weakness_level": state.weakness_level,
            "recent_wrong_count": state.recent_wrong_count,
            "last_practiced_at": state.last_practiced_at.isoformat() if state.last_practiced_at else None,
            "last_wrong_at": state.last_wrong_at.isoformat() if state.last_wrong_at else None,
        }
        for state, kp_name in rows
    ]
