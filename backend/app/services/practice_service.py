from datetime import date, datetime, timedelta
import re

import logging
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.behavior_service import record_answer_behavior
from app.services.review_scheduler import auto_schedule_wrong_question
from app.services.wrong_question_service import record_wrong
from app.core.time_utils import utcnow

logger = logging.getLogger(__name__)

_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}


def _normalize_true_false_answer(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in _TRUE_FALSE_TRUE:
        return "A"
    if v in _TRUE_FALSE_FALSE:
        return "B"
    return v.upper()


def _normalize_blank_choice_answer(value: str) -> dict[str, str]:
    result = {}
    for part in re.split(r"[;；,，\n]+", str(value or "")):
        match = re.match(r"^(.+?)\s*[:：=]\s*([A-Za-z])\s*$", part.strip())
        if match:
            result[match.group(1).strip()] = match.group(2).upper()
    return result


def _is_multi_blank_answer_correct(user_answer: str, correct_answer: str) -> bool:
    correct_map = _normalize_blank_choice_answer(correct_answer)
    if not correct_map:
        return False
    return _normalize_blank_choice_answer(user_answer) == correct_map


async def get_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str,
    count: int = 20,
    mode: str = "random",
    knowledge_points: list[str] | None = None,
    exclude_answered: bool = False,
) -> list[Question]:
    # 精确匹配子科目，或前缀匹配父科目（exam408 → exam408、exam408-ds、exam408-os …）
    subject_cond = or_(
        Question.subject == subject,
        Question.subject.like(f"{subject}-%"),
    )
    conditions = [Question.is_active == True, subject_cond]

    if knowledge_points:
        for kp in knowledge_points:
            conditions.append(Question.knowledge_points.like(f'%"{kp}"%'))

    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    q = select(Question).where(and_(*conditions))

    if mode == "random":
        q = q.order_by(func.random())
    else:
        q = q.order_by(Question.id.asc())

    q = q.limit(count)
    result = await db.execute(q)
    questions = list(result.scalars().all())

    logger.info(
        "[Practice Query] subject=%s mode=%s count=%d resultCount=%d",
        subject, mode, count, len(questions),
    )
    return questions


async def submit_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    used_time: int | None = None,
) -> dict:
    result = await db.execute(
        select(Question).where(
            Question.id == question_id, Question.is_active == True
        )
    )
    question = result.scalar_one_or_none()
    if not question:
        raise ValueError(f"题目不存在: {question_id}")

    if question.question_type == "multi_blank_choice":
        is_correct = _is_multi_blank_answer_correct(user_answer, question.answer)
    elif question.question_type in ("true_false", "judgement"):
        is_correct = _normalize_true_false_answer(user_answer) == _normalize_true_false_answer(question.answer)
    else:
        is_correct = user_answer.strip().lower() == question.answer.strip().lower()

    record = PracticeRecord(
        user_id=user_id,
        question_id=question_id,
        subject=question.subject,
        question_type=question.question_type,
        user_answer=user_answer.strip(),
        is_correct=is_correct,
        used_time=used_time,
        answered_at=utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    is_wrong_added = False
    if not is_correct:
        await record_wrong(db, user_id, question_id, user_answer.strip())
        await auto_schedule_wrong_question(db, user_id, question_id)
        is_wrong_added = True

    await record_answer_behavior(
        db=db,
        user_id=user_id,
        question_id=question_id,
        practice_record_id=record.id,
        time_spent_sec=used_time or 0,
        is_first_correct=is_correct,
        is_final_correct=is_correct,
        user_answer=user_answer.strip(),
        correct_answer=question.answer,
        subject=question.subject,
        session_type="practice",
    )

    return {
        "record_id": record.id,
        "question_id": question_id,
        "is_correct": is_correct,
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "knowledge_points": question.knowledge_points or [],
        "is_wrong_added": is_wrong_added,
    }


async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
) -> dict:
    question_ids = [a["question_id"] for a in answers]
    result = await db.execute(
        select(Question).where(
            Question.id.in_(question_ids), Question.is_active == True
        )
    )
    questions = {q.id: q for q in result.scalars().all()}

    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise ValueError(f"题目不存在: {missing}")

    results = []
    total_correct = 0
    total_wrong = 0

    for a in answers:
        r = await submit_answer(
            db=db,
            user_id=user_id,
            question_id=a["question_id"],
            user_answer=a.get("user_answer", a.get("answer", "")),
            used_time=a.get("used_time"),
        )
        results.append(r)
        if r["is_correct"]:
            total_correct += 1
        else:
            total_wrong += 1

    return {
        "results": results,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
    }


