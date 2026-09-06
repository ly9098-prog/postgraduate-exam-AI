"""推荐指标每日聚合 + 日志保留清理调度器。

周期触发只负责调度；实际执行、分布式锁、运行条件检查和遥测全部由
``system_task_service.execute_scheduled_task`` 统一处理，确保定时执行与管理端
“立即执行”走完全相同的生产代码路径。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger = logging.getLogger("2240ai.recommendation_metrics")


class RecommendationMetricsScheduler:
    """APScheduler wrapper for daily recommendation metrics aggregation + cleanup."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        if not settings.RECOMMENDATION_METRICS_AGG_ENABLED:
            logger.info("推荐指标聚合未启用 (RECOMMENDATION_METRICS_AGG_ENABLED=false)")
            return

        hour = settings.RECOMMENDATION_METRICS_AGG_HOUR_UTC
        if not 0 <= hour <= 23:
            logger.warning("RECOMMENDATION_METRICS_AGG_HOUR_UTC=%d 无效，使用默认值 4", hour)
            hour = 4

        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.add_job(
            self._safe_run,
            "cron",
            hour=hour,
            id="recommendation_metrics_daily",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._running = True
        from app.services.system_task_service import register_scheduler_task
        register_scheduler_task("recommendation_metrics_daily")
        logger.info(
            "推荐指标聚合调度器已启动: 每天 %02d:00 UTC, 日志保留 %d 天",
            hour,
            settings.RECOMMENDATION_LOG_RETENTION_DAYS,
        )

    async def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            from app.services.system_task_service import unregister_scheduler_task
            unregister_scheduler_task("recommendation_metrics_daily")
            logger.info("推荐指标聚合调度器已停止")

    async def _safe_run(self) -> None:
        from app.services.system_task_service import execute_scheduled_task

        try:
            outcome = await execute_scheduled_task("recommendation_metrics_daily", source="scheduler")
            if outcome.status == "failed":
                logger.error("推荐指标聚合失败: %s", outcome.message)
            elif outcome.status == "skipped":
                logger.info("推荐指标聚合跳过: %s", outcome.message)
        except Exception:
            logger.exception("推荐指标聚合调度执行异常")


recommendation_metrics_scheduler = RecommendationMetricsScheduler()
