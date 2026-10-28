"""Pure study-plan rules for phases, allocation and dynamic remaining budget.

This module owns the deterministic planning arithmetic. It performs no database
or network access so the rules can be tested without an application session.
"""

from __future__ import annotations

import math
from datetime import date

from app.services.pomodoro_attribution import split_duration_excluding_intervals

CATEGORIES = ("review", "weakness", "new", "exam")
PRIORITY_LABELS = {
    "balanced": "均衡推进",
    "review": "记忆复习优先",
    "weakness": "薄弱点优先",
    "new": "新知识推进优先",
    "exam": "真题检测优先",
}


def focus_duration_for_subject_scope(
    session, split: dict, subject_ids: set[int]
) -> int:
    allocations = list(getattr(session, "subject_allocations", []) or [])
    total = 0
    for seconds in split.values():
        if allocations:
            weights = [max(0, int(item.weight_basis_points or 0)) for item in allocations]
            denominator = sum(int(item.weight_basis_points or 0) for item in allocations)
            if denominator <= 0:
                continue
            exact = [seconds * weight / denominator for weight in weights]
            parts = [int(value) for value in exact]
            remainder = seconds - sum(parts)
            order = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
            for index in order[:remainder]:
                parts[index] += 1
            total += sum(
                value
                for item, value in zip(allocations, parts)
                if item.subject_id in subject_ids
            )
        elif session.subject_id in subject_ids:
            total += seconds
    return total


def phase_for_days(days_remaining: int) -> tuple[str, str]:
    if days_remaining <= 0:
        return "target_day", "目标日"
    if days_remaining <= 45:
        return "sprint", "冲刺阶段"
    if days_remaining <= 180:
        return "steady", "强化阶段"
    return "foundation", "基础阶段"


def allocate_integer(total: int, weights: dict[str, float]) -> dict[str, int]:
    total = max(0, int(total or 0))
    result = {category: 0 for category in CATEGORIES}
    positive = {k: max(0.0, float(weights.get(k, 0.0))) for k in CATEGORIES}
    weight_sum = sum(positive.values())
    if total <= 0 or weight_sum <= 0:
        return result

    raw = {k: total * positive[k] / weight_sum for k in CATEGORIES}
    floors = {k: int(math.floor(raw[k])) for k in CATEGORIES}
    remainder = total - sum(floors.values())
    ranked = sorted(
        CATEGORIES,
        key=lambda key: (-(raw[key] - floors[key]), CATEGORIES.index(key)),
    )
    for key in ranked[:remainder]:
        floors[key] += 1
    return floors


def category_availability(hub: dict, exam_suggestion: dict | None) -> dict[str, bool]:
    task_types = {
        str(task.get("task_type")) for task in (hub.get("tasks") or []) if task
    }
    return {
        "review": "review" in task_types,
        "weakness": "weakness" in task_types,
        "new": bool(hub.get("scope_ready", True)) and "smart_practice" in task_types,
        "exam": exam_suggestion is not None,
    }


def build_weights(
    *,
    phase: str,
    priority_mode: str,
    availability: dict[str, bool],
) -> dict[str, float]:
    weights = {"review": 0.28, "weakness": 0.30, "new": 0.27, "exam": 0.15}
    if phase == "foundation":
        weights["new"] += 0.10
        weights["weakness"] += 0.05
        weights["exam"] = max(0.05, weights["exam"] - 0.05)
    elif phase == "steady":
        weights["weakness"] += 0.08
        weights["exam"] += 0.05
    elif phase in {"sprint", "target_day"}:
        weights["exam"] += 0.18
        weights["review"] += 0.05
        weights["new"] = max(0.05, weights["new"] - 0.08)

    if priority_mode in CATEGORIES:
        weights[priority_mode] += 0.18

    for category in CATEGORIES:
        if not availability.get(category, False):
            weights[category] = 0.0
    return weights


def ceil_minutes(seconds: int | float | None) -> int:
    value = max(0, int(seconds or 0))
    return (value + 59) // 60 if value else 0