async def get_practice_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    base = select(
        func.count(PracticeRecord.id),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
        ),
    ).where(PracticeRecord.user_id == user_id)

    total_row = (await db.execute(base)).one()
    total_answered = total_row[0]
    total_correct = total_row[1]
    accuracy = round(total_correct / total_answered, 4) if total_answered > 0 else 0.0

    # By subject
    subject_result = await db.execute(
        select(
            PracticeRecord.subject,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject)
    )
    by_subject = {}
    for row in subject_result.all():
        answered = row[1]
        correct = row[2]
        by_subject[row[0]] = {
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct / answered, 4) if answered > 0 else 0.0,
        }

    # Daily stats
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    daily_result = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(func.date(PracticeRecord.answered_at))
        .order_by(func.date(PracticeRecord.answered_at))
    )
    daily_map = {str(r[0]): {"answered": r[1], "correct": r[2]} for r in daily_result.all()}

    daily_stats = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        entry = daily_map.get(d, {"answered": 0, "correct": 0})
        daily_stats.append({"date": d, **entry})

    streak = await _calc_streak(db, user_id)

    return {
        "total_answered": total_answered,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "by_subject": by_subject,
        "daily_stats": daily_stats,
        "current_streak": streak,
    }


async def _calc_streak(db: AsyncSession, user_id: int) -> int:
    today = date.today()
    result = await db.execute(
        select(func.date(PracticeRecord.answered_at))
        .where(PracticeRecord.user_id == user_id)
        .distinct()
        .order_by(func.date(PracticeRecord.answered_at).desc())
    )
    dates = {row[0] for row in result.all()}

    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            streak += 1
        else:
            break
    return streak


async def get_wrong_questions(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.services.wrong_question_service import list_wrong

    items, total = await list_wrong(
        db, user_id, subject=subject, page=page, page_size=page_size
    )

    question_ids = [wq.question_id for wq in items]
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        q_map = {q.id: q for q in q_result.scalars().all()}
    else:
        q_map = {}

    wrong_list = []
    for wq in items:
        q = q_map.get(wq.question_id)
        wrong_list.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "wrong_answer": wq.wrong_answer,
            "review_count": wq.review_count,
            "mastered": wq.mastered,
            "last_review_at": str(wq.last_review_at) if wq.last_review_at else None,
            "question": {
                "id": q.id,
                "subject": q.subject,
                "question_type": q.question_type,
                "content": q.content,
                "options": q.options,
                "answer": q.answer,
                "analysis": q.analysis,
            } if q else None,
        })

    return {
        "items": wrong_list,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def review_wrong_question(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
) -> dict:
    # Judge and record
    submit_result = await submit_answer(
        db=db,
        user_id=user_id,
        question_id=question_id,
        user_answer=user_answer,
    )

    # Update wrong question mastery
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    wq = wq_result.scalar_one_or_none()

    if wq:
        from app.services.sm2_service import calc_sm2

        if submit_result["is_correct"]:
            quality = 5
        else:
            quality = 1

        sm2_result = calc_sm2(
            quality=quality,
            efactor=wq.efactor or 2.5,
            interval=wq.interval or 0,
            repetitions=wq.repetitions or 0,
            review_date=date.today(),
        )
        wq.quality = quality
        wq.efactor = sm2_result["efactor"]
        wq.interval = sm2_result["interval"]
        wq.repetitions = sm2_result["repetitions"]
        wq.next_review_date = sm2_result["next_review_date"]
        wq.last_review_at = utcnow()
        wq.review_count = (wq.review_count or 0) + 1

        if quality >= 4 and wq.repetitions >= 3:
            wq.mastered = True

        await db.commit()
        await db.refresh(wq)

        submit_result["sm2"] = sm2_result
        submit_result["mastered"] = wq.mastered

    return submit_result
