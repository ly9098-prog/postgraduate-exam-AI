import logging
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, shanghai_today, utcnow
from app.services import stats_query_service
from app.services.learning_time_projection import (
    china_date_expr as _china_date_expr,  # noqa: F401 - compatibility alias
)
from app.services.learning_time_projection import (
    china_hour_expr as _china_hour_expr,  # noqa: F401 - compatibility alias
)
from app.services.learning_time_projection import (
    coerce_date as _coerce_date,
)
from app.services.learning_time_projection import (
    date_utc_range as _date_utc_range,
)
from app.services.learning_time_projection import (
    today_utc as _today_utc,
)
from app.services.stats_ai_projection import (
    build_dashboard_ai_payload,
    build_dashboard_ai_prompt,
    build_dashboard_ai_response,
    build_knowledge_point_stats,
    build_local_ai_diagnosis,
    build_rule_based_dashboard_analysis,
    extract_json_object,
    normalize_dashboard_actions,
    normalize_knowledge_points,
    normalize_text_list,
)
from app.services.stats_dashboard_projection import (
    build_dashboard_adaptive,
    build_dashboard_growth,
    build_dashboard_overview,
    build_dashboard_review_risk,
    build_dashboard_subjects,
    build_dashboard_trends,
    build_dashboard_yearly_summary,
    previous_trend_start,
)
from app.services.stats_growth_projection import build_growth_profile
from app.services.stats_recommendation_projection import (
    build_adaptive_summary,
    build_dashboard_recommendation,
    build_subject_items_with_label,
)

logger = logging.getLogger(__name__)

# Synchronous AI endpoints are called directly from the mini-program. Keep the
# provider budget below the client transport timeout so a slow reasoning model
# can degrade to a deterministic local diagnosis instead of failing at wx.request.
_SYNC_AI_PROVIDER_TIMEOUT_SEC = 42.0
_AI_DIAGNOSIS_MAX_TOKENS = 900
_DASHBOARD_AI_MAX_TOKENS = 1000
_extract_json_object = extract_json_object
_normalize_text_list = normalize_text_list
_normalize_dashboard_actions = normalize_dashboard_actions
_subject_items_with_label = build_subject_items_with_label
_build_recommendation = build_dashboard_recommendation
_adaptive_summary = build_adaptive_summary


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    """学习总览统计"""
    today_start = _today_utc()
    (
        total_practices,
        total_correct,
        total_wrong,
        total_duration,
    ) = await stats_query_service.load_practice_totals(db, user_id)
    total_questions = total_correct + total_wrong

    (
        today_count,
        today_correct,
        today_duration,
    ) = await stats_query_service.load_today_practice_totals(db, user_id, today_start)
    consecutive_days = await _calc_consecutive_days(db, user_id)
    total_wq, mastered_count = await stats_query_service.load_wrong_question_totals(
        db, user_id
    )
    active_408_ids = await stats_query_service.load_active_408_subject_ids(db)
    due_count = await stats_query_service.count_due_reviews(
        db, user_id, active_408_ids, utcnow()
    )

    return {
        "total_questions": total_questions,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "accuracy": round(total_correct / total_questions, 4)
        if total_questions > 0
        else 0.0,
        "total_duration_sec": total_duration or 0,
        "consecutive_days": consecutive_days,
        "today_questions": today_count,
        "today_correct": today_correct,
        "today_duration_sec": today_duration or 0,
        "mastered_count": mastered_count or 0,
        "due_review_count": due_count,
        "wrong_question_count": total_wq or 0,
    }


async def _calc_consecutive_days(db: AsyncSession, user_id: int) -> int:
    today = shanghai_today()
    since = _date_utc_range(today - timedelta(days=364))[0]
    rows = await stats_query_service.load_answer_days(db, user_id, since)
    return _count_consecutive_days(today, rows)


def _count_consecutive_days(today: date, rows) -> int:
    dates = {d for row in rows if (d := _coerce_date(row[0])) is not None}
    days = 0
    for index in range(365):
        if today - timedelta(days=index) not in dates:
            break
        days += 1
    return days


