"""题目 CRUD（保持精简，业务流转见 features.question_pipeline）。"""
import random

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.services.admin_subject_service import resolve_subject_ids


async def create(
    db: AsyncSession,
    question_type: str,
    content: dict,
    answer: str,
    subject: str | None = None,
    options: dict | None = None,
    analysis: str | None = None,
    knowledge_points: list[str] | None = None,
    difficulty: int = 3,
    source: str | None = None,
    year: int | None = None,
    subject_id: int | None = None,
) -> Question:
    # Resolve subject_id: prefer explicit subject_id, fall back to legacy subject string
    if subject_id is None and subject:
        from app.services.admin_subject_service import resolve_subject_id as _resolve_sid
        subject_id = await _resolve_sid(db, subject)
    q = Question(
        subject_id=subject_id,
        question_type=question_type,
        content=content,
        options=options,
        answer=answer,
        analysis=analysis,
        knowledge_points=knowledge_points,
        difficulty=difficulty,
        source=source,
        year=year,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def get_by_id(db: AsyncSession, question_id: int) -> Question | None:
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active == True)
    )
    return result.scalar_one_or_none()


def _type_conditions(question_type: str) -> list:
    """构建题型过滤条件。"""
    from app.features.question_type import normalize_question_type

    canonical, _warnings = normalize_question_type(question_type)
    if canonical is None:
        return [Question.question_type == question_type]
    return [Question.question_type == canonical]


async def list_questions(
    db: AsyncSession,
    subject: str | None = None,
    question_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Question], int]:
    conditions = [Question.is_active == True]
    if subject:
        conditions.append(Question.subject_id.in_(await resolve_subject_ids(db, subject)))
    if question_type:
        conditions.extend(_type_conditions(question_type))

    total = (await db.execute(
        select(func.count(Question.id)).where(and_(*conditions))
    )).scalar()

    res = await db.execute(
        select(Question)
        .where(and_(*conditions))
        .order_by(Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), total


async def get_random(
    db: AsyncSession,
    subject: str | None = None,
    question_type: str | None = None,
    exclude_ids: list[int] | None = None,
) -> Question | None:
    conditions = [Question.is_active == True]
    if subject:
        conditions.append(Question.subject_id.in_(await resolve_subject_ids(db, subject)))
    if question_type:
        conditions.extend(_type_conditions(question_type))
    if exclude_ids:
        conditions.append(Question.id.notin_(exclude_ids))
    base = select(Question).where(and_(*conditions))
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    if total == 0:
        return None
    offset = random.randint(0, total - 1)
    res = await db.execute(base.order_by(Question.id.asc()).offset(offset).limit(1))
    return res.scalar_one_or_none()
