from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer_behavior import AnswerBehavior
from app.models.practice_record import PracticeRecord
from app.models.wrong_question import WrongQuestion


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    """学习总览统计"""
    today = date.today()
    today_start = datetime(today.year, today.month, today.day)

    # 总练习数据
    pr_result = await db.execute(
        select(
            func.coalesce(func.sum(PracticeRecord.correct_count), 0),
            func.coalesce(func.sum(PracticeRecord.wrong_count), 0),
            func.coalesce(func.sum(PracticeRecord.duration_sec), 0),
            func.count(PracticeRecord.id),
        ).where(PracticeRecord.user_id == user_id)
    )
    total_correct, total_wrong, total_duration, total_practices = pr_result.one()

    total_questions = total_correct + total_wrong

    # 今日数据
    today_result = await db.execute(
        select(
            func.coalesce(func.sum(PracticeRecord.correct_count), 0),
            func.coalesce(func.sum(PracticeRecord.wrong_count), 0),
            func.coalesce(func.sum(PracticeRecord.duration_sec), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.created_at >= today_start,
        )
    )
    today_correct, today_wrong, today_duration = today_result.one()

    # 连续学习天数
    consecutive_days = await _calc_consecutive_days(db, user_id)

    # 错题统计
    wq_result = await db.execute(
        select(
            func.count(WrongQuestion.id),
            func.coalesce(func.sum(case((WrongQuestion.mastered == True, 1), else_=0)), 0),
        ).where(WrongQuestion.user_id == user_id)
    )
    total_wq, mastered_count = wq_result.one()

    # 今日待复习
    due_count = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
            WrongQuestion.next_review_date <= today,
        )
    )

    return {
        "total_questions": total_questions,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "accuracy": round(total_correct / total_questions, 4) if total_questions > 0 else 0.0,
        "total_duration_sec": total_duration,
        "consecutive_days": consecutive_days,
        "today_questions": today_correct + today_wrong,
        "today_correct": today_correct,
        "today_duration_sec": today_duration,
        "mastered_count": mastered_count or 0,
        "due_review_count": due_count.scalar() or 0,
    }


async def _calc_consecutive_days(db: AsyncSession, user_id: int) -> int:
    """计算连续学习天数（从今天往前数，有练习记录的天数）"""
    today = date.today()
    days = 0
    for i in range(365):
        d = today - timedelta(days=i)
        day_start = datetime(d.year, d.month, d.day)
        day_end = day_start + timedelta(days=1)
        result = await db.execute(
            select(func.count(PracticeRecord.id)).where(
                PracticeRecord.user_id == user_id,
                PracticeRecord.created_at >= day_start,
                PracticeRecord.created_at < day_end,
            )
        )
        if result.scalar() > 0:
            days += 1
        else:
            break
    return days


async def get_subject_stats(db: AsyncSession, user_id: int) -> list[dict]:
    """学科维度统计"""
    result = await db.execute(
        select(
            PracticeRecord.subject,
            func.coalesce(func.sum(PracticeRecord.correct_count), 0),
            func.coalesce(func.sum(PracticeRecord.wrong_count), 0),
            func.coalesce(func.sum(PracticeRecord.duration_sec), 0),
            func.count(PracticeRecord.id),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject)
    )
    rows = []
    for r in result.all():
        total_q = r[1] + r[2]
        rows.append({
            "subject": r[0],
            "total_questions": total_q,
            "correct_count": r[1],
            "wrong_count": r[2],
            "accuracy": round(r[1] / total_q, 4) if total_q > 0 else 0.0,
            "total_duration_sec": r[3],
            "avg_duration_sec": round(r[3] / r[4], 1) if r[4] > 0 else 0.0,
        })
    return rows


