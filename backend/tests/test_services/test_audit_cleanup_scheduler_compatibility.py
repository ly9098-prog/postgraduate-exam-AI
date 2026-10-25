"""Pure-function compatibility baseline for AuditLogCleanupScheduler config gating.

Pins the module-level singleton instance, the start/stop state-machine behaviour
(disabled-short-circuit, hour validation with fallback to 3, start idempotency,
stop-no-op when not running), the APScheduler add_job configuration
(trigger=cron, id=audit_log_cleanup, max_instances=1, coalesce=True,
misfire_grace_time=3600, timezone=UTC), and the system_task_service registration
hook so that later refactors cannot silently change when the scheduler fires,
how it deduplicates missed runs, or which task-id it registers as live.

The actual cleanup execution lives in system_task_service.execute_scheduled_task
and is shared with the admin "run now" path; this file pins the SCHEDULING
contract only, not the cleanup semantics.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit_cleanup_scheduler import (
    AuditLogCleanupScheduler,
    audit_log_cleanup_scheduler,
)


class TestModuleSingleton:
    """audit_log_cleanup_scheduler is a process-singleton instance."""

    def test_singleton_is_audit_log_cleanup_scheduler(self):
        assert isinstance(audit_log_cleanup_scheduler, AuditLogCleanupScheduler)

    def test_module_exports_class_and_shared_instance(self):
        # The module surface is the class plus one process-local instance;
        # importers use the shared instance so runtime metrics and shutdown
        # hooks observe the same scheduler object.
        import app.services.audit_cleanup_scheduler as module

        assert getattr(module, "AuditLogCleanupScheduler") is AuditLogCleanupScheduler
        assert getattr(module, "audit_log_cleanup_scheduler") is audit_log_cleanup_scheduler


class TestStartDisabledShortCircuit:
    """When AUDIT_LOG_CLEANUP_ENABLED=False, start() returns without creating
    a scheduler or registering a task."""

    @pytest.mark.asyncio
    async def test_disabled_does_not_create_scheduler(self):
        s = AuditLogCleanupScheduler()
        with patch("app.services.audit_cleanup_scheduler.settings") as m:
            m.AUDIT_LOG_CLEANUP_ENABLED = False
            await s.start()
        assert s._scheduler is None
        assert s._running is False

    @pytest.mark.asyncio
    async def test_disabled_does_not_call_register_scheduler_task(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ) as reg,
            patch(
                "app.services.audit_cleanup_scheduler.AsyncIOScheduler"
            ) as Sch,
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = False
            await s.start()
        reg.assert_not_called()
        Sch.assert_not_called()


class TestStartIdempotency:
    """start() is a no-op when already running."""

    @pytest.mark.asyncio
    async def test_start_when_running_returns_early(self):
        s = AuditLogCleanupScheduler()
        s._running = True
        # Should return without creating a scheduler or re-registering the task
        with (
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ) as reg,
        ):
            await s.start()
        Sch.assert_not_called()
        reg.assert_not_called()
        # State unchanged
        assert s._running is True
        assert s._scheduler is None


class TestHourValidation:
    """AUDIT_LOG_CLEANUP_HOUR_UTC must be in [0, 23]; invalid values fall back
    to 3 with a warning log. Valid values pass through unchanged."""

    @pytest.mark.asyncio
    async def test_invalid_hour_25_falls_back_to_3(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 25
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        kwargs = inst.add_job.call_args.kwargs
        assert kwargs["hour"] == 3

    @pytest.mark.asyncio
    async def test_invalid_negative_hour_falls_back_to_3(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = -1
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        kwargs = inst.add_job.call_args.kwargs
        assert kwargs["hour"] == 3

    @pytest.mark.asyncio
    async def test_boundary_hour_0_is_valid(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 0
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        kwargs = inst.add_job.call_args.kwargs
        assert kwargs["hour"] == 0

    @pytest.mark.asyncio
    async def test_boundary_hour_23_is_valid(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 23
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        kwargs = inst.add_job.call_args.kwargs
        assert kwargs["hour"] == 23

    @pytest.mark.asyncio
    async def test_invalid_hour_logs_warning(self, caplog):
        import logging

        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 99
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            with caplog.at_level(
                logging.WARNING, logger="2240ai.audit_cleanup"
            ):
                await s.start()
        assert any(
            "AUDIT_LOG_CLEANUP_HOUR_UTC=99" in rec.getMessage()
            and "默认值 3" in rec.getMessage()
            for rec in caplog.records
        )


class TestAddJobConfiguration:
    """The cron job is registered with an exact call pin.

    The exact-call assertion transitively pins: the job callable is
    ``s._safe_cleanup`` (not any other callback), the trigger is ``"cron"``,
    the fire hour is the validated config value, the job id, overlap and
    misfire behaviour, AND that no additional schedule kwargs (minute, day,
    day_of_week, month) are present — adding any of them changes fire
    semantics and must break this baseline.
    """

    @pytest.mark.asyncio
    async def test_add_job_exact_call_and_start(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 5
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        inst.add_job.assert_called_once_with(
            s._safe_cleanup,
            "cron",
            hour=5,
            id="audit_log_cleanup",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        # Dropping scheduler.start() would mean the job never fires
        inst.start.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_scheduler_timezone_is_utc(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 5
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        assert Sch.call_args.kwargs["timezone"] == "UTC"


class TestStartRegistersTask:
    """On successful start, register_scheduler_task('audit_log_cleanup') is
    called to declare the scheduler as a live task."""

    @pytest.mark.asyncio
    async def test_register_called_with_audit_log_cleanup(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ) as reg,
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 5
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        reg.assert_called_once_with("audit_log_cleanup")

    @pytest.mark.asyncio
    async def test_running_flag_set_true_after_start(self):
        s = AuditLogCleanupScheduler()
        with (
            patch("app.services.audit_cleanup_scheduler.settings") as m,
            patch("app.services.audit_cleanup_scheduler.AsyncIOScheduler") as Sch,
            patch(
                "app.services.system_task_service.register_scheduler_task"
            ),
        ):
            m.AUDIT_LOG_CLEANUP_ENABLED = True
            m.AUDIT_LOG_CLEANUP_HOUR_UTC = 5
            m.AUDIT_LOG_RETENTION_DAYS = 180
            m.AUDIT_LOG_CLEANUP_BATCH_SIZE = 1000
            inst = MagicMock()
            Sch.return_value = inst
            await s.start()
        assert s._running is True


class TestStopNoOpWhenNotRunning:
    """stop() is a safe no-op when the scheduler was never started."""

    @pytest.mark.asyncio
    async def test_stop_without_start_does_not_raise(self):
        s = AuditLogCleanupScheduler()
        # _scheduler is None, _running is False — stop must be a no-op
        await s.stop()
        assert s._running is False
        assert s._scheduler is None

    @pytest.mark.asyncio
    async def test_stop_does_not_unregister_when_not_running(self):
        s = AuditLogCleanupScheduler()
        with patch(
            "app.services.system_task_service.unregister_scheduler_task"
        ) as unreg:
            await s.stop()
        unreg.assert_not_called()


class TestStopWithRunningScheduler:
    """stop() shuts down the scheduler, clears _running, and unregisters."""

    @pytest.mark.asyncio
    async def test_stop_calls_shutdown(self):
        s = AuditLogCleanupScheduler()
        inst = MagicMock()
        inst.shutdown = MagicMock()
        s._scheduler = inst
        s._running = True
        with patch(
            "app.services.system_task_service.unregister_scheduler_task"
        ):
            await s.stop()
        inst.shutdown.assert_called_once_with(wait=False)
        assert s._running is False

    @pytest.mark.asyncio
    async def test_stop_unregisters_audit_log_cleanup(self):
        s = AuditLogCleanupScheduler()
        inst = MagicMock()
        s._scheduler = inst
        s._running = True
        with patch(
            "app.services.system_task_service.unregister_scheduler_task"
        ) as unreg:
            await s.stop()
        unreg.assert_called_once_with("audit_log_cleanup")

    @pytest.mark.asyncio
    async def test_stop_when_scheduler_none_but_running_is_safe(self):
        # Defensive: if _running is True but _scheduler is None (shouldn't
        # happen but the guard is `if self._scheduler and self._running`),
        # stop is a no-op for shutdown but still unregisters? No — the guard
        # is `and`, so _scheduler=None skips the whole block. Pin this.
        s = AuditLogCleanupScheduler()
        s._running = True
        s._scheduler = None
        with patch(
            "app.services.system_task_service.unregister_scheduler_task"
        ) as unreg:
            await s.stop()
        # Guard `if self._scheduler and self._running` is False, so no unregister
        unreg.assert_not_called()
        # _running stays True because the guard was False — pinned defect
        assert s._running is True


class TestSafeCleanupDelegates:
    """_safe_cleanup calls execute_scheduled_task('audit_log_cleanup',
    source='scheduler') and routes the outcome to logs."""

    @pytest.mark.asyncio
    async def test_calls_execute_scheduled_task_with_correct_args(self):
        s = AuditLogCleanupScheduler()
        outcome = MagicMock()
        outcome.status = "completed"
        outcome.message = "ok"
        execute = AsyncMock(return_value=outcome)
        with patch(
            "app.services.system_task_service.execute_scheduled_task",
            new=execute,
        ):
            await s._safe_cleanup()
        execute.assert_awaited_once_with(
            "audit_log_cleanup", source="scheduler"
        )

    @pytest.mark.asyncio
    async def test_completed_outcome_does_not_log_error_or_skip(self, caplog):
        import logging

        s = AuditLogCleanupScheduler()
        outcome = MagicMock()
        outcome.status = "completed"
        outcome.message = "ok"
        with (
            patch(
                "app.services.system_task_service.execute_scheduled_task",
                new=AsyncMock(return_value=outcome),
            ),
            caplog.at_level(logging.INFO, logger="2240ai.audit_cleanup"),
        ):
            await s._safe_cleanup()
        # Success is silent: neither the failed nor skipped message appears
        assert not any(
            "审计日志清理失败" in rec.getMessage() for rec in caplog.records
        )
        assert not any(
            "审计日志清理跳过" in rec.getMessage() for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_failed_outcome_logs_error(self, caplog):
        import logging

        s = AuditLogCleanupScheduler()
        outcome = MagicMock()
        outcome.status = "failed"
        outcome.message = "boom"
        with (
            patch(
                "app.services.system_task_service.execute_scheduled_task",
                new=AsyncMock(return_value=outcome),
            ),
            caplog.at_level(logging.ERROR, logger="2240ai.audit_cleanup"),
        ):
            await s._safe_cleanup()
        assert any(
            "审计日志清理失败" in rec.getMessage() and "boom" in rec.getMessage()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_skipped_outcome_logs_info(self, caplog):
        import logging

        s = AuditLogCleanupScheduler()
        outcome = MagicMock()
        outcome.status = "skipped"
        outcome.message = "already running"
        with (
            patch(
                "app.services.system_task_service.execute_scheduled_task",
                new=AsyncMock(return_value=outcome),
            ),
            caplog.at_level(logging.INFO, logger="2240ai.audit_cleanup"),
        ):
            await s._safe_cleanup()
        assert any(
            "审计日志清理跳过" in rec.getMessage()
            and "already running" in rec.getMessage()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_exception_in_execute_is_caught(self, caplog):
        # _safe_cleanup must not raise even if execute_scheduled_task throws
        import logging

        s = AuditLogCleanupScheduler()
        with (
            patch(
                "app.services.system_task_service.execute_scheduled_task",
                new=AsyncMock(side_effect=RuntimeError("kaboom")),
            ),
            caplog.at_level(logging.ERROR, logger="2240ai.audit_cleanup"),
        ):
            # Should not raise
            await s._safe_cleanup()
        # logger.exception logs at ERROR with the message prefix
        assert any(
            "审计日志清理调度执行异常" in rec.getMessage() for rec in caplog.records
        )