async def get_subject_stats(db: AsyncSession, user_id: int) -> list[dict]:
    """学科维度统计 — 按 PracticeRecord.subject_id 分组。"""
    rows = await stats_query_service.load_subject_stat_rows(db, user_id)
    return [_subject_stat_row(row) for row in rows]


def _subject_stat_row(row) -> dict:
    total_q = row[3]
    correct = row[4]
    return {
        "subject_id": row[0],
        "subject_code": row[1] or "",
        "subject_name": row[2] or "",
        "total_questions": total_q,
        "correct_count": correct,
        "wrong_count": row[5],
        "accuracy": round(correct / total_q, 4) if total_q > 0 else 0.0,
        "total_duration_sec": row[6] or 0,
        "avg_duration_sec": round((row[6] or 0) / total_q, 1) if total_q > 0 else 0.0,
    }


async def get_trends(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
    start_date: date | None = None,
) -> list[dict]:
    """学习趋势（按天聚合）

    start_date: 起始日期（含），默认自动向前推 days 天。
    """
    today = shanghai_today()
    if start_date is None:
        start_date = today - timedelta(days=days - 1)

    since = _date_utc_range(start_date)[0]
    until = _date_utc_range(start_date + timedelta(days=days))[0]
    rows = await stats_query_service.load_trend_rows(db, user_id, since, until)
    data = {
        str(row[0]): {"count": row[1], "correct": row[2], "wrong": row[3]}
        for row in rows
    }
    return _fill_trend_points(start_date, days, data)


def _fill_trend_points(start_date: date, days: int, data: dict) -> list[dict]:
    points = []
    for index in range(days):
        day = (start_date + timedelta(days=index)).isoformat()
        entry = data.get(day, {"count": 0, "correct": 0, "wrong": 0})
        total = entry["count"]
        points.append(
            {
                "date": day,
                "questions": total,
                "correct": entry["correct"],
                "accuracy": round(entry["correct"] / total, 4) if total > 0 else 0.0,
            }
        )
    return points


async def get_behavior_stats(db: AsyncSession, user_id: int) -> dict:
    """学习行为分析"""
    (
        avg_time,
        total_ans,
        view_cnt,
        abandon_cnt,
    ) = await stats_query_service.load_behavior_totals(db, user_id)
    error_dist = [
        {"type": row[0], "count": row[1]}
        for row in await stats_query_service.load_error_type_distribution(db, user_id)
    ]
    hourly = _empty_hourly_activity()
    for row in await stats_query_service.load_hourly_activity(db, user_id):
        hour = int(row[0])
        if 0 <= hour < 24:
            hourly[hour]["count"] = row[1]

    return {
        "avg_time_sec": round(float(avg_time), 1) if avg_time else 0.0,
        "total_answers": total_ans or 0,
        "view_answer_rate": round(view_cnt / total_ans, 4) if total_ans > 0 else 0.0,
        "abandon_rate": round(abandon_cnt / total_ans, 4) if total_ans > 0 else 0.0,
        "error_type_distribution": error_dist,
        "hourly_activity": [item for item in hourly if item["count"] > 0],
    }


def _empty_hourly_activity() -> list[dict]:
    return [{"hour": hour, "count": 0} for hour in range(24)]


async def get_forgetting_trends(db: AsyncSession, user_id: int) -> dict:
    """遗忘趋势分析（基于 SM-2 数据，SM-2 状态源为 ReviewSchedule）"""
    today = shanghai_today()
    high_forget_count = await stats_query_service.count_stuck_questions(db, user_id)
    pseudo_rows = await stats_query_service.load_pseudo_mastered_rows(
        db, user_id, _date_utc_range(today + timedelta(days=3))[0]
    )
    stuck_questions = await stats_query_service.count_long_unmastered(
        db, user_id, _date_utc_range(today - timedelta(days=7))[0]
    )
    topic_rows = await stats_query_service.load_top_forgotten_topic_rows(db, user_id)
    return {
        "high_forget_count": high_forget_count,
        "stuck_questions": stuck_questions,
        "pseudo_mastered": _pseudo_mastered_items(pseudo_rows),
        "top_forgotten_topics": [
            {"topic": str(name), "count": int(count or 0)} for name, count in topic_rows
        ],
    }


