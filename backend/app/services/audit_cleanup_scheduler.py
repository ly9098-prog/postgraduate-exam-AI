"""审计日志定时清理调度器。

每天在配置的 UTC 时间执行一次，通过 Redis 分布式锁防止多 worker 重复执行。
"""
from __future__ import annotations

import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.time_utils import utcnow
from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session
from app.services.admin_audit_service import cleanup_expired_admin_audit_logs

logger = logging.getLogger("2240ai.audit_cleanup")

_LOCK_KEY = "audit:cleanup:lock"
_LOCK_TTL = 600  # 10 minutes — well beyond a single batch run


class AuditLogCleanupScheduler:
    """APScheduler wrapper for periodic audit log cleanup."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._running = False
        self._instance_id = uuid.uuid4().hex

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
            next_run_time=utcnow(),  # 启动后尽快执行一次（约 5s 后）
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._running = True
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
            logger.info("审计日志清理调度器已停止")

    async def _safe_cleanup(self) -> None:
        """Try to acquire the distributed lock; skip if held by another worker."""
        retention_days = max(7, settings.AUDIT_LOG_RETENTION_DAYS)
        batch_size = max(10, settings.AUDIT_LOG_CLEANUP_BATCH_SIZE)

        locked = await cache.acquire_lock(_LOCK_KEY, self._instance_id, ttl=_LOCK_TTL)
        if not locked:
            if cache.is_enabled:
                logger.info("审计日志清理锁被其他实例持有，本轮跳过")
            else:
                logger.warning(
                    "Redis 未配置，多 Worker 环境下审计日志清理可能重复执行。"
                    "建议配置 REDIS_URL 或设置 AUDIT_LOG_CLEANUP_ENABLED=false"
                )
            return

        try:
            async with async_session() as db:
                deleted = await cleanup_expired_admin_audit_logs(
                    db,
                    retention_days=retention_days,
                    batch_size=batch_size,
                )
            if deleted:
                logger.info(
                    "审计日志清理完成：删除 %d 条，保留天数 %d",
                    deleted,
                    retention_days,
                )
            else:
                logger.info("审计日志清理：没有过期数据需要清理")
        except Exception:
            logger.exception("审计日志清理失败（非致命）")
        finally:
            try:
                await cache.release_lock(_LOCK_KEY, self._instance_id)
            except Exception:
                pass


audit_log_cleanup_scheduler = AuditLogCleanupScheduler()
