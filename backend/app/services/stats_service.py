import json
from datetime import date, datetime, timedelta

from sqlalchemy import Date as SQLDate, Integer, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import (
    serialize_utc_datetime,
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.models.answer_behavior import AnswerBehavior
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.knowledge_point_service import load_question_kps


def _today_utc() -> datetime:
    """Return China today's 00:00 boundary as naive UTC for DB queries."""
    return shanghai_today_boundaries()[0]


async def _china_date_expr(db: AsyncSession, column):
    """SQL expression that buckets a naive-UTC DB timestamp by China date."""
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)


async def _china_hour_expr(db: AsyncSession, column):
    """SQL expression for the China wall-clock hour of a UTC DB timestamp."""
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return cast(func.strftime("%H", column, "+8 hours"), Integer)
    return func.extract("hour", column + text("INTERVAL '8 hours'"))


def _coerce_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    """学习总览统计"""
    today_start = _today_utc()

    pr_result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        ).where(PracticeRecord.user_id == user_id)
    )
    total_practices, total_correct, total_wrong, total_duration = pr_result.one()
    total_questions = total_correct + total_wrong

    today_result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        ).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= today_start,
        )
    )
    today_count, today_correct, today_duration = today_result.one()

    consecutive_days = await _calc_consecutive_days(db, user_id)

    wq_result = await db.execute(
        select(
            func.count(WrongQuestion.id),
            func.coalesce(
                func.sum(case((WrongQuestion.mastered, 1), else_=0)), 0
            ),
        ).where(WrongQuestion.user_id == user_id)
    )
    total_wq, mastered_count = wq_result.one()

    due_count = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= utcnow(),
        )
    )

    return {
        "total_questions": total_questions,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "accuracy": round(total_correct / total_questions, 4) if total_questions > 0 else 0.0,
        "total_duration_sec": total_duration or 0,
        "consecutive_days": consecutive_days,
        "today_questions": today_count,
        "today_correct": today_correct,
        "today_duration_sec": today_duration or 0,
        "mastered_count": mastered_count or 0,
        "due_review_count": due_count.scalar() or 0,
        "wrong_question_count": total_wq or 0,
    }


async def _calc_consecutive_days(db: AsyncSession, user_id: int) -> int:
    today = shanghai_today()
    first_day = today - timedelta(days=364)
    since = shanghai_date_utc_range(first_day)[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)

    result = await db.execute(
        select(day_expr)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .distinct()
        .order_by(day_expr.desc())
    )
    dates = {d for row in result.all() if (d := _coerce_date(row[0])) is not None}

    days = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            days += 1
        else:
            break
    return days


