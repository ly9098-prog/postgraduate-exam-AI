from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
        conditions.append(Question.question_type == question_type)

    count_q = select(func.count(Question.id)).where(and_(*conditions))
    total = (await db.execute(count_q)).scalar()

    q = (
        select(Question)
        .where(and_(*conditions))
        .order_by(Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    return list(result.scalars().all()), total


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
        conditions.append(Question.question_type == question_type)
    if exclude_ids:
        conditions.append(Question.id.notin_(exclude_ids))

    q = select(Question).where(and_(*conditions)).order_by(func.random()).limit(1)
    result = await db.execute(q)
    return result.scalar_one_or_none()