def study_day_seconds(
    *,
    start,
    end,
    duration_sec: int | None,
    target_day: date,
    day_start_minute: int,
) -> int:
    if start is None or end is None or end <= start:
        return 0
    return int(
        split_duration_excluding_intervals(
            start,
            end,
            max(0, int(duration_sec or 0)),
            [],
            day_start_minute,
        ).get(target_day, 0)
    )


def task_by_type(hub: dict, task_type: str) -> dict | None:
    return next(
        (
            task
            for task in (hub.get("tasks") or [])
            if task and task.get("task_type") == task_type
        ),
        None,
    )


def dynamic_remaining(
    *,
    target_minutes: int,
    planned: dict[str, int],
    completed: dict[str, int],
    extra_completed_minutes: int = 0,
    current_weights: dict[str, float],
    availability: dict[str, bool],
) -> dict[str, int]:
    completed_total = min(
        max(0, int(target_minutes)),
        sum(max(0, int(completed.get(category) or 0)) for category in CATEGORIES)
        + max(0, int(extra_completed_minutes)),
    )
    budget = max(0, int(target_minutes) - completed_total)
    if budget <= 0:
        return {category: 0 for category in CATEGORIES}

    need_weights: dict[str, float] = {}
    for category in CATEGORIES:
        if not availability.get(category, False):
            need_weights[category] = 0.0
            continue
        plan_value = max(0, int(planned.get(category) or 0))
        done_value = max(0, int(completed.get(category) or 0))
        if plan_value > 0:
            need_ratio = max(0.0, min(1.0, (plan_value - done_value) / plan_value))
        else:
            need_ratio = 1.0
        # Keep a small floor for still-available work even when its original
        # bucket is already met; this lets the plan absorb time released by a
        # finished/unavailable category without changing the historical snapshot.
        need_weights[category] = float(current_weights.get(category, 0.0)) * (
            0.25 + 0.75 * need_ratio
        )
    return allocate_integer(budget, need_weights)


def credit_supplemental_focus(
    *,
    completed: dict[str, int],
    target_minutes: int,
    supplement_minutes: int,
) -> int:
    """Return the de-duplicated Pomodoro minutes credited to today's target.

    Pomodoro focus has no durable task-category intent, so it advances only the
    headline time budget instead of being mislabeled as review/weakness/new/exam.
    The credit is capped at the still-unfilled target after authoritative activity
    minutes have been counted.
    """
    direct_total = sum(
        max(0, int(completed.get(category) or 0)) for category in CATEGORIES
    )
    return min(
        max(0, int(supplement_minutes)),
        max(0, int(target_minutes) - direct_total),
    )


def completed_by_category(
    *,
    review_count: int,
    smart_minutes: int,
    exam_minutes: int,
    other_minutes: int,
    planned: dict[str, int],
) -> dict[str, int]:
    completed = {category: 0 for category in CATEGORIES}
    # Review runner has no server-side elapsed timer. Keep the same 2 questions /
    # minute estimate used by review_scheduler.get_today_review_overview().
    completed["review"] = (review_count + 1) // 2 if review_count else 0
    completed["exam"] = exam_minutes
    completed["new"] = smart_minutes

    # Non-smart practice may be weak-point training or free/random training. There
    # is no durable source tag on PracticeSession, so distribute it according to
    # the stable daily weak/new plan instead of pretending we know exact intent.
    weak_planned = max(0, int(planned.get("weakness") or 0))
    new_planned = max(0, int(planned.get("new") or 0))
    if other_minutes > 0:
        if weak_planned <= 0:
            completed["new"] += other_minutes
        elif new_planned <= 0:
            completed["weakness"] += other_minutes
        else:
            split = allocate_integer(
                other_minutes,
                {"weakness": float(weak_planned), "new": float(new_planned)},
            )
            completed["weakness"] += split["weakness"]
            completed["new"] += split["new"]
    return completed
