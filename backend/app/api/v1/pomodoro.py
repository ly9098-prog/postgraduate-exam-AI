from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.pomodoro import (
    PomodoroCompleteRequest,
    PomodoroHistoryResponse,
    PomodoroResumeRequest,
    PomodoroSessionResponse,
    PomodoroStartRequest,
    PomodoroStatsResponse,
    PomodoroSubjectBreakdown,
    PomodoroTrendPoint,
)
from app.services import pomodoro_service as svc

router = APIRouter(prefix="/api/v1/pomodoro")


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
    req: PomodoroCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = await svc.complete_session(db, session_id, current_user.id, req.total_paused_ms, req.actual_duration_sec)
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
        session = await svc.interrupt_session(db, session_id, current_user.id, req.total_paused_ms, req.actual_duration_sec)
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
    session = await svc.resume_session(
        db, session_id, current_user.id,
        client_total_paused_ms=req.total_paused_ms,
        client_total_paused_sec=req.total_paused_sec,
    )
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
    return session



@router.get("/active", response_model=PomodoroSessionResponse | None)
async def get_active(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await svc.get_active_session(db, current_user.id)
    if session is None:
        return None
    return PomodoroSessionResponse.from_orm_with_subject(session)


@router.get("/stats", response_model=PomodoroStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_stats(db, current_user.id)
    return data


@router.get("/trends", response_model=list[PomodoroTrendPoint])
async def get_trends(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_trends(db, current_user.id, days)
    return [PomodoroTrendPoint(**d) for d in data]


@router.get("/subjects", response_model=list[PomodoroSubjectBreakdown])
async def get_subject_breakdown(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await svc.get_subject_breakdown(db, current_user.id)


@router.get("/history", response_model=PomodoroHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filter_date = None
    if date:
        filter_date = datetime.strptime(date, "%Y-%m-%d").date()
    sessions, total = await svc.get_history(db, current_user.id, page, page_size, filter_date)
    return {
        "items": [PomodoroSessionResponse.from_orm_with_subject(s) for s in sessions],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
