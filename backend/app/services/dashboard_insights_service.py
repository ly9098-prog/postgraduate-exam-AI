"""
Dashboard insights service — practice diagnosis computed entirely from existing tables.
Each metric function is independent and returns None when data is insufficient.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import Date as SQLDate
from sqlalchemy import case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import (
    serialize_utc_datetime,
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.models.admin import QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.review_scheduler import ReviewSchedule
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.wrong_question import WrongQuestion
from app.services import dashboard_action_projection as actions
from app.services import dashboard_balance_projection as balance
from app.services import dashboard_quality_projection as quality
from app.services import dashboard_speed_projection as speed
from app.services import dashboard_topic_projection as topics


async def _china_date_expr(db: AsyncSession, column):
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)


# ──────────────────────────────────────────────
# 1. Today Quality Score
# ──────────────────────────────────────────────


async def compute_today_quality(db: AsyncSession, user_id: int) -> dict | None:
    """今日学习质量评分 (0-100)，不足 5 题返回 None。"""
    today_start = shanghai_today_boundaries()[0]

    row = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.avg(PracticeRecord.used_time), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= today_start,
        )
    )
    count, correct, avg_time = row.one()
    return quality.today_quality(count, correct, avg_time)


# ──────────────────────────────────────────────
# 2. Weekly Consistency
# ──────────────────────────────────────────────


async def compute_weekly_consistency(
    db: AsyncSession, user_id: int, days: int = 7
) -> dict | None:
    """学习稳定性评分：活跃天数、每日题量方差、正确率方差。"""
    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)

    rows = await db.execute(
        select(
            day_expr,
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(day_expr)
    )
    return quality.weekly_consistency(rows.all(), today, days)


# ──────────────────────────────────────────────
# 3. Weak Topic Ranking
# ──────────────────────────────────────────────


async def compute_weak_topic_ranking(
    db: AsyncSession, user_id: int, limit: int = 10
) -> dict | None:
    """薄弱知识点排行。

    优先从 UserKnowledgeState 获取，数据不足时从 WrongQuestion 推导。
    """
    # Try UserKnowledgeState first
    rows = await db.execute(
        select(
            UserKnowledgeState.knowledge_point_id,
            KnowledgePoint.name,
            UserKnowledgeState.subject_id,
            Subject.code,
            Subject.name,
            UserKnowledgeState.mastery_score,
            UserKnowledgeState.attempt_count,
            UserKnowledgeState.wrong_count,
            UserKnowledgeState.recent_wrong_count,
            UserKnowledgeState.last_practiced_at,
        )
        .join(
            KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id
        )
        .outerjoin(Subject, UserKnowledgeState.subject_id == Subject.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.mastery_score < 45,
            UserKnowledgeState.attempt_count >= 2,
        )
        .order_by(UserKnowledgeState.mastery_score.asc())
        .limit(limit)
    )
    items_data = rows.all()

    if items_data:
        # Get due review counts per KP from ReviewSchedule
        due_counts = await _compute_kp_due_review_counts(db, user_id)

        return topics.weak_topic_items(
            items_data, due_counts, lambda value: serialize_utc_datetime(value)
        )

    # Fallback: derive from the immutable revision attached to each wrong row.
    # Historical weak-topic attribution must not move when the mutable Question
    # is later edited or remapped to different knowledge points.
    kp_rows = await db.execute(
        select(
            func.coalesce(
                SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name
            ).label("frozen_name"),
            func.count(WrongQuestion.id).label("wrong_count"),
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id
            == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
        )
        .join(
            WrongQuestion,
            WrongQuestion.question_version_id
            == QuestionVersionKnowledgePoint.question_version_id,
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
            ~WrongQuestion.mastered,
        )
        .group_by(
            KnowledgePoint.id,
            func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
        )
        .order_by(func.count(WrongQuestion.id).desc(), KnowledgePoint.id.asc())
        .limit(limit)
    )
    return topics.fallback_weak_topics(kp_rows.all())


async def _compute_kp_due_review_counts(
    db: AsyncSession, user_id: int
) -> dict[int, int]:
    """Count due reviews per knowledge_point_id."""
    now = utcnow()
    rows = await db.execute(
        select(
            QuestionVersionKnowledgePoint.knowledge_point_id,
            func.count(ReviewSchedule.id),
        )
        .join(
            ReviewSchedule,
            ReviewSchedule.question_version_id
            == QuestionVersionKnowledgePoint.question_version_id,
        )
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= now,
        )
        .group_by(QuestionVersionKnowledgePoint.knowledge_point_id)
    )
    return {row[0]: row[1] for row in rows.all()}


# ──────────────────────────────────────────────
# 4. Repeat Wrong Analysis
# ──────────────────────────────────────────────


async def compute_repeat_wrong_analysis(db: AsyncSession, user_id: int) -> dict | None:
    """错题复发分析：review_count>0 但仍未 mastered 的错题。"""
    total = await db.execute(
        select(func.count(WrongQuestion.id)).where(WrongQuestion.user_id == user_id)
    )
    total_wq = total.scalar() or 0
    if total_wq < 3:
        return None

    repeat = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
            WrongQuestion.review_count >= 1,
        )
    )
    repeat_count = repeat.scalar() or 0
    rate = repeat_count / max(total_wq, 1)

    # Top repeat topics are attributed to the revision that was actually wrong.
    topic_rows = await db.execute(
        select(
            func.coalesce(
                SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name
            ).label("frozen_name"),
            func.count(WrongQuestion.id).label("wrong_count"),
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id
            == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
        )
        .join(
            WrongQuestion,
            WrongQuestion.question_version_id
            == QuestionVersionKnowledgePoint.question_version_id,
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
            ~WrongQuestion.mastered,
            WrongQuestion.review_count >= 1,
        )
        .group_by(
            KnowledgePoint.id,
            func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
        )
        .order_by(func.count(WrongQuestion.id).desc(), KnowledgePoint.id.asc())
        .limit(5)
    )
    top_topics = [
        {"name": str(name), "count": int(count or 0)}
        for name, count in topic_rows.all()
    ]

    return topics.repeat_wrong_analysis(total_wq, repeat_count, rate, top_topics)


# ──────────────────────────────────────────────
# 5. Speed-Accuracy Analysis
# ──────────────────────────────────────────────


async def compute_speed_accuracy(db: AsyncSession, user_id: int) -> dict | None:
    """速度与准确率分析：正确/错误题平均用时对比。"""
    row = await db.execute(
        select(
            func.coalesce(
                func.avg(
                    case((PracticeRecord.is_correct == True, PracticeRecord.used_time))  # noqa: E712
                ),
                0,  # noqa: E712
            ),
            func.coalesce(
                func.avg(
                    case((PracticeRecord.is_correct == False, PracticeRecord.used_time))  # noqa: E712
                ),
                0,  # noqa: E712
            ),
            func.coalesce(func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.used_time.isnot(None),
            PracticeRecord.used_time > 0,
        )
    )
    avg_correct, avg_wrong, wrong_count = row.one()
    avg_correct = float(avg_correct or 0)
    avg_wrong = float(avg_wrong or 0)
    wrong_count = wrong_count or 0

    if avg_correct == 0 and avg_wrong == 0:
        return None

    # Fast wrong (<15s) and slow wrong (>120s) in single query
    fw_sw = await db.execute(
        select(
            func.coalesce(
                func.sum(case((PracticeRecord.used_time < 15, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((PracticeRecord.used_time > 120, 1), else_=0)), 0
            ),
        ).where(
            PracticeRecord.user_id == user_id,
            ~PracticeRecord.is_correct,
            PracticeRecord.used_time.isnot(None),
        )
    )
    fast_wrong, slow_wrong = fw_sw.one()
    fast_wrong = int(fast_wrong or 0)
    slow_wrong = int(slow_wrong or 0)

    status = speed.classify_speed(
        avg_correct, avg_wrong, wrong_count, fast_wrong, slow_wrong
    )

    # Per-subject breakdown
    subj_rows = await db.execute(
        select(
            PracticeRecord.subject_id,
            Subject.code,
            Subject.name,
            func.coalesce(
                func.avg(
                    case((PracticeRecord.is_correct == True, PracticeRecord.used_time))  # noqa: E712
                ),
                0,  # noqa: E712
            ),
            func.coalesce(
                func.avg(
                    case((PracticeRecord.is_correct == False, PracticeRecord.used_time))  # noqa: E712
                ),
                0,  # noqa: E712
            ),
            func.count(PracticeRecord.id),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.used_time.isnot(None),
            PracticeRecord.used_time > 0,
        )
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    return speed.speed_accuracy(
        avg_correct, avg_wrong, fast_wrong, slow_wrong, status, subj_rows.all()
    )


# ──────────────────────────────────────────────
# 6. New vs Review
# ──────────────────────────────────────────────


async def compute_new_vs_review(db: AsyncSession, user_id: int) -> dict | None:
    """新题 vs 复习题对比分析。

    通过 PracticeRecord 是否有同 user+question 的先前记录来区分：
    - 首次作答 = 新题
    - 后续作答 = 复习题
    """
    # Get first practice time per question for this user
    first_subq = (
        select(
            PracticeRecord.question_id,
            func.min(PracticeRecord.id).label("first_id"),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.question_id)
    ).subquery()

    # Count all practice records per type
    rows = await db.execute(
        select(
            case(
                (PracticeRecord.id == first_subq.c.first_id, "new"),
                else_="review",
            ).label("ptype"),
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
        )
        .join(
            first_subq,
            PracticeRecord.question_id == first_subq.c.question_id,
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by("ptype")
    )
    return balance.new_vs_review(rows.all())


# ──────────────────────────────────────────────
# 7. Input-Output Analysis
# ──────────────────────────────────────────────


async def compute_input_output(
    db: AsyncSession, user_id: int, trend_days: int = 90
) -> dict | None:
    """投入产出分析：按学科对比用时与正确率。

    效率分 = 正确率 / (该科每题均时 / 全局每题均时)
    """
    since = shanghai_date_utc_range(shanghai_today() - timedelta(days=trend_days - 1))[
        0
    ]

    rows = await db.execute(
        select(
            PracticeRecord.subject_id,
            Subject.code,
            Subject.name,
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
            PracticeRecord.used_time.isnot(None),
            PracticeRecord.used_time > 0,
        )
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    return balance.input_output(rows.all())


# ──────────────────────────────────────────────
# 8. Action Plan
# ──────────────────────────────────────────────


async def compute_action_plan(
    db: AsyncSession,
    user_id: int,
    overview: dict | None = None,
    repeat_wrong: dict | None = None,
    weak_topics: dict | None = None,
    new_vs_review: dict | None = None,
) -> dict:
    """Rule-based action plan based on all available metrics."""
    return actions.action_plan(overview, repeat_wrong, weak_topics, new_vs_review)


# ──────────────────────────────────────────────
# Top-level aggregator
# ──────────────────────────────────────────────


async def get_dashboard_insights(
    db: AsyncSession,
    user_id: int,
    *,
    days: int = 7,
    include_subjects: bool = True,
    include_topics: bool = True,
) -> dict:
    """聚合所有诊断指标。每个指标独立计算，失败不影响其他。"""
    from app.core.cache import cache

    cache_key = f"stats:insights:{user_id}:{days}:{include_subjects}:{include_topics}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    # Run independent computations concurrently
    tasks = [
        compute_today_quality(db, user_id),
        compute_weekly_consistency(db, user_id, days),
    ]
    if include_topics:
        tasks.append(compute_weak_topic_ranking(db, user_id))
    tasks.append(compute_repeat_wrong_analysis(db, user_id))
    tasks.append(compute_speed_accuracy(db, user_id))
    tasks.append(compute_new_vs_review(db, user_id))
    if include_subjects:
        tasks.append(compute_input_output(db, user_id, days))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    def safe_get(idx: int):
        val = results[idx] if idx < len(results) else None
        if isinstance(val, Exception):
            return None
        return val

    idx = 0
    today_quality = safe_get(idx)
    idx += 1
    weekly_consistency = safe_get(idx)
    idx += 1
    weak_topics = safe_get(idx) if include_topics else None
    if include_topics:
        idx += 1
    repeat_wrong = safe_get(idx)
    idx += 1
    speed_accuracy = safe_get(idx)
    idx += 1
    new_vs_review = safe_get(idx)
    idx += 1
    input_output = safe_get(idx) if include_subjects else None

    # Get overview for action plan (due_review_count)
    from app.services.stats_service import get_overview

    overview = await get_overview(db, user_id)

    action_plan = await compute_action_plan(
        db,
        user_id,
        overview=overview,
        repeat_wrong=repeat_wrong,
        weak_topics=weak_topics,
        new_vs_review=new_vs_review,
    )

    result = {
        "today_quality": today_quality,
        "weekly_consistency": weekly_consistency,
        "weak_topic_ranking": weak_topics,
        "repeat_wrong_analysis": repeat_wrong,
        "speed_accuracy": speed_accuracy,
        "new_vs_review": new_vs_review,
        "input_output": input_output,
        "action_plan": action_plan,
    }

    try:
        await cache.set(cache_key, result, ttl=120)
    except Exception:
        pass

    return result
