"""Phase 4.5 — 推荐系统缓存失效服务。

Redis 不可用时静默降级，不影响主流程。
"""
import logging

from app.core.cache import cache

logger = logging.getLogger(__name__)


async def invalidate_strategy_cache() -> int:
    """策略配置更新后清理相关缓存。"""
    try:
        return await cache.delete("recommendation:strategy:*")
    except Exception:
        logger.warning("清理策略缓存失败", exc_info=True)
        return 0


async def invalidate_experiment_cache(experiment_id: int | None = None) -> int:
    """实验状态更新后清理相关缓存。"""
    try:
        if experiment_id:
            return await cache.delete(f"recommendation:experiment:{experiment_id}:*")
        return await cache.delete("recommendation:experiment:*")
    except Exception:
        logger.warning("清理实验缓存失败", exc_info=True)
        return 0


async def invalidate_knowledge_path_cache(subject_id: int | None = None) -> int:
    """知识边 force_rebuild 后清理相关缓存。"""
    try:
        subj = subject_id if subject_id is not None else "*"
        total = 0
        total += await cache.delete(f"knowledge:path:{subj}:*")
        total += await cache.delete(f"practice:smart:{subj}:*")
        total += await cache.delete(f"recommendation:path:{subj}:*")
        return total
    except Exception:
        logger.warning("清理知识路径缓存失败", exc_info=True)
        return 0