async def get_subject_stats(db: AsyncSession, user_id: int) -> list[dict]:
    """学科维度统计 — 按 PracticeRecord.subject_id 分组。"""
    from app.models.admin import Subject

    result = await db.execute(
        select(
            PracticeRecord.subject_id.label("subject_id"),
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    rows = []
    for r in result.all():
        total_q = r[3]
        correct = r[4]
        rows.append(
            {
                "subject_id": r[0],
                "subject_code": r[1] or "",
                "subject_name": r[2] or "",
                "total_questions": total_q,
                "correct_count": correct,
                "wrong_count": r[5],
                "accuracy": round(correct / total_q, 4) if total_q > 0 else 0.0,
                "total_duration_sec": r[6] or 0,
                "avg_duration_sec": round((r[6] or 0) / total_q, 1) if total_q > 0 else 0.0,
            }
        )
    return rows


async def get_trends(
    db: AsyncSession, user_id: int, days: int = 7,
    start_date: date | None = None,
) -> list[dict]:
    """学习趋势（按天聚合）

    start_date: 起始日期（含），默认自动向前推 days 天。
    """
    today = shanghai_today()
    if start_date is None:
        start_date = today - timedelta(days=days - 1)

    since = shanghai_date_utc_range(start_date)[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)

    result = await db.execute(
        select(
            day_expr,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((~PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(day_expr)
        .order_by(day_expr)
    )
    data = {
        str(r[0]): {"count": r[1], "correct": r[2], "wrong": r[3]}
        for r in result.all()
    }

    points = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        entry = data.get(d, {"count": 0, "correct": 0, "wrong": 0})
        total = entry["count"]
        points.append(
            {
                "date": d,
                "questions": total,
                "correct": entry["correct"],
                "accuracy": round(entry["correct"] / total, 4) if total > 0 else 0.0,
            }
        )
    return points


async def get_behavior_stats(db: AsyncSession, user_id: int) -> dict:
    """学习行为分析"""
    base = await db.execute(
        select(
            func.coalesce(func.avg(AnswerBehavior.time_spent_sec), 0),
            func.count(AnswerBehavior.id),
            func.coalesce(func.sum(AnswerBehavior.view_answer_count), 0),
            func.coalesce(
                func.sum(case((AnswerBehavior.is_abandoned, 1), else_=0)), 0
            ),
        ).where(
            AnswerBehavior.user_id == user_id,
            AnswerBehavior.time_spent_sec > 0,
        )
    )
    avg_time, total_ans, view_cnt, abandon_cnt = base.one()

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

    hourly = []
    for h in range(24):
        hourly.append({"hour": h, "count": 0})

    hour_expr = await _china_hour_expr(db, AnswerBehavior.created_at)
    ab_result = await db.execute(
        select(
            hour_expr,
            func.count(AnswerBehavior.id),
        )
        .where(AnswerBehavior.user_id == user_id)
        .group_by(hour_expr)
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
    """遗忘趋势分析（基于 SM-2 数据，SM-2 状态源为 ReviewSchedule）"""
    today = shanghai_today()

    stuck = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
            WrongQuestion.review_count >= 3,
        )
    )

    # Pseudo-mastered: mastered with upcoming review in next 3 days
    pseudo = await db.execute(
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
            & (ReviewSchedule.question_id == WrongQuestion.question_id),
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered,
            WrongQuestion.review_count >= 1,
            ReviewSchedule.next_review_at <= shanghai_date_utc_range(
                today + timedelta(days=3)
            )[0],
        )
        .order_by(ReviewSchedule.next_review_at)
        .limit(10)
    )
    pseudo_items = []
    for row in pseudo.all():
        pseudo_items.append(
            {
                "id": row[0],
                "question_id": row[1],
                "review_count": row[2],
                "interval": row[3],
                "efactor": row[4],
                "next_review_date": str(row[5].date()) if row[5] else "",
            }
        )

    long_unmastered = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= shanghai_date_utc_range(
                today - timedelta(days=7)
            )[0],
        )
    )

    # Aggregate forgotten topics from unmastered wrong questions
    kp_result = await db.execute(
        select(Question.id)
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
        .where(
            WrongQuestion.user_id == user_id,
            ~WrongQuestion.mastered,
        )
    )
    forgotten_qids = [row[0] for row in kp_result.all()]
    kp_map = await load_question_kps(db, forgotten_qids)
    kp_counter: dict[str, int] = {}
    for qid in forgotten_qids:
        for kp in kp_map.get(qid, []):
            if isinstance(kp, str):
                kp_counter[kp] = kp_counter.get(kp, 0) + 1
    top_forgotten = sorted(kp_counter.items(), key=lambda x: x[1], reverse=True)[:8]
    top_forgotten_topics = [{"topic": k, "count": v} for k, v in top_forgotten]

    return {
        "high_forget_count": stuck.scalar() or 0,
        "stuck_questions": long_unmastered.scalar() or 0,
        "pseudo_mastered": pseudo_items,
        "top_forgotten_topics": top_forgotten_topics,
    }


async def get_growth_profile(
    db: AsyncSession, user_id: int, overview: dict | None = None,
) -> dict:
    """成长体系：经验值、等级、徽章，全部基于真实统计数据。"""
    if overview is None:
        overview = await get_overview(db, user_id)

    total_q = overview["total_questions"]
    accuracy = overview["accuracy"]
    streak = overview["consecutive_days"]
    mastered = overview["mastered_count"]
    today_q = overview["today_questions"]
    overview["due_review_count"]

    total_exp = total_q * 10 + mastered * 20 + streak * 5
    if accuracy >= 0.7 and total_q >= 10:
        total_exp += int(total_q * accuracy * 5)

    levels = [
        (0, 200, 1, "Lv1 起步"),
        (200, 600, 2, "Lv2 坚持者"),
        (600, 1500, 3, "Lv3 刷题达人"),
        (1500, 3500, 4, "Lv4 高效进阶"),
        (3500, None, 5, "Lv5 上岸冲刺"),
    ]
    current_level = levels[0]
    for lo, hi, lv, title in levels:
        if total_exp >= lo:
            current_level = (lo, hi, lv, title)

    lo, hi, lv, title = current_level
    if hi is None:
        level_pct = 100
        exp_current = total_exp - lo
        exp_to_next = 0
    else:
        level_pct = min(100, round((total_exp - lo) / (hi - lo) * 100))
        exp_current = total_exp - lo
        exp_to_next = hi - lo

    if streak >= 30:
        streak_title = "连续学习 30 天以上，习惯已成"
    elif streak >= 15:
        streak_title = "连续学习 15 天，节奏渐稳"
    elif streak >= 7:
        streak_title = "连续学习 7 天，势头正盛"
    elif streak > 0:
        streak_title = f"连续学习 {streak} 天，继续加油"
    else:
        streak_title = "开始今天的学习，点亮第一天"

    if today_q > 0 and total_q > 0:
        daily_boost = f"今日已练 {today_q} 题，连续 {streak} 天，累计 {total_q} 题"
    elif total_q > 0:
        daily_boost = f"累计 {total_q} 题，连续 {streak} 天，今日本站首练"
    else:
        daily_boost = "完成第一道题，开启成长之旅"

    badges = [
        {"key": "first_learn", "title": "首次学习", "desc": "完成第一道题", "unlocked": total_q > 0, "progress": 100 if total_q > 0 else 0, "progress_text": "已解锁" if total_q > 0 else "0/1"},
        {"key": "streak_7", "title": "连续7天", "desc": "保持一周学习节奏", "unlocked": streak >= 7, "progress": min(100, round(streak / 7 * 100)), "progress_text": f"{min(streak, 7)}/7天"},
        {"key": "streak_30", "title": "连续30天", "desc": "形成长期学习习惯", "unlocked": streak >= 30, "progress": min(100, round(streak / 30 * 100)), "progress_text": f"{min(streak, 30)}/30天"},
        {"key": "hundred", "title": "百题积累", "desc": "累计完成100题", "unlocked": total_q >= 100, "progress": min(100, round(total_q / 100 * 100)), "progress_text": f"{min(total_q, 100)}/100题"},
        {"key": "five_hundred", "title": "500题达人", "desc": "累计完成500题", "unlocked": total_q >= 500, "progress": min(100, round(total_q / 500 * 100)), "progress_text": f"{min(total_q, 500)}/500题"},
        {"key": "thousand", "title": "千题斩", "desc": "累计完成1000题", "unlocked": total_q >= 1000, "progress": min(100, round(total_q / 1000 * 100)), "progress_text": f"{min(total_q, 1000)}/1000题"},
        {"key": "accuracy_90", "title": "正确率90%", "desc": "稳定高质量输出", "unlocked": accuracy >= 0.9 and total_q >= 30, "progress": min(100, round(accuracy / 0.9 * 100)) if total_q >= 10 else 0, "progress_text": f"{round(accuracy * 100)}%"},
        {"key": "master_50", "title": "掌握50题", "desc": "错题转化为能力", "unlocked": mastered >= 50, "progress": min(100, round(mastered / 50 * 100)), "progress_text": f"{min(mastered, 50)}/50题"},
        {"key": "master_100", "title": "掌握100题", "desc": "突破核心知识点", "unlocked": mastered >= 100, "progress": min(100, round(mastered / 100 * 100)), "progress_text": f"{min(mastered, 100)}/100题"},
    ]

    return {
        "total_exp": total_exp,
        "level": lv,
        "level_title": title,
        "level_progress_pct": level_pct,
        "exp_current": exp_current,
        "exp_to_next": exp_to_next,
        "streak_days": streak,
        "streak_title": streak_title,
        "daily_boost": daily_boost,
        "badges": badges,
    }


async def get_dashboard_v2(
    db: AsyncSession, user_id: int, *,
    trend_days: int = 7,
    include_yearly_summary: bool = True,
    include_growth: bool = True,
    include_adaptive: bool = True,
) -> dict:
    """dashboard-v2 聚合接口，整合学习总览、推荐、趋势、学科、遗忘、成长、自适应、年度摘要。"""
    from app.core.cache import cache

    cache_key = f"stats:dashboard_v2:{user_id}:{trend_days}:{include_yearly_summary}:{include_growth}:{include_adaptive}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    # 1. Overview
    overview = await get_overview(db, user_id)
    wrong_count = overview.get("wrong_question_count", 0)
    mastered_count = overview.get("mastered_count", 0)
    ov = {
        "total_questions": overview["total_questions"],
        "total_correct": overview["total_correct"],
        "total_wrong": overview["total_wrong"],
        "accuracy": overview["accuracy"],
        "today_questions": overview["today_questions"],
        "today_correct": overview["today_correct"],
        "today_accuracy": round(overview["today_correct"] / max(1, overview["today_questions"]), 4) if overview["today_questions"] > 0 else 0.0,
        "today_duration_sec": overview["today_duration_sec"],
        "consecutive_days": overview["consecutive_days"],
        "due_review_count": overview["due_review_count"],
        "wrong_question_count": wrong_count,
        "mastered_wrong_count": mastered_count,
        "mastery_rate": round(mastered_count / wrong_count, 4) if wrong_count > 0 else 0.0,
    }

    # 2. Recommendation
    forgetting_data = await get_forgetting_trends(db, user_id)
    subjects_raw = await get_subject_stats(db, user_id)
    subj_items = _subject_items_with_label(subjects_raw)
    weak_subj = min(subj_items, key=lambda s: s["accuracy"]) if subj_items else None

    rec = _build_recommendation(ov, forgetting_data, weak_subj)

    # 3. Trends (current + previous period)
    trend_points = await get_trends(db, user_id, trend_days)
    today = shanghai_today()
    previous_start = today - timedelta(days=2 * trend_days - 1)
    previous_points = await get_trends(db, user_id, trend_days, start_date=previous_start)

    trend_total = sum(t.get("questions", 0) for t in trend_points)
    trend_correct = sum(t.get("correct", 0) for t in trend_points)
    trend_active = sum(1 for t in trend_points if t.get("questions", 0) > 0)
    trend_avg_acc = round(trend_correct / trend_total, 4) if trend_total > 0 else 0.0

    prev_total = sum(p.get("questions", 0) for p in previous_points)
    prev_correct = sum(p.get("correct", 0) for p in previous_points)
    prev_active = sum(1 for p in previous_points if p.get("questions", 0) > 0)
    prev_avg_acc = round(prev_correct / prev_total, 4) if prev_total > 0 else 0.0

    tr = {
        "days": trend_days,
        "points": trend_points,
        "previous_points": previous_points,
        "total_questions": trend_total,
        "active_days": trend_active,
        "avg_accuracy": trend_avg_acc,
        "previous_total_questions": prev_total,
        "previous_active_days": prev_active,
        "previous_avg_accuracy": prev_avg_acc,
        "summary": f"近{trend_days}天累计做题{trend_total}题，平均正确率{round(trend_avg_acc * 100)}%，活跃{trend_active}天。",
    }

    # 4. Subjects
    strongest = max(subj_items, key=lambda s: s["accuracy"]) if subj_items else None
    weakest = min(subj_items, key=lambda s: s["accuracy"]) if subj_items else None
    sa = {
        "items": subj_items,
        "strongest": strongest,
        "weakest": weakest,
        "total_questions": sum(s.get("total_questions", 0) for s in subj_items),
    }

    # 5. Review risk
    pseudo_count = len(forgetting_data.get("pseudo_mastered", []))
    rr = {
        "high_forget_count": forgetting_data.get("high_forget_count", 0),
        "stuck_questions": forgetting_data.get("stuck_questions", 0),
        "pseudo_mastered_count": pseudo_count,
        "top_topics": forgetting_data.get("top_forgotten_topics", [])[:5],
    }

    # 6. Growth (best-effort)
    growth_data = None
    if include_growth:
        try:
            g = await get_growth_profile(db, user_id, overview=overview)
            badges = g.get("badges", [])
            unlocked = [b for b in badges if b.get("unlocked")]
            locked_sorted = sorted([b for b in badges if not b.get("unlocked")], key=lambda b: b.get("progress", 0), reverse=True)
            featured = (unlocked[-3:] if len(unlocked) >= 3 else unlocked + locked_sorted[:3 - len(unlocked)])[:3]
            growth_data = {
                "level": g.get("level", 1),
                "level_title": g.get("level_title", ""),
                "level_progress_pct": g.get("level_progress_pct", 0),
                "streak_title": g.get("streak_title", ""),
                "featured_badges": [
                    {"key": b["key"], "title": b["title"], "desc": b["desc"],
                     "unlocked": b.get("unlocked", False), "progress_text": b.get("progress_text", "")}
                    for b in featured
                ],
            }
        except Exception:
            pass

    # 7. Adaptive (best-effort)
    adaptive_data = None
    if include_adaptive:
        try:
            from app.services.adaptive_learning_service import get_adaptive_overview
            a = await get_adaptive_overview(db, user_id)
            if a:
                status_map = {
                    "fast_forgetting": "遗忘较快",
                    "slightly_fast_forgetting": "略偏快遗忘",
                    "normal": "节奏正常",
                    "stable_memory": "记忆稳定",
                }
                status = a.get("interval_status", "normal")
                label = status_map.get(status, "节奏正常")
                recall_rate = a.get("recent_due_recall_rate", 0)
                target = a.get("target_recall_rate", 0.8)
                adaptive_data = {
                    "visible": (a.get("interval_factor") != 1.0) or (a.get("hard_question_count", 0) > 0),
                    "interval_status": status,
                    "interval_status_label": label,
                    "recent_due_recall_rate": recall_rate,
                    "target_recall_rate": target,
                    "summary": _adaptive_summary(status, recall_rate, target),
                }
        except Exception:
            pass

    # 8. Yearly summary
    yearly_data = None
    if include_yearly_summary:
        try:
            yearly_trends = await get_trends(db, user_id, 365)
            active_days = sum(1 for t in yearly_trends if t.get("questions", 0) > 0)
            total_q = sum(t.get("questions", 0) for t in yearly_trends)
            best = max(yearly_trends, key=lambda t: t.get("questions", 0)) if yearly_trends else {}
            best_text = f"{best.get('date', '')[-5:]} · {best.get('questions', 0)}题" if best.get("questions", 0) else "暂无记录"
            yearly_data = {
                "active_days": active_days,
                "total_questions": total_q,
                "best_day_text": best_text,
            }
        except Exception:
            pass

    result = {
        "overview": ov,
        "recommendation": rec,
        "trends": tr,
        "subjects": sa,
        "review_risk": rr,
        "growth": growth_data,
        "adaptive": adaptive_data,
        "yearly_summary": yearly_data,
    }

    await cache.set(cache_key, result, ttl=120)
    return result


def _subject_items_with_label(subjects_raw: list[dict]) -> list[dict]:
    """带科目展示信息的学科统计项（subject_id + code/name）。"""
    items = []
    for s in subjects_raw:
        subject_name = s.get("subject_name", "")
        items.append({
            "subject_id": s.get("subject_id"),
            "subject_code": s.get("subject_code", ""),
            "subject_name": subject_name,
            "label": subject_name,
            "total_questions": s.get("total_questions", 0),
            "correct_count": s.get("correct_count", 0),
            "wrong_count": s.get("wrong_count", 0),
            "accuracy": s.get("accuracy", 0.0),
            "total_duration_sec": s.get("total_duration_sec", 0),
        })
    return items


def _build_recommendation(ov: dict, forgetting: dict, weak_subj: dict | None) -> dict:
    """根据数据生成智能建议。"""
    due = ov.get("due_review_count", 0)
    high_forget = forgetting.get("high_forget_count", 0)
    total_q = ov.get("total_questions", 0)
    today_q = ov.get("today_questions", 0)
    streak = ov.get("consecutive_days", 0)

    if total_q == 0:
        return {
            "priority": "practice",
            "title": "完成第一次练习",
            "desc": "练习、复习和错题数据会在这里汇总。先开始第一道题吧！",
            "tags": ["数据不足"],
            "cta_text": "开始练习",
            "cta_type": "practice",
        }

    if due > 0:
        return {
            "priority": "review",
            "title": "优先复习到期题",
            "desc": f"建议先完成 {due} 道到期复习，再进行新题练习。",
            "tags": ["待复习", "优先处理"],
            "cta_text": "去复习",
            "cta_type": "review",
        }

    if high_forget > 0:
        return {
            "priority": "wrong",
            "title": "巩固高频遗忘题",
            "desc": f"有 {high_forget} 道高频遗忘题目，建议集中复盘。",
            "tags": ["高频遗忘", "需要复盘"],
            "cta_text": "查看错题",
            "cta_type": "wrong",
        }

    if weak_subj and weak_subj["accuracy"] < 0.5 and weak_subj["total_questions"] >= 3:
        return {
            "priority": "subject",
            "title": "巩固薄弱学科",
            "desc": f"{weak_subj['label']}正确率仅{round(weak_subj['accuracy'] * 100)}%，建议优先复盘该学科错题。",
            "tags": ["薄弱学科", "需要补强"],
            "cta_text": "查看学科错题",
            "cta_type": "subject",
        }

    if streak >= 3 and today_q > 0:
        return {
            "priority": "keep",
            "title": "节奏稳定，继续保持",
            "desc": f"已连续学习 {streak} 天，今日完成 {today_q} 题，保持节奏。",
            "tags": ["节奏稳定", "状态良好"],
            "cta_text": "继续练习",
            "cta_type": "practice",
        }

    return {
        "priority": "practice",
        "title": "保持每日练习",
        "desc": f"累计 {total_q} 题，连续 {streak} 天。每天进步一点点。",
        "tags": ["保持节奏"],
        "cta_text": "开始练习",
        "cta_type": "practice",
    }


def _adaptive_summary(status: str, recall_rate: float, target: float) -> str:
    if status == "fast_forgetting":
        return "系统已自动缩短复习间隔，帮助巩固记忆"
    if status == "slightly_fast_forgetting":
        return "系统已略微缩短复习间隔"
    if status == "stable_memory":
        return "记忆保持良好，间隔适当拉长"
    return "复习节奏合理，继续保持"


async def get_ai_diagnosis(db: AsyncSession, user_id: int) -> dict:
    """AI 错题诊断：基于真实错题数据调用后台配置的兼容模型。"""
    from app.ai.gateway import chat_with_db_model, resolve_llm_runtime_config
    from app.ai.prompts_learning import build_report_prompt

    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=60))[0]

    from app.models.admin import Subject
    result = await db.execute(
        select(
            Subject.code,
            func.count(WrongQuestion.id),
            func.coalesce(
                func.sum(case((WrongQuestion.mastered, 1), else_=0)), 0
            ),
        )
        .join(Question, WrongQuestion.question_id == Question.id)
        .join(Subject, Question.subject_id == Subject.id)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.created_at >= since,
        )
        .group_by(Subject.id, Subject.code)
    )
    subject_rows = result.all()
    if not subject_rows:
        return {"weak_points": [], "strong_points": [], "learning_suggestions": [], "summary": "暂无足够错题数据生成诊断。继续练习后会自动触发分析。", "generated": False}

    # 获取各科正确率
    overview = await get_overview(db, user_id)
    total_q = overview["total_questions"]
    accuracy = overview["accuracy"]

    knowledge_point_stats = []
    for row in subject_rows:
        subj = row[0]
        total = row[1]
        mastered = row[2]
        mastery_rate = round(mastered / total, 2) if total > 0 else 0.0
        knowledge_point_stats.append({
            "knowledge_point": subj,
            "mastery_rate": mastery_rate,
            "mastered": mastered,
            "total_wrong": total,
        })

    runtime = await resolve_llm_runtime_config(db, feature="analysis")
    if runtime is None:
        # 本地降级：基于错题掌握率生成诊断
        weak = [kp for kp in knowledge_point_stats if kp["mastery_rate"] < 0.5]
        strong = [kp for kp in knowledge_point_stats if kp["mastery_rate"] >= 0.7]
        suggestions = []
        if weak:
            suggestions.append(f"优先复盘{weak[0]['knowledge_point']}错题，当前掌握率仅{int(weak[0]['mastery_rate'] * 100)}%")
        if total_q < 50:
            suggestions.append("题量较少，建议达到50题后诊断会更准确")
        suggestions.append("每天保持10题以上练习，有利于形成稳定记忆")
        return {
            "weak_points": [{"knowledge_point": w["knowledge_point"], "accuracy": w["mastery_rate"], "suggestion": "建议针对性复盘练习"} for w in weak[:3]],
            "strong_points": [{"knowledge_point": s["knowledge_point"], "accuracy": s["mastery_rate"], "suggestion": "已较好地掌握错题，保持节奏"} for s in strong[:2]],
            "learning_suggestions": suggestions,
            "summary": f"基于最近60天{len(subject_rows)}个科目的错题数据分析（本地降级模式）。",
            "generated": False,
        }

    try:
        subj_label = subject_rows[0][0] if subject_rows else "全科"
        messages = build_report_prompt(
            subject=subj_label,
            days=60,
            total=total_q,
            accuracy=accuracy,
            knowledge_point_stats=knowledge_point_stats,
        )

        ai_resp = await chat_with_db_model(db, messages, feature="analysis", temperature=0.3)
        if ai_resp is None:
            raise RuntimeError("AI分析模型未配置")
        content = ai_resp["content"]
        import json
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError, IndexError):
            return {
                "weak_points": [],
                "strong_points": [],
                "learning_suggestions": ["AI 诊断暂时不可用，请稍后重试"],
                "summary": "AI 返回格式异常，已记录。",
                "generated": False,
            }
        return {
            "weak_points": parsed.get("weak_points", [])[:5],
            "strong_points": parsed.get("strong_points", [])[:3],
            "learning_suggestions": parsed.get("learning_suggestions", [])[:5],
            "summary": f"基于最近60天{len(subject_rows)}个科目的真实错题数据进行AI诊断。",
            "generated": True,
        }
    except Exception:
        return {
            "weak_points": [],
            "strong_points": [],
            "learning_suggestions": ["AI 服务暂不可用，请检查 API Key 配置"],
            "summary": "AI 服务连接失败。",
            "generated": False,
        }


