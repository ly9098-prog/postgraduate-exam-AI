"""掌握度服务 — 用户知识点掌握度计算与更新。

V3: 增量更新模型。mastery_score 范围 0-100，初始 50（未知状态）。
答对加分、答错扣分，结合难度修正和连续错误修正。
confidence 随 answer_count 增加，低置信度时不做过强判断。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow, serialize_utc_datetime
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.admin_subject_service import resolve_subject_ids

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


# ── V3 核心：答题后更新知识点掌握度 ──


async def update_user_knowledge_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    question_version_id: int,
    used_time: int | None = None,
) -> dict:
    """答题后更新相关知识点掌握度（V3 增量模型）。

    流程：
    1. 查找题目的知识点映射（QuestionKnowledgePoint → KnowledgePoint，唯一事实源）。
    2. 遍历每个知识点，创建或更新 UserKnowledgeState。
    3. 使用 compute_mastery_delta 计算增量，更新 mastery_score。
    4. 更新 confidence、recent_* 系列统计。

    返回: {"updated": int, "created": int, "mastery_before": float | None,
           "mastery_after": float | None, "mastery_delta": float | None}
    mastery_* 为本题关联知识点掌握度的平均值，用于推荐效果闭环指标。
    """
    now = utcnow()

    # Knowledge evidence is always attributed to the immutable revision that was
    # actually answered. Current Question mappings are never used for historical data.
    result = await db.execute(
        select(QuestionVersionKnowledgePoint, KnowledgePoint)
        .join(
            KnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id == question_version_id)
        .order_by(
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    mappings = result.all()
    difficulty = await db.scalar(
        select(QuestionVersion.difficulty).where(QuestionVersion.id == question_version_id)
    )

    if not mappings:
        return {
            "updated": 0, "created": 0,
            "mastery_before": None, "mastery_after": None, "mastery_delta": None,
        }

    if difficulty is None:
        return {
            "updated": 0, "created": 0,
            "mastery_before": None, "mastery_after": None, "mastery_delta": None,
        }

    # 批量查询现有 UserKnowledgeState（替代每 KP 一次 SELECT）
    kp_ids = [kp.id for _, kp in mappings]
    states_result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(kp_ids),
        )
    )
    existing_states = {
        s.knowledge_point_id: s for s in states_result.scalars().all()
    }

    updated = 0
    created = 0
    mastery_before_values: list[float] = []
    mastery_after_values: list[float] = []

    for _qkp, kp in mappings:
        state = existing_states.get(kp.id)

        if not state:
            state = UserKnowledgeState(
                user_id=user_id,
                subject_id=kp.subject_id,
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
            created += 1

        mastery_before = float(
            state.mastery_score if state.mastery_score is not None else MASTERY_INITIAL_SCORE
        )
        mastery_before_values.append(mastery_before)

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
        state.mastery_score = clamp_mastery_score(mastery_before + delta)
        mastery_after_values.append(float(state.mastery_score))

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

    mastery_before_avg = (
        sum(mastery_before_values) / len(mastery_before_values)
        if mastery_before_values else None
    )
    mastery_after_avg = (
        sum(mastery_after_values) / len(mastery_after_values)
        if mastery_after_values else None
    )
    mastery_delta_avg = (
        mastery_after_avg - mastery_before_avg
        if mastery_before_avg is not None and mastery_after_avg is not None
        else None
    )
    return {
        "updated": updated,
        "created": created,
        "mastery_before": round(mastery_before_avg, 4) if mastery_before_avg is not None else None,
        "mastery_after": round(mastery_after_avg, 4) if mastery_after_avg is not None else None,
        "mastery_delta": round(mastery_delta_avg, 4) if mastery_delta_avg is not None else None,
    }


# ── 查询接口 ──


async def get_user_weak_knowledge_points(
    db: AsyncSession,
    user_id: int,
    subject: str | int | None,
    limit: int = 5,
) -> list[dict]:
    """获取用户薄弱知识点。

    优先从 user_knowledge_states 读取，数据不足时 fallback 到近 30 天 PracticeRecord。
    """
    # 1. 从 UserKnowledgeState 查找
    subject_ids = await resolve_subject_ids(db, subject)
    if not subject_ids:
        return []
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(subject_ids),
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
                "subject_id": state.subject_id,
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
    subject: str | int | None,
    limit: int = 5,
) -> list[dict]:
    """Fallback: 从近 30 天做题记录统计薄弱知识点。"""
    subject_ids = await resolve_subject_ids(db, subject)
    if not subject_ids:
        return []
    cutoff = utcnow() - timedelta(days=30)

    result = await db.execute(
        select(
            PracticeRecord.is_correct,
            QuestionVersionKnowledgePoint.knowledge_point_id,
            KnowledgePoint.name,
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id == PracticeRecord.question_version_id,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            PracticeRecord.subject_id.in_(subject_ids),
        )
    )
    rows = result.all()

    if not rows:
        return []

    kp_stats: dict[int, dict] = {}
    for is_correct, kp_id, kp_name in rows:
        stats = kp_stats.setdefault(
            int(kp_id), {"name": str(kp_name), "total": 0, "correct": 0}
        )
        stats["total"] += 1
        if bool(is_correct):
            stats["correct"] += 1

    weak = []
    for kp_id, stats in kp_stats.items():
        kp_name = stats["name"]
        total = stats["total"]
        correct = stats["correct"]
        if total >= 2:
            accuracy = correct / total
            if accuracy < 0.65:
                weak.append({
                    "knowledge_point_id": kp_id,
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
    subject: str | int | None,
) -> list[dict]:
    """获取用户某科目下所有知识点掌握状态。"""
    subject_ids = await resolve_subject_ids(db, subject)
    if not subject_ids:
        return []
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(subject_ids),
        )
        .order_by(KnowledgePoint.name)
    )
    rows = result.all()

    # Bulk-load subject labels (single query, avoid N+1)
    subject_ids_used = {state.subject_id for state, _ in rows}
    subject_map: dict[int, Subject] = {}
    if subject_ids_used:
        subj_result = await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids_used))
        )
        subject_map = {s.id: s for s in subj_result.scalars().all()}

    items = []
    for state, kp_name in rows:
        subj = subject_map.get(state.subject_id)
        items.append({
            "knowledge_point_id": state.knowledge_point_id,
            "name": kp_name,
            "subject_id": state.subject_id,
            "subject_name": subj.name if subj else "",
            "attempt_count": state.attempt_count,
            "correct_count": state.correct_count,
            "wrong_count": state.wrong_count,
            "accuracy": round(state.accuracy, 4),
            "mastery_score": round(state.mastery_score, 2),
            "confidence": round(state.confidence, 2),
            "weakness_level": state.weakness_level,
            "recent_wrong_count": state.recent_wrong_count,
            "last_practiced_at": serialize_utc_datetime(state.last_practiced_at) if state.last_practiced_at else None,
            "last_wrong_at": serialize_utc_datetime(state.last_wrong_at) if state.last_wrong_at else None,
        })
    return items
