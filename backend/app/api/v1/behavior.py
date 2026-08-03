from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.behavior import BehaviorStatsResponse, BehaviorSubmit
from app.services import behavior_service as svc

router = APIRouter(prefix="/api/v1/behavior")


@router.post("/record")
async def record_behavior(
    data: BehaviorSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量记录答题行为"""
    for r in data.records:
        await svc.record_answer_behavior(
            db=db,
            user_id=current_user.id,
            question_id=r.question_id,
            practice_record_id=None,
            time_spent_sec=r.time_spent_sec,
            is_final_correct=r.is_final_correct,
            view_answer_count=r.view_answer_count,
            switch_count=r.switch_count,
            is_abandoned=r.is_abandoned,
            user_answer=r.user_answer,
            correct_answer=r.correct_answer,
            subject_id=data.subject_id,
            session_type=data.session_type,
        )
    return {"status": "ok"}


@router.get("/stats", response_model=BehaviorStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取答题行为统计"""
    stats = await svc.get_behavior_stats(db, current_user.id)
    return BehaviorStatsResponse(**stats)
