"""Read-only aggregate queries backing learning statistics.

The module owns SQL shape and database session usage; ``stats_service`` keeps
the public compatibility entrypoints and response projection.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import selected_408_subject_ids
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.answer_behavior import AnswerBehavior
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.wrong_question import WrongQuestion
from app.services.learning_time_projection import (
    china_date_expr,
    china_hour_expr,
)


async def load_practice_totals(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        ).where(PracticeRecord.user_id == user_id)
    )
    return result.one()


async def load_today_practice_totals(
    db: AsyncSession, user_id: int, today_start: datetime
):
    result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= today_start,
        )
    )
    return result.one()


async def load_wrong_question_totals(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(
            func.count(WrongQuestion.id),
            func.coalesce(func.sum(case((WrongQuestion.mastered, 1), else_=0)), 0),
        ).where(WrongQuestion.user_id == user_id, WrongQuestion.is_active)
    )
    return result.one()


async def load_active_408_subject_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(select(Subject))
    return selected_408_subject_ids(result.scalars().all())


async def count_due_reviews(
    db: AsyncSession, user_id: int, active_408_ids: set[int], now: datetime
):
    result = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id)))
        .join(QuestionVersion, QuestionVersion.id == ReviewSchedule.question_version_id)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= now,
            QuestionVersion.question_id == ReviewSchedule.question_id,
            (QuestionVersion.subject_id.in_(active_408_ids))
            | (
                QuestionVersion.subject_id.is_(None)
                & ReviewSchedule.subject_id.in_(active_408_ids)
            ),
        )
    )
    return result.scalar() or 0


async def load_answer_days(db: AsyncSession, user_id: int, since: datetime):
    day_expr = await china_date_expr(db, PracticeRecord.answered_at)
    result = await db.execute(
        select(day_expr)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .distinct()
        .order_by(day_expr.desc())
    )
    return result.all()


async def load_subject_stat_rows(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(
            PracticeRecord.subject_id.label("subject_id"),
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    return result.all()


async def load_trend_rows(
    db: AsyncSession,
    user_id: int,
    since: datetime,
    until: datetime,
):
    day_expr = await china_date_expr(db, PracticeRecord.answered_at)
    result = await db.execute(
        select(
            day_expr,
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
            func.coalesce(func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
            PracticeRecord.answered_at < until,
        )
        .group_by(day_expr)
        .order_by(day_expr)
    )
    return result.all()


async def load_behavior_totals(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(
            func.coalesce(func.avg(AnswerBehavior.time_spent_sec), 0),
            func.count(AnswerBehavior.id),
            func.coalesce(func.sum(AnswerBehavior.view_answer_count), 0),
            func.coalesce(func.sum(case((AnswerBehavior.is_abandoned, 1), else_=0)), 0),
        ).where(
            AnswerBehavior.user_id == user_id,
            AnswerBehavior.time_spent_sec > 0,
        )
    )
    return result.one()


async def load_error_type_distribution(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(
            WrongQuestion.error_type,
            func.count(WrongQuestion.id),
        )
        .where(WrongQuestion.user_id == user_id)
        .group_by(WrongQuestion.error_type)
        .order_by(func.count(WrongQuestion.id).desc())
    )
    return result.all()


async def load_hourly_activity(db: AsyncSession, user_id: int):
    hour_expr = await china_hour_expr(db, AnswerBehavior.created_at)
    result = await db.execute(
        select(
            hour_expr,
            func.count(AnswerBehavior.id),
        )
        .where(AnswerBehavior.user_id == user_id)
        .group_by(hour_expr)
    )
    return result.all()


async def count_stuck_questions(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
            WrongQuestion.review_count >= 3,
        )
    )
    return result.scalar() or 0


async def load_pseudo_mastered_rows(
    db: AsyncSession, user_id: int, due_before: datetime
):
    result = await db.execute(
        select(
            WrongQuestion.id,
            WrongQuestion.question_id,
            WrongQuestion.review_count,
            ReviewSchedule.interval,
            ReviewSchedule.ease_factor,
            ReviewSchedule.next_review_at,
        )
        .join(
            ReviewSchedule,
            (ReviewSchedule.user_id == WrongQuestion.user_id)
            & (ReviewSchedule.question_id == WrongQuestion.question_id)
            & (ReviewSchedule.question_version_id == WrongQuestion.question_version_id),
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
            WrongQuestion.mastered,
            ReviewSchedule.is_active,
            WrongQuestion.review_count >= 1,
            ReviewSchedule.next_review_at <= due_before,
        )
        .order_by(ReviewSchedule.next_review_at)
        .limit(10)
    )
    return result.all()


async def count_long_unmastered(db: AsyncSession, user_id: int, due_before: datetime):
    result = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= due_before,
        )
    )
    return result.scalar() or 0


async def load_top_forgotten_topic_rows(db: AsyncSession, user_id: int):
    frozen_name = func.coalesce(
        SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name
    )
    result = await db.execute(
        select(frozen_name, func.count(func.distinct(WrongQuestion.id)))
        .select_from(QuestionVersionKnowledgePoint)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
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
        .group_by(KnowledgePoint.id, frozen_name)
        .order_by(
            func.count(func.distinct(WrongQuestion.id)).desc(), KnowledgePoint.id.asc()
        )
        .limit(8)
    )
    return result.all()


async def load_ai_diagnosis_subject_rows(
    db: AsyncSession, user_id: int, since: datetime
):
    result = await db.execute(
        select(
            Subject.code,
            func.count(WrongQuestion.id),
            func.coalesce(func.sum(case((WrongQuestion.mastered, 1), else_=0)), 0),
        )
        .join(Question, WrongQuestion.question_id == Question.id)
        .join(Subject, Question.subject_id == Subject.id)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.created_at >= since,
        )
        .group_by(Subject.id, Subject.code)
    )
    return result.all()
