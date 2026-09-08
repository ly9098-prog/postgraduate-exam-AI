"""408 long-horizon study planning service.

The planner coordinates existing learning facts instead of inventing a second
completion system. Configuration + daily allocation snapshots live here;
completion is projected from ReviewRecord / PracticeSession / ExamAttempt.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import EXAM408_ALL_CODES, EXAM408_CORE_CODES
from app.core.time_utils import (
    shanghai_date_for_utc,
    shanghai_date_utc_range,
    shanghai_today,
)
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAttempt
from app.models.pomodoro import PomodoroSession
from app.models.practice_session import PracticeSession
from app.models.review_scheduler import ReviewRecord
from app.models.study_plan import StudyPlan, StudyPlanDay
from app.schemas.study_plan import StudyPlanUpsertRequest

CATEGORIES = ("review", "weakness", "new", "exam")
PRIORITY_LABELS = {
    "balanced": "均衡推进",
    "review": "记忆复习优先",
    "weakness": "薄弱点优先",
    "new": "新知识推进优先",
    "exam": "真题检测优先",
}


def _phase_for_days(days_remaining: int) -> tuple[str, str]:
    if days_remaining <= 0:
        return "target_day", "目标日"
    if days_remaining <= 45:
        return "sprint", "冲刺阶段"
    if days_remaining <= 180:
        return "steady", "强化阶段"
    return "foundation", "基础阶段"


def _allocate_integer(total: int, weights: dict[str, float]) -> dict[str, int]:
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


def _category_availability(hub: dict, exam_suggestion: dict | None) -> dict[str, bool]:
    task_types = {str(task.get("task_type")) for task in (hub.get("tasks") or []) if task}
    return {
        "review": "review" in task_types,
        "weakness": "weakness" in task_types,
        "new": bool(hub.get("scope_ready", True)) and "smart_practice" in task_types,
        "exam": exam_suggestion is not None,
    }


def _build_weights(
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


def _ceil_minutes(seconds: int | float | None) -> int:
    value = max(0, int(seconds or 0))
    return (value + 59) // 60 if value else 0


def _plan_select(db: AsyncSession, user_id: int, *, lock: bool = False):
    stmt = select(StudyPlan).where(StudyPlan.user_id == user_id)
    bind = db.get_bind()
    if lock and bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return stmt


async def _get_user_plan(
    db: AsyncSession,
    user_id: int,
    *,
    lock: bool = False,
) -> StudyPlan | None:
    return await db.scalar(_plan_select(db, user_id, lock=lock))


async def _load_scope_ids(db: AsyncSession) -> tuple[list[int], list[int]]:
    rows = (await db.execute(
        select(Subject.id, Subject.code).where(Subject.code.in_(EXAM408_ALL_CODES))
    )).all()
    all_ids = [int(row.id) for row in rows]
    core_ids = [int(row.id) for row in rows if str(row.code) in EXAM408_CORE_CODES]
    return all_ids, core_ids


async def _load_exam_suggestion(db: AsyncSession, user_id: int) -> dict | None:
    # Reuse the public exam list semantics so plan recommendations never expose
    # archived/draft papers or compute a different attempt status projection.
    from app.services import exam_service

    papers = await exam_service.list_published_papers(db, user_id)
    if not papers:
        return None
    unfinished = [
        paper for paper in papers
        if paper.get("latest_attempt_status") not in {"submitted", "expired"}
    ]
    paper = unfinished[0] if unfinished else papers[0]
    question_count = max(0, int(paper.get("question_count") or 0))
    duration_sec = int(paper.get("duration_sec") or 0)
    estimated_minutes = _ceil_minutes(duration_sec) if duration_sec > 0 else max(15, _ceil_minutes(question_count * 90))
    return {
        "paper_id": int(paper["id"]),
        "title": str(paper.get("title") or "408 选择题套卷"),
        "year": paper.get("year"),
        "question_count": question_count,
        "estimated_minutes": estimated_minutes,
        "latest_attempt_status": paper.get("latest_attempt_status"),
    }


async def _load_activity_dates(
    db: AsyncSession,
    user_id: int,
    *,
    start_date: date,
    end_date: date,
    all_408_ids: list[int],
    core_408_ids: list[int],
) -> set[date]:
    if end_date < start_date:
        return set()
    start_utc = shanghai_date_utc_range(start_date)[0]
    end_utc = shanghai_date_utc_range(end_date + timedelta(days=1))[0]
    timestamps = []

    if all_408_ids:
        timestamps.extend((await db.scalars(
            select(PracticeSession.finished_at).where(
                PracticeSession.user_id == user_id,
                PracticeSession.subject_id.in_(all_408_ids),
                PracticeSession.finished_at >= start_utc,
                PracticeSession.finished_at < end_utc,
            )
        )).all())
        timestamps.extend((await db.scalars(
            select(PomodoroSession.end_time).where(
                PomodoroSession.user_id == user_id,
                PomodoroSession.subject_id.in_(all_408_ids),
                PomodoroSession.status == "completed",
                PomodoroSession.end_time.is_not(None),
                PomodoroSession.end_time >= start_utc,
                PomodoroSession.end_time < end_utc,
            )
        )).all())

    if core_408_ids:
        timestamps.extend((await db.scalars(
            select(ReviewRecord.reviewed_at)
            .join(QuestionVersion, QuestionVersion.id == ReviewRecord.question_version_id)
            .where(
                ReviewRecord.user_id == user_id,
                QuestionVersion.subject_id.in_(core_408_ids),
                ReviewRecord.reviewed_at >= start_utc,
                ReviewRecord.reviewed_at < end_utc,
            )
        )).all())

    timestamps.extend((await db.scalars(
        select(ExamAttempt.submitted_at).where(
            ExamAttempt.user_id == user_id,
            ExamAttempt.submitted_at.is_not(None),
            ExamAttempt.submitted_at >= start_utc,
            ExamAttempt.submitted_at < end_utc,
            ExamAttempt.status.in_(("submitted", "expired")),
        )
    )).all())

    return {
        shanghai_date_for_utc(value)
        for value in timestamps
        if value is not None
    }


async def _today_completion(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    planned: dict[str, int],
    all_408_ids: list[int],
    core_408_ids: list[int],
) -> tuple[dict[str, int], int]:
    start_utc, end_utc = shanghai_date_utc_range(today)

    review_count = 0
    if core_408_ids:
        review_count = int((await db.execute(
            select(func.count(ReviewRecord.id))
            .join(QuestionVersion, QuestionVersion.id == ReviewRecord.question_version_id)
            .where(
                ReviewRecord.user_id == user_id,
                QuestionVersion.subject_id.in_(core_408_ids),
                ReviewRecord.reviewed_at >= start_utc,
                ReviewRecord.reviewed_at < end_utc,
            )
        )).scalar_one() or 0)

    session_rows = []
    if all_408_ids:
        session_rows = (await db.execute(
            select(PracticeSession.mode, PracticeSession.duration_sec).where(
                PracticeSession.user_id == user_id,
                PracticeSession.subject_id.in_(all_408_ids),
                PracticeSession.finished_at >= start_utc,
                PracticeSession.finished_at < end_utc,
                PracticeSession.status == "completed",
            )
        )).all()

    smart_sec = sum(int(row.duration_sec or 0) for row in session_rows if str(row.mode or "") == "smart")
    other_sec = sum(int(row.duration_sec or 0) for row in session_rows if str(row.mode or "") != "smart")
    smart_minutes = _ceil_minutes(smart_sec)
    other_minutes = _ceil_minutes(other_sec)

    exam_sec = int((await db.execute(
        select(func.coalesce(func.sum(ExamAttempt.duration_sec), 0)).where(
            ExamAttempt.user_id == user_id,
            ExamAttempt.submitted_at.is_not(None),
            ExamAttempt.submitted_at >= start_utc,
            ExamAttempt.submitted_at < end_utc,
            ExamAttempt.status.in_(("submitted", "expired")),
        )
    )).scalar_one() or 0)

    focus_sec = 0
    if all_408_ids:
        focus_sec = int((await db.execute(
            select(func.coalesce(func.sum(PomodoroSession.actual_duration), 0)).where(
                PomodoroSession.user_id == user_id,
                PomodoroSession.subject_id.in_(all_408_ids),
                PomodoroSession.status == "completed",
                PomodoroSession.end_time.is_not(None),
                PomodoroSession.end_time >= start_utc,
                PomodoroSession.end_time < end_utc,
            )
        )).scalar_one() or 0)

    completed = {category: 0 for category in CATEGORIES}
    # Review runner has no server-side elapsed timer. Keep the same 2 questions /
    # minute estimate used by review_scheduler.get_today_review_overview().
    completed["review"] = (review_count + 1) // 2 if review_count else 0
    completed["exam"] = _ceil_minutes(exam_sec)
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
            split = _allocate_integer(
                other_minutes,
                {"weakness": float(weak_planned), "new": float(new_planned)},
            )
            completed["weakness"] += split["weakness"]
            completed["new"] += split["new"]

    return completed, _ceil_minutes(focus_sec)


def _task_by_type(hub: dict, task_type: str) -> dict | None:
    return next(
        (task for task in (hub.get("tasks") or []) if task and task.get("task_type") == task_type),
        None,
    )


def _build_snapshot_payload(
    *,
    plan: StudyPlan,
    today: date,
    hub: dict,
    exam_suggestion: dict | None,
    prior_active_days: int,
) -> tuple[int, bool, dict[str, int], dict]:
    days_remaining_raw = (plan.target_date - today).days
    phase, _ = _phase_for_days(max(0, days_remaining_raw))
    availability = _category_availability(hub, exam_suggestion)

    target_passed = days_remaining_raw < 0
    rest_day = (
        not target_passed
        and today != plan.target_date
        and prior_active_days >= int(plan.weekly_days)
    )
    target_minutes = 0 if target_passed or rest_day else int(plan.daily_minutes)
    weights = _build_weights(
        phase=phase,
        priority_mode=str(plan.priority_mode),
        availability=availability,
    )
    allocation = _allocate_integer(target_minutes, weights)
    basis = {
        "phase": phase,
        "priority_mode": str(plan.priority_mode),
        "priority_label": PRIORITY_LABELS.get(str(plan.priority_mode), "均衡推进"),
        "availability": availability,
        "weights": {key: round(float(value), 4) for key, value in weights.items()},
        "prior_active_days": int(prior_active_days),
        "target_passed": bool(target_passed),
        "exam": exam_suggestion or {},
    }
    return target_minutes, rest_day, allocation, basis


async def _ensure_day_snapshot(
    db: AsyncSession,
    *,
    plan: StudyPlan,
    today: date,
    hub: dict,
    exam_suggestion: dict | None,
    prior_active_days: int,
) -> StudyPlanDay:
    day_stmt = select(StudyPlanDay).where(
        StudyPlanDay.plan_id == int(plan.id),
        StudyPlanDay.plan_date == today,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        day_stmt = day_stmt.with_for_update()
    row = await db.scalar(day_stmt)
    if row is not None and int(row.plan_revision) == int(plan.revision):
        return row

    target_minutes, rest_day, allocation, basis = _build_snapshot_payload(
        plan=plan,
        today=today,
        hub=hub,
        exam_suggestion=exam_suggestion,
        prior_active_days=prior_active_days,
    )
    if row is not None:
        row.plan_revision = int(plan.revision)
        row.target_minutes = target_minutes
        row.is_rest_day = rest_day
        row.allocation_json = allocation
        row.basis_json = basis
        await db.commit()
        return row

    row = StudyPlanDay(
        plan_id=int(plan.id),
        plan_revision=int(plan.revision),
        plan_date=today,
        target_minutes=target_minutes,
        is_rest_day=rest_day,
        allocation_json=allocation,
        basis_json=basis,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        await db.commit()
        return row
    except IntegrityError:
        # Two devices may materialize the same day's snapshot concurrently. The
        # unique(plan_id, plan_date) constraint is authoritative; reload winner.
        await db.rollback()
        winner = await db.scalar(
            select(StudyPlanDay).where(
                StudyPlanDay.plan_id == int(plan.id),
                StudyPlanDay.plan_date == today,
            )
        )
        if winner is None:
            raise
        return winner


def _dynamic_remaining(
    *,
    target_minutes: int,
    planned: dict[str, int],
    completed: dict[str, int],
    current_weights: dict[str, float],
    availability: dict[str, bool],
) -> dict[str, int]:
    completed_total = min(
        max(0, int(target_minutes)),
        sum(max(0, int(completed.get(category) or 0)) for category in CATEGORIES),
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
        need_weights[category] = float(current_weights.get(category, 0.0)) * (0.25 + 0.75 * need_ratio)
    return _allocate_integer(budget, need_weights)


def _build_allocation_views(
    *,
    hub: dict,
    exam_suggestion: dict | None,
    planned: dict[str, int],
    completed: dict[str, int],
    adjusted: dict[str, int],
    availability: dict[str, bool],
) -> list[dict]:
    hub_tasks = {
        "review": _task_by_type(hub, "review"),
        "weakness": _task_by_type(hub, "weakness"),
        "new": _task_by_type(hub, "smart_practice"),
    }
    result: list[dict] = []
    for category in CATEGORIES:
        planned_minutes = max(0, int(planned.get(category) or 0))
        completed_minutes = max(0, int(completed.get(category) or 0))
        remaining_minutes = max(0, planned_minutes - completed_minutes)
        adjusted_minutes = max(0, int(adjusted.get(category) or 0))
        available = bool(availability.get(category, False))

        task = hub_tasks.get(category)
        route = None
        route_params: dict = {}
        action_label = ""
        estimated_question_count = 0
        if task and available:
            route = task.get("route")
            route_params = dict(task.get("route_params") or {})
            action_label = str(task.get("action_label") or "开始")
            estimated_question_count = max(0, int(task.get("estimated_question_count") or 0))
        elif category == "exam" and exam_suggestion and available:
            route = "exam_list"
            route_params = {"suggested_paper_id": int(exam_suggestion["paper_id"])}
            action_label = "去做选择题套卷"
            estimated_question_count = int(exam_suggestion.get("question_count") or 0)

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
            title = str(task.get("title")) if task else "继续 408 新题推进"
            reason = str(task.get("reason")) if task else "用新题持续扩展知识边界并刷新推荐状态。"
        else:
            title = exam_suggestion["title"] if exam_suggestion else "暂无可用 408 选择题套卷"
            if exam_suggestion:
                reason = (
                    f"建议套卷约 {exam_suggestion['question_count']} 题 / "
                    f"{exam_suggestion['estimated_minutes']} 分钟；交卷后成绩会继续进入学习诊断。"
                )
            else:
                reason = "当前没有已发布且可用的 408 选择题真题/模拟卷，这部分时间会自动转给其他任务。"

        if adjusted_minutes > 0 and available:
            reason = f"动态调整后今天建议投入约 {adjusted_minutes} 分钟。{reason}"

        if adjusted_minutes <= 0 and completed_minutes >= planned_minutes and planned_minutes > 0:
            status = "done"
        elif available:
            status = "available"
        else:
            status = "unavailable"

        result.append({
            "category": category,
            "title": title,
            "reason": reason,
            "planned_minutes": planned_minutes,
            "completed_minutes": completed_minutes,
            "remaining_minutes": remaining_minutes,
            "adjusted_minutes": adjusted_minutes,
            "status": status,
            "action_label": action_label,
            "route": route,
            "route_params": route_params,
            "estimated_question_count": estimated_question_count,
        })
    return result


async def upsert_study_plan(
    db: AsyncSession,
    user_id: int,
    data: StudyPlanUpsertRequest,
) -> StudyPlan:
    today = shanghai_today()
    if data.target_date < today:
        raise ValueError("目标日期不能早于今天")

    # Serialize updates for an existing plan so revision increments cannot be
    # lost when two devices save settings at nearly the same time. PostgreSQL
    # uses a row lock; SQLite still relies on the unique user constraint below.
    plan = await _get_user_plan(db, user_id, lock=True)
    created = False
    if plan is None:
        candidate = StudyPlan(
            user_id=user_id,
            target_date=data.target_date,
            daily_minutes=int(data.daily_minutes),
            weekly_days=int(data.weekly_days),
            priority_mode=str(data.priority_mode),
            revision=1,
            is_active=True,
        )
        try:
            # A savepoint keeps the outer request transaction usable if another
            # device wins the first-create race on uq_study_plans_user.
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            plan = candidate
            created = True
        except IntegrityError:
            plan = await _get_user_plan(db, user_id, lock=True)
            if plan is None:
                raise

    if not created:
        changed = any((
            plan.target_date != data.target_date,
            int(plan.daily_minutes) != int(data.daily_minutes),
            int(plan.weekly_days) != int(data.weekly_days),
            str(plan.priority_mode) != str(data.priority_mode),
            not bool(plan.is_active),
        ))
        plan.target_date = data.target_date
        plan.daily_minutes = int(data.daily_minutes)
        plan.weekly_days = int(data.weekly_days)
        plan.priority_mode = str(data.priority_mode)
        plan.is_active = True
        if changed:
            plan.revision = int(plan.revision or 1) + 1

    await db.commit()
    await db.refresh(plan)
    return plan


async def deactivate_study_plan(db: AsyncSession, user_id: int) -> None:
    plan = await _get_user_plan(db, user_id, lock=True)
    if plan is None or not plan.is_active:
        return
    plan.is_active = False
    plan.revision = int(plan.revision or 1) + 1
    await db.commit()


async def get_study_plan_overview(db: AsyncSession, user_id: int) -> dict:
    today = shanghai_today()
    plan = await db.scalar(
        select(StudyPlan).where(
            StudyPlan.user_id == user_id,
            StudyPlan.is_active.is_(True),
        )
    )
    if plan is None:
        return {
            "configured": False,
            "date": today,
            "suggested_defaults": {
                "daily_minutes": 90,
                "weekly_days": 6,
                "priority_mode": "balanced",
            },
        }

    from app.services import study_hub_service

    hub = await study_hub_service.get_study_hub_overview(db, user_id)
    exam_suggestion = await _load_exam_suggestion(db, user_id)
    all_408_ids, core_408_ids = await _load_scope_ids(db)

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    prior_dates = await _load_activity_dates(
        db,
        user_id,
        start_date=week_start,
        end_date=today - timedelta(days=1),
        all_408_ids=all_408_ids,
        core_408_ids=core_408_ids,
    )

    # Hub/exam aggregation above can take long enough for another device to save
    # new plan settings. Re-read and lock the plan before materializing today's
    # snapshot so an older overview request can never overwrite a newer
    # plan_revision with stale allocation data.
    latest_plan = await _get_user_plan(db, user_id, lock=True)
    if latest_plan is None or not latest_plan.is_active:
        await db.rollback()
        return {
            "configured": False,
            "date": today,
            "suggested_defaults": {
                "daily_minutes": 90,
                "weekly_days": 6,
                "priority_mode": "balanced",
            },
        }
    plan = latest_plan
    day = await _ensure_day_snapshot(
        db,
        plan=plan,
        today=today,
        hub=hub,
        exam_suggestion=exam_suggestion,
        prior_active_days=len(prior_dates),
    )
    # _ensure_day_snapshot may return an already-current row without committing;
    # release the plan row lock before the remaining read-only aggregation.
    await db.commit()

    planned = {category: int((day.allocation_json or {}).get(category) or 0) for category in CATEGORIES}
    completed, focus_minutes = await _today_completion(
        db,
        user_id,
        today=today,
        planned=planned,
        all_408_ids=all_408_ids,
        core_408_ids=core_408_ids,
    )
    current_availability = _category_availability(hub, exam_suggestion)
    days_remaining_raw = (plan.target_date - today).days
    days_remaining = max(0, days_remaining_raw)
    phase, phase_label = _phase_for_days(days_remaining)
    current_weights = _build_weights(
        phase=phase,
        priority_mode=str(plan.priority_mode),
        availability=current_availability,
    )
    adjusted = _dynamic_remaining(
        target_minutes=int(day.target_minutes),
        planned=planned,
        completed=completed,
        current_weights=current_weights,
        availability=current_availability,
    )
    allocations = _build_allocation_views(
        hub=hub,
        exam_suggestion=exam_suggestion,
        planned=planned,
        completed=completed,
        adjusted=adjusted,
        availability=current_availability,
    )

    completed_total = min(
        int(day.target_minutes),
        sum(max(0, int(completed.get(category) or 0)) for category in CATEGORIES),
    )
    remaining_total = max(0, int(day.target_minutes) - completed_total)
    completion_percent = (
        100 if int(day.target_minutes) <= 0
        else min(100, round(completed_total / int(day.target_minutes) * 100))
    )
    primary = next(
        (
            item["category"]
            for item in sorted(
                allocations,
                key=lambda item: (-int(item["adjusted_minutes"]), CATEGORIES.index(item["category"])),
            )
            if int(item["adjusted_minutes"]) > 0 and item["status"] == "available"
        ),
        None,
    )

    active_dates = set(prior_dates)
    actual_activity_minutes = sum(max(0, int(completed.get(category) or 0)) for category in CATEGORIES)
    if actual_activity_minutes > 0 or focus_minutes > 0:
        active_dates.add(today)
    active_days = len(active_dates)

    plan_payload = {
        "id": int(plan.id),
        "target_date": plan.target_date,
        "daily_minutes": int(plan.daily_minutes),
        "weekly_days": int(plan.weekly_days),
        "priority_mode": str(plan.priority_mode),
        "revision": int(plan.revision),
        "is_active": bool(plan.is_active),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }
    if days_remaining_raw < 0:
        phase_label = "目标日已过，请更新计划"
    elif days_remaining_raw == 0:
        phase_label = "目标日"

    return {
        "configured": True,
        "date": today,
        "plan": plan_payload,
        "countdown": {
            "target_date": plan.target_date,
            "days_remaining": days_remaining,
            "phase": phase,
            "phase_label": phase_label,
        },
        "weekly": {
            "week_start": week_start,
            "week_end": week_end,
            "target_days": int(plan.weekly_days),
            "active_days": active_days,
            "remaining_days": max(0, int(plan.weekly_days) - active_days),
            "target_met": active_days >= int(plan.weekly_days),
        },
        "today": {
            "date": today,
            "target_minutes": int(day.target_minutes),
            "completed_minutes": completed_total,
            "remaining_minutes": remaining_total,
            "focus_minutes": focus_minutes,
            "is_rest_day": bool(day.is_rest_day),
            "completion_percent": completion_percent,
            "primary_category": primary,
            "allocations": allocations,
        },
        "suggested_defaults": {
            "daily_minutes": 90,
            "weekly_days": 6,
            "priority_mode": "balanced",
        },
    }
