from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.behavior import BehaviorStatsResponse
from app.services import behavior_service as svc
from app.core.runtime_paths import API_V1_PREFIX
router = APIRouter(prefix=f"{API_V1_PREFIX}/behavior")


@router.get("/stats", response_model=BehaviorStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取答题行为统计"""
    stats = await svc.get_behavior_stats(db, current_user.id)
    return BehaviorStatsResponse(**stats)
