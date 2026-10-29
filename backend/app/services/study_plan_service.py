"""408 long-horizon study planning service.

The planner coordinates existing learning facts instead of inventing a second
completion system. Configuration + daily allocation snapshots live here;
completion is projected from ReviewRecord / PracticeSession / ExamAttempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import (
    or_,  # noqa: F401
    select,
)
from sqlalchemy.exc import IntegrityError  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # noqa: F401

from app.core.subject_scope import EXAM408_ALL_CODES, EXAM408_CORE_CODES
from app.core.time_utils import (
    current_study_day,
    shanghai_today,  # noqa: F401 -- live request dependency port
    study_day_for_utc,  # noqa: F401 -- live request dependency port
    study_day_utc_range,  # noqa: F401 -- live request dependency port
)
from app.models.admin import QuestionVersion, Subject  # noqa: F401
from app.models.exam import ExamAttempt  # noqa: F401
from app.models.pomodoro import (
    PomodoroSession,  # noqa: F401
    PomodoroSubjectAllocation,  # noqa: F401
    UserPomodoroSettings,
)
from app.models.practice_session import PracticeSession  # noqa: F401
from app.models.review_scheduler import ReviewRecord  # noqa: F401
from app.models.study_plan import StudyPlan, StudyPlanDay
from app.schemas.study_plan import StudyPlanUpsertRequest
from app.services import study_plan_activity as _activity
from app.services import study_plan_request as _request
from app.services.pomodoro_attribution import (
    split_duration_excluding_intervals,  # noqa: F401
    split_session_duration_by_study_day,  # noqa: F401
)
from app.services.study_plan_completion import load_today_completion
from app.services.study_plan_rules import (
    CATEGORIES,
    allocate_integer,
    build_weights,
    category_availability,
    ceil_minutes,
    credit_supplemental_focus,
    dynamic_remaining,
    focus_duration_for_subject_scope,
    phase_for_days,
    study_day_seconds,
)
from app.services.study_plan_views import (
    build_allocation_views,
    build_snapshot_payload,
    task_by_type,
)
from app.services.unique_conflict import (
    is_unique_violation as _is_unique_violation,  # noqa: F401
)
from app.services.unique_conflict import (
    start_explicit_transaction as _start_explicit_transaction,  # noqa: F401
)

# Underscore aliases keep the historical private names importable by tests and
# existing call sites while the single definition lives in study_plan_rules.
_allocate_integer = allocate_integer
_build_weights = build_weights
_category_availability = category_availability
_ceil_minutes = ceil_minutes
_credit_supplemental_focus = credit_supplemental_focus
_dynamic_remaining = dynamic_remaining
_focus_duration_for_subject_scope = focus_duration_for_subject_scope
_study_day_seconds = study_day_seconds
_phase_for_days = phase_for_days
_task_by_type = task_by_type
_build_allocation_views = build_allocation_views
_build_snapshot_payload = build_snapshot_payload


def _study_plan_request_port(name):
    """Resolve historical service names when the request uses them."""
    return globals()[name]


async def _load_day_start_minute(db: AsyncSession, user_id: int) -> int:
    value = await db.scalar(
        select(UserPomodoroSettings.day_start_minute).where(
            UserPomodoroSettings.user_id == user_id
        )
    )
    return max(0, min(1439, int(value or 0)))


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
    rows = (
        await db.execute(
            select(Subject.id, Subject.code).where(Subject.code.in_(EXAM408_ALL_CODES))
        )
    ).all()
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
        paper
        for paper in papers
        if paper.get("latest_attempt_status") not in {"submitted", "expired"}
    ]
    paper = unfinished[0] if unfinished else papers[0]
    question_count = max(0, int(paper.get("question_count") or 0))
    duration_sec = int(paper.get("duration_sec") or 0)
    estimated_minutes = (
        _ceil_minutes(duration_sec)
        if duration_sec > 0
        else max(15, _ceil_minutes(question_count * 90))
    )
    return {
        "paper_id": int(paper["id"]),
        "title": str(paper.get("title") or "选择题套卷"),
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
    day_start_minute: int,
) -> set[date]:
    return await _activity._load_activity_dates(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        all_408_ids=all_408_ids,
        core_408_ids=core_408_ids,
        day_start_minute=day_start_minute,
        ports=_study_plan_request_port,
    )


async def _ensure_day_snapshot(
    db: AsyncSession,
    *,
    plan: StudyPlan,
    today: date,
    hub: dict,
    exam_suggestion: dict | None,
    prior_active_days: int,
    day_start_minute: int,
) -> StudyPlanDay:
    return await _request._ensure_day_snapshot(
        db,
        plan=plan,
        today=today,
        hub=hub,
        exam_suggestion=exam_suggestion,
        prior_active_days=prior_active_days,
        day_start_minute=day_start_minute,
        ports=_study_plan_request_port,
    )


async def upsert_study_plan(
    db: AsyncSession,
    user_id: int,
    data: StudyPlanUpsertRequest,
) -> StudyPlan:
    return await _request.upsert_study_plan(
        db, user_id, data, ports=_study_plan_request_port
    )


async def deactivate_study_plan(db: AsyncSession, user_id: int) -> None:
    await _request.deactivate_study_plan(db, user_id, ports=_study_plan_request_port)


@dataclass(slots=True)
class _OverviewInputs:
    hub: dict
    exam_suggestion: dict | None
    all_408_ids: list[int]
    core_408_ids: list[int]
    prior_dates: set[date]
    week_start: date
    week_end: date


@dataclass(slots=True)
class _OverviewFacts:
    planned: dict[str, int]
    completed: dict[str, int]
    focus_minutes: int
    supplemented_focus_minutes: int
    credited_focus_minutes: int


@dataclass(slots=True)
class _OverviewTotals:
    availability: dict[str, bool]
    adjusted: dict[str, int]
    allocations: list[dict]
    completed_total: int
    remaining_total: int
    completion_percent: int
    primary_category: str | None
    active_days: int
    days_remaining: int
    days_remaining_raw: int
    phase: str
    phase_label: str


async def _today_completion(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    planned: dict[str, int],
    all_408_ids: list[int],
    core_408_ids: list[int],
    day_start_minute: int,
) -> tuple[dict[str, int], int, int]:
    return await load_today_completion(
        db,
        user_id,
        today=today,
        planned=planned,
        all_408_ids=all_408_ids,
        core_408_ids=core_408_ids,
        day_start_minute=day_start_minute,
    )


def _unconfigured_overview(today: date) -> dict:
    return {
        "configured": False,
        "date": today,
        "suggested_defaults": {
            "daily_minutes": 90,
            "weekly_days": 6,
            "priority_mode": "balanced",
        },
    }


async def _load_active_plan(db: AsyncSession, user_id: int) -> StudyPlan | None:
    return await db.scalar(
        select(StudyPlan).where(
            StudyPlan.user_id == user_id,
            StudyPlan.is_active.is_(True),
        )
    )


async def _load_overview_inputs(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    day_start_minute: int,
) -> _OverviewInputs:
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
        day_start_minute=day_start_minute,
    )
    return _OverviewInputs(
        hub=hub,
        exam_suggestion=exam_suggestion,
        all_408_ids=all_408_ids,
        core_408_ids=core_408_ids,
        prior_dates=prior_dates,
        week_start=week_start,
        week_end=week_end,
    )


async def _materialize_overview_day(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    day_start_minute: int,
    inputs: _OverviewInputs,
) -> tuple[StudyPlan | None, StudyPlanDay | None]:
    # Hub/exam aggregation above can take long enough for another device to save
    # new plan settings. Re-read and lock the plan before materializing today's
    # snapshot so an older overview request can never overwrite a newer
    # plan_revision with stale allocation data.
    latest_plan = await _get_user_plan(db, user_id, lock=True)
    if latest_plan is None or not latest_plan.is_active:
        await db.rollback()
        return None, None
    day = await _ensure_day_snapshot(
        db,
        plan=latest_plan,
        today=today,
        hub=inputs.hub,
        exam_suggestion=inputs.exam_suggestion,
        prior_active_days=len(inputs.prior_dates),
        day_start_minute=day_start_minute,
    )
    # _ensure_day_snapshot may return an already-current row without committing;
    # release the plan row lock before the remaining read-only aggregation.
    await db.commit()
    return latest_plan, day


async def _load_overview_facts(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    day: StudyPlanDay,
    inputs: _OverviewInputs,
    day_start_minute: int,
) -> _OverviewFacts:
    planned = {
        category: int((day.allocation_json or {}).get(category) or 0)
        for category in CATEGORIES
    }
    completed, focus_minutes, supplemental_focus_minutes = await _today_completion(
        db,
        user_id,
        today=today,
        planned=planned,
        all_408_ids=inputs.all_408_ids,
        core_408_ids=inputs.core_408_ids,
        day_start_minute=day_start_minute,
    )
    credited_focus_minutes = _credit_supplemental_focus(
        completed=completed,
        target_minutes=int(day.target_minutes),
        supplement_minutes=supplemental_focus_minutes,
    )
    return _OverviewFacts(
        planned=planned,
        completed=completed,
        focus_minutes=focus_minutes,
        supplemented_focus_minutes=supplemental_focus_minutes,
        credited_focus_minutes=credited_focus_minutes,
    )


def _overview_totals(
    *,
    plan: StudyPlan,
    today: date,
    day: StudyPlanDay,
    inputs: _OverviewInputs,
    facts: _OverviewFacts,
) -> _OverviewTotals:
    availability = _category_availability(inputs.hub, inputs.exam_suggestion)
    days_remaining_raw = (plan.target_date - today).days
    days_remaining = max(0, days_remaining_raw)
    phase, phase_label = _phase_for_days(days_remaining)
    current_weights = _build_weights(
        phase=phase,
        priority_mode=str(plan.priority_mode),
        availability=availability,
    )
    adjusted = _dynamic_remaining(
        target_minutes=int(day.target_minutes),
        planned=facts.planned,
        completed=facts.completed,
        extra_completed_minutes=facts.credited_focus_minutes,
        current_weights=current_weights,
        availability=availability,
    )
    allocations = _build_allocation_views(
        hub=inputs.hub,
        exam_suggestion=inputs.exam_suggestion,
        planned=facts.planned,
        completed=facts.completed,
        adjusted=adjusted,
        availability=availability,
    )
    completed_total = _completed_total(day.target_minutes, facts)
    return _OverviewTotals(
        availability=availability,
        adjusted=adjusted,
        allocations=allocations,
        completed_total=completed_total,
        remaining_total=max(0, int(day.target_minutes) - completed_total),
        completion_percent=_completion_percent(day.target_minutes, completed_total),
        primary_category=_primary_category(allocations),
        active_days=_overview_active_days(inputs.prior_dates, facts, today),
        days_remaining=days_remaining,
        days_remaining_raw=days_remaining_raw,
        phase=phase,
        phase_label=_phase_label(phase_label, days_remaining_raw),
    )


def _completed_total(target_minutes: int, facts: _OverviewFacts) -> int:
    return min(
        int(target_minutes),
        sum(max(0, int(facts.completed.get(category) or 0)) for category in CATEGORIES)
        + max(0, int(facts.credited_focus_minutes)),
    )


def _completion_percent(target_minutes: int, completed_total: int) -> int:
    if int(target_minutes) <= 0:
        return 100
    return min(100, round(completed_total / int(target_minutes) * 100))


def _primary_category(allocations: list[dict]) -> str | None:
    return next(
        (
            item["category"]
            for item in sorted(
                allocations,
                key=lambda item: (
                    -int(item["adjusted_minutes"]),
                    CATEGORIES.index(item["category"]),
                ),
            )
            if int(item["adjusted_minutes"]) > 0 and item["status"] == "available"
        ),
        None,
    )


def _overview_active_days(
    prior_dates: set[date], facts: _OverviewFacts, today: date
) -> int:
    active_dates = set(prior_dates)
    actual_activity_minutes = sum(
        max(0, int(facts.completed.get(category) or 0)) for category in CATEGORIES
    )
    if actual_activity_minutes > 0 or facts.focus_minutes > 0:
        active_dates.add(today)
    return len(active_dates)


def _phase_label(phase_label: str, days_remaining_raw: int) -> str:
    if days_remaining_raw < 0:
        return "目标日已过，请更新计划"
    if days_remaining_raw == 0:
        return "目标日"
    return phase_label


def _plan_payload(plan: StudyPlan) -> dict:
    return {
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


def _overview_response(
    *,
    plan: StudyPlan,
    today: date,
    day: StudyPlanDay,
    inputs: _OverviewInputs,
    facts: _OverviewFacts,
    totals: _OverviewTotals,
) -> dict:
    return {
        "configured": True,
        "date": today,
        "plan": _plan_payload(plan),
        "countdown": {
            "target_date": plan.target_date,
            "days_remaining": totals.days_remaining,
            "phase": totals.phase,
            "phase_label": totals.phase_label,
        },
        "weekly": {
            "week_start": inputs.week_start,
            "week_end": inputs.week_end,
            "target_days": int(plan.weekly_days),
            "active_days": totals.active_days,
            "remaining_days": max(0, int(plan.weekly_days) - totals.active_days),
            "target_met": totals.active_days >= int(plan.weekly_days),
        },
        "today": {
            "date": today,
            "target_minutes": int(day.target_minutes),
            "completed_minutes": totals.completed_total,
            "remaining_minutes": totals.remaining_total,
            "focus_minutes": facts.focus_minutes,
            "is_rest_day": bool(day.is_rest_day),
            "completion_percent": totals.completion_percent,
            "primary_category": totals.primary_category,
            "allocations": totals.allocations,
        },
        "suggested_defaults": {
            "daily_minutes": 90,
            "weekly_days": 6,
            "priority_mode": "balanced",
        },
    }


async def get_study_plan_overview(db: AsyncSession, user_id: int) -> dict:
    day_start_minute = await _load_day_start_minute(db, user_id)
    today = current_study_day(day_start_minute)
    plan = await _load_active_plan(db, user_id)
    if plan is None:
        return _unconfigured_overview(today)
    inputs = await _load_overview_inputs(
        db, user_id, today=today, day_start_minute=day_start_minute
    )
    latest_plan, day = await _materialize_overview_day(
        db,
        user_id,
        today=today,
        day_start_minute=day_start_minute,
        inputs=inputs,
    )
    if latest_plan is None or day is None:
        return _unconfigured_overview(today)
    facts = await _load_overview_facts(
        db,
        user_id,
        today=today,
        day=day,
        inputs=inputs,
        day_start_minute=day_start_minute,
    )
    totals = _overview_totals(
        plan=latest_plan, today=today, day=day, inputs=inputs, facts=facts
    )
    return _overview_response(
        plan=latest_plan,
        today=today,
        day=day,
        inputs=inputs,
        facts=facts,
        totals=totals,
    )