# ──────────────────────────────────────────────
# Dashboard LLM analysis (manual trigger)
# ──────────────────────────────────────────────


async def get_dashboard_llm_analysis(
    db: AsyncSession, user_id: int, *, trend_days: int = 7
) -> dict:
    """Dashboard LLM 手动分析 — 聚合学习数据，调用后台配置的兼容模型。"""
    from app.core.time_utils import utcnow

    now = utcnow()

    # Build reduced data payload (no full questions, no privacy info)
    overview = await get_overview(db, user_id)
    subjects_raw = await get_subject_stats(db, user_id)
    trends = await get_trends(db, user_id, trend_days)
    forgetting = await get_forgetting_trends(db, user_id)

    subj_items = _subject_items_with_label(subjects_raw)
    strong_subj = max(subj_items, key=lambda s: s["accuracy"]) if subj_items else None
    weak_subj = min(subj_items, key=lambda s: s["accuracy"]) if subj_items else None

    trend_total = sum(t.get("questions", 0) for t in trends)
    trend_correct = sum(t.get("correct", 0) for t in trends)
    trend_active = sum(1 for t in trends if t.get("questions", 0) > 0)

    data_payload = {
        "overview": {
            "today_questions": overview["today_questions"],
            "today_accuracy": round(overview["today_correct"] / max(1, overview["today_questions"]), 4) if overview["today_questions"] > 0 else 0.0,
            "due_review_count": overview["due_review_count"],
            "consecutive_days": overview["consecutive_days"],
            "total_questions": overview["total_questions"],
            "total_accuracy": overview["accuracy"],
        },
        "trends": {
            "days": trend_days,
            "total_questions": trend_total,
            "active_days": trend_active,
            "avg_accuracy": round(trend_correct / trend_total, 4) if trend_total > 0 else 0.0,
        },
        "subjects": {
            "strongest": strong_subj["label"] if strong_subj else None,
            "weakest": weak_subj["label"] if weak_subj else None,
            "items": [
                {"label": s["label"], "accuracy": s["accuracy"], "total_questions": s["total_questions"]}
                for s in subj_items
            ],
        },
        "review_risk": {
            "high_forget_count": forgetting.get("high_forget_count", 0),
            "stuck_questions": forgetting.get("stuck_questions", 0),
            "top_topics": forgetting.get("top_forgotten_topics", [])[:5],
        },
    }

    from app.ai.gateway import chat_with_db_model, resolve_llm_runtime_config
    runtime = await resolve_llm_runtime_config(db, feature="analysis")
    if runtime is None:
        return _rule_based_dashboard_analysis(data_payload, now, trend_days)

    prompt_messages = _build_dashboard_llm_prompt(data_payload, trend_days)
    try:
        ai_resp = await chat_with_db_model(db, prompt_messages, feature="analysis", temperature=0.3)
        if ai_resp is None:
            return _rule_based_dashboard_analysis(data_payload, now, trend_days)
        content = ai_resp["content"]
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError, IndexError):
            return _rule_based_dashboard_analysis(data_payload, now, trend_days)

        model_used = ai_resp.get("model", runtime.model_name)
        return {
            "summary": parsed.get("summary", ""),
            "findings": parsed.get("findings", [])[:6],
            "risks": parsed.get("risks", [])[:4],
            "actions": parsed.get("actions", [])[:4],
            "generated_at": serialize_utc_datetime(now),
            "model": model_used,
        }
    except Exception:
        return _rule_based_dashboard_analysis(data_payload, now, trend_days)


