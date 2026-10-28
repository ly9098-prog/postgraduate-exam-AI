"""Pure study-plan payloads for the daily snapshot and allocation views."""

from __future__ import annotations

from datetime import date

from app.services.study_plan_rules import (
    CATEGORIES,
    PRIORITY_LABELS,
    allocate_integer,
    build_weights,
    category_availability,
    phase_for_days,
    task_by_type,
)

HUB_TASK_TYPES = {
    "review": "review",
    "weakness": "weakness",
    "new": "smart_practice",
}


def build_snapshot_payload(
    *,
    plan,
    today: date,
    hub: dict,
    exam_suggestion: dict | None,
    prior_active_days: int,
    day_start_minute: int,
) -> tuple[int, bool, dict[str, int], dict]:
    days_remaining_raw = (plan.target_date - today).days
    phase, _ = phase_for_days(max(0, days_remaining_raw))
    availability = category_availability(hub, exam_suggestion)

    target_passed = days_remaining_raw < 0
    rest_day = (
        not target_passed
        and today != plan.target_date
        and prior_active_days >= int(plan.weekly_days)
    )
    target_minutes = 0 if target_passed or rest_day else int(plan.daily_minutes)
    weights = build_weights(
        phase=phase,
        priority_mode=str(plan.priority_mode),
        availability=availability,
    )
    allocation = allocate_integer(target_minutes, weights)
    basis = {
        "phase": phase,
        "priority_mode": str(plan.priority_mode),
        "priority_label": PRIORITY_LABELS.get(str(plan.priority_mode), "均衡推进"),
        "availability": availability,
        "weights": {key: round(float(value), 4) for key, value in weights.items()},
        "prior_active_days": int(prior_active_days),
        "day_start_minute": int(day_start_minute),
        "target_passed": bool(target_passed),
        "exam": exam_suggestion or {},
    }
    return target_minutes, rest_day, allocation, basis


def build_allocation_views(
    *,
    hub: dict,
    exam_suggestion: dict | None,
    planned: dict[str, int],
    completed: dict[str, int],
    adjusted: dict[str, int],
    availability: dict[str, bool],
) -> list[dict]:
    hub_tasks = {
        category: task_by_type(hub, task_type)
        for category, task_type in HUB_TASK_TYPES.items()
    }
    return [
        _allocation_entry(
            category,
            task=hub_tasks.get(category),
            exam_suggestion=exam_suggestion,
            planned=planned,
            completed=completed,
            adjusted=adjusted,
            availability=availability,
        )
        for category in CATEGORIES
    ]


def _allocation_entry(
    category: str,
    *,
    task: dict | None,
    exam_suggestion: dict | None,
    planned: dict[str, int],
    completed: dict[str, int],
    adjusted: dict[str, int],
    availability: dict[str, bool],
) -> dict:
    planned_minutes = max(0, int(planned.get(category) or 0))
    completed_minutes = max(0, int(completed.get(category) or 0))
    adjusted_minutes = max(0, int(adjusted.get(category) or 0))
    available = bool(availability.get(category, False))
    route, route_params, action_label, estimated = _allocation_route(
        category,
        task=task,
        exam_suggestion=exam_suggestion,
        available=available,
    )
    title, reason = _allocation_copy(
        category,
        task=task,
        exam_suggestion=exam_suggestion,
        adjusted_minutes=adjusted_minutes,
        available=available,
    )
    return {
        "category": category,
        "title": title,
        "reason": reason,
        "planned_minutes": planned_minutes,
        "completed_minutes": completed_minutes,
        "remaining_minutes": max(0, planned_minutes - completed_minutes),
        "adjusted_minutes": adjusted_minutes,
        "status": _allocation_status(
            adjusted_minutes=adjusted_minutes,
            completed_minutes=completed_minutes,
            planned_minutes=planned_minutes,
            available=available,
        ),
        "action_label": action_label,
        "route": route,
        "route_params": route_params,
        "estimated_question_count": estimated,
    }


def _allocation_route(
    category: str,
    *,
    task: dict | None,
    exam_suggestion: dict | None,
    available: bool,
) -> tuple[str | None, dict, str, int]:
    if task and available:
        return (
            task.get("route"),
            dict(task.get("route_params") or {}),
            str(task.get("action_label") or "开始"),
            max(0, int(task.get("estimated_question_count") or 0)),
        )
    if category == "exam" and exam_suggestion and available:
        return (
            "exam_list",
            {"suggested_paper_id": int(exam_suggestion["paper_id"])},
            "去做选择题套卷",
            int(exam_suggestion.get("question_count") or 0),
        )
    return None, {}, "", 0


def _allocation_copy(
    category: str,
    *,
    task: dict | None,
    exam_suggestion: dict | None,
    adjusted_minutes: int,
    available: bool,
) -> tuple[str, str]:
    if category == "review":
        title = str(task.get("title")) if task else "今日到期复习已清空"
        reason = (
            str(task.get("reason"))
            if task
            else "当前没有到期复习，原计划中的剩余时间会自动转给其他可执行任务。"
        )
    elif category == "weakness":
        title = str(task.get("title")) if task else "当前没有需要优先强化的弱项"
        reason = (
            str(task.get("reason"))
            if task
            else "掌握状态暂未识别出可训练弱项，这部分时间会动态转给新题或真题。"
        )
    elif category == "new":
        title = str(task.get("title")) if task else "继续新题推进"
        reason = (
            str(task.get("reason"))
            if task
            else "用新题持续扩展知识边界并刷新推荐状态。"
        )
    else:
        title = exam_suggestion["title"] if exam_suggestion else "暂无可用选择题套卷"
        if exam_suggestion:
            reason = (
                f"建议套卷约 {exam_suggestion['question_count']} 题 / "
                f"{exam_suggestion['estimated_minutes']} 分钟；交卷后成绩会继续进入学习诊断。"
            )
        else:
            reason = "当前没有已发布且可用的选择题真题/模拟卷，这部分时间会自动转给其他任务。"

    if adjusted_minutes > 0 and available:
        reason = f"动态调整后今天建议投入约 {adjusted_minutes} 分钟。{reason}"
    return title, reason


def _allocation_status(
    *,
    adjusted_minutes: int,
    completed_minutes: int,
    planned_minutes: int,
    available: bool,
) -> str:
    if adjusted_minutes <= 0 and completed_minutes >= planned_minutes and planned_minutes > 0:
        return "done"
    if available:
        return "available"
    return "unavailable"
