from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pomodoro import PomodoroSession
from app.models.user import User
from app.core.time_utils import utcnow


async def start_session(
    db: AsyncSession,
    user_id: int,
    subject: str,
    chapter_id: str | None,
    preset: str,
    work_duration: int,
    break_duration: int,
    notification_enabled: bool = False,
) -> PomodoroSession:
    await _cancel_running(db, user_id)

    user_row = await db.execute(select(User.openid).where(User.id == user_id))
    openid_snapshot = user_row.scalar_one_or_none()

    start = utcnow()
    expected_end = start + timedelta(minutes=max(0, work_duration)) if work_duration > 0 else None

    session = PomodoroSession(
        user_id=user_id,
        subject=subject,
        chapter_id=chapter_id,
        preset=preset,
        work_duration=work_duration,
        break_duration=break_duration,
        start_time=start,
        expected_end_time=expected_end,
        status="running",
        notification_enabled=bool(notification_enabled),
        notification_sent=False,
        openid_snapshot=openid_snapshot,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def complete_session(db: AsyncSession, session_id: int, user_id: int, total_paused_ms: int = 0, actual_duration_sec: int | None = None) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession).where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    now = utcnow()
    session.end_time = now
    if actual_duration_sec is not None:
        session.actual_duration = actual_duration_sec
    else:
        raw_seconds = int((now - session.start_time).total_seconds())
        session.actual_duration = max(0, raw_seconds - int(total_paused_ms / 1000))
    session.status = "completed"
    # 用户已主动 complete → 调度器不再发送通知（防止双重提醒）
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user completed before scheduler"
    await db.flush()
    await db.refresh(session)
    return session


async def interrupt_session(db: AsyncSession, session_id: int, user_id: int, total_paused_ms: int = 0, actual_duration_sec: int | None = None) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession).where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    now = utcnow()
    session.end_time = now
    if actual_duration_sec is not None:
        session.actual_duration = actual_duration_sec
    else:
        raw_seconds = int((now - session.start_time).total_seconds())
        session.actual_duration = max(0, raw_seconds - int(total_paused_ms / 1000))
    session.status = "interrupted"
    # 主动中断 → 关闭通知通道
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user interrupted"
    await db.flush()
    await db.refresh(session)
    return session


async def pause_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    """暂停 running 会话。已暂停时返回原状（幂等）。

    暂停期间 expected_end_time 保持不动；scheduler 通过 paused_at IS NOT NULL 跳过。
    """
    result = await db.execute(
        select(PomodoroSession).where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    if session.paused_at is None:
        session.paused_at = utcnow()
        await db.flush()
    await db.refresh(session)
    return session


async def resume_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    """恢复暂停中的会话；将暂停时长加到 expected_end_time，清空 paused_at。"""
    result = await db.execute(
        select(PomodoroSession).where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    if session.paused_at is not None:
        now = utcnow()
        paused_for = now - session.paused_at
        if session.expected_end_time is not None and paused_for.total_seconds() > 0:
            session.expected_end_time = session.expected_end_time + paused_for
        session.paused_at = None
        await db.flush()
    await db.refresh(session)
    return session


async def get_active_session(db: AsyncSession, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
        .order_by(PomodoroSession.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _cancel_running(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(
        select(PomodoroSession)
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "running",
        )
        .with_for_update()
    )
    for session in result.scalars().all():
        now = utcnow()
        session.end_time = now
        session.actual_duration = int((now - session.start_time).total_seconds())
        session.status = "interrupted"
        if not session.notification_sent:
            session.notification_sent = True
            session.notification_sent_at = now
            if not session.notification_error:
                session.notification_error = "skipped: superseded by new session"


async def get_stats(db: AsyncSession, user_id: int) -> dict:
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    _status_cond = PomodoroSession.status.in_(["completed", "interrupted"])
    today_result = await db.execute(
        select(
            func.count(PomodoroSession.id),
            func.coalesce(func.sum(PomodoroSession.actual_duration), 0),
        ).where(
            PomodoroSession.user_id == user_id,
            _status_cond,
            PomodoroSession.end_time >= today_start,
        )
    )
    today_sessions, today_duration = today_result.one()

    week_result = await db.execute(
        select(
            func.count(PomodoroSession.id),
            func.coalesce(func.sum(PomodoroSession.actual_duration), 0),
        ).where(
            PomodoroSession.user_id == user_id,
            _status_cond,
            PomodoroSession.end_time >= week_start,
        )
    )
    week_sessions, week_duration = week_result.one()

    return {
        "today_sessions": today_sessions or 0,
        "today_duration_sec": today_duration or 0,
        "week_sessions": week_sessions or 0,
        "week_duration_sec": week_duration or 0,
    }


async def get_trends(db: AsyncSession, user_id: int, days: int = 7) -> list[dict]:
    since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    result = await db.execute(
        select(
            func.date(PomodoroSession.end_time),
            func.count(PomodoroSession.id),
            func.coalesce(func.sum(PomodoroSession.actual_duration), 0),
        )
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["completed", "interrupted"]),
            PomodoroSession.end_time >= since,
        )
        .group_by(func.date(PomodoroSession.end_time))
        .order_by(func.date(PomodoroSession.end_time))
    )
    data = {str(r[0]): {"sessions": r[1], "duration": r[2]} for r in result.all()}

    points = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        entry = data.get(d, {"sessions": 0, "duration": 0})
        points.append({
            "date": d,
            "sessions": entry["sessions"],
            "duration_sec": entry["duration"],
        })
    return points


async def get_subject_breakdown(db: AsyncSession, user_id: int) -> list[dict]:
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            PomodoroSession.subject,
            func.count(PomodoroSession.id),
            func.coalesce(func.sum(PomodoroSession.actual_duration), 0),
        )
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["completed", "interrupted"]),
            PomodoroSession.end_time >= today_start,
        )
        .group_by(PomodoroSession.subject)
        .order_by(func.sum(PomodoroSession.actual_duration).desc())
    )
    return [
        {"subject": r[0] or "未分类", "sessions": r[1], "duration_sec": r[2]}
        for r in result.all()
    ]


async def get_history(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20,
    filter_date: date | None = None,
) -> tuple[list[PomodoroSession], int]:
    where = [
        PomodoroSession.user_id == user_id,
        PomodoroSession.status != "running",
    ]
    if filter_date is not None:
        where.append(func.date(PomodoroSession.end_time) == filter_date)

    count_result = await db.execute(
        select(func.count(PomodoroSession.id)).where(*where)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(PomodoroSession)
        .where(*where)
        .order_by(PomodoroSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all(), total