def _build_dashboard_llm_prompt(payload: dict, trend_days: int) -> list[dict]:
    system_prompt = (
        "你是一个学习数据分析助手。你只能根据输入的学习统计数据生成简洁、可执行的学习诊断。"
        "不要编造输入中不存在的数据。不要输出泛泛鸡汤。"
        "请用 JSON 返回，格式为："
        '{"summary": "一句话总结", "findings": ["发现1", "发现2"], "risks": ["风险1"], '
        '"actions": [{"type": "review|wrong|practice|subject|none", "title": "行动标题", "desc": "行动描述"}]}'
    )
    user_prompt = (
        f"以下是一位考研学生近 {trend_days} 天的学习统计数据，请生成诊断。\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _rule_based_dashboard_analysis(payload: dict, now, trend_days: int) -> dict:
    """Rule-based analysis when LLM is unavailable (labeled as 学习建议, not AI)."""
    ov = payload.get("overview", {})
    tr = payload.get("trends", {})
    rr = payload.get("review_risk", {})
    sb = payload.get("subjects", {})

    findings = []
    risks = []
    actions = []
    total_q = ov.get("total_questions", 0)

    if total_q == 0:
        findings.append("暂无学习数据，完成第一次练习后生成分析。")
        return {
            "summary": "数据不足，无法生成分析。",
            "findings": findings,
            "risks": [],
            "actions": [{"type": "practice", "title": "开始第一次练习", "desc": "完成练习后回来查看分析。"}],
            "generated_at": serialize_utc_datetime(now),
            "model": "rule-based",
        }

    today_q = ov.get("today_questions", 0)
    due = ov.get("due_review_count", 0)
    streak = ov.get("consecutive_days", 0)
    trend_total = tr.get("total_questions", 0)
    active_days = tr.get("active_days", 0)
    avg_acc = tr.get("avg_accuracy", 0)
    hf = rr.get("high_forget_count", 0)
    rr.get("stuck_questions", 0)
    weak_label = sb.get("weakest")
    top_topics = rr.get("top_topics", [])

    findings.append(f"近{trend_days}天完成{trend_total}题，活跃{active_days}天，平均正确率{round(avg_acc * 100)}%。")
    if today_q > 0:
        findings.append(f"今日完成{today_q}题，连续学习{streak}天。")
    if total_q > 0:
        findings.append(f"累计做题{total_q}题，总正确率{round(ov.get('total_accuracy', 0) * 100)}%。")

    if due > 0:
        findings.append(f"当前有{due}道到期复习。")
        actions.append({"type": "review", "title": f"先完成{due}道到期复习", "desc": "建议优先处理复习任务。"})
    if hf > 0:
        risks.append(f"高频遗忘知识点{hf}个，建议集中复盘。")
        actions.append({"type": "wrong", "title": f"复盘{hf}道高频遗忘错题", "desc": "针对高频遗忘点做专项巩固。"})
    if weak_label:
        findings.append(f"薄弱学科：{weak_label}。")
        actions.append({"type": "subject", "title": f"重点看{weak_label}错题", "desc": "该学科正确率偏低，建议优先复盘。"})
    if top_topics:
        topics_str = "、".join(t["topic"] for t in top_topics[:3])
        risks.append(f"高频遗忘知识点：{topics_str}。")

    if not actions:
        actions.append({"type": "practice", "title": "保持练习节奏", "desc": "当前状态良好，继续每日练习。"})

    if due == 0 and hf == 0 and not weak_label:
        summary = f"学习节奏稳定，累计{total_q}题，连续{streak}天。继续保持！"
    elif due > 0:
        summary = f"学习数据良好，但到期复习{due}道需尽快处理。"
    else:
        summary = f"近{trend_days}天平均正确率{round(avg_acc * 100)}%，建议关注薄弱环节。"

    return {
        "summary": summary,
        "findings": findings[:4],
        "risks": risks[:3],
        "actions": actions[:3],
        "generated_at": serialize_utc_datetime(now),
        "model": "rule-based",
    }
