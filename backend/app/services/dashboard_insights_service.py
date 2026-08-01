"""
Dashboard insights service — practice diagnosis computed entirely from existing tables.
Each metric function is independent and returns None when data is insufficient.
"""

import asyncio
import math
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.review_scheduler import ReviewSchedule
from app.models.subject_resolver import get_subject_label
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.wrong_question import WrongQuestion

# ──────────────────────────────────────────────
# 1. Today Quality Score
# ──────────────────────────────────────────────


async def compute_today_quality(db: AsyncSession, user_id: int) -> dict | None:
    """今日学习质量评分 (0-100)，不足 5 题返回 None。"""
    today_start = datetime.combine(utcnow().date(), datetime.min.time())

    row = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(func.avg(PracticeRecord.used_time), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= today_start,
        )
    )
    count, correct, avg_time = row.one()
    count = count or 0
    if count < 5:
        return None

    accuracy = correct / count if count > 0 else 0.0

    # Score components (0-100 each)
    acc_score = accuracy * 100  # 正确率分
    vol_score = min(100, (count / 20) * 100)  # 完成量分 (20题=满分)
    time_score = 100 if avg_time and 20 <= avg_time <= 120 else max(
        0, 100 - abs((avg_time or 60) - 60) * 0.5
    )  # 用时稳定性

    total = acc_score * 0.4 + vol_score * 0.3 + time_score * 0.3

    if total >= 85:
        label = "优秀"
    elif total >= 70:
        label = "良好"
    elif total >= 50:
        label = "一般"
    else:
        label = "需要加油"

    return {
        "data_available": True,
        "score": round(total),
        "label": label,
        "questions": count,
        "accuracy": round(accuracy, 4),
        "avg_time_sec": round(avg_time, 1) if avg_time else 0.0,
    }


# ──────────────────────────────────────────────
# 2. Weekly Consistency
# ──────────────────────────────────────────────


async def compute_weekly_consistency(
    db: AsyncSession, user_id: int, days: int = 7
) -> dict | None:
    """学习稳定性评分：活跃天数、每日题量方差、正确率方差。"""
    since = datetime.combine(
        utcnow().date() - timedelta(days=days - 1), datetime.min.time()
    )

    rows = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(func.date(PracticeRecord.answered_at))
    )
    daily_data = {}
    for date_str, q_count, c_count in rows.all():
        daily_data[str(date_str)] = {
            "questions": q_count or 0,
            "correct": c_count or 0,
        }

    total_q = sum(d["questions"] for d in daily_data.values())
    if total_q < 5 or not daily_data:
        return None

    active_days = len(daily_data)
    active_ratio = active_days / max(days, 1)

    # Daily question counts (with zero-fill for inactive days)
    q_values = []
    acc_values = []
    breakdown = []
    for i in range(days):
        d = (utcnow().date() - timedelta(days=days - 1 - i)).isoformat()
        dd = daily_data.get(d, {"questions": 0, "correct": 0})
        q_count = dd["questions"]
        acc = dd["correct"] / q_count if q_count > 0 else 0
        q_values.append(q_count)
        if q_count > 0:
            acc_values.append(acc)
        breakdown.append({"date": d, "questions": q_count, "accuracy": round(acc, 4)})

    # Coefficient of variation for daily question counts
    mean_q = sum(q_values) / max(days, 1)
    var_q = (
        sum((x - mean_q) ** 2 for x in q_values) / max(days, 1) if days > 0 else 0
    )
    cv_q = math.sqrt(var_q) / max(mean_q, 1)

    # Accuracy std dev
    mean_acc = sum(acc_values) / max(len(acc_values), 1) if acc_values else 0
    acc_var = (
        sum((x - mean_acc) ** 2 for x in acc_values) / max(len(acc_values), 1)
        if acc_values
        else 0
    )
    acc_std = math.sqrt(acc_var)

    # Composite score (0-100)
    active_score = active_ratio * 100
    cv_score = max(0, 100 - min(cv_q * 60, 60))
    acc_stability = max(0, 100 - min(acc_std * 120, 60))
    total = active_score * 0.4 + cv_score * 0.35 + acc_stability * 0.25

    if total >= 80:
        label = "非常稳定"
    elif total >= 60:
        label = "较为稳定"
    else:
        label = "波动较大"

    return {
        "data_available": True,
        "score": round(total),
        "label": label,
        "active_days": active_days,
        "days": days,
        "total_questions": total_q,
        "day_breakdown": breakdown,
    }


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
            UserKnowledgeState.subject,
            UserKnowledgeState.mastery_score,
            UserKnowledgeState.attempt_count,
            UserKnowledgeState.wrong_count,
            UserKnowledgeState.recent_wrong_count,
            UserKnowledgeState.last_practiced_at,
        )
        .join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)
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

        items = []
        for row in items_data:
            kp_id = row[0]
            items.append({
                "knowledge_point_id": kp_id,
                "name": row[1],
                "subject": row[2],
                "subject_label": get_subject_label(row[2]),
                "mastery_score": round(row[3], 1),
                "attempt_count": row[4] or 0,
                "wrong_count": row[5] or 0,
                "recent_wrong_count": row[6] or 0,
                "due_review_count": due_counts.get(kp_id, 0),
                "last_practiced_at": (
                    row[7].isoformat() if row[7] else None
                ),
            })
        return {"data_available": True, "items": items}

    # Fallback: derive from WrongQuestion -> Question.knowledge_points (JSON)
    rows = await db.execute(
        select(
            Question.id,
            Question.knowledge_points,
            Question.subject_id,
        )
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
        .where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
        )
    )
    kp_counter: dict[str, int] = {}
    for q_id, kps, subj_id in rows.all():
        if kps and isinstance(kps, list):
            for kp in kps:
                if isinstance(kp, str):
                    kp_counter[kp] = kp_counter.get(kp, 0) + 1

    if not kp_counter:
        return None

    sorted_kps = sorted(kp_counter.items(), key=lambda x: x[1], reverse=True)[:limit]
    items = [
        {
            "knowledge_point_id": 0,
            "name": name,
            "subject": "",
            "subject_label": "",
            "mastery_score": max(0, 100 - count * 15),
            "attempt_count": count,
            "wrong_count": count,
            "recent_wrong_count": count,
            "due_review_count": 0,
            "last_practiced_at": None,
        }
        for name, count in sorted_kps
    ]
    return {"data_available": True, "items": items}


