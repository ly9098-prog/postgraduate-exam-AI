from fastapi import APIRouter, Depends, Query

from app.core.cache import cache
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/cache")


@router.get("/stats")
async def cache_stats(
    _: User = Depends(get_current_user),
):
    """缓存命中统计（管理员）。"""
    return cache.get_stats()


@router.delete("/clear")
async def cache_clear(
    pattern: str = Query("*", description="匹配模式，默认清除所有"),
    _: User = Depends(get_current_user),
):
    """清除指定模式的缓存。"""
    deleted = await cache.delete(pattern)
    return {"deleted": deleted}


@router.post("/clear-all")
async def cache_clear_all(
    _: User = Depends(get_current_user),
):
    """清空全部缓存。"""
    await cache.clear()
    return {"status": "cleared"}
