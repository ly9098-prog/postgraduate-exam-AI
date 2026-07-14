from fastapi import APIRouter, Depends, Query

from app.core.admin_security import require_permissions
from app.core.cache import cache

router = APIRouter(prefix="/api/v1/cache")


@router.get("/stats")
async def cache_stats(
    _=Depends(require_permissions("cache:read")),
):
    """缓存命中统计（管理员）。"""
    return cache.get_stats()


@router.delete("/clear")
async def cache_clear(
    pattern: str = Query("app:", description="缓存 key 模式（限制应用命名空间，默认 app:）"),
    _=Depends(require_permissions("cache:write")),
):
    """清除指定模式的应用缓存。

    仅限 ``app:*`` 命名空间内的 key。不允许删除任务队列、JWT 黑名单或
    分布式锁等系统 namespace。pattern 参数前自动加上 ``app:`` 前缀保护。
    """
    safe_pattern = _validate_cache_pattern(pattern)
    deleted = await cache.delete_namespaced(safe_pattern)
    return {"deleted": deleted, "namespace": safe_pattern}


def _validate_cache_pattern(pattern: str) -> str:
    """Validate the cache pattern is within allowed namespaces.

    Only permits patterns under ``app:`` prefix. Using ``*`` alone or
    ``import:*``, ``admin:*``, ``pomodoro:*``, ``audit:*``, ``ai:*``,
    etc. is rejected to prevent clearing system namespaces.
    """
    ALLOWED_PREFIXES = ("app:",)
    clean = pattern.strip()
    if not clean:
        raise ValueError("pattern 不能为空")
    # Coerce bare patterns into the app: namespace
    if not clean.startswith("app:"):
        clean = f"app:{clean.lstrip('*')}"
    # Verify prefix is in allowed list
    if not any(clean.startswith(p) for p in ALLOWED_PREFIXES):
        raise ValueError(f"pattern 必须以 {ALLOWED_PREFIXES[0]} 开头")
    return clean