async def get_trends(
    db: AsyncSession, user_id: int, days: int = 7
) -> list[dict]:
    """学习趋势（按天聚合）"""
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())

    result = await db.execute(
        select(
            func.date(PracticeRecord.created_at),
            func.coalesce(func.sum(PracticeRecord.correct_count), 0),
            func.coalesce(func.sum(PracticeRecord.wrong_count), 0),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.created_at >= since,
        )
        .group_by(func.date(PracticeRecord.created_at))
        .order_by(func.date(PracticeRecord.created_at))
    )
    data = {str(r[0]): {"correct": r[1], "wrong": r[2]} for r in result.all()}

    points = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        entry = data.get(d, {"correct": 0, "wrong": 0})
        total = entry["correct"] + entry["wrong"]
        points.append({
            "date": d,
            "questions": total,
            "correct": entry["correct"],
            "accuracy": round(entry["correct"] / total, 4) if total > 0 else 0.0,
        })
    return points


async def get_behavior_stats(db: AsyncSession, user_id: int) -> dict:
    """学习行为分析"""
    # 基础统计
    base = await db.execute(
        select(
            func.coalesce(func.avg(AnswerBehavior.time_spent_sec), 0),
            func.count(AnswerBehavior.id),
            func.coalesce(func.sum(AnswerBehavior.view_answer_count), 0),
            func.coalesce(func.sum(case((AnswerBehavior.is_abandoned == True, 1), else_=0)), 0),
        ).where(
            AnswerBehavior.user_id == user_id,
            AnswerBehavior.time_spent_sec > 0,
        )
    )
    avg_time, total_ans, view_cnt, abandon_cnt = base.one()

    # 错误类型分布
    err_result = await db.execute(
        select(
            WrongQuestion.error_type,
            func.count(WrongQuestion.id),
        )
        .where(WrongQuestion.user_id == user_id)
        .group_by(WrongQuestion.error_type)
        .order_by(func.count(WrongQuestion.id).desc())
    )
    error_dist = [{"type": r[0], "count": r[1]} for r in err_result.all()]

    # 学习时段分布
    hourly = []
    for h in range(24):
        hourly.append({"hour": h, "count": 0})

    ab_result = await db.execute(
        select(
            func.extract("hour", AnswerBehavior.created_at),
            func.count(AnswerBehavior.id),
        )
        .where(AnswerBehavior.user_id == user_id)
        .group_by(func.extract("hour", AnswerBehavior.created_at))
    )
    for r in ab_result.all():
        h = int(r[0])
        if 0 <= h < 24:
            hourly[h]["count"] = r[1]

    return {
        "avg_time_sec": round(float(avg_time), 1) if avg_time else 0.0,
        "total_answers": total_ans or 0,
        "view_answer_rate": round(view_cnt / total_ans, 4) if total_ans > 0 else 0.0,
        "abandon_rate": round(abandon_cnt / total_ans, 4) if total_ans > 0 else 0.0,
        "error_type_distribution": error_dist,
        "hourly_activity": [h for h in hourly if h["count"] > 0],
    }


async def get_forgetting_trends(db: AsyncSession, user_id: int) -> dict:
    """遗忘趋势分析（基于 SM-2 数据）"""
    today = date.today()

    # 高频遗忘：interval 小但 review_count 高的题 → 反复记不住
    stuck = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
            WrongQuestion.review_count >= 3,
        )
    )

    # 假掌握：matered=true 但 next_review_date 很近（上次复习质量高但间隔短）
    pseudo = await db.execute(
        select(WrongQuestion)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == True,
            WrongQuestion.review_count >= 1,
            WrongQuestion.next_review_date <= today + timedelta(days=3),
        )
        .order_by(WrongQuestion.next_review_date)
        .limit(10)
    )
    pseudo_items = []
    for wq in pseudo.scalars().all():
        pseudo_items.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "review_count": wq.review_count,
            "interval": wq.interval,
            "efactor": wq.efactor,
            "next_review_date": str(wq.next_review_date) if wq.next_review_date else "",
        })

    # 长期未掌握
    long_unmastered = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
            WrongQuestion.next_review_date <= today - timedelta(days=7),
        )
    )

    return {
        "high_forget_count": stuck.scalar() or 0,
        "stuck_questions": long_unmastered.scalar() or 0,
        "pseudo_mastered": pseudo_items,
        "top_forgotten_topics": [],
    }
