"""408 long-horizon study planning service.

The planner coordinates existing learning facts instead of inventing a second
completion system. Configuration + daily allocation snapshots live here;
completion is projected from ReviewRecord / PracticeSession / ExamAttempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.subject_scope import EXAM408_ALL_CODES, EXAM408_CORE_CODES
from app.core.time_utils import (
    current_study_day,
    shanghai_today,
    study_day_for_utc,
    study_day_utc_range,
)
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAttempt
from app.models.pomodoro import (
    PomodoroSession,
    PomodoroSubjectAllocation,
    UserPomodoroSettings,
)
from app.models.practice_session import PracticeSession
from app.models.review_scheduler import ReviewRecord
from app.models.study_plan import StudyPlan, StudyPlanDay
from app.schemas.study_plan import StudyPlanUpsertRequest
from app.services.pomodoro_attribution import (
    split_duration_excluding_intervals,
    split_session_duration_by_study_day,
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
    is_unique_violation as _is_unique_violation,
)
from app.services.unique_conflict import (
    start_explicit_transaction as _start_explicit_transaction,
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
    if end_date < start_date:
        return set()
    start_utc = study_day_utc_range(start_date, day_start_minute)[0]
    end_utc = study_day_utc_range(end_date, day_start_minute)[1]
    active_dates: set[date] = set()

    if core_408_ids:
        reviewed_at_values = (
            await db.scalars(
                select(ReviewRecord.reviewed_at)
                .join(
                    QuestionVersion,
                    QuestionVersion.id == ReviewRecord.question_version_id,
                )
                .where(
                    ReviewRecord.user_id == user_id,
                    QuestionVersion.subject_id.in_(core_408_ids),
                    ReviewRecord.reviewed_at >= start_utc,
                    ReviewRecord.reviewed_at < end_utc,
                )
            )
        ).all()
        active_dates.update(
            study_day_for_utc(value, day_start_minute)
            for value in reviewed_at_values
            if value is not None
        )

    if all_408_ids:
        practice_rows = (
            await db.execute(
                select(
                    PracticeSession.started_at,
                    PracticeSession.finished_at,
                    PracticeSession.duration_sec,
                ).where(
                    PracticeSession.user_id == user_id,
                    PracticeSession.subject_id.in_(all_408_ids),
                    PracticeSession.status == "completed",
                    PracticeSession.started_at < end_utc,
                    PracticeSession.finished_at > start_utc,
                )
            )
        ).all()
        for row in practice_rows:
            split = split_duration_excluding_intervals(
                row.started_at,
                row.finished_at,
                max(0, int(row.duration_sec or 0)),
                [],
                day_start_minute,
            )
            active_dates.update(
                day
                for day, sec in split.items()
                if start_date <= day <= end_date and sec > 0
            )

        pomodoro_rows = (
            (
                await db.execute(
                    select(PomodoroSession)
                    .options(
                        selectinload(PomodoroSession.pause_intervals),
                        selectinload(PomodoroSession.subject_allocations),
                    )
                    .where(
                        PomodoroSession.user_id == user_id,
                        or_(
                            PomodoroSession.subject_id.in_(all_408_ids),
                            PomodoroSession.id.in_(
                                select(PomodoroSubjectAllocation.session_id).where(
                                    PomodoroSubjectAllocation.subject_id.in_(all_408_ids)
                                )
                            ),
                        ),
                        PomodoroSession.status == "completed",
                        PomodoroSession.end_time.is_not(None),
                        PomodoroSession.start_time < end_utc,
                        PomodoroSession.end_time > start_utc,
                    )
                )
            )
            .scalars()
            .all()
        )
        for session in pomodoro_rows:
            split = split_session_duration_by_study_day(
                session,
                session.pause_intervals,
                day_start_minute,
            )
            active_dates.update(
                day
                for day, sec in split.items()
                if start_date <= day <= end_date
                and _focus_duration_for_subject_scope(
                    session, {day: sec}, set(all_408_ids)
                ) > 0
            )

    exam_rows = (
        await db.execute(
            select(
                ExamAttempt.started_at,
                ExamAttempt.submitted_at,
                ExamAttempt.duration_sec,
            ).where(
                ExamAttempt.user_id == user_id,
                ExamAttempt.submitted_at.is_not(None),
                ExamAttempt.status.in_(("submitted", "expired")),
                ExamAttempt.started_at < end_utc,
                ExamAttempt.submitted_at > start_utc,
            )
        )
    ).all()
    for row in exam_rows:
        split = split_duration_excluding_intervals(
            row.started_at,
            row.submitted_at,
            max(0, int(row.duration_sec or 0)),
            [],
            day_start_minute,
        )
        active_dates.update(
            day
            for day, sec in split.items()
            if start_date <= day <= end_date and sec > 0
        )

    return active_dates


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
    day_stmt = select(StudyPlanDay).where(
        StudyPlanDay.plan_id == int(plan.id),
        StudyPlanDay.plan_date == today,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        day_stmt = day_stmt.with_for_update()
    row = await db.scalar(day_stmt)
    if row is not None and int(row.plan_revision) == int(plan.revision):
        snapshot_day_start = int((row.basis_json or {}).get("day_start_minute") or 0)
        if snapshot_day_start == int(day_start_minute):
            return row

    target_minutes, rest_day, allocation, basis = _build_snapshot_payload(
        plan=plan,
        today=today,
        hub=hub,
        exam_suggestion=exam_suggestion,
        prior_active_days=prior_active_days,
        day_start_minute=day_start_minute,
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
        # SQLite may defer BEGIN until the first write. Start the caller's outer
        # transaction before the savepoint so a losing claim cannot survive a
        # later request rollback.
        await _start_explicit_transaction(db)
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        await db.commit()
        return row
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise
        # Two devices may materialize the same day's snapshot concurrently. The
        # unique(plan_id, plan_date) constraint is authoritative. Keep the outer
        # transaction and loaded plan usable while reloading the winner.
        winner = await db.scalar(
            select(StudyPlanDay).where(
                StudyPlanDay.plan_id == int(plan.id),
                StudyPlanDay.plan_date == today,
            )
        )
        if winner is None:
            raise
        return winner


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
            await _start_explicit_transaction(db)
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            plan = candidate
            created = True
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            plan = await _get_user_plan(db, user_id, lock=True)
            if plan is None:
                raise

    if not created:
        changed = any(
            (
                plan.target_date != data.target_date,
                int(plan.daily_minutes) != int(data.daily_minutes),
                int(plan.weekly_days) != int(data.weekly_days),
                str(plan.priority_mode) != str(data.priority_mode),
                not bool(plan.is_active),
            )
        )
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
