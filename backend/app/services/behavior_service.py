from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer_behavior import AnswerBehavior


async def record_answer_behavior(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    practice_record_id: int | None = None,
    time_spent_sec: int = 0,
    is_first_correct: bool | None = None,
    is_final_correct: bool | None = None,
    view_answer_count: int = 0,
    switch_count: int = 0,
    is_abandoned: bool = False,
    user_answer: str | None = None,
    correct_answer: str | None = None,
    subject: str | None = None,
    session_type: str = "random",
) -> AnswerBehavior:
    """记录一条答题行为数据"""
    # 检查是否已有相同记录
    if practice_record_id:
        result = await db.execute(
            select(AnswerBehavior).where(
                AnswerBehavior.user_id == user_id,
                AnswerBehavior.question_id == question_id,
                AnswerBehavior.practice_record_id == practice_record_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            # 更新已有记录
            existing.time_spent_sec = time_spent_sec
            existing.is_first_correct = is_first_correct if is_first_correct is not None else existing.is_first_correct
            existing.is_final_correct = is_final_correct
            existing.view_answer_count = view_answer_count
            existing.switch_count = switch_count
            existing.user_answer = user_answer or existing.user_answer
            existing.correct_answer = correct_answer or existing.correct_answer
            await db.commit()
            await db.refresh(existing)
            return existing

    behavior = AnswerBehavior(
        user_id=user_id,
        question_id=question_id,
        practice_record_id=practice_record_id,
        time_spent_sec=time_spent_sec,
        is_first_correct=is_first_correct,
        is_final_correct=is_final_correct,
        view_answer_count=view_answer_count,
        switch_count=switch_count,
        is_abandoned=is_abandoned,
        user_answer=user_answer,
        correct_answer=correct_answer,
        subject=subject,
        session_type=session_type,
    )
    db.add(behavior)
    await db.commit()
    await db.refresh(behavior)
    return behavior


async def get_behavior_stats(
    db: AsyncSession, user_id: int
) -> dict:
    """获取用户答题行为统计"""
    from sqlalchemy import func, select

    # 总答题数
    total_q = select(func.count(AnswerBehavior.id)).where(
        AnswerBehavior.user_id == user_id
    )
    total = (await db.execute(total_q)).scalar() or 0

    # 平均耗时
    avg_time_q = select(func.avg(AnswerBehavior.time_spent_sec)).where(
        AnswerBehavior.user_id == user_id,
        AnswerBehavior.time_spent_sec > 0,
    )
    avg_time = (await db.execute(avg_time_q)).scalar() or 0

    # 正确率
    correct_q = select(func.count(AnswerBehavior.id)).where(
        AnswerBehavior.user_id == user_id,
        AnswerBehavior.is_final_correct == True,
    )
    correct = (await db.execute(correct_q)).scalar() or 0

    # 按科目统计
    from sqlalchemy import select as sa_select
    subject_q = sa_select(
        AnswerBehavior.subject,
        func.count(AnswerBehavior.id).label("count"),
        func.avg(AnswerBehavior.time_spent_sec).label("avg_time"),
    ).where(
        AnswerBehavior.user_id == user_id,
        AnswerBehavior.subject.isnot(None),
    ).group_by(AnswerBehavior.subject)
    subject_result = await db.execute(subject_q)
    by_subject = [
        {
            "subject": r.subject,
            "count": r.count,
            "avg_time_sec": round(float(r.avg_time), 1) if r.avg_time else 0,
        }
        for r in subject_result.all()
    ]

    return {
        "total_answers": total,
        "correct_count": correct,
        "accuracy": round(correct / total, 4) if total > 0 else 0,
        "avg_time_sec": round(float(avg_time), 1),
        "by_subject": by_subject,
    }
