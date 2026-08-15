"""推荐指标每日聚合 + 日志保留清理调度器。

每天在配置的 UTC 时间执行一次，通过 Redis 严格分布式锁防止多实例重复执行。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import async_session
from app.core.distributed_lock import DistributedLock
from app.core.time_utils import utcnow
from app.services.recommendation_log_service import cleanup_expired_recommendation_logs
from app.services.recommendation_metrics_service import (
    aggregate_recommendation_metrics_daily,
)

logger = logging.getLogger("2240ai.recommendation_metrics")

_LOCK_TTL = 600  # 10 minutes — well beyond a single aggregation+cleanup run


class RecommendationMetricsScheduler:
    """APScheduler wrapper for daily recommendation metrics aggregation + log cleanup."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._running = False
        self._lock = DistributedLock(
            "recommendation:metrics:daily", instance_id=self.__class__.__name__
        )

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
            next_run_time=utcnow(),  # 启动后尽快执行一次（约 5s 后）
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "推荐指标聚合调度器已启动: 每天 %02d:00 UTC, 日志保留 %d 天",
            hour,
            settings.RECOMMENDATION_LOG_RETENTION_DAYS,
        )

    async def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("推荐指标聚合调度器已停止")

    async def _safe_run(self) -> None:
        """Aggregate yesterday's metrics and clean logs with shared telemetry."""
        from app.services.system_task_service import TaskRunOutcome, record_system_task_execution

        async def _run_once():
            retention_days = max(7, settings.RECOMMENDATION_LOG_RETENTION_DAYS)

            async with self._lock.acquire_and_renew(ttl=_LOCK_TTL, renew_interval=120) as handle:
                if not handle.is_still_held():
                    logger.info("推荐指标聚合锁被其他实例持有，本轮跳过")
                    return TaskRunOutcome(status="skipped", message="锁被其他实例持有，本轮跳过")

                try:
                    async with async_session() as db:
                        target_date = date.today() - timedelta(days=1)
                        result = await aggregate_recommendation_metrics_daily(
                            db, target_date=target_date,
                        )
                        await db.commit()
                        deleted = await cleanup_expired_recommendation_logs(
                            db, retention_days=retention_days,
                        )
                        logger.info(
                            "推荐指标聚合完成: date=%s aggregated_rows=%d cleanup_deleted=%d",
                            target_date, result.get("aggregated_rows", 0), deleted,
                        )
                    return TaskRunOutcome(
                        status="success",
                        message=f"聚合 {result.get('aggregated_rows', 0)} 行，清理 {deleted} 条推荐日志",
                    )
                except Exception as exc:
                    logger.exception("推荐指标聚合失败（非致命）")
                    return TaskRunOutcome(status="failed", message=str(exc)[:400])

        await record_system_task_execution("recommendation_metrics_daily", _run_once, source="scheduler")



recommendation_metrics_scheduler = RecommendationMetricsScheduler()
