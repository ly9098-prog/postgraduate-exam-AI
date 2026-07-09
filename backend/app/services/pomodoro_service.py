from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.admin import Subject
from app.models.pomodoro import PomodoroSession
from app.models.user import User
from app.core.time_utils import utcnow


async def start_session(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    chapter_id: str | None,
    preset: str,
    work_duration: int,
    break_duration: int,
    notification_enabled: bool = False,
) -> PomodoroSession:
    await _cancel_running(db, user_id)

    user_row = await db.execute(select(User.openid).where(User.id == user_id))
    openid_snapshot = user_row.scalar_one_or_none()

    # Free timer overrides: no countdown, no notification
    if preset == "free":
        work_duration = 0
        break_duration = 0
        notification_enabled = False
    elif work_duration <= 0:
        raise ValueError("非自由计时模式需要设置学习时长")

    start = utcnow()
    expected_end = start + timedelta(minutes=max(0, work_duration)) if work_duration > 0 else None

    # Validate subject_id
    subj = await db.get(Subject, subject_id)
    if subj is None:
        raise ValueError(f"科目不存在: subject_id={subject_id}")
    if not subj.is_active:
        raise ValueError(f"科目不可用: {subj.name}")
    # Check leaf: if subject has active children, reject
    child_count = await db.scalar(
        select(func.count(Subject.id)).where(
            Subject.parent_id == subject_id,
            Subject.is_active.is_(True),
        )
    )
    if child_count and child_count > 0:
        raise ValueError(f"请选择具体子科目，不能选择父级科目: {subj.name}")

    session = PomodoroSession(
        user_id=user_id,
        subject_id=subject_id,
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
    # Populate subject_ref for post-commit serialization
    session.subject_ref = subj
    return session


async def complete_session(db: AsyncSession, session_id: int, user_id: int, total_paused_ms: int = 0, actual_duration_sec: int | None = None) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
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
        paused = (session.total_paused_sec or 0) + int(total_paused_ms / 1000)
        raw_seconds = int((now - session.start_time).total_seconds())
        session.actual_duration = max(0, raw_seconds - paused)
    session.status = "completed"
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
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
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
        paused = (session.total_paused_sec or 0) + int(total_paused_ms / 1000)
        raw_seconds = int((now - session.start_time).total_seconds())
        session.actual_duration = max(0, raw_seconds - paused)
    session.status = "interrupted"
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user interrupted"
    await db.flush()
    await db.refresh(session)
    return session


async def pause_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
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
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
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
        paused_sec = max(0, int(paused_for.total_seconds()))
        session.total_paused_sec = (session.total_paused_sec or 0) + paused_sec
        if session.expected_end_time is not None and paused_sec > 0:
            session.expected_end_time = session.expected_end_time + timedelta(seconds=paused_sec)
        session.paused_at = None
        await db.flush()
    await db.refresh(session)
    return session


async def get_active_session(db: AsyncSession, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
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
        raw_seconds = int((now - session.start_time).total_seconds())
        paused = session.total_paused_sec or 0
        session.actual_duration = max(0, raw_seconds - paused)
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
            PomodoroSession.subject_id,
            func.count(PomodoroSession.id),
            func.coalesce(func.sum(PomodoroSession.actual_duration), 0),
        )
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["completed", "interrupted"]),
            PomodoroSession.end_time >= today_start,
        )
        .group_by(PomodoroSession.subject_id)
        .order_by(func.sum(PomodoroSession.actual_duration).desc())
    )

    # Build a lookup for subject names from the subjects table
    subj_rows = await db.execute(select(Subject.id, Subject.code, Subject.name).where(Subject.is_active.is_(True)))
    subj_map = {r[0]: {"code": r[1], "name": r[2]} for r in subj_rows.all()}

    result_rows = []
    for r in result.all():
        sid = r[0]
        sessions = r[1]
        duration = r[2]
        if sid and sid in subj_map:
            result_rows.append({
                "subject_id": sid,
                "subject_code": subj_map[sid]["code"],
                "subject_name": subj_map[sid]["name"],
                "sessions": sessions,
                "duration_sec": duration,
            })
        else:
            result_rows.append({
                "subject_id": None,
                "subject_code": "",
                "subject_name": "未分类",
                "sessions": sessions,
                "duration_sec": duration,
            })
    return result_rows


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
        .options(joinedload(PomodoroSession.subject_ref))
        .where(*where)
        .order_by(PomodoroSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all(), total
