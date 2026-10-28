"""掌握度服务 — 用户知识点掌握度计算与更新。

V3: 增量更新模型。mastery_score 范围 0-100，初始 50（未知状态）。
答对加分、答错扣分，结合难度修正和连续错误修正。
confidence 随 answer_count 增加，低置信度时不做过强判断。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.subject_resolution import resolve_subject_ids
from app.services.unique_conflict import (
    is_unique_violation as _is_unique_violation,
)
from app.services.unique_conflict import (
    start_explicit_transaction as _start_explicit_transaction,
)

logger = logging.getLogger(__name__)

# ── V3 掌握度阈值 ──
MASTERY_WEAK_THRESHOLD = 40
MASTERY_NORMAL_THRESHOLD = 70
MASTERY_GOOD_THRESHOLD = 85
MASTERY_INITIAL_SCORE = 50.0


# ── V3 核心工具函数 ──


async def _claim_knowledge_state(
    db: AsyncSession,
    *,
    user_id: int,
    knowledge_point: KnowledgePoint,
) -> UserKnowledgeState | None:
    state = UserKnowledgeState(
        user_id=user_id,
        subject_id=knowledge_point.subject_id,
        knowledge_point_id=knowledge_point.id,
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
    try:
        async with db.begin_nested():
            db.add(state)
            await db.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise
        return None
    return state


async def _reload_knowledge_state(
    db: AsyncSession,
    *,
    user_id: int,
    knowledge_point_id: int,
) -> UserKnowledgeState:
    state = await db.scalar(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id == knowledge_point_id,
        )
    )
    if state is None:
        raise RuntimeError("user knowledge state disappeared after unique conflict")
    return state


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


def _empty_mastery_update_summary() -> dict:
    return {
        "updated": 0,
        "created": 0,
        "mastery_before": None,
        "mastery_after": None,
        "mastery_delta": None,
    }


async def _load_version_knowledge_mappings(db: AsyncSession, question_version_id: int):
    """Load the answered revision's immutable knowledge-point mappings in order."""
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
    return result.all()


async def _load_version_difficulty(
    db: AsyncSession, question_version_id: int
) -> int | None:
    return await db.scalar(
        select(QuestionVersion.difficulty).where(
            QuestionVersion.id == question_version_id
        )
    )


async def _ensure_knowledge_states(
    db: AsyncSession, user_id: int, mappings: list
) -> tuple[dict[int, UserKnowledgeState], set[int]]:
    """Claim missing knowledge states and reload the winners of a unique race."""
    kp_ids = [kp.id for _, kp in mappings]
    states_result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(kp_ids),
        )
    )
    existing_states = {s.knowledge_point_id: s for s in states_result.scalars().all()}
    missing_mappings = [
        (qkp, kp) for qkp, kp in mappings if kp.id not in existing_states
    ]
    if missing_mappings:
        await _start_explicit_transaction(db)
    missing_claim_states: set[int] = set()
    for _qkp, kp in missing_mappings:
        state = await _claim_knowledge_state(
            db,
            user_id=user_id,
            knowledge_point=kp,
        )
        if state is None:
            state = await _reload_knowledge_state(
                db,
                user_id=user_id,
                knowledge_point_id=kp.id,
            )
        else:
            missing_claim_states.add(state.id)
        existing_states[kp.id] = state
    return existing_states, missing_claim_states


def _apply_answer_to_knowledge_state(
    state: UserKnowledgeState,
    *,
    is_correct: bool,
    used_time: int | None,
    difficulty: int | None,
    now,
) -> tuple[float, float]:
    """Apply one answer to one state and return its mastery before/after pair."""
    mastery_before = float(
        state.mastery_score
        if state.mastery_score is not None
        else MASTERY_INITIAL_SCORE
    )
    delta = compute_mastery_delta(
        is_correct=is_correct,
        used_time=used_time,
        difficulty=difficulty,
        recent_wrong_count=state.recent_wrong_count or 0,
    )

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
        state.correct_count / state.attempt_count if state.attempt_count > 0 else 0.0
    )

    state.mastery_score = clamp_mastery_score(mastery_before + delta)
    state.confidence = compute_confidence(state.attempt_count)
    state.weakness_level = get_mastery_label(state.mastery_score, state.confidence)
    state.last_is_correct = is_correct
    state.last_answer_time_seconds = used_time
    state.last_practiced_at = now
    return mastery_before, float(state.mastery_score)


