"""V5 学习报告服务 — 纯统计查询，不修改任何数据。"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import shanghai_today, utcnow
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.user_question_state import UserQuestionState
from app.services.learning_time_projection import (
    china_date_expr as _china_date_expr,
)
from app.services.learning_time_projection import (
    date_utc_range as _date_utc_range,
)
from app.services.learning_time_projection import (
    today_utc as _today_utc,
)
from app.services.study_report_projection import (
    build_knowledge_mastery_response,
    build_leitner_distribution_response,
    build_overview_response,
    build_review_plan_item,
    build_wrong_question_item,
    calc_priority,
    classify_mastery,
    extract_title,
    mastery_suggestion,
    normalize_study_trend_counts,
    safe_accuracy,
)

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


_safe_accuracy = safe_accuracy
_extract_title = extract_title
_classify_mastery = classify_mastery
_mastery_suggestion = mastery_suggestion
_calc_priority = calc_priority


async def _subject_exists(db: AsyncSession, subject_id: int) -> bool:
    """Check whether a subject id exists in the subjects table."""
    from app.models.admin import Subject

    result = await db.execute(
        select(Subject.id).where(Subject.id == subject_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── 1. Overview ─────────────────────────────────────────────────────


def _practice_counts_query(
    user_id: int,
    subject_id: int | None,
    today_start,
    recent_start,
):
    """Build the single practice-record aggregation query."""
    query = select(
        func.coalesce(
            func.sum(case((PracticeRecord.answered_at >= today_start, 1), else_=0)), 0
        ).label("today_count"),
        func.coalesce(
            func.sum(
                case(
                    (
                        (PracticeRecord.answered_at >= today_start)
                        & (PracticeRecord.is_correct == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("today_correct"),
        func.coalesce(
            func.sum(case((PracticeRecord.answered_at >= recent_start, 1), else_=0)), 0
        ).label("recent_count"),
        func.coalesce(
            func.sum(
                case(
                    (
                        (PracticeRecord.answered_at >= recent_start)
                        & (PracticeRecord.is_correct == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("recent_correct"),
        func.count(PracticeRecord.id).label("total_count"),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)),  # noqa: E712
            0,  # noqa: E712
        ).label("total_correct"),
    ).where(PracticeRecord.user_id == user_id)

    if subject_id is not None:
        query = query.where(PracticeRecord.subject_id == subject_id)
    return query


async def _load_practice_counts(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None,
    today_start,
    recent_start,
) -> tuple[int, int, int, int, int, int]:
    """Execute the practice aggregation once and return integer counters."""
    row = (
        await db.execute(
            _practice_counts_query(user_id, subject_id, today_start, recent_start)
        )
    ).one()
    return (
        int(row.today_count or 0),
        int(row.today_correct or 0),
        int(row.recent_count or 0),
        int(row.recent_correct or 0),
        int(row.total_count or 0),
        int(row.total_correct or 0),
    )


def _review_state_count_query(user_id: int, subject_id: int | None, where_extra):
    """Build a UserQuestionState count query with optional subject filtering."""
    query = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id, *where_extra
    )
    if subject_id is not None:
        query = query.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    return query


async def _count_review_states(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None,
    now,
    overdue_threshold,
) -> tuple[int, int]:
    """Count due and overdue review states in the original query order."""
    due_count = (
        await db.execute(
            _review_state_count_query(
                user_id,
                subject_id,
                [
                    UserQuestionState.next_review_at <= now,
                    UserQuestionState.next_review_at.isnot(None),
                ],
            )
        )
    ).scalar_one()
    overdue_count = (
        await db.execute(
            _review_state_count_query(
                user_id,
                subject_id,
                [
                    UserQuestionState.next_review_at < overdue_threshold,
                    UserQuestionState.next_review_at.isnot(None),
                ],
            )
        )
    ).scalar_one()
    return int(due_count), int(overdue_count)


def _wrong_state_count_query(user_id: int, subject_id: int | None, where_extra):
    """Build a wrong-question count query with optional subject filtering."""
    query = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count > 0,
        *where_extra,
    )
    if subject_id is not None:
        query = query.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    return query


async def _count_wrong_states(
    db: AsyncSession, user_id: int, subject_id: int | None
) -> tuple[int, int]:
    """Count wrong-question totals and repeated wrong questions."""
    wrong_total = (
        await db.execute(_wrong_state_count_query(user_id, subject_id, []))
    ).scalar_one()
    repeated_wrong = (
        await db.execute(
            _wrong_state_count_query(
                user_id, subject_id, [UserQuestionState.wrong_count >= 3]
            )
        )
    ).scalar_one()
    return int(wrong_total), int(repeated_wrong)


def _knowledge_state_count_query(user_id: int, subject_id: int | None, where_extra):
    """Build a UserKnowledgeState count query with optional subject filtering."""
    subject_filter = []
    if subject_id is not None:
        subject_filter.append(UserKnowledgeState.subject_id == subject_id)
    return select(func.count(UserKnowledgeState.id)).where(
        UserKnowledgeState.user_id == user_id, *subject_filter, *where_extra
    )


async def _count_knowledge_states(
    db: AsyncSession, user_id: int, subject_id: int | None
) -> tuple[int, int, int]:
    """Count weak, unstable and mastered knowledge states in query order."""
    weak_count = (
        await db.execute(
            _knowledge_state_count_query(
                user_id,
                subject_id,
                [
                    UserKnowledgeState.mastery_score < 40,
                    UserKnowledgeState.confidence >= 0.3,
                ],
            )
        )
    ).scalar_one()
    unstable_count = (
        await db.execute(
            _knowledge_state_count_query(
                user_id,
                subject_id,
                [
                    UserKnowledgeState.mastery_score >= 40,
                    UserKnowledgeState.mastery_score < 85,
                    UserKnowledgeState.confidence >= 0.3,
                ],
            )
        )
    ).scalar_one()
    mastered_count = (
        await db.execute(
            _knowledge_state_count_query(
                user_id,
                subject_id,
                [
                    UserKnowledgeState.mastery_score >= 85,
                    UserKnowledgeState.confidence >= 0.5,
                ],
            )
        )
    ).scalar_one()
    return int(weak_count), int(unstable_count), int(mastered_count)


async def get_overview(
    db: AsyncSession, user_id: int, subject_id: int | None = None, days: int = 7
) -> dict:
    now = utcnow()
    today_start = _today_utc()
    recent_start = today_start - timedelta(days=days)

    (
        today_count,
        today_correct,
        recent_count,
        recent_correct,
        total_count,
        total_correct,
    ) = await _load_practice_counts(db, user_id, subject_id, today_start, recent_start)

    due_count, overdue_count = await _count_review_states(
        db, user_id, subject_id, now, now - timedelta(days=1)
    )
    wrong_total, repeated_wrong = await _count_wrong_states(db, user_id, subject_id)

    weak_count = unstable_count = mastered_count = 0
    if subject_id is None:
        weak_count, unstable_count, mastered_count = await _count_knowledge_states(
            db, user_id, None
        )
    elif await _subject_exists(db, subject_id):
        weak_count, unstable_count, mastered_count = await _count_knowledge_states(
            db, user_id, subject_id
        )
    # 该 subject_id 不存在时知识点统计保持 0，但错题统计仍有效

    return build_overview_response(
        today_count=today_count,
        today_correct=today_correct,
        recent_count=recent_count,
        recent_correct=recent_correct,
        total_count=total_count,
        total_correct=total_correct,
        due_count=due_count,
        overdue_count=overdue_count,
        weak_count=weak_count,
        unstable_count=unstable_count,
        mastered_count=mastered_count,
        wrong_total=wrong_total,
        repeated_wrong=repeated_wrong,
    )


# ── 2. Review Plan ──────────────────────────────────────────────────


async def get_review_plan(
    db: AsyncSession, user_id: int, subject_id: int | None = None, limit: int = 20
) -> dict:
    now = utcnow()
    overdue_threshold = now - timedelta(days=1)

    # 总数
    def _rp_count_q(where_extra):
        q = select(func.count(UserQuestionState.id)).where(
            UserQuestionState.user_id == user_id, *where_extra
        )
        if subject_id is not None:
            q = q.join(Question, UserQuestionState.question_id == Question.id).where(
                Question.subject_id == subject_id
            )
        return q

    due_count = (
        await db.execute(
            _rp_count_q(
                [
                    UserQuestionState.next_review_at <= now,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    overdue_count = (
        await db.execute(
            _rp_count_q(
                [
                    UserQuestionState.next_review_at < overdue_threshold,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    # 明细列表（按优先级排序）
    items_q = select(
        UserQuestionState.question_id,
        UserQuestionState.box_level,
        UserQuestionState.wrong_count,
        UserQuestionState.correct_count,
        UserQuestionState.next_review_at,
    ).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.next_review_at <= now,
        UserQuestionState.next_review_at.isnot(None),
    )
    if subject_id is not None:
        items_q = items_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)

    items_q = items_q.order_by(
        UserQuestionState.next_review_at.asc(),
        UserQuestionState.box_level.asc(),
        UserQuestionState.wrong_count.desc(),
    ).limit(limit)

    rows = (await db.execute(items_q)).all()
    q_ids = [r.question_id for r in rows]

    # 批量加载知识点
    kp_map: dict[int, tuple[int, str]] = {}
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

    items = []
    for r in rows:
        kp = kp_map.get(r.question_id)
        items.append(build_review_plan_item(row=r, knowledge_point=kp, now=now))

    return {
        "due_count": int(due_count),
        "overdue_count": int(overdue_count),
        "today_recommended_count": len(items),
        "items": items,
    }


# ── 3. Leitner Distribution ─────────────────────────────────────────


async def get_leitner_distribution(
    db: AsyncSession, user_id: int, subject_id: int | None = None
) -> dict:
    q = select(
        UserQuestionState.box_level,
        func.count(UserQuestionState.id).label("cnt"),
    ).where(UserQuestionState.user_id == user_id)

    if subject_id is not None:
        q = q.join(Question, UserQuestionState.question_id == Question.id).where(
            Question.subject_id == subject_id
        )

    q = q.group_by(UserQuestionState.box_level)
    rows = (await db.execute(q)).all()
    counts = {r.box_level: int(r.cnt) for r in rows}
    return build_leitner_distribution_response(counts)


# ── 4. Knowledge Mastery ────────────────────────────────────────────


async def get_knowledge_mastery(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 50,
    sort: str = "weak_first",
) -> dict:
    q = select(
        UserKnowledgeState.knowledge_point_id,
        KnowledgePoint.name.label("kp_name"),
        UserKnowledgeState.mastery_score,
        UserKnowledgeState.confidence,
        UserKnowledgeState.attempt_count,
        UserKnowledgeState.correct_count,
        UserKnowledgeState.wrong_count,
        UserKnowledgeState.recent_wrong_count,
        UserKnowledgeState.last_practiced_at,
    ).join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)

    q = q.where(UserKnowledgeState.user_id == user_id)
    if subject_id is not None:
        if not await _subject_exists(db, subject_id):
            return {
                "summary": {
                    "weak_count": 0,
                    "normal_count": 0,
                    "good_count": 0,
                    "mastered_count": 0,
                    "unknown_count": 0,
                },
                "items": [],
            }
        q = q.where(UserKnowledgeState.subject_id == subject_id)

    # 排序
    if sort == "mastered_first":
        q = q.order_by(UserKnowledgeState.mastery_score.desc())
    elif sort == "confidence_low":
        q = q.order_by(UserKnowledgeState.confidence.asc())
    elif sort == "recent_practiced":
        q = q.order_by(UserKnowledgeState.last_practiced_at.desc().nullslast())
    else:  # weak_first
        q = q.order_by(UserKnowledgeState.mastery_score.asc())

    q = q.limit(limit)
    rows = (await db.execute(q)).all()

    return build_knowledge_mastery_response(rows)


# ── 5. Wrong Questions ──────────────────────────────────────────────


async def get_wrong_questions_summary(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 20,
    min_wrong_count: int = 1,
) -> dict:
    # 总数
    count_q = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        count_q = count_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    wrong_total = (await db.execute(count_q)).scalar_one()

    repeated_q = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= 3,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        repeated_q = repeated_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    repeated_count = (await db.execute(repeated_q)).scalar_one()

    # 明细（先查 UserQuestionState + Question，再批量加载知识点，避免 outerjoin 行膨胀）
    detail_q = select(
        UserQuestionState.question_id,
        UserQuestionState.wrong_count,
        UserQuestionState.correct_count,
        UserQuestionState.answer_count,
        UserQuestionState.last_answered_at,
        UserQuestionState.next_review_at,
        UserQuestionState.box_level,
        Question.content.label("q_content"),
    ).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        detail_q = detail_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    else:
        detail_q = detail_q.join(Question, UserQuestionState.question_id == Question.id)

    detail_q = detail_q.order_by(
        UserQuestionState.wrong_count.desc(),
        UserQuestionState.box_level.asc(),
        UserQuestionState.last_answered_at.desc().nullslast(),
    ).limit(limit)

    rows = (await db.execute(detail_q)).all()
    q_ids = [r.question_id for r in rows]

    # 批量加载知识点（每题只取第一个 KP）
    kp_map: dict[int, tuple[int, str]] = {}
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

    items = []
    for r in rows:
        kp = kp_map.get(r.question_id)
        items.append(build_wrong_question_item(row=r, knowledge_point=kp))

    return {
        "wrong_question_count": int(wrong_total),
        "repeated_wrong_question_count": int(repeated_count),
        "items": items,
    }


# ── 6. Study Trend ──────────────────────────────────────────────────


async def get_study_trend(
    db: AsyncSession, user_id: int, subject_id: int | None = None, days: int = 7
) -> dict:
    today = shanghai_today()
    since = _date_utc_range(today - timedelta(days=days - 1))[0]
    until = _date_utc_range(today + timedelta(days=1))[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)

    q = select(
        day_expr.label("d"),
        func.count(PracticeRecord.id).label("total"),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)),  # noqa: E712
            0,  # noqa: E712
        ).label("correct"),
    ).where(
        PracticeRecord.user_id == user_id,
        PracticeRecord.answered_at >= since,
        PracticeRecord.answered_at < until,
    )
    if subject_id is not None:
        q = q.where(PracticeRecord.subject_id == subject_id)

    q = q.group_by(day_expr).order_by(day_expr)
    rows = (await db.execute(q)).all()
    return normalize_study_trend_counts(rows, today=today, days=days)
