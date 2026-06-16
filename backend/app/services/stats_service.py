from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer_behavior import AnswerBehavior
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.wrong_question import WrongQuestion


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    """学习总览统计"""
    today = date.today()
    today_start = datetime(today.year, today.month, today.day)

    pr_result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == False, 1), else_=0)), 0
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
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
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
                func.sum(case((WrongQuestion.mastered == True, 1), else_=0)), 0
            ),
        ).where(WrongQuestion.user_id == user_id)
    )
    total_wq, mastered_count = wq_result.one()

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
        "total_duration_sec": total_duration or 0,
        "consecutive_days": consecutive_days,
        "today_questions": today_count,
        "today_correct": today_correct,
        "today_duration_sec": today_duration or 0,
        "mastered_count": mastered_count or 0,
        "due_review_count": due_count.scalar() or 0,
    }


async def _calc_consecutive_days(db: AsyncSession, user_id: int) -> int:
    today = date.today()

    result = await db.execute(
        select(func.date(PracticeRecord.answered_at))
        .where(PracticeRecord.user_id == user_id)
        .distinct()
        .order_by(func.date(PracticeRecord.answered_at).desc())
    )
    dates = {row[0] for row in result.all()}

    days = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            days += 1
        else:
            break
    return days


async def get_subject_stats(db: AsyncSession, user_id: int) -> list[dict]:
    """学科维度统计"""
    result = await db.execute(
        select(
            PracticeRecord.subject,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == False, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(PracticeRecord.used_time), 0),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject)
    )
    rows = []
    for r in result.all():
        total_q = r[1]
        correct = r[2]
        wrong = r[3]
        rows.append(
            {
                "subject": r[0],
                "total_questions": total_q,
                "correct_count": correct,
                "wrong_count": wrong,
                "accuracy": round(correct / total_q, 4) if total_q > 0 else 0.0,
                "total_duration_sec": r[4] or 0,
                "avg_duration_sec": round((r[4] or 0) / total_q, 1) if total_q > 0 else 0.0,
            }
        )
    return rows


async def get_trends(
    db: AsyncSession, user_id: int, days: int = 7
) -> list[dict]:
    """学习趋势（按天聚合）"""
    since = datetime.combine(
        date.today() - timedelta(days=days - 1), datetime.min.time()
    )

    result = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == False, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(func.date(PracticeRecord.answered_at))
        .order_by(func.date(PracticeRecord.answered_at))
    )
    data = {
        str(r[0]): {"count": r[1], "correct": r[2], "wrong": r[3]}
        for r in result.all()
    }

    points = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
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
                func.sum(case((AnswerBehavior.is_abandoned == True, 1), else_=0)), 0
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

    stuck = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
            WrongQuestion.review_count >= 3,
        )
    )

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
        pseudo_items.append(
            {
                "id": wq.id,
                "question_id": wq.question_id,
                "review_count": wq.review_count,
                "interval": wq.interval,
                "efactor": wq.efactor,
                "next_review_date": str(wq.next_review_date)
                if wq.next_review_date
                else "",
            }
        )

    long_unmastered = await db.execute(
        select(func.count(WrongQuestion.id)).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
            WrongQuestion.next_review_date <= today - timedelta(days=7),
        )
    )

    # Aggregate forgotten topics from unmastered wrong questions
    kp_result = await db.execute(
        select(Question.knowledge_points)
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered == False,
        )
    )
    kp_counter: dict[str, int] = {}
    for (kps,) in kp_result.all():
        if kps and isinstance(kps, list):
            for kp in kps:
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


async def get_growth_profile(db: AsyncSession, user_id: int) -> dict:
    """成长体系：经验值、等级、徽章，全部基于真实统计数据。"""
    overview = await get_overview(db, user_id)

    total_q = overview["total_questions"]
    accuracy = overview["accuracy"]
    streak = overview["consecutive_days"]
    mastered = overview["mastered_count"]
    today_q = overview["today_questions"]
    due = overview["due_review_count"]

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


async def get_ai_diagnosis(db: AsyncSession, user_id: int) -> dict:
    """AI 错题诊断：基于真实错题数据调用 DeepSeek 生成个性化诊断报告。"""
    from app.ai.client import deepseek
    from app.ai.prompts_learning import build_report_prompt

    today = date.today()
    since = today - timedelta(days=60)

    result = await db.execute(
        select(
            WrongQuestion.subject,
            func.count(WrongQuestion.id),
            func.coalesce(
                func.sum(case((WrongQuestion.mastered == True, 1), else_=0)), 0
            ),
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.created_at >= since,
        )
        .group_by(WrongQuestion.subject)
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

    if not deepseek.is_available():
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

        # Use DB-configured model when available
        from app.services.model_config_resolver import ensure_db_model_configured
        _creds = await ensure_db_model_configured(db)
        _model_name = _creds[2] if _creds else None

        ai_resp = await deepseek.chat(messages, temperature=0.3, model=_model_name)
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
    except RuntimeError:
        return {
            "weak_points": [],
            "strong_points": [],
            "learning_suggestions": ["AI 服务暂不可用，请检查 API Key 配置"],
            "summary": "AI 服务连接失败。",
            "generated": False,
        }