def _apply_answer_to_mappings(
    mappings: list,
    existing_states: dict[int, UserKnowledgeState],
    missing_claim_states: set[int],
    *,
    is_correct: bool,
    used_time: int | None,
    difficulty: int | None,
    now,
) -> tuple[int, int, list[float], list[float]]:
    """Apply the answer to every mapped state, counting created vs updated rows."""
    updated = 0
    created = 0
    mastery_before_values: list[float] = []
    mastery_after_values: list[float] = []
    for _qkp, kp in mappings:
        state = existing_states.get(kp.id)
        if not state:
            raise RuntimeError("user knowledge state missing after claim/reload")
        if state.id in missing_claim_states:
            created += 1
        mastery_before, mastery_after = _apply_answer_to_knowledge_state(
            state,
            is_correct=is_correct,
            used_time=used_time,
            difficulty=difficulty,
            now=now,
        )
        mastery_before_values.append(mastery_before)
        mastery_after_values.append(mastery_after)
        updated += 1
    return updated, created, mastery_before_values, mastery_after_values


def _build_mastery_update_summary(
    updated: int,
    created: int,
    mastery_before_values: list[float],
    mastery_after_values: list[float],
) -> dict:
    """Average this question's per-knowledge-point mastery movement."""
    mastery_before_avg = (
        sum(mastery_before_values) / len(mastery_before_values)
        if mastery_before_values
        else None
    )
    mastery_after_avg = (
        sum(mastery_after_values) / len(mastery_after_values)
        if mastery_after_values
        else None
    )
    mastery_delta_avg = (
        mastery_after_avg - mastery_before_avg
        if mastery_before_avg is not None and mastery_after_avg is not None
        else None
    )
    return {
        "updated": updated,
        "created": created,
        "mastery_before": round(mastery_before_avg, 4)
        if mastery_before_avg is not None
        else None,
        "mastery_after": round(mastery_after_avg, 4)
        if mastery_after_avg is not None
        else None,
        "mastery_delta": round(mastery_delta_avg, 4)
        if mastery_delta_avg is not None
        else None,
    }


async def update_user_knowledge_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    question_version_id: int,
    used_time: int | None = None,
) -> dict:
    """答题后更新相关知识点掌握度（V3 增量模型）。

    映射使用实际作答的不可变版本（Current Question 映射不参与历史归属）；
    mastery_* 为本题关联知识点掌握度的平均值，用于推荐效果闭环指标。
    """
    now = utcnow()
    # Knowledge evidence is always attributed to the immutable revision that was
    # actually answered. Current Question mappings are never used for historical data.
    mappings = await _load_version_knowledge_mappings(db, question_version_id)
    difficulty = await _load_version_difficulty(db, question_version_id)
    if not mappings or difficulty is None:
        return _empty_mastery_update_summary()

    existing_states, missing_claim_states = await _ensure_knowledge_states(
        db, user_id, mappings
    )
    updated, created, mastery_before_values, mastery_after_values = (
        _apply_answer_to_mappings(
            mappings,
            existing_states,
            missing_claim_states,
            is_correct=is_correct,
            used_time=used_time,
            difficulty=difficulty,
            now=now,
        )
    )

    await db.flush()
    return _build_mastery_update_summary(
        updated,
        created,
        mastery_before_values,
        mastery_after_values,
    )


# ── 查询接口 ──


async def _load_weak_state_rows(
    db: AsyncSession, user_id: int, subject_ids: list[int], limit: int
):
    """Weak-first candidate rows; the caller truncates to the requested limit."""
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(
            KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id
        )
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
    return result.all()


def _weak_point_from_state(state: UserKnowledgeState, kp_name: str) -> dict:
    return {
        "knowledge_point_id": state.knowledge_point_id,
        "name": kp_name,
        "subject_id": state.subject_id,
        "mastery_score": state.mastery_score,
        "confidence": state.confidence,
        "accuracy": state.accuracy,
        "attempt_count": state.attempt_count,
        "weakness_level": state.weakness_level,
    }


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
    rows = await _load_weak_state_rows(db, user_id, subject_ids, limit)

    weak_points = []
    for state, kp_name in rows:
        # V3: 使用新阈值判断薄弱（mastery_score < 70 即 weak 或 normal）
        if state.mastery_score < MASTERY_NORMAL_THRESHOLD:
            weak_points.append(_weak_point_from_state(state, kp_name))
        if len(weak_points) >= limit:
            break

    if weak_points:
        return weak_points

    # 2. Fallback: 近 30 天 PracticeRecord 统计
    logger.info("user_knowledge_states 无足够数据，fallback 到 PracticeRecord 统计")
    return await _fallback_weak_kps(db, user_id, subject, limit)


