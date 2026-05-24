from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.services.behavior_service import record_answer_behavior
from app.services.wrong_question_service import record_wrong


async def submit(
    db: AsyncSession,
    user_id: int,
    subject: str,
    answers: list[dict],
    mode: str = "random",
    duration_sec: int = 0,
) -> tuple[PracticeRecord, list[dict]]:
    question_ids = [a["question_id"] for a in answers]

    result = await db.execute(
        select(Question).where(
            Question.id.in_(question_ids), Question.is_active == True
        )
    )
    questions = {q.id: q for q in result.scalars().all()}

    wrong_ids = [qid for qid in question_ids if qid not in questions]
    if wrong_ids:
        raise ValueError(f"题目不存在: {wrong_ids}")

    answers_dict = {}
    results = []
    correct_count = 0
    wrong_count = 0

    for a in answers:
        q = questions[a["question_id"]]
        answers_dict[str(a["question_id"])] = a["answer"]
        is_correct = a["answer"].strip() == q.answer.strip()
        results.append(
            {
                "question_id": q.id,
                "user_answer": a["answer"],
                "correct_answer": q.answer,
                "is_correct": is_correct,
                "analysis": q.analysis,
            }
        )
        if is_correct:
            correct_count += 1
        else:
            wrong_count += 1
            await record_wrong(db, user_id, q.id, a["answer"])

    record = PracticeRecord(
        user_id=user_id,
        subject=subject,
        mode=mode,
        question_ids=question_ids,
        answers=answers_dict,
        correct_count=correct_count,
        wrong_count=wrong_count,
        duration_sec=duration_sec,
        finished_at=datetime.utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 记录答题行为
    for a in answers:
        q = questions[a["question_id"]]
        ans_time = a.get("time_spent_sec", 0)
        await record_answer_behavior(
            db=db,
            user_id=user_id,
            question_id=a["question_id"],
            practice_record_id=record.id,
            time_spent_sec=ans_time,
            is_first_correct=a["answer"].strip() == q.answer.strip(),
            is_final_correct=a["answer"].strip() == q.answer.strip(),
            user_answer=a["answer"],
            correct_answer=q.answer,
            subject=subject,
            session_type=mode,
        )

    return record, results


async def list_records(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PracticeRecord], int]:
    conditions = [PracticeRecord.user_id == user_id]
    if subject:
        conditions.append(PracticeRecord.subject == subject)

    count_q = select(func.count(PracticeRecord.id)).where(and_(*conditions))
    total = (await db.execute(count_q)).scalar()

    q = (
        select(PracticeRecord)
        .where(and_(*conditions))
        .order_by(PracticeRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_by_id(
    db: AsyncSession, user_id: int, record_id: int
) -> PracticeRecord | None:
    result = await db.execute(
        select(PracticeRecord).where(
            PracticeRecord.id == record_id, PracticeRecord.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def get_batch_questions(
    db: AsyncSession,
    subject: str,
    count: int = 10,
    exclude_ids: list[int] | None = None,
) -> list[Question]:
    """批量预加载题目"""
    conditions = [Question.is_active == True, Question.subject == subject]
    if exclude_ids:
        conditions.append(Question.id.notin_(exclude_ids))

    q = (
        select(Question)
        .where(and_(*conditions))
        .order_by(func.random())
        .limit(count)
    )
    result = await db.execute(q)
    return list(result.scalars().all())