async def _compute_kp_due_review_counts(db: AsyncSession, user_id: int) -> dict[int, int]:
    """Count due reviews per knowledge_point_id."""
    now = utcnow()
    rows = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            func.count(ReviewSchedule.id),
        )
        .join(ReviewSchedule, ReviewSchedule.question_id == QuestionKnowledgePoint.question_id)
        .where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= now,
            QuestionKnowledgePoint.role == "main",
        )
        .group_by(QuestionKnowledgePoint.knowledge_point_id)
    )
    return {row[0]: row[1] for row in rows.all()}


# ──────────────────────────────────────────────
# 4. Repeat Wrong Analysis
# ──────────────────────────────────────────────


async def compute_repeat_wrong_analysis(
    db: AsyncSession, user_id: int
) -> dict | None:
    """错题复发分析：review_count>0 但仍未 mastered 的错题。"""
    total = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id
        )
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

    # Top repeat topics
    rows = await db.execute(
        select(Question.knowledge_points)
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
        .where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
            WrongQuestion.review_count >= 1,
        )
    )
    kp_counter: dict[str, int] = {}
    for (kps,) in rows.all():
        if kps and isinstance(kps, list):
            for kp in kps:
                if isinstance(kp, str):
                    kp_counter[kp] = kp_counter.get(kp, 0) + 1
    top_topics = [
        {"name": k, "count": v}
        for k, v in sorted(kp_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    is_high = rate > 0.3
    if is_high:
        status_label = "偏高"
    elif rate > 0.15:
        status_label = "中等"
    else:
        status_label = "较低"

    return {
        "data_available": True,
        "repeat_wrong_count": repeat_count,
        "total_wrong_count": total_wq,
        "repeat_rate": round(rate, 4),
        "is_high": is_high,
        "status_label": status_label,
        "top_repeat_topics": top_topics,
    }


# ──────────────────────────────────────────────
# 5. Speed-Accuracy Analysis
# ──────────────────────────────────────────────


async def compute_speed_accuracy(db: AsyncSession, user_id: int) -> dict | None:
    """速度与准确率分析：正确/错误题平均用时对比。"""
    row = await db.execute(
        select(
            func.coalesce(
                func.avg(case((PracticeRecord.is_correct == True, PracticeRecord.used_time))), 0  # noqa: E712
            ),
            func.coalesce(
                func.avg(case((PracticeRecord.is_correct == False, PracticeRecord.used_time))), 0  # noqa: E712
            ),
            func.coalesce(
                func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0
            ),
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
            func.coalesce(func.sum(case((PracticeRecord.used_time < 15, 1), else_=0)), 0),
            func.coalesce(func.sum(case((PracticeRecord.used_time > 120, 1), else_=0)), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            ~PracticeRecord.is_correct,
            PracticeRecord.used_time.isnot(None),
        )
    )
    fast_wrong, slow_wrong = fw_sw.one()
    fast_wrong = int(fast_wrong or 0)
    slow_wrong = int(slow_wrong or 0)

    # Determine status
    if avg_wrong > avg_correct * 1.3 and avg_wrong > 20:
        overall_status = "knowledge_gap"
        overall_label = "知识点不熟"
    elif fast_wrong > wrong_count * 0.3 and wrong_count > 5:
        overall_status = "hasty"
        overall_label = "审题不稳"
    elif slow_wrong > wrong_count * 0.3 and wrong_count > 5:
        overall_status = "unfamiliar"
        overall_label = "解法不熟"
    else:
        overall_status = "normal"
        overall_label = "速度正常"

    # Per-subject breakdown
    subj_rows = await db.execute(
        select(
            PracticeRecord.subject,
            func.coalesce(
                func.avg(case((PracticeRecord.is_correct == True, PracticeRecord.used_time))), 0  # noqa: E712
            ),
            func.coalesce(
                func.avg(case((PracticeRecord.is_correct == False, PracticeRecord.used_time))), 0  # noqa: E712
            ),
            func.count(PracticeRecord.id),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.used_time.isnot(None),
            PracticeRecord.used_time > 0,
        ).group_by(PracticeRecord.subject)
    )
    by_subject = []
    for subj, ac, aw, cnt in subj_rows.all():
        ac = float(ac or 0)
        aw = float(aw or 0)
        cnt = cnt or 0
        if cnt < 3:
            continue
        if aw > ac * 1.3 and aw > 15:
            sl = "知识点不熟"
        else:
            sl = "速度正常"
        by_subject.append({
            "subject": subj,
            "subject_label": get_subject_label(subj),
            "avg_time_correct_sec": round(ac, 1),
            "avg_time_wrong_sec": round(aw, 1),
            "questions": cnt,
            "status_label": sl,
        })

    return {
        "data_available": True,
        "overall_status": overall_status,
        "overall_label": overall_label,
        "avg_time_correct_sec": round(avg_correct, 1),
        "avg_time_wrong_sec": round(avg_wrong, 1),
        "fast_wrong_count": fast_wrong,
        "slow_wrong_count": slow_wrong,
        "by_subject": by_subject,
    }


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
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .join(
            first_subq,
            PracticeRecord.question_id == first_subq.c.question_id,
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by("ptype")
    )
    new_count = 0
    new_correct = 0
    review_count = 0
    review_correct = 0
    for ptype, cnt, corr in rows.all():
        if ptype == "new":
            new_count = cnt or 0
            new_correct = corr or 0
        else:
            review_count = cnt or 0
            review_correct = corr or 0

    total = new_count + review_count
    if total < 5:
        return None

    new_acc = new_correct / max(new_count, 1)
    review_acc = review_correct / max(review_count, 1)

    if review_count >= 5 and new_count >= 5:
        if review_acc > new_acc + 0.1:
            label = "复习效果较好"
        elif new_acc > review_acc + 0.1:
            label = "新题表现更佳"
        else:
            label = "表现均衡"
    elif review_count < 5 and new_count >= 5:
        label = "侧重刷题"
    elif review_count >= 5 and new_count < 5:
        label = "侧重复习"
    else:
        label = "数据不足"

    summary = ""
    if review_count >= 3 and new_count >= 3:
        diff = review_acc - new_acc
        if diff > 0.15:
            summary = f"复习题正确率高出{round(diff * 100)}%，复习效果明显"
        elif diff < -0.15:
            summary = "新题正确率更高，可以适当增加新题练习"
        else:
            summary = "新题和复习题表现接近，节奏均衡"
    elif new_count >= 5:
        summary = "新题练习较多，建议增加复习巩固"

    return {
        "data_available": True,
        "new_count": new_count,
        "new_accuracy": round(new_acc, 4),
        "review_count": review_count,
        "review_accuracy": round(review_acc, 4),
        "label": label,
        "summary": summary,
    }


# ──────────────────────────────────────────────
# 7. Input-Output Analysis
# ──────────────────────────────────────────────


async def compute_input_output(
    db: AsyncSession, user_id: int, trend_days: int = 90
) -> dict | None:
    """投入产出分析：按学科对比用时与正确率。

    效率分 = 正确率 / (该科每题均时 / 全局每题均时)
    """
    since = datetime.combine(
        utcnow().date() - timedelta(days=trend_days - 1), datetime.min.time()
    )

    rows = await db.execute(
        select(
            PracticeRecord.subject,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
            PracticeRecord.used_time.isnot(None),
            PracticeRecord.used_time > 0,
        )
        .group_by(PracticeRecord.subject)
    )
    subject_data = {}
    total_q = 0
    total_time = 0
    for subj, cnt, corr, tm in rows.all():
        cnt = cnt or 0
        if cnt < 3:
            continue
        subject_data[subj] = {
            "questions": cnt,
            "correct": corr or 0,
            "time": tm or 0,
        }
        total_q += cnt
        total_time += tm or 0

    if not subject_data or total_q < 5:
        return None

    global_avg = total_time / max(total_q, 1)

    items = []
    for subj, sd in subject_data.items():
        accuracy = sd["correct"] / max(sd["questions"], 1)
        time_per_q = sd["time"] / max(sd["questions"], 1)
        efficiency = accuracy / max(time_per_q / max(global_avg, 1), 0.1)

        if efficiency >= 1.2:
            eff_label = "高"
            suggestion = "继续保持当前学习方法"
        elif efficiency >= 0.8:
            eff_label = "中"
            suggestion = "提升空间较大，建议侧重薄弱知识点"
        else:
            eff_label = "低"
            suggestion = "投入时间多但收益偏低，建议先复盘错题"

        # Accuracy overrides — only when they don't mask efficiency concerns
        if accuracy < 0.6 and sd["questions"] >= 10:
            suggestion = "正确率偏低，建议减少盲目刷题，优先复盘错题"
        elif accuracy >= 0.85 and efficiency >= 1.0:
            suggestion = "掌握良好，可以保持节奏"
        elif accuracy >= 0.85 and efficiency < 0.8:
            suggestion = "耗时较长但正确率尚可，建议优化做题速度"

        items.append({
            "subject": subj,
            "subject_label": get_subject_label(subj),
            "total_questions": sd["questions"],
            "total_duration_sec": sd["time"],
            "accuracy": round(accuracy, 4),
            "time_per_question_sec": round(time_per_q, 1),
            "efficiency_score": round(efficiency, 2),
            "efficiency_label": eff_label,
            "suggestion": suggestion,
        })

    items.sort(key=lambda x: x["efficiency_score"])
    return {
        "data_available": True,
        "items": items,
        "global_avg_time_sec": round(global_avg, 1),
    }


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
    items = []
    priority = 0

    # 1. Overdue reviews
    if overview:
        due = overview.get("due_review_count", 0)
        if due > 0:
            priority += 1
            items.append({
                "type": "review",
                "priority": priority,
                "title": f"完成 {due} 道到期复习",
                "desc": f"有 {due} 道复习题已到期，建议优先完成",
                "action_data": {},
            })

    # 2. Repeat wrong rate high
    if repeat_wrong and repeat_wrong.get("is_high"):
        priority += 1
        count = repeat_wrong.get("repeat_wrong_count", 0)
        items.append({
            "type": "wrong",
            "priority": priority,
            "title": f"复盘 {count} 道复发错题",
            "desc": f"错题复发率 {round(repeat_wrong['repeat_rate'] * 100)}%，建议集中复盘",
            "action_data": {},
        })

    # 3. Weak topics exist
    if weak_topics and weak_topics.get("items"):
        top = weak_topics["items"][0]
        priority += 1
        items.append({
            "type": "wrong",
            "priority": priority,
            "title": f"巩固「{top['name']}」知识点",
            "desc": f"该知识点掌握度 {top['mastery_score']} 分，错误 {top['wrong_count']} 次",
            "action_data": {"topic": top["name"]},
        })

    # 4. New vs review imbalance
    if new_vs_review:
        nr_label = new_vs_review.get("label", "")
        if "复习效果较好" in nr_label:
            priority += 1
            items.append({
                "type": "practice",
                "priority": priority,
                "title": "适当增加新题练习",
                "desc": "复习效果较好，可以适当推进新题",
                "action_data": {},
            })
        elif "新题表现更佳" in nr_label:
            priority += 1
            items.append({
                "type": "review",
                "priority": priority,
                "title": "增加复习巩固",
                "desc": "新题表现好但复习不足，建议平衡练习结构",
                "action_data": {},
            })

    # 5. Default: keep practicing
    if not items:
        items.append({
            "type": "practice",
            "priority": 1,
            "title": "保持练习节奏",
            "desc": "当前状态良好，继续每日练习",
            "action_data": {},
        })

    return {"data_available": True, "items": items}


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
        db, user_id,
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