async def _load_recent_practice_rows(
    db: AsyncSession, user_id: int, subject_ids: list[int], cutoff: datetime
):
    """Recent practice rows projected to (is_correct, kp_id, snapshot name)."""
    result = await db.execute(
        select(
            PracticeRecord.is_correct,
            QuestionVersionKnowledgePoint.knowledge_point_id,
            func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id
            == PracticeRecord.question_version_id,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
        )
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id
            == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            PracticeRecord.subject_id.in_(subject_ids),
        )
    )
    return result.all()


def _aggregate_practice_rows(rows) -> dict[int, dict]:
    kp_stats: dict[int, dict] = {}
    for is_correct, kp_id, kp_name in rows:
        stats = kp_stats.setdefault(
            int(kp_id), {"name": str(kp_name), "total": 0, "correct": 0}
        )
        stats["total"] += 1
        if bool(is_correct):
            stats["correct"] += 1
    return kp_stats


def _weak_point_from_practice_stats(kp_id: int, stats: dict) -> dict | None:
    """Project one aggregated practice bucket, keeping the V1 thresholds."""
    total = stats["total"]
    if total < 2:
        return None
    correct = stats["correct"]
    accuracy = correct / total
    if accuracy >= 0.65:
        return None
    return {
        "knowledge_point_id": kp_id,
        "name": stats["name"],
        "mastery_score": round(accuracy * 100, 2),
        "confidence": round(min(1.0, total / 10.0), 2),
        "accuracy": round(accuracy, 4),
        "attempt_count": total,
        "weakness_level": "weak" if accuracy < 0.45 else "normal",
    }


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
    rows = await _load_recent_practice_rows(db, user_id, subject_ids, cutoff)

    if not rows:
        return []

    weak = []
    for kp_id, stats in _aggregate_practice_rows(rows).items():
        projected = _weak_point_from_practice_stats(kp_id, stats)
        if projected is not None:
            weak.append(projected)

    weak.sort(key=lambda x: (x["accuracy"], -x["attempt_count"]))
    return weak[:limit]


async def _load_knowledge_state_rows(
    db: AsyncSession, user_id: int, subject_ids: list[int]
):
    result = await db.execute(
        select(UserKnowledgeState, KnowledgePoint.name)
        .join(
            KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id
        )
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(subject_ids),
        )
        .order_by(KnowledgePoint.name)
    )
    return result.all()


async def _load_subject_label_map(db: AsyncSession, rows) -> dict[int, Subject]:
    """Bulk-load subject labels for the projected rows (single query, no N+1)."""
    subject_ids_used = {state.subject_id for state, _ in rows}
    if not subject_ids_used:
        return {}
    subj_result = await db.execute(
        select(Subject).where(Subject.id.in_(subject_ids_used))
    )
    return {s.id: s for s in subj_result.scalars().all()}


def _knowledge_state_view(
    state: UserKnowledgeState, kp_name: str, subject_map: dict[int, Subject]
) -> dict:
    subj = subject_map.get(state.subject_id)
    return {
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
        "last_practiced_at": serialize_utc_datetime(state.last_practiced_at)
        if state.last_practiced_at
        else None,
        "last_wrong_at": serialize_utc_datetime(state.last_wrong_at)
        if state.last_wrong_at
        else None,
    }


async def get_user_knowledge_states(
    db: AsyncSession,
    user_id: int,
    subject: str | int | None,
) -> list[dict]:
    """获取用户某科目下所有知识点掌握状态。"""
    subject_ids = await resolve_subject_ids(db, subject)
    if not subject_ids:
        return []
    rows = await _load_knowledge_state_rows(db, user_id, subject_ids)
    subject_map = await _load_subject_label_map(db, rows)
    return [
        _knowledge_state_view(state, kp_name, subject_map) for state, kp_name in rows
    ]
