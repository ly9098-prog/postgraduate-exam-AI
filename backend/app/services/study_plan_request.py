"""Materialize study-plan day snapshots and save or deactivate plan settings."""

from __future__ import annotations

from typing import Any


async def _claim_day_snapshot(db, row, plan, today, *, ports):
    try:
        # SQLite needs an outer BEGIN before a claim's savepoint is released.
        await ports("_start_explicit_transaction")(db)
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        await db.commit()
        return row
    except ports("IntegrityError") as exc:
        if not ports("_is_unique_violation")(exc):
            raise
        # Reload the winning claim without rolling back the caller's plan changes.
        winner = await db.scalar(
            ports("select")(ports("StudyPlanDay")).where(
                ports("StudyPlanDay").plan_id == int(plan.id),
                ports("StudyPlanDay").plan_date == today,
            )
        )
        if winner is None:
            raise
        return winner


async def _ensure_day_snapshot(
    db: Any,
    *,
    plan: Any,
    today: Any,
    hub: dict,
    exam_suggestion: dict | None,
    prior_active_days: int,
    day_start_minute: int,
    ports,
):
    day_stmt = ports("select")(ports("StudyPlanDay")).where(
        ports("StudyPlanDay").plan_id == int(plan.id),
        ports("StudyPlanDay").plan_date == today,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        day_stmt = day_stmt.with_for_update()
    row = await db.scalar(day_stmt)
    if row is not None and int(row.plan_revision) == int(plan.revision):
        snapshot_day_start = int((row.basis_json or {}).get("day_start_minute") or 0)
        if snapshot_day_start == int(day_start_minute):
            return row
    target_minutes, rest_day, allocation, basis = ports("_build_snapshot_payload")(
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
    row = ports("StudyPlanDay")(
        plan_id=int(plan.id),
        plan_revision=int(plan.revision),
        plan_date=today,
        target_minutes=target_minutes,
        is_rest_day=rest_day,
        allocation_json=allocation,
        basis_json=basis,
    )
    return await _claim_day_snapshot(db, row, plan, today, ports=ports)


async def upsert_study_plan(db: Any, user_id: int, data: Any, *, ports):
    today = ports("shanghai_today")()
    if data.target_date < today:
        raise ValueError("目标日期不能早于今天")
    plan = await ports("_get_user_plan")(db, user_id, lock=True)
    created = False
    if plan is None:
        candidate = ports("StudyPlan")(
            user_id=user_id,
            target_date=data.target_date,
            daily_minutes=int(data.daily_minutes),
            weekly_days=int(data.weekly_days),
            priority_mode=str(data.priority_mode),
            revision=1,
            is_active=True,
        )
        try:
            await ports("_start_explicit_transaction")(db)
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            plan = candidate
            created = True
        except ports("IntegrityError") as exc:
            if not ports("_is_unique_violation")(exc):
                raise
            plan = await ports("_get_user_plan")(db, user_id, lock=True)
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


async def deactivate_study_plan(db: Any, user_id: int, *, ports):
    plan = await ports("_get_user_plan")(db, user_id, lock=True)
    if plan is None or not plan.is_active:
        return
    plan.is_active = False
    plan.revision = int(plan.revision or 1) + 1
    await db.commit()
