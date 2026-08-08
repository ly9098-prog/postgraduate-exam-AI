from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.pomodoro import (
    PomodoroCompleteRequest,
    PomodoroDailySummaryResponse,
    PomodoroHistoryResponse,
    PomodoroResumeRequest,
    PomodoroSessionResponse,
    PomodoroSettingsResponse,
    PomodoroSettingsUpdate,
    PomodoroStartRequest,
    PomodoroStatisticsOverviewResponse,
    PomodoroStatsResponse,
)
from app.services import pomodoro_service as svc

router = APIRouter(prefix="/api/v1/pomodoro")


def _parse_study_date(value: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD study day; 400 on malformed input."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD format") from exc


@router.post("/start", response_model=PomodoroSessionResponse)
async def start_session(
    req: PomodoroStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = await svc.start_session(
            db,
            current_user.id,
            req.subject_id,
            req.chapter_id,
            req.preset,
            req.work_duration,
            req.break_duration,
            notification_enabled=req.notification_enabled,
        )
    except ValueError as e:
        from fastapi import HTTPException
        detail = str(e)
        status_code = 409 if "已有进行中的专注" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail)
    await db.commit()
    return PomodoroSessionResponse.from_orm_with_subject(session)


@router.post("/{session_id}/complete", response_model=PomodoroSessionResponse)
async def complete_session(
    session_id: int,
    req: PomodoroCompleteRequest = PomodoroCompleteRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = await svc.complete_session(db, session_id, current_user.id)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No running session found")
    await db.commit()
    return PomodoroSessionResponse.from_orm_with_subject(session)


@router.post("/{session_id}/interrupt", response_model=PomodoroSessionResponse)
async def interrupt_session(
    session_id: int,
    req: PomodoroCompleteRequest = PomodoroCompleteRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = await svc.interrupt_session(db, session_id, current_user.id)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No running session found")
    await db.commit()
    return PomodoroSessionResponse.from_orm_with_subject(session)



@router.post("/{session_id}/resume", response_model=PomodoroSessionResponse)
async def resume_session(
    session_id: int,
    req: PomodoroResumeRequest = PomodoroResumeRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await svc.resume_session(db, session_id, current_user.id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No running session found")
    await db.commit()
    return PomodoroSessionResponse.from_orm_with_subject(session)


@router.post("/{session_id}/pause", response_model=PomodoroSessionResponse)
async def pause_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await svc.pause_session(db, session_id, current_user.id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No running session found")
    await db.commit()
    return PomodoroSessionResponse.from_orm_with_subject(session)



@router.get("/active", response_model=PomodoroSessionResponse | None)
async def get_active(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await svc.get_active_session(db, current_user.id)
    if session is None:
        return None
    return PomodoroSessionResponse.from_orm_with_subject(session)


@router.get("/settings", response_model=PomodoroSettingsResponse)
async def get_pomodoro_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await svc.get_pomodoro_settings(db, current_user.id)


@router.put("/settings", response_model=PomodoroSettingsResponse)
async def update_pomodoro_settings(
    req: PomodoroSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.update_pomodoro_settings(db, current_user.id, req.day_start_minute)
    await db.commit()
    return data


@router.get("/stats", response_model=PomodoroStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_stats(db, current_user.id)
    return data


@router.get("/statistics-overview", response_model=PomodoroStatisticsOverviewResponse)
async def get_statistics_overview(
    date: str | None = Query(None, description="Study day (YYYY-MM-DD) for the daily summary, defaults to the current study day"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """统计页首屏：stats + trends + daily_summary 一次返回（单次窗口加载 + 单次归因）。"""
    data = await svc.build_pomodoro_statistics_snapshot(
        db,
        current_user.id,
        target_date=_parse_study_date(date),
        need_stats=True,
        need_trends=True,
        need_daily_summary=True,
    )
    return data


@router.get("/daily-summary", response_model=PomodoroDailySummaryResponse)
async def get_daily_summary(
    date: str | None = Query(None, description="Study day (YYYY-MM-DD), defaults to the current study day"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await svc.get_daily_summary(db, current_user.id, _parse_study_date(date))


@router.get("/history", response_model=PomodoroHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions, total = await svc.get_history(
        db, current_user.id, page, page_size, _parse_study_date(date)
    )
    return {
        "items": [PomodoroSessionResponse.from_orm_with_subject(s) for s in sessions],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
