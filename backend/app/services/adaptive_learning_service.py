"""V6 个性化调度服务 — 间隔倍率 + 题目难度校准 + 知识点路径推荐。

V6.1: 根据用户到期复习表现动态调整间隔倍率。
V6.2: 根据用户作答表现自动校准每道题的个人难度。
V6.3: 根据知识点前置关系，为 smart 推荐提供路径感知评分。

所有函数均为 best-effort：出错只记日志，不抛异常，不影响主流程。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import utcnow, serialize_utc_datetime
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_adaptive_profile import UserAdaptiveProfile
from app.models.user_knowledge_adaptive_state import UserKnowledgeAdaptiveState
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.user_question_difficulty_state import UserQuestionDifficultyState
from app.models.user_question_state import UserQuestionState
from app.models.user_recommend_preference import UserRecommendPreference

logger = logging.getLogger(__name__)


# V6.5 knowledge-graph recommendation defaults.  Keep these in one place so
# prerequisite gating is consistent between the graph service and smart
# recommendation.  mastery_score is always 0..100; confidence is 0..1.
GRAPH_PREREQUISITE_MASTERY_THRESHOLD = 60.0
GRAPH_PREREQUISITE_CONFIDENCE_THRESHOLD = 0.3
GRAPH_MAX_DEPTH = 2
GRAPH_MAX_EXPANSION_NODES = 24


def normalize_edge_weight(weight: float | None) -> float:
    """Normalize a knowledge-edge weight to 0..1.

    Existing imported graph data uses 0..1, while the model intentionally
    permits larger values (up to 10 in admin/import workflows).  Preserve the
    common 0..1 scale and gracefully normalize larger values.
    """
    try:
        value = max(0.0, float(weight or 0.0))
    except (TypeError, ValueError):
        return 0.0
    if value <= 1.0:
        return value
    return min(value / 10.0, 1.0)


def _clamp01(value: float | None) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


# ── 纯函数 ───────────────────────────────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def calculate_personalized_interval_days(
    base_interval_days: int,
    user_interval_factor: float = 1.0,
    knowledge_interval_factor: float = 1.0,
    difficulty_factor: float = 1.0,
    min_days: int = 1,
    max_days: int = 180,
) -> int:
    """基础间隔 × 用户倍率 × 知识点倍率 × 难度倍率，clamp 到 [min_days, max_days]。"""
    raw = (
        base_interval_days
        * user_interval_factor
        * knowledge_interval_factor
        * difficulty_factor
    )
    return max(min_days, min(int(round(raw)), max_days))


def get_difficulty_factor(difficulty_label: str) -> float:
    """简单题拉长间隔，困难题缩短间隔。"""
    if difficulty_label == "easy":
        return 1.15
    if difficulty_label == "hard":
        return 0.75
    return 1.0


def get_difficulty_label(score: float) -> str:
    if score < 30:
        return "easy"
    if score < 70:
        return "normal"
    return "hard"


def _estimate_expected_time(difficulty: int) -> int:
    """根据题目 difficulty (1-5) 估算期望作答时间（秒）。"""
    return 30 + difficulty * 15  # difficulty=1→45s, 3→75s, 5→105s


# ── DB helpers ────────────────────────────────────────────────────────


async def _get_or_create_profile(db: AsyncSession, user_id: int) -> UserAdaptiveProfile:
    result = await db.execute(
        select(UserAdaptiveProfile).where(UserAdaptiveProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserAdaptiveProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


async def _get_knowledge_adaptive(
    db: AsyncSession, user_id: int, kp_id: int
) -> UserKnowledgeAdaptiveState | None:
    result = await db.execute(
        select(UserKnowledgeAdaptiveState).where(
            UserKnowledgeAdaptiveState.user_id == user_id,
            UserKnowledgeAdaptiveState.knowledge_point_id == kp_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_or_create_difficulty(
    db: AsyncSession, user_id: int, question_id: int
) -> UserQuestionDifficultyState:
    result = await db.execute(
        select(UserQuestionDifficultyState).where(
            UserQuestionDifficultyState.user_id == user_id,
            UserQuestionDifficultyState.question_id == question_id,
        )
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = UserQuestionDifficultyState(user_id=user_id, question_id=question_id)
        db.add(state)
        await db.flush()
    return state


# ── V6.1: 用户间隔倍率更新 ───────────────────────────────────────────


async def update_user_interval_factor(
    db: AsyncSession,
    user_id: int,
    is_due_review: bool,
    is_correct: bool,
    is_overdue_review: bool,
) -> float:
    """根据到期复习表现调整用户全局 interval_factor，返回新值。"""
    profile = await _get_or_create_profile(db, user_id)

    old_factor = profile.interval_factor
    factor = old_factor

    if is_due_review and not is_correct:
        factor = factor * 0.92
    elif is_due_review and is_correct:
        if is_overdue_review:
            factor = factor * 1.08
        else:
            factor = factor * 1.04

    factor = _clamp(factor, profile.min_interval_factor, profile.max_interval_factor)

    profile.interval_factor = round(factor, 4)
    profile.last_adjusted_at = utcnow()

    # 更新近期统计（滑动窗口简化：每次到期复习 +1）
    if is_due_review:
        profile.recent_due_count += 1
        if is_correct:
            profile.recent_due_correct_count += 1

    await db.flush()

    if abs(factor - old_factor) > 0.001:
        logger.info(
            "adaptive_interval_adjusted user=%d old=%.4f new=%.4f due=%s correct=%s overdue=%s",
            user_id,
            old_factor,
            factor,
            is_due_review,
            is_correct,
            is_overdue_review,
        )

    return factor


async def update_knowledge_interval_factor(
    db: AsyncSession,
    user_id: int,
    knowledge_point_ids: list[int],
    is_due_review: bool,
    is_correct: bool,
    is_overdue_review: bool,
) -> None:
    """根据复习表现调整知识点级 interval_factor。"""
    if not knowledge_point_ids:
        return

    # 批量加载已有状态
    existing_result = await db.execute(
        select(UserKnowledgeAdaptiveState).where(
            UserKnowledgeAdaptiveState.user_id == user_id,
            UserKnowledgeAdaptiveState.knowledge_point_id.in_(knowledge_point_ids),
        )
    )
    state_map: dict[int, UserKnowledgeAdaptiveState] = {
        s.knowledge_point_id: s for s in existing_result.scalars().all()
    }

    # 批量创建缺失状态。新 ORM 对象的 Column(default=...) 在 flush 前未必
    # 已填入 Python 属性；必须先 flush，才能安全读取 interval_factor / 计数器。
    created_any = False
    for kp_id in knowledge_point_ids:
        if kp_id not in state_map:
            state = UserKnowledgeAdaptiveState(
                user_id=user_id,
                knowledge_point_id=kp_id,
            )
            db.add(state)
            state_map[kp_id] = state
            created_any = True
    if created_any:
        await db.flush()

    # 统一更新
    for kp_id in knowledge_point_ids:
        state = state_map[kp_id]
        old = state.interval_factor
        factor = old

        if is_due_review and not is_correct:
            factor = factor * 0.92
        elif is_due_review and is_correct:
            if is_overdue_review:
                factor = factor * 1.08
            else:
                factor = factor * 1.04

        factor = _clamp(factor, 0.6, 1.6)
        state.interval_factor = round(factor, 4)
        state.last_adjusted_at = utcnow()

        if is_due_review:
            state.due_review_count += 1
            if is_correct:
                state.due_review_correct_count += 1
            if is_overdue_review and not is_correct:
                state.overdue_wrong_count += 1

    await db.flush()


# ── V6.2: 题目难度校准 ───────────────────────────────────────────────


async def update_question_difficulty_state(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    answer_time_seconds: int | None,
    expected_time_seconds: int | None,
    is_overdue_review: bool,
) -> UserQuestionDifficultyState:
    """更新用户视角下的题目难度分数。"""
    state = await _get_or_create_difficulty(db, user_id, question_id)

    old_score = state.personal_difficulty_score
    delta = 0.0

    # 基础对错
    if is_correct:
        delta -= 4
    else:
        delta += 8

    # 耗时修正
    if (
        answer_time_seconds is not None
        and expected_time_seconds is not None
        and expected_time_seconds > 0
    ):
        if is_correct and answer_time_seconds > expected_time_seconds * 1.5:
            delta += 3  # 答对但很慢
        if not is_correct and answer_time_seconds > expected_time_seconds * 1.5:
            delta += 4  # 答错且很慢
        if is_correct and answer_time_seconds < expected_time_seconds * 0.6:
            delta -= 3  # 快速答对

    # 逾期答错额外惩罚
    if is_overdue_review and not is_correct:
        delta += 5

    new_score = _clamp(old_score + delta, 0, 100)
    state.personal_difficulty_score = round(new_score, 1)
    state.difficulty_label = get_difficulty_label(new_score)

    # 计数器
    state.answer_count += 1
    if is_correct:
        state.correct_count += 1
    else:
        state.wrong_count += 1

    if (
        answer_time_seconds is not None
        and expected_time_seconds is not None
        and expected_time_seconds > 0
    ):
        if is_correct and answer_time_seconds < expected_time_seconds * 0.6:
            state.fast_correct_count += 1
        if answer_time_seconds > expected_time_seconds * 1.5:
            if is_correct:
                state.slow_correct_count += 1
            else:
                state.slow_wrong_count += 1

    if is_overdue_review and not is_correct:
        state.overdue_wrong_count += 1

    # 滑动平均作答时间
    if answer_time_seconds is not None:
        if state.avg_answer_time_seconds is None:
            state.avg_answer_time_seconds = float(answer_time_seconds)
        else:
            n = state.answer_count
            state.avg_answer_time_seconds = (
                state.avg_answer_time_seconds * (n - 1) + answer_time_seconds
            ) / n

    state.last_updated_at = utcnow()
    await db.flush()

    if abs(new_score - old_score) > 0.01:
        logger.info(
            "question_difficulty_updated user=%d q=%d old=%.1f new=%.1f label=%s",
            user_id,
            question_id,
            old_score,
            new_score,
            state.difficulty_label,
        )

    return state


# ── 集成入口 ──────────────────────────────────────────────────────────


async def apply_personalized_interval(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    base_interval_days: int,
) -> int | None:
    """计算个性化间隔并覆盖 UserQuestionState.next_review_at。

    返回最终间隔天数；如果 V6 未启用或出错返回 None。
    """
    if not settings.ADAPTIVE_LEARNING_ENABLED or not settings.ADAPTIVE_INTERVAL_ENABLED:
        return None

    # 用户倍率
    profile_result = await db.execute(
        select(UserAdaptiveProfile).where(UserAdaptiveProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    user_factor = profile.interval_factor if profile else 1.0

    # 知识点倍率（取该题所有知识点的平均值）
    kp_rows = (
        await db.execute(
            select(QuestionKnowledgePoint.knowledge_point_id).where(
                QuestionKnowledgePoint.question_id == question_id
            )
        )
    ).all()
    kp_ids = [r.knowledge_point_id for r in kp_rows]

    knowledge_factor = 1.0
    if kp_ids:
        ka_result = await db.execute(
            select(
                UserKnowledgeAdaptiveState.knowledge_point_id,
                UserKnowledgeAdaptiveState.interval_factor,
            ).where(
                UserKnowledgeAdaptiveState.user_id == user_id,
                UserKnowledgeAdaptiveState.knowledge_point_id.in_(kp_ids),
            )
        )
        factors = [r.interval_factor for r in ka_result.all()]
        if factors:
            knowledge_factor = sum(factors) / len(factors)

    # 难度倍率
    diff_result = await db.execute(
        select(UserQuestionDifficultyState).where(
            UserQuestionDifficultyState.user_id == user_id,
            UserQuestionDifficultyState.question_id == question_id,
        )
    )
    diff_state = diff_result.scalar_one_or_none()
    difficulty_factor = (
        get_difficulty_factor(diff_state.difficulty_label) if diff_state else 1.0
    )

    # 计算最终间隔
    final_days = calculate_personalized_interval_days(
        base_interval_days=base_interval_days,
        user_interval_factor=user_factor,
        knowledge_interval_factor=knowledge_factor,
        difficulty_factor=difficulty_factor,
    )

    # 覆盖 next_review_at
    uqs_result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
    )
    uqs = uqs_result.scalar_one_or_none()
    if uqs is not None:
        now = utcnow()
        uqs.next_review_at = now + timedelta(days=final_days)
        await db.flush()

        logger.info(
            "adaptive_interval_applied user=%d q=%d base=%d final=%d "
            "user_f=%.3f kp_f=%.3f diff_f=%.3f",
            user_id,
            question_id,
            base_interval_days,
            final_days,
            user_factor,
            knowledge_factor,
            difficulty_factor,
        )

    return final_days


async def update_adaptive_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    answer_time_seconds: int | None,
    answered_at: datetime,
    is_due_review: bool | None = None,
    is_overdue_review: bool | None = None,
) -> None:
    """答题后更新 V6 全部自适应状态。

    ``is_due_review`` / ``is_overdue_review`` 应优先由 Leitner 更新函数在覆盖
    ``next_review_at`` **之前**计算并传入。保留空值回退只用于兼容旧调用方；
    新答题链路不得依赖更新后的 ``next_review_at`` 判断本次是否到期。

    调用方应在 try/except 中调用此函数，确保 V6 出错不影响主流程。
    """
    if not settings.ADAPTIVE_LEARNING_ENABLED:
        return

    uqs_result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
    )
    uqs = uqs_result.scalar_one_or_none()

    # 兼容旧调用方：只有未显式传入 pre-update 状态时才自行判断。
    # 注意：如果调用方已经先更新了 Leitner，这个 fallback 读到的是未来时间，
    # 因此当前 practice 单题/批量链路都会显式传入两个布尔值。
    nra = getattr(uqs, "next_review_at", None) if uqs is not None else None
    if is_due_review is None:
        is_due_review = bool(nra is not None and answered_at >= nra)
    if is_overdue_review is None:
        is_overdue_review = bool(
            nra is not None and answered_at >= nra + timedelta(days=1)
        )

    # V6.1: 更新用户间隔倍率
    if settings.ADAPTIVE_INTERVAL_ENABLED and is_due_review:
        await update_user_interval_factor(
            db,
            user_id,
            is_due_review=True,
            is_correct=is_correct,
            is_overdue_review=is_overdue_review,
        )

        # 知识点级倍率
        kp_rows = (
            await db.execute(
                select(QuestionKnowledgePoint.knowledge_point_id).where(
                    QuestionKnowledgePoint.question_id == question_id
                )
            )
        ).all()
        kp_ids = [r.knowledge_point_id for r in kp_rows]
        if kp_ids:
            await update_knowledge_interval_factor(
                db,
                user_id,
                kp_ids,
                is_due_review=True,
                is_correct=is_correct,
                is_overdue_review=is_overdue_review,
            )

    # V6.2: 更新题目难度
    if settings.ADAPTIVE_DIFFICULTY_ENABLED:
        q_result = await db.execute(
            select(Question.difficulty).where(Question.id == question_id)
        )
        q_difficulty = q_result.scalar_one_or_none()
        expected_time = _estimate_expected_time(q_difficulty or 3)

        await update_question_difficulty_state(
            db,
            user_id,
            question_id,
            is_correct=is_correct,
            answer_time_seconds=answer_time_seconds,
            expected_time_seconds=expected_time,
            is_overdue_review=is_overdue_review,
        )

    # 个性化间隔覆盖（仅在 dry_run=False 时生效）
    if not settings.ADAPTIVE_DRY_RUN and uqs is not None:
        from app.services.question_review_service import LEITNER_INTERVAL_DAYS

        base_days = LEITNER_INTERVAL_DAYS.get(uqs.box_level, 1)
        await apply_personalized_interval(db, user_id, question_id, base_days)


# ── API: 个性化概览 ──────────────────────────────────────────────────


async def get_adaptive_overview(db: AsyncSession, user_id: int) -> dict:
    """返回个性化调度概览，用于学习报告展示。"""
    # 用户间隔倍率
    profile_result = await db.execute(
        select(UserAdaptiveProfile).where(UserAdaptiveProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    interval_factor = profile.interval_factor if profile else 1.0
    target_recall = profile.target_recall_rate if profile else 0.8
    recent_due = profile.recent_due_count if profile else 0
    recent_correct = profile.recent_due_correct_count if profile else 0
    recall_rate = (recent_correct / recent_due) if recent_due > 0 else 0.0

    if interval_factor < 0.9:
        interval_status = "fast_forgetting"
    elif interval_factor < 0.98:
        interval_status = "slightly_fast_forgetting"
    elif interval_factor > 1.1:
        interval_status = "stable_memory"
    else:
        interval_status = "normal"

    # 遗忘较快的知识点数
    fast_forgetting_result = await db.execute(
        select(func.count(UserKnowledgeAdaptiveState.id)).where(
            UserKnowledgeAdaptiveState.user_id == user_id,
            UserKnowledgeAdaptiveState.interval_factor < 0.9,
        )
    )
    fast_forgetting_count = fast_forgetting_result.scalar_one()

    # 个人难题数
    hard_result = await db.execute(
        select(func.count(UserQuestionDifficultyState.id)).where(
            UserQuestionDifficultyState.user_id == user_id,
            UserQuestionDifficultyState.difficulty_label == "hard",
        )
    )
    hard_count = hard_result.scalar_one()

    # V6.3: 路径阻塞知识点数（有薄弱前置的 KP 数量）
    path_blocked_count = 0
    try:
        if settings.ADAPTIVE_PATH_ENABLED:
            # 查所有有 prerequisite 边的 target KP
            targets_result = await db.execute(
                select(KnowledgeEdge.target_knowledge_point_id)
                .where(
                    KnowledgeEdge.relation_type == "prerequisite",
                    KnowledgeEdge.is_active == True,  # noqa: E712
                )
                .distinct()
            )
            all_target_ids = [r[0] for r in targets_result.all()]
            if all_target_ids:
                blocked = await get_blocked_knowledge_points(
                    db,
                    user_id,
                    all_target_ids,
                    "",
                )
                path_blocked_count = len(blocked)
    except Exception:
        logger.debug("path_blocked_count 计算失败", exc_info=True)

    # V6.4: 权重状态
    weights_adjusted = False
    weight_summary = ""
    try:
        if settings.ADAPTIVE_WEIGHT_ENABLED:
            pref_result = await db.execute(
                select(UserRecommendPreference).where(
                    UserRecommendPreference.user_id == user_id,
                )
            )
            pref = pref_result.scalar_one_or_none()
            if pref and pref.last_adjusted_at:
                weights_adjusted = True
                # 生成摘要：找出偏离 1.0 最大的权重
                deviations = []
                for field in _WEIGHT_FIELDS:
                    val = getattr(pref, field, 1.0)
                    if abs(val - 1.0) >= 0.05:
                        direction = "偏重" if val > 1.0 else "偏轻"
                        label = field.replace("_weight", "")
                        deviations.append(f"{label}{direction}")
                weight_summary = "；".join(deviations[:3]) if deviations else ""
    except Exception:
        logger.debug("weight_summary 计算失败", exc_info=True)

    return {
        "interval_factor": round(interval_factor, 3),
        "interval_status": interval_status,
        "target_recall_rate": target_recall,
        "recent_due_recall_rate": round(recall_rate, 3),
        "fast_forgetting_knowledge_count": int(fast_forgetting_count),
        "hard_question_count": int(hard_count),
        "path_blocked_knowledge_count": int(path_blocked_count),
        "weights_adjusted": weights_adjusted,
        "weight_summary": weight_summary,
    }


async def get_hard_questions(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> dict:
    """返回用户个人难题列表。"""
    q = (
        select(
            UserQuestionDifficultyState.question_id,
            UserQuestionDifficultyState.personal_difficulty_score,
            UserQuestionDifficultyState.difficulty_label,
            UserQuestionDifficultyState.wrong_count,
            UserQuestionDifficultyState.avg_answer_time_seconds,
        )
        .where(
            UserQuestionDifficultyState.user_id == user_id,
            UserQuestionDifficultyState.difficulty_label == "hard",
        )
        .order_by(
            UserQuestionDifficultyState.personal_difficulty_score.desc(),
        )
        .limit(limit)
    )

    rows = (await db.execute(q)).all()

    # 批量加载 KP 名称和 next_review_at
    q_ids = [r.question_id for r in rows]
    kp_map: dict[int, tuple[int | None, str | None]] = {}
    review_map: dict[int, str | None] = {}

    if q_ids:
        kp_rows = (
            await db.execute(
                select(
                    QuestionKnowledgePoint.question_id,
                    QuestionKnowledgePoint.knowledge_point_id,
                    KnowledgePoint.name,
                )
                .join(
                    KnowledgePoint,
                    QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
                )
                .where(QuestionKnowledgePoint.question_id.in_(q_ids))
                .order_by(QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.id)
            )
        ).all()
        for r in kp_rows:
            if r.question_id not in kp_map:
                kp_map[r.question_id] = (r.knowledge_point_id, r.name)

        uqs_rows = (
            await db.execute(
                select(
                    UserQuestionState.question_id,
                    UserQuestionState.next_review_at,
                ).where(
                    UserQuestionState.user_id == user_id,
                    UserQuestionState.question_id.in_(q_ids),
                )
            )
        ).all()
        for r in uqs_rows:
            review_map[r.question_id] = (
                serialize_utc_datetime(r.next_review_at) if r.next_review_at else None
            )

    items = []
    for r in rows:
        kp = kp_map.get(r.question_id)
        items.append(
            {
                "question_id": r.question_id,
                "knowledge_point_id": kp[0] if kp else None,
                "knowledge_point_name": kp[1] if kp else None,
                "personal_difficulty_score": round(r.personal_difficulty_score, 1),
                "difficulty_label": r.difficulty_label,
                "wrong_count": r.wrong_count,
                "avg_answer_time_seconds": (
                    round(r.avg_answer_time_seconds, 1)
                    if r.avg_answer_time_seconds
                    else None
                ),
                "next_review_at": review_map.get(r.question_id),
            }
        )

    return {"total": len(items), "items": items}


async def get_knowledge_path_adaptive(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> dict:
    """返回知识点路径阻塞建议。"""
    # 查所有有 prerequisite 边的 target KP
    targets_result = await db.execute(
        select(KnowledgeEdge.target_knowledge_point_id)
        .where(
            KnowledgeEdge.relation_type == "prerequisite",
            KnowledgeEdge.is_active == True,  # noqa: E712
        )
        .distinct()
    )
    all_target_ids = [r[0] for r in targets_result.all()]
    if not all_target_ids:
        return {"total": 0, "items": []}

    blocked = await get_blocked_knowledge_points(db, user_id, all_target_ids, "")
    if not blocked:
        return {"total": 0, "items": []}

    # 加载 KP 名称
    kp_ids = list(blocked.keys())
    name_result = await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(
            KnowledgePoint.id.in_(kp_ids),
        )
    )
    kp_names = {r.id: r.name for r in name_result.all()}

    items = []
    for kp_id, weak_prereqs in blocked.items():
        items.append(
            {
                "knowledge_point_id": kp_id,
                "knowledge_point_name": kp_names.get(kp_id, ""),
                "status": "blocked",
                "reason": "前置知识点掌握度不足",
                "blocked_by": weak_prereqs,
            }
        )

    items.sort(key=lambda x: len(x["blocked_by"]), reverse=True)
    return {"total": len(items), "items": items[:limit]}


# ── V6.3: 知识点路径推荐 ─────────────────────────────────────────────


async def get_recommendation_graph_context(
    db: AsyncSession,
    user_id: int,
    target_kp_ids: list[int],
    subject_ids: list[int] | None = None,
    max_depth: int = GRAPH_MAX_DEPTH,
    max_nodes: int = GRAPH_MAX_EXPANSION_NODES,
    min_mastery: float = GRAPH_PREREQUISITE_MASTERY_THRESHOLD,
    min_confidence: float = GRAPH_PREREQUISITE_CONFIDENCE_THRESHOLD,
) -> dict:
    """Batch-load prerequisite context for smart recommendation.

    ``A --prerequisite--> B`` means A should be learned before B.  This helper
    does two jobs in one bounded traversal:

    * ``blocked_targets``: direct prerequisites that are *confirmed* weak and
      should suppress the advanced target a little.
    * ``prerequisite_candidates``: prerequisite KPs that should themselves be
      eligible for question recall.  Unknown prerequisites are kept as soft
      diagnostic candidates, never as a hard block.

    Traversal is bounded by depth/node count and carries a visited (node,
    origin) set, so future bad data containing cycles cannot loop forever.
    Cross-subject edges are filtered at query time when ``subject_ids`` is
    supplied.
    """
    origin_ids = list(dict.fromkeys(int(k) for k in target_kp_ids if k))
    if not origin_ids:
        return {
            "blocked_targets": {},
            "prerequisite_candidates": {},
            "prerequisites_by_target": {},
        }

    max_depth = max(1, min(int(max_depth or 1), GRAPH_MAX_DEPTH))
    max_nodes = max(1, int(max_nodes or GRAPH_MAX_EXPANSION_NODES))

    # state[(current_node, origin_target)] = cumulative path quality before the
    # next edge.  Start each origin at quality 1.0.
    frontier: dict[tuple[int, int], dict[str, float]] = {
        (origin, origin): {"weight": 1.0, "confidence": 1.0} for origin in origin_ids
    }
    visited: set[tuple[int, int]] = set(frontier)
    relations: list[dict] = []

    for depth in range(1, max_depth + 1):
        if not frontier or len(relations) >= max_nodes:
            break

        current_targets = list({node_id for node_id, _origin in frontier})
        edge_conditions = [
            KnowledgeEdge.target_knowledge_point_id.in_(current_targets),
            KnowledgeEdge.relation_type == "prerequisite",
            KnowledgeEdge.is_active == True,  # noqa: E712
        ]
        if subject_ids:
            scope_ids = list({int(sid) for sid in subject_ids})
            scoped_kps = select(KnowledgePoint.id).where(
                KnowledgePoint.is_active == True,  # noqa: E712
                KnowledgePoint.subject_id.in_(scope_ids),
            )
            edge_conditions.extend(
                [
                    KnowledgeEdge.subject_id.in_(scope_ids),
                    KnowledgeEdge.source_knowledge_point_id.in_(scoped_kps),
                    KnowledgeEdge.target_knowledge_point_id.in_(scoped_kps),
                ]
            )

        edge_result = await db.execute(
            select(
                KnowledgeEdge.id,
                KnowledgeEdge.target_knowledge_point_id,
                KnowledgeEdge.source_knowledge_point_id,
                KnowledgeEdge.weight,
                KnowledgeEdge.confidence,
                KnowledgeEdge.source,
            ).where(*edge_conditions)
        )
        edges_by_target: dict[int, list] = {}
        for edge in edge_result.all():
            edges_by_target.setdefault(edge.target_knowledge_point_id, []).append(edge)

        next_frontier: dict[tuple[int, int], dict[str, float]] = {}
        for (current_id, origin_id), parent_quality in frontier.items():
            for edge in edges_by_target.get(current_id, []):
                prereq_id = edge.source_knowledge_point_id
                pair = (prereq_id, origin_id)
                if pair in visited:
                    continue

                edge_weight = normalize_edge_weight(edge.weight)
                edge_confidence = _clamp01(edge.confidence)
                cumulative_weight = parent_quality["weight"] * edge_weight
                cumulative_confidence = parent_quality["confidence"] * edge_confidence
                depth_decay = 1.0 if depth == 1 else 0.65
                path_quality = cumulative_weight * cumulative_confidence * depth_decay

                relations.append(
                    {
                        "knowledge_point_id": prereq_id,
                        "origin_knowledge_point_id": origin_id,
                        "depth": depth,
                        "edge_id": edge.id,
                        "edge_weight": edge_weight,
                        "edge_confidence": edge_confidence,
                        "edge_source": edge.source,
                        "path_quality": max(0.0, min(path_quality, 1.0)),
                    }
                )
                visited.add(pair)
                if len(relations) >= max_nodes:
                    break
                if depth < max_depth:
                    next_frontier[pair] = {
                        "weight": cumulative_weight,
                        "confidence": cumulative_confidence,
                    }
            if len(relations) >= max_nodes:
                break
        frontier = next_frontier

    if not relations:
        return {
            "blocked_targets": {},
            "prerequisite_candidates": {},
            "prerequisites_by_target": {},
        }

    all_kp_ids = list(
        {
            *origin_ids,
            *(r["knowledge_point_id"] for r in relations),
        }
    )

    name_result = await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.name, KnowledgePoint.subject_id).where(
            KnowledgePoint.id.in_(all_kp_ids),
            KnowledgePoint.is_active == True,  # noqa: E712
        )
    )
    kp_info = {
        row.id: {"name": row.name, "subject_id": row.subject_id}
        for row in name_result.all()
    }

    mastery_result = await db.execute(
        select(
            UserKnowledgeState.knowledge_point_id,
            UserKnowledgeState.mastery_score,
            UserKnowledgeState.confidence,
        ).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(all_kp_ids),
        )
    )
    mastery = {
        row.knowledge_point_id: (float(row.mastery_score), float(row.confidence))
        for row in mastery_result.all()
    }

    blocked_targets: dict[int, list[dict]] = {}
    prerequisites_by_target: dict[int, list[dict]] = {}
    prerequisite_candidates: dict[int, dict] = {}

    for rel in relations:
        prereq_id = rel["knowledge_point_id"]
        origin_id = rel["origin_knowledge_point_id"]
        if prereq_id not in kp_info or origin_id not in kp_info:
            continue
        if subject_ids and (
            kp_info[prereq_id]["subject_id"] not in subject_ids
            or kp_info[origin_id]["subject_id"] not in subject_ids
        ):
            continue

        prereq_mastery, prereq_conf = mastery.get(prereq_id, (50.0, 0.0))
        origin_mastery, origin_conf = mastery.get(origin_id, (50.0, 0.0))
        confirmed_gap = prereq_conf >= min_confidence and prereq_mastery < min_mastery
        unknown_gap = prereq_conf < min_confidence

        item = {
            **rel,
            "name": kp_info[prereq_id]["name"],
            "subject_id": kp_info[prereq_id]["subject_id"],
            "mastery_score": round(prereq_mastery, 1),
            "mastery_confidence": round(prereq_conf, 3),
            "origin_name": kp_info[origin_id]["name"],
            "origin_mastery_score": round(origin_mastery, 1),
            "origin_mastery_confidence": round(origin_conf, 3),
            "confirmed_gap": confirmed_gap,
            "unknown_gap": unknown_gap,
        }
        prerequisites_by_target.setdefault(origin_id, []).append(item)

        # Hard blocking only uses a direct, sufficiently observed weak prereq.
        if rel["depth"] == 1 and confirmed_gap:
            blocked_targets.setdefault(origin_id, []).append(item)

        # Candidate expansion: confirmed gaps are strong; unknown direct
        # prerequisites can be softly diagnosed; mastered prerequisites are
        # deliberately excluded so they cannot keep dominating recommendations.
        eligible_candidate = confirmed_gap or (rel["depth"] == 1 and unknown_gap)
        if not eligible_candidate:
            continue

        # Prefer the strongest origin/path when the same prerequisite supports
        # multiple weak targets.
        current = prerequisite_candidates.get(prereq_id)
        rank = (
            1 if confirmed_gap else 0,
            rel["path_quality"],
            -rel["depth"],
        )
        current_rank = (
            1 if current and current.get("confirmed_gap") else 0,
            current.get("path_quality", 0.0) if current else -1.0,
            -current.get("depth", 99) if current else -99,
        )
        if current is None or rank > current_rank:
            prerequisite_candidates[prereq_id] = item

    return {
        "blocked_targets": blocked_targets,
        "prerequisite_candidates": prerequisite_candidates,
        "prerequisites_by_target": prerequisites_by_target,
    }


async def get_blocked_knowledge_points(
    db: AsyncSession,
    user_id: int,
    kp_ids: list[int],
    subject: str,
    min_mastery: float = GRAPH_PREREQUISITE_MASTERY_THRESHOLD,
    min_confidence: float = GRAPH_PREREQUISITE_CONFIDENCE_THRESHOLD,
) -> dict[int, list[dict]]:
    """批量检查 kp_ids 中哪些知识点的前置知识点薄弱。

    返回 {kp_id: [{"knowledge_point_id": int, "name": str, "mastery_score": float}, ...]}
    仅包含存在薄弱前置的 kp_id。

    用于 calculate_smart_score 的 path_blocked 维度。
    """
    if not kp_ids:
        return {}
    context = await get_recommendation_graph_context(
        db=db,
        user_id=user_id,
        target_kp_ids=kp_ids,
        max_depth=1,
        min_mastery=min_mastery,
        min_confidence=min_confidence,
    )
    return context["blocked_targets"]


def can_recommend_advanced_knowledge(
    prerequisite_states: list[dict],
    min_mastery_score: float = GRAPH_PREREQUISITE_MASTERY_THRESHOLD,
    min_confidence: float = GRAPH_PREREQUISITE_CONFIDENCE_THRESHOLD,
) -> bool:
    """判断前置知识点是否满足推荐高阶知识点的条件。

    prerequisite_states: [{"mastery_score": float, "confidence": float}, ...]
    如果任一前置知识点 mastery < min_mastery_score 且 confidence >= min_confidence，
    返回 False（不应推荐高阶）。
    """
    if not prerequisite_states:
        return True
    for state in prerequisite_states:
        if (
            state["confidence"] >= min_confidence
            and state["mastery_score"] < min_mastery_score
        ):
            return False
    return True


# ── V6.4: 推荐权重个性化 ─────────────────────────────────────────────

# 默认权重（所有维度 = 1.0）
_DEFAULT_WEIGHTS = {
    "due_weight": 1.0,
    "weakness_weight": 1.0,
    "wrong_weight": 1.0,
    "new_question_weight": 1.0,
    "diversity_weight": 1.0,
    "difficulty_weight": 1.0,
    "path_weight": 1.0,
}

_WEIGHT_FIELDS = list(_DEFAULT_WEIGHTS.keys())
_WEIGHT_MIN, _WEIGHT_MAX = 0.7, 1.3
_ADJUST_STEP = 0.05  # 每次微调步长


def default_weights() -> dict[str, float]:
    """返回默认权重字典的副本。"""
    return dict(_DEFAULT_WEIGHTS)


async def get_recommend_weights(
    db: AsyncSession,
    user_id: int,
) -> dict[str, float]:
    """加载用户推荐权重。无记录时返回默认值（不创建记录）。"""
    if not settings.ADAPTIVE_LEARNING_ENABLED or not settings.ADAPTIVE_WEIGHT_ENABLED:
        return default_weights()

    result = await db.execute(
        select(UserRecommendPreference).where(
            UserRecommendPreference.user_id == user_id,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        return default_weights()

    return {field: getattr(pref, field) for field in _WEIGHT_FIELDS}


async def _get_or_create_preference(
    db: AsyncSession,
    user_id: int,
) -> UserRecommendPreference:
    result = await db.execute(
        select(UserRecommendPreference).where(
            UserRecommendPreference.user_id == user_id,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = UserRecommendPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


def _adjust_weight(current: float, direction: int) -> float:
    """单步微调权重：direction=+1 增加，-1 减少。clamp 到 [0.7, 1.3]。"""
    return _clamp(current + direction * _ADJUST_STEP, _WEIGHT_MIN, _WEIGHT_MAX)


async def adjust_recommend_weights(
    db: AsyncSession,
    user_id: int,
) -> dict[str, float]:
    """根据近期表现自动微调推荐权重。

    调节规则：
    - 最近到期错题多 → due_weight +0.05
    - 薄弱知识点无改善 → weakness_weight +0.05
    - 新题推进太少 → new_question_weight +0.05
    - 推荐过于集中 → diversity_weight +0.05
    - 到期正确率高 → due_weight -0.05（可以减少关注到期）
    - 新题比例正常 → new_question_weight -0.05

    建议每完成 20 题或每周调用一次。
    """
    if not settings.ADAPTIVE_LEARNING_ENABLED or not settings.ADAPTIVE_WEIGHT_ENABLED:
        return default_weights()

    pref = await _get_or_create_preference(db, user_id)
    now = utcnow()
    recent_start = now - timedelta(days=14)

    # 近期答题统计
    recent_result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)),  # noqa: E712
                0,  # noqa: E712
            ),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= recent_start,
        )
    )
    recent_count, recent_correct = recent_result.one()
    recent_count = int(recent_count or 0)
    recent_correct = int(recent_correct or 0)

    if recent_count < 5:
        # 数据不足，不调整
        return {field: getattr(pref, field) for field in _WEIGHT_FIELDS}

    recent_accuracy = recent_correct / recent_count if recent_count > 0 else 0

    # 到期复习正确率
    due_result = await db.execute(
        select(
            func.count(UserQuestionState.id),
            func.coalesce(
                func.sum(case((UserQuestionState.last_is_correct == True, 1), else_=0)),  # noqa: E712
                0,  # noqa: E712
            ),
        ).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.last_answered_at >= recent_start,
        )
    )
    due_count, due_correct = due_result.one()
    due_count = int(due_count or 0)
    due_correct = int(due_correct or 0)
    due_accuracy = due_correct / due_count if due_count > 0 else 0.5

    # 开始调节
    adjustments: dict[str, int] = {f: 0 for f in _WEIGHT_FIELDS}

    # 到期正确率低 → 增加 due 权重
    if due_accuracy < 0.6 and due_count >= 3:
        adjustments["due_weight"] += 1
    # 到期正确率高 → 可以降低 due 权重
    elif due_accuracy >= 0.85 and due_count >= 5:
        adjustments["due_weight"] -= 1

    # 整体正确率低 → 增加 weakness 权重
    if recent_accuracy < 0.5:
        adjustments["weakness_weight"] += 1

    # 新题比例：用 answer_count == 1 的记录占比估算
    # 简化：如果近期答题少，增加新题权重
    if recent_count < 10:
        adjustments["new_question_weight"] += 1
    elif recent_count > 30:
        adjustments["new_question_weight"] -= 1

    # 应用调节
    for field, direction in adjustments.items():
        if direction != 0:
            current = getattr(pref, field)
            new_val = _adjust_weight(current, direction)
            setattr(pref, field, new_val)

    pref.last_adjusted_at = now
    await db.flush()

    result_weights = {field: getattr(pref, field) for field in _WEIGHT_FIELDS}

    if any(d != 0 for d in adjustments.values()):
        logger.info(
            "adaptive_weights_adjusted user=%d adjustments=%s weights=%s",
            user_id,
            {k: v for k, v in adjustments.items() if v != 0},
            result_weights,
        )

    return result_weights
