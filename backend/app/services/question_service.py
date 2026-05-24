"""题目 CRUD（保持精简，业务流转见 features.question_pipeline）。"""
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_pipeline import normalizer
from app.models.question import Question


async def create(
    db: AsyncSession,
    subject: str,
    question_type: str,
    content: dict,
    answer: str,
    options: dict | None = None,
    analysis: str | None = None,
    knowledge_points: list[str] | None = None,
    difficulty: int = 3,
    source: str | None = None,
    year: int | None = None,
) -> Question:
    q = Question(
        subject=subject,
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
    canonical = normalizer.normalize_type(question_type)
    legacy = {"single_choice": "choice", "fill_blank": "fill"}
    return [Question.question_type.in_([canonical, legacy.get(canonical, canonical)])]


async def list_questions(
    db: AsyncSession,
    subject: str | None = None,
    question_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Question], int]:
    conditions = [Question.is_active == True]
    if subject:
        conditions.append(Question.subject == subject)
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
        conditions.append(Question.subject == subject)
    if question_type:
        conditions.extend(_type_conditions(question_type))
    if exclude_ids:
        conditions.append(Question.id.notin_(exclude_ids))
    res = await db.execute(
        select(Question).where(and_(*conditions)).order_by(func.random()).limit(1)
    )
    return res.scalar_one_or_none()
