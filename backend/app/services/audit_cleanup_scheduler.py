"""审计日志定时清理调度器。

周期触发只负责调度；实际执行、分布式锁、运行条件检查和遥测全部由
``system_task_service.execute_scheduled_task`` 统一处理，确保定时执行与管理端
“立即执行”走完全相同的生产代码路径。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger = logging.getLogger("2240ai.audit_cleanup")


class AuditLogCleanupScheduler:
    """APScheduler wrapper for periodic audit log cleanup."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        if not settings.AUDIT_LOG_CLEANUP_ENABLED:
            logger.info("审计日志清理未启用 (AUDIT_LOG_CLEANUP_ENABLED=false)")
            return

        hour = settings.AUDIT_LOG_CLEANUP_HOUR_UTC
        if not 0 <= hour <= 23:
            logger.warning("AUDIT_LOG_CLEANUP_HOUR_UTC=%d 无效，使用默认值 3", hour)
            hour = 3

        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.add_job(
            self._safe_cleanup,
            "cron",
            hour=hour,
            id="audit_log_cleanup",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._running = True
        from app.services.system_task_service import register_scheduler_task
        register_scheduler_task("audit_log_cleanup")
        logger.info(
            "审计日志清理调度器已启动: 每天 %02d:00 UTC, 保留 %d 天, 批次 %d 条",
            hour,
            settings.AUDIT_LOG_RETENTION_DAYS,
            settings.AUDIT_LOG_CLEANUP_BATCH_SIZE,
        )

    async def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            from app.services.system_task_service import unregister_scheduler_task
            unregister_scheduler_task("audit_log_cleanup")
            logger.info("审计日志清理调度器已停止")

    async def _safe_cleanup(self) -> None:
        from app.services.system_task_service import execute_scheduled_task

        try:
            outcome = await execute_scheduled_task("audit_log_cleanup", source="scheduler")
            if outcome.status == "failed":
                logger.error("审计日志清理失败: %s", outcome.message)
            elif outcome.status == "skipped":
                logger.info("审计日志清理跳过: %s", outcome.message)
        except Exception:
            logger.exception("审计日志清理调度执行异常")


audit_log_cleanup_scheduler = AuditLogCleanupScheduler()
