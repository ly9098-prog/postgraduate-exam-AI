"""Admin-facing catalog and telemetry for recurring system jobs.

The production deployment runs scheduler work in a separate process from the
HTTP admin service.  This module therefore keeps the job catalog deterministic
and stores lightweight execution telemetry in Redis so the admin UI can observe
runs across process boundaries without turning the web process into a scheduler.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable, Literal

import redis.asyncio as redis_async

from app.core.config import settings
from app.core.time_utils import serialize_utc_datetime, utcnow

RunStatus = Literal["success", "failed", "skipped"]
TaskStatus = Literal["idle", "running", "failed", "disabled"]

_TELEMETRY_PREFIX = "admin:system-task"
_TELEMETRY_TTL_SEC = 30 * 86400
_MAX_MESSAGE_LEN = 400


@dataclass(frozen=True)
class TaskRunOutcome:
    status: RunStatus
    message: str


@dataclass(frozen=True)
class ScheduledTaskDefinition:
    task_id: str
    name: str
    description: str
    schedule_label: str
    interval_seconds: int | None = None
    daily_hour_utc: int | None = None
    enabled: bool = True
    can_run_now: bool = True
    task_type: Literal["scheduled", "system"] = "scheduled"
    executor: str = "scheduler"


def _definitions() -> tuple[ScheduledTaskDefinition, ...]:
    audit_hour = settings.AUDIT_LOG_CLEANUP_HOUR_UTC
    if not 0 <= audit_hour <= 23:
        audit_hour = 3
    recommendation_hour = settings.RECOMMENDATION_METRICS_AGG_HOUR_UTC
    if not 0 <= recommendation_hour <= 23:
        recommendation_hour = 4

    return (
        ScheduledTaskDefinition(
            task_id="refresh_token_cleanup",
            name="Refresh Token 清理",
            description="删除过期或已撤销超过 24 小时的 refresh token。",
            schedule_label="每 6 小时",
            interval_seconds=6 * 3600,
        ),
        ScheduledTaskDefinition(
            task_id="staging_cleanup",
            name="暂存文件清理",
            description="清理导入流水线遗留的过期 staging 对象。",
            schedule_label="每 1 小时",
            interval_seconds=3600,
        ),
        ScheduledTaskDefinition(
            task_id="audit_log_cleanup",
            name="审计日志清理",
            description=f"按保留策略删除超过 {settings.AUDIT_LOG_RETENTION_DAYS} 天的管理员审计日志。",
            schedule_label=f"每天 {audit_hour:02d}:00 UTC",
            daily_hour_utc=audit_hour,
            enabled=bool(settings.AUDIT_LOG_CLEANUP_ENABLED),
        ),
        ScheduledTaskDefinition(
            task_id="recommendation_metrics_daily",
            name="推荐指标聚合",
            description="聚合昨日推荐指标并清理超过保留期的推荐日志。",
            schedule_label=f"每天 {recommendation_hour:02d}:00 UTC",
            daily_hour_utc=recommendation_hour,
            enabled=bool(settings.RECOMMENDATION_METRICS_AGG_ENABLED),
        ),
        ScheduledTaskDefinition(
            task_id="export_cleanup",
            name="导出文件清理",
            description=f"清理过期导出文件、快照与任务记录（保留 {settings.EXPORT_RETENTION_DAYS} 天）。",
            schedule_label="每 1 小时",
            interval_seconds=3600,
        ),
        ScheduledTaskDefinition(
            task_id="postgres_backup",
            name="PostgreSQL 数据备份",
            description="生产数据库全量备份；周期调度由宿主机 systemd timer 负责，后台仅提供状态观测与手动备份。",
            schedule_label="每天 03:00（systemd）",
            enabled=bool(settings.POSTGRES_BACKUP_ENABLED),
            can_run_now=True,
            task_type="system",
            executor="systemd",
        ),
    )


def get_scheduled_task_definition(task_id: str) -> ScheduledTaskDefinition | None:
    return next((item for item in _definitions() if item.task_id == task_id), None)


async def _open_redis():
    if not settings.REDIS_URL:
        return None
    return redis_async.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=True,
    )


def _telemetry_key(task_id: str) -> str:
    return f"{_TELEMETRY_PREFIX}:{task_id}"


async def _write_telemetry(task_id: str, values: dict[str, str | int | float]) -> None:
    client = await _open_redis()
    if client is None:
        return
    try:
        mapping = {key: str(value) for key, value in values.items()}
        await client.hset(_telemetry_key(task_id), mapping=mapping)
        await client.expire(_telemetry_key(task_id), _TELEMETRY_TTL_SEC)
    except Exception:
        # Observability must never make the business job fail.
        return
    finally:
        await client.aclose()


async def _read_all_telemetry(task_ids: list[str]) -> dict[str, dict[str, str]]:
    client = await _open_redis()
    if client is None:
        return {}
    try:
        pipe = client.pipeline(transaction=False)
        for task_id in task_ids:
            pipe.hgetall(_telemetry_key(task_id))
        rows = await pipe.execute()
        return {task_id: row or {} for task_id, row in zip(task_ids, rows, strict=False)}
    except Exception:
        return {}
    finally:
        await client.aclose()


def _serialize_value(value) -> str:
    if value is None:
        return "执行完成"
    if isinstance(value, TaskRunOutcome):
        return value.message
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    except Exception:
        return str(value)


async def record_system_task_execution(
    task_id: str,
    runner: Callable[[], Awaitable[object]],
    *,
    source: str = "scheduler",
) -> TaskRunOutcome:
    """Execute ``runner`` and persist cross-process run telemetry when Redis exists."""
    started = utcnow()
    started_mono = time.monotonic()
    await _write_telemetry(
        task_id,
        {
            "state": "running",
            "last_started_at": serialize_utc_datetime(started),
            "last_source": source,
        },
    )

    try:
        raw = await runner()
        if isinstance(raw, TaskRunOutcome):
            outcome = raw
        else:
            outcome = TaskRunOutcome(status="success", message=_serialize_value(raw))
    except Exception as exc:
        finished = utcnow()
        await _write_telemetry(
            task_id,
            {
                "state": "idle",
                "last_status": "failed",
                "last_message": str(exc)[:_MAX_MESSAGE_LEN],
                "last_finished_at": serialize_utc_datetime(finished),
                "last_duration_ms": int((time.monotonic() - started_mono) * 1000),
                "last_source": source,
            },
        )
        raise

    finished = utcnow()
    await _write_telemetry(
        task_id,
        {
            "state": "idle",
            "last_status": outcome.status,
            "last_message": outcome.message[:_MAX_MESSAGE_LEN],
            "last_finished_at": serialize_utc_datetime(finished),
            "last_duration_ms": int((time.monotonic() - started_mono) * 1000),
            "last_source": source,
        },
    )
    return outcome


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _next_run_at(definition: ScheduledTaskDefinition, telemetry: dict[str, str], now: datetime) -> str | None:
    if not definition.enabled:
        return None
    if definition.daily_hour_utc is not None:
        candidate = now.replace(hour=definition.daily_hour_utc, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return serialize_utc_datetime(candidate)
    if definition.interval_seconds:
        anchor = _parse_datetime(telemetry.get("last_finished_at")) or now
        candidate = anchor + timedelta(seconds=definition.interval_seconds)
        if candidate <= now:
            candidate = now + timedelta(seconds=definition.interval_seconds)
        return serialize_utc_datetime(candidate)
    return None


async def list_system_scheduled_tasks() -> list[dict]:
    definitions = _definitions()
    telemetry_by_id = await _read_all_telemetry([item.task_id for item in definitions])
    now = utcnow()
    result: list[dict] = []

    backup_info: dict | None = None
    try:
        from app.services.database_backup_service import inspect_database_backup

        backup_info = await inspect_database_backup()
    except Exception:
        # The system task center must remain usable even when host-level
        # observability (systemd/filesystem) is unavailable.
        backup_info = None

    for definition in definitions:
        telemetry = telemetry_by_id.get(definition.task_id, {})
        state = telemetry.get("state")
        last_status = telemetry.get("last_status")
        definition_enabled = definition.enabled
        can_run_now = definition.can_run_now and definition_enabled
        next_run_at = _next_run_at(definition, telemetry, now)
        extra: dict = {}

        if definition.task_id == "postgres_backup" and backup_info is not None:
            definition_enabled = bool(backup_info.get("enabled"))
            can_run_now = bool(backup_info.get("can_run_now"))
            latest = backup_info.get("latest_artifact") or {}
            # systemd owns the schedule.  Prefer its real next-run label instead
            # of pretending the web process knows the host timezone.
            next_run_at = None
            artifact_at = _parse_datetime(str(latest.get("created_at") or ""))
            telemetry_at = _parse_datetime(telemetry.get("last_finished_at"))
            if artifact_at and (telemetry_at is None or artifact_at > telemetry_at):
                telemetry = {
                    **telemetry,
                    "last_finished_at": str(latest.get("created_at")),
                    "last_status": "success",
                    "last_message": f"最近备份：{latest.get('name')}（{latest.get('size_bytes', 0)} bytes）",
                    "last_source": "systemd",
                }
                last_status = "success"
            extra = {
                "executor_available": bool(backup_info.get("systemd_observable")),
                "executor_state": backup_info.get("timer_state"),
                "next_run_label": backup_info.get("next_run_label"),
                "note": backup_info.get("note"),
                "artifact_name": latest.get("name"),
                "artifact_size_bytes": latest.get("size_bytes"),
                "artifact_created_at": latest.get("created_at"),
                "backup_count": int(backup_info.get("backup_count") or 0),
                "backup_dir": backup_info.get("backup_dir"),
                "script_available": bool(backup_info.get("script_available")),
                "pg_dump_available": bool(backup_info.get("pg_dump_available")),
                "timer_unit": backup_info.get("timer_unit"),
                "service_unit": backup_info.get("service_unit"),
                "service_loaded": bool(backup_info.get("service_loaded")),
            }

        if not definition_enabled:
            status: TaskStatus = "disabled"
        elif state == "running":
            status = "running"
        elif last_status == "failed":
            status = "failed"
        else:
            status = "idle"

        result.append(
            {
                "task_id": definition.task_id,
                "name": definition.name,
                "description": definition.description,
                "task_type": definition.task_type,
                "executor": definition.executor,
                "status": status,
                "enabled": definition_enabled,
                "schedule": definition.schedule_label,
                "next_run_at": next_run_at,
                "last_run_at": telemetry.get("last_finished_at") or telemetry.get("last_started_at") or None,
                "last_status": last_status or None,
                "last_message": telemetry.get("last_message") or None,
                "last_duration_ms": int(telemetry["last_duration_ms"]) if telemetry.get("last_duration_ms", "").isdigit() else None,
                "last_source": telemetry.get("last_source") or None,
                "can_run_now": can_run_now,
                **extra,
            }
        )
    return result


async def _run_with_lock(lock_name: str, work: Callable[[], Awaitable[object]], *, ttl: int = 600) -> TaskRunOutcome:
    from app.core.distributed_lock import DistributedLock

    lock = DistributedLock(lock_name, instance_id="admin-system-task")
    async with lock.acquire_and_renew(ttl=ttl, renew_interval=max(30, min(120, ttl // 3))) as handle:
        if not handle.is_still_held():
            return TaskRunOutcome(status="skipped", message="已有实例正在执行，本次已跳过")
        result = await work()
        return TaskRunOutcome(status="success", message=_serialize_value(result))


async def _run_refresh_token_cleanup() -> TaskRunOutcome:
    async def work():
        from app.core.database import async_session
        from app.services import token_service

        async with async_session() as db:
            deleted = await token_service.cleanup_expired_tokens(db)
        return f"清理 {deleted} 条过期 refresh token"

    return await _run_with_lock("token:cleanup", work, ttl=300)


async def _run_staging_cleanup() -> TaskRunOutcome:
    from app.services.staging_storage import async_cleanup_orphans

    removed = await async_cleanup_orphans()
    return TaskRunOutcome(status="success", message=f"清理 {removed} 个过期 staging 对象")


async def _run_audit_cleanup() -> TaskRunOutcome:
    async def work():
        from app.core.database import async_session
        from app.services.admin_audit_service import cleanup_expired_admin_audit_logs

        retention_days = max(7, settings.AUDIT_LOG_RETENTION_DAYS)
        batch_size = max(10, settings.AUDIT_LOG_CLEANUP_BATCH_SIZE)
        async with async_session() as db:
            deleted = await cleanup_expired_admin_audit_logs(
                db,
                retention_days=retention_days,
                batch_size=batch_size,
            )
        return f"删除 {deleted} 条过期审计日志"

    return await _run_with_lock("audit:cleanup", work)


async def _run_recommendation_metrics() -> TaskRunOutcome:
    async def work():
        from datetime import date

        from app.core.database import async_session
        from app.services.recommendation_log_service import cleanup_expired_recommendation_logs
        from app.services.recommendation_metrics_service import aggregate_recommendation_metrics_daily

        target_date = date.today() - timedelta(days=1)
        retention_days = max(7, settings.RECOMMENDATION_LOG_RETENTION_DAYS)
        async with async_session() as db:
            result = await aggregate_recommendation_metrics_daily(db, target_date=target_date)
            await db.commit()
            deleted = await cleanup_expired_recommendation_logs(db, retention_days=retention_days)
        return f"聚合 {result.get('aggregated_rows', 0)} 行，清理 {deleted} 条推荐日志"

    return await _run_with_lock("recommendation:metrics:daily", work)


async def _run_export_cleanup() -> TaskRunOutcome:
    from app.core.database import async_session
    from app.services.export.cleanup import cleanup_expired

    async with async_session() as db:
        stats = await cleanup_expired(db)
    return TaskRunOutcome(
        status="success",
        message=f"过期任务 {stats.get('tasks_expired', 0)}，删除文件 {stats.get('files_deleted', 0)}",
    )


async def _run_postgres_backup() -> TaskRunOutcome:
    from app.services.database_backup_service import run_postgres_backup

    async def work():
        result = await run_postgres_backup()
        return result.message

    # The backup itself can be long-running; the lock prevents an admin run
    # from overlapping another admin run in a shared Redis deployment.
    return await _run_with_lock("system:postgres-backup", work, ttl=max(1800, settings.POSTGRES_BACKUP_TIMEOUT_SEC + 300))


_MANUAL_RUNNERS: dict[str, Callable[[], Awaitable[TaskRunOutcome]]] = {
    "refresh_token_cleanup": _run_refresh_token_cleanup,
    "staging_cleanup": _run_staging_cleanup,
    "audit_log_cleanup": _run_audit_cleanup,
    "recommendation_metrics_daily": _run_recommendation_metrics,
    "export_cleanup": _run_export_cleanup,
    "postgres_backup": _run_postgres_backup,
}


async def run_scheduled_task_now(task_id: str) -> TaskRunOutcome:
    definition = get_scheduled_task_definition(task_id)
    if definition is None:
        raise KeyError(task_id)
    if not definition.enabled:
        return TaskRunOutcome(status="skipped", message="任务已在配置中停用")
    if task_id == "postgres_backup":
        from app.services.database_backup_service import inspect_database_backup

        info = await inspect_database_backup()
        if not info.get("enabled"):
            return TaskRunOutcome(status="skipped", message=info.get("note") or "当前环境不允许 PostgreSQL 备份")
        if not info.get("can_run_now"):
            return TaskRunOutcome(status="skipped", message="未找到备份脚本或 pg_dump，无法从后台立即执行")
    runner = _MANUAL_RUNNERS.get(task_id)
    if runner is None:
        return TaskRunOutcome(status="skipped", message="该任务不支持后台手动执行")
    return await record_system_task_execution(task_id, runner, source="manual")