def _pseudo_mastered_items(rows) -> list[dict]:
    return [
        {
            "id": row[0],
            "question_id": row[1],
            "review_count": row[2],
            "interval": row[3],
            "efactor": row[4],
            "next_review_date": str(row[5].date()) if row[5] else "",
        }
        for row in rows
    ]


async def get_growth_profile(
    db: AsyncSession,
    user_id: int,
    overview: dict | None = None,
) -> dict:
    """成长体系：经验值、等级、徽章，全部基于真实统计数据。"""
    if overview is None:
        overview = await get_overview(db, user_id)
    return build_growth_profile(overview)


async def get_dashboard_v2(
    db: AsyncSession,
    user_id: int,
    *,
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

    overview = await get_overview(db, user_id)
    ov = build_dashboard_overview(overview)
    forgetting_data = await get_forgetting_trends(db, user_id)
    subject_items = _subject_items_with_label(await get_subject_stats(db, user_id))
    weak_subject = (
        min(subject_items, key=lambda item: item["accuracy"]) if subject_items else None
    )
    recommendation = _build_recommendation(ov, forgetting_data, weak_subject)
    trends = await _load_dashboard_trends(db, user_id, trend_days)
    subjects = build_dashboard_subjects(subject_items)
    review_risk = build_dashboard_review_risk(forgetting_data)
    growth_data = await _dashboard_growth(db, user_id, overview, include=include_growth)
    adaptive_data = await _dashboard_adaptive(db, user_id, include=include_adaptive)
    yearly_data = await _dashboard_yearly(db, user_id, include=include_yearly_summary)

    result = {
        "overview": ov,
        "recommendation": recommendation,
        "trends": trends,
        "subjects": subjects,
        "review_risk": review_risk,
        "growth": growth_data,
        "adaptive": adaptive_data,
        "yearly_summary": yearly_data,
    }
    await cache.set(cache_key, result, ttl=120)
    return result


async def _load_dashboard_trends(db: AsyncSession, user_id: int, trend_days: int):
    trend_points = await get_trends(db, user_id, trend_days)
    previous_start = previous_trend_start(shanghai_today(), trend_days)
    previous_points = await get_trends(
        db, user_id, trend_days, start_date=previous_start
    )
    return build_dashboard_trends(
        trend_days=trend_days,
        trend_points=trend_points,
        previous_points=previous_points,
    )


async def _dashboard_growth(
    db: AsyncSession, user_id: int, overview: dict, *, include: bool
):
    if not include:
        return None
    try:
        growth = await get_growth_profile(db, user_id, overview=overview)
        return build_dashboard_growth(growth)
    except Exception:
        return None


async def _dashboard_adaptive(db: AsyncSession, user_id: int, *, include: bool):
    if not include:
        return None
    try:
        from app.services.adaptive_learning_service import get_adaptive_overview

        adaptive = await get_adaptive_overview(db, user_id)
        if not adaptive:
            return None
        data = build_dashboard_adaptive(adaptive)
        data["summary"] = _adaptive_summary(
            data["interval_status"],
            data["recent_due_recall_rate"],
            data["target_recall_rate"],
        )
        return data
    except Exception:
        return None


async def _dashboard_yearly(db: AsyncSession, user_id: int, *, include: bool):
    if not include:
        return None
    try:
        yearly_trends = await get_trends(db, user_id, 365)
        return build_dashboard_yearly_summary(yearly_trends)
    except Exception:
        return None


async def get_ai_diagnosis(db: AsyncSession, user_id: int) -> dict:
    """AI 错题诊断：优先使用后台模型，超时/异常时快速降级为数据诊断。"""
    today = shanghai_today()
    since = _date_utc_range(today - timedelta(days=60))[0]
    subject_rows = await stats_query_service.load_ai_diagnosis_subject_rows(
        db, user_id, since
    )
    if not subject_rows:
        return {
            "weak_points": [],
            "strong_points": [],
            "learning_suggestions": [],
            "summary": "暂无足够错题数据生成诊断。继续练习后会自动触发分析。",
            "generated": False,
        }

    overview = await get_overview(db, user_id)
    total_q = overview["total_questions"]
    accuracy = overview["accuracy"]
    knowledge_point_stats = build_knowledge_point_stats(subject_rows)
    local = _local_ai_diagnosis(knowledge_point_stats, len(subject_rows), total_q)
    runtime, runtime_failed = await _load_ai_diagnosis_runtime(db, user_id)
    if runtime_failed:
        return local(provider_failed=True)
    if runtime is None:
        return local()

    try:
        ai_resp = await _call_ai_diagnosis_provider(
            db,
            runtime,
            subject_rows,
            total_q,
            accuracy,
            knowledge_point_stats,
        )
        return _parse_ai_diagnosis_or_local(
            ai_resp, user_id, runtime.model_name, local, len(subject_rows)
        )
    except Exception as exc:
        logger.warning(
            "stats.ai_diagnosis.provider_failed user_id=%s model=%s error_type=%s",
            user_id,
            runtime.model_name,
            type(exc).__name__,
        )
        return local(provider_failed=True)


async def _load_ai_diagnosis_runtime(db: AsyncSession, user_id: int):
    from app.ai.gateway import resolve_llm_runtime_config

    try:
        # Model configuration is part of the remote-AI dependency boundary too.
        # Keep configuration failures on the deterministic fallback path.
        return await resolve_llm_runtime_config(db, feature="analysis"), False
    except Exception as exc:
        logger.warning(
            "stats.ai_diagnosis.runtime_config_failed user_id=%s error_type=%s",
            user_id,
            type(exc).__name__,
        )
        return None, True


def _local_ai_diagnosis(
    knowledge_point_stats: list[dict],
    subject_count: int,
    total_questions: int,
):
    def local(*, provider_failed: bool = False) -> dict:
        return build_local_ai_diagnosis(
            knowledge_point_stats=knowledge_point_stats,
            subject_count=subject_count,
            total_questions=total_questions,
            provider_failed=provider_failed,
        )

    return local


async def _call_ai_diagnosis_provider(
    db: AsyncSession,
    runtime,
    subject_rows,
    total_q: int,
    accuracy: float,
    knowledge_point_stats: list[dict],
):
    from app.ai.client import llm
    from app.ai.prompts_learning import build_report_prompt

    subj_label = subject_rows[0][0] if subject_rows else "全科"
    messages = build_report_prompt(
        subject=subj_label,
        days=60,
        total=total_q,
        accuracy=accuracy,
        knowledge_point_stats=knowledge_point_stats,
    )
    # This endpoint is synchronous: cap provider time/output so a reasoning
    # model cannot occupy the whole wx.request timeout window.
    return await llm.chat(
        messages,
        temperature=0.2,
        model=runtime.model_name,
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        provider=runtime.provider,
        timeout=_SYNC_AI_PROVIDER_TIMEOUT_SEC,
        max_tokens=_AI_DIAGNOSIS_MAX_TOKENS,
        response_format={"type": "json_object"},
        prefer_direct_answer=True,
    )


def _parse_ai_diagnosis_or_local(
    ai_resp: dict,
    user_id: int,
    model_name: str,
    local,
    subject_count: int,
) -> dict:
    parsed = _extract_json_object(ai_resp.get("content"))
    if parsed is None:
        logger.warning(
            "stats.ai_diagnosis.invalid_json user_id=%s model=%s",
            user_id,
            model_name,
        )
        return local(provider_failed=True)

    weak_points = normalize_knowledge_points(parsed.get("weak_points"), limit=5)
    strong_points = normalize_knowledge_points(parsed.get("strong_points"), limit=3)
    suggestions = _normalize_text_list(
        parsed.get("learning_suggestions"),
        limit=5,
        max_chars=240,
    )
    if not weak_points and not strong_points and not suggestions:
        return local(provider_failed=True)
    return {
        "weak_points": weak_points,
        "strong_points": strong_points,
        "learning_suggestions": suggestions,
        "summary": f"基于最近60天{subject_count}个科目的真实错题数据进行AI诊断。",
        "generated": True,
    }


# ──────────────────────────────────────────────
# Dashboard LLM analysis (manual trigger)
# ──────────────────────────────────────────────


async def get_dashboard_llm_analysis(
    db: AsyncSession, user_id: int, *, trend_days: int = 7
) -> dict:
    """Generate a bounded dashboard diagnosis with deterministic fallback."""
    data_payload = await _load_dashboard_ai_payload(db, user_id, trend_days)
    prompt_messages = build_dashboard_ai_prompt(data_payload, trend_days)
    from app.ai.gateway import chat_with_db_model

    try:
        ai_resp = await _call_dashboard_ai(db, chat_with_db_model, prompt_messages)
        if ai_resp is None:
            return _rule_based_dashboard_analysis(data_payload, trend_days)
        return _parse_dashboard_ai_response(ai_resp, data_payload, trend_days, user_id)
    except Exception as exc:
        logger.warning(
            "stats.dashboard_ai.provider_failed user_id=%s error_type=%s",
            user_id,
            type(exc).__name__,
        )
        return _rule_based_dashboard_analysis(data_payload, trend_days)


async def _load_dashboard_ai_payload(
    db: AsyncSession, user_id: int, trend_days: int
) -> dict:
    overview = await get_overview(db, user_id)
    subjects_raw = await get_subject_stats(db, user_id)
    trends = await get_trends(db, user_id, trend_days)
    forgetting = await get_forgetting_trends(db, user_id)
    return build_dashboard_ai_payload(
        overview=overview,
        subject_items=_subject_items_with_label(subjects_raw),
        trends=trends,
        forgetting=forgetting,
        trend_days=trend_days,
    )


async def _call_dashboard_ai(
    db: AsyncSession, chat_with_db_model, prompt_messages: list[dict]
):
    # Resolve and invoke only once so the selected model cannot change between
    # configuration resolution and the actual provider call.
    return await chat_with_db_model(
        db,
        prompt_messages,
        feature="analysis",
        temperature=0.2,
        timeout=_SYNC_AI_PROVIDER_TIMEOUT_SEC,
        max_tokens=_DASHBOARD_AI_MAX_TOKENS,
        response_format={"type": "json_object"},
        prefer_direct_answer=True,
    )


def _parse_dashboard_ai_response(
    ai_resp: dict, data_payload: dict, trend_days: int, user_id: int
) -> dict:
    parsed = _extract_json_object(ai_resp.get("content"))
    if parsed is None:
        logger.warning(
            "stats.dashboard_ai.invalid_json user_id=%s model=%s",
            user_id,
            ai_resp.get("model") or "-",
        )
        return _rule_based_dashboard_analysis(data_payload, trend_days)

    response = build_dashboard_ai_response(
        parsed=parsed,
        ai_response=ai_resp,
        generated_at=serialize_utc_datetime(utcnow()),
    )
    if response is None:
        logger.warning(
            "stats.dashboard_ai.empty_payload user_id=%s model=%s",
            user_id,
            ai_resp.get("model") or "-",
        )
        return _rule_based_dashboard_analysis(data_payload, trend_days)
    return response


def _rule_based_dashboard_analysis(payload: dict, trend_days: int) -> dict:
    """Rule-based analysis when LLM is unavailable (labeled as 学习建议, not AI)."""
    return build_rule_based_dashboard_analysis(
        payload,
        trend_days,
        now=utcnow(),
        serialize_now=serialize_utc_datetime,
    )
