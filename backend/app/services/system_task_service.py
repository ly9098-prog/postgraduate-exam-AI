"""Admin-facing catalog, execution and telemetry for recurring system jobs.

The production deployment runs scheduler work in a separate process from the
HTTP admin service.  The catalog is deterministic, scheduler/manual execution
shares one code path, and lightweight telemetry is stored in Redis so the admin
UI reports *current executor health* instead of only the last result.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Literal

import redis.asyncio as redis_async

from app.core.config import settings
from app.core.time_utils import (
    normalize_to_naive_utc,
    serialize_utc_datetime,
    shanghai_today,
    utcnow,
)

logger = logging.getLogger(__name__)

RunStatus = Literal["success", "failed", "skipped"]
TaskStatus = Literal["idle", "running", "failed", "disabled", "unavailable", "unobservable"]

_TELEMETRY_PREFIX = "admin:system-task"
_TELEMETRY_TTL_SEC = 30 * 86400
_MAX_MESSAGE_LEN = 400
_SCHEDULER_HEARTBEAT_KEY = f"{_TELEMETRY_PREFIX}:scheduler-heartbeat"
_SCHEDULER_HEARTBEAT_INTERVAL_SEC = 20
_SCHEDULER_HEARTBEAT_TTL_SEC = 75
# Scheduler-role loops register themselves here.  This lets the cross-process
# heartbeat distinguish "scheduler process is alive" from "this specific job
# loop actually started and is still alive".
_SCHEDULER_REGISTERED_TASKS: set[str] = set()


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
    # Deterministic UTC cadence for interval-style jobs.  Keeping the fire
    # minute/hour in the catalog prevents process restart drift.
    cron_minute_utc: int | None = None
    cron_hours_utc: tuple[int, ...] | None = None
    daily_hour_utc: int | None = None
    enabled: bool = True
    can_run_now: bool = True
    task_type: Literal["scheduled", "system"] = "scheduled"
    executor: str = "scheduler"
    requires_database: bool = True


@dataclass(frozen=True)
class SchedulerHealth:
    available: bool
    state: str
    database_available: bool | None = None
    database_note: str | None = None
    task_capabilities: dict[str, bool] | None = None
    task_notes: dict[str, str] | None = None
    registered_tasks: set[str] | None = None


@dataclass(frozen=True)
class TaskCapability:
    """Runtime capability for a maintenance task.

    ``can_run_now`` is the HTTP process' manual-run ability.  The recurring
    executor is represented independently by ``executor_available`` so a task
    does not look healthy merely because the web process can execute it once.
    """

    can_run_now: bool
    executor_available: bool | None = None
    executor_state: str | None = None
    note: str | None = None


def register_scheduler_task(task_id: str) -> None:
    """Mark one recurring loop as started in this scheduler process."""
    if get_scheduled_task_definition(task_id) is None:
        raise KeyError(task_id)
    _SCHEDULER_REGISTERED_TASKS.add(task_id)


def unregister_scheduler_task(task_id: str) -> None:
    """Remove a recurring loop registration on stop/crash."""
    _SCHEDULER_REGISTERED_TASKS.discard(task_id)


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
            schedule_label="每 6 小时（UTC xx:05）",
            interval_seconds=6 * 3600,
            cron_minute_utc=5,
            cron_hours_utc=(0, 6, 12, 18),
        ),
        ScheduledTaskDefinition(
            task_id="staging_cleanup",
            name="暂存文件清理",
            description="清理导入流水线遗留的过期 staging 对象。",
            schedule_label="每 1 小时（UTC xx:00）",
            interval_seconds=3600,
            cron_minute_utc=0,
            requires_database=False,
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
            description="滚动回补最近 7 天推荐指标并清理超过保留期的推荐日志。",
            schedule_label=f"每天 {recommendation_hour:02d}:00 UTC",
            daily_hour_utc=recommendation_hour,
            enabled=bool(settings.RECOMMENDATION_METRICS_AGG_ENABLED),
        ),
        ScheduledTaskDefinition(
            task_id="export_cleanup",
            name="导出文件清理",
            description=(
                "清理过期导出文件与无引用快照，并将任务标记为已过期"
                f"（文件保留 {settings.EXPORT_RETENTION_DAYS} 天）。"
            ),
            schedule_label="每 1 小时（UTC xx:02）",
            interval_seconds=3600,
            cron_minute_utc=2,
        ),
        ScheduledTaskDefinition(
            task_id="postgres_backup",
            name="PostgreSQL 数据备份",
            description=(
                "生产数据库全量备份；周期调度由宿主机 systemd timer 负责，"
                "后台仅提供状态观测与手动备份。"
            ),
            schedule_label="由宿主机 systemd timer 配置",
            enabled=bool(settings.POSTGRES_BACKUP_ENABLED),
            can_run_now=True,
            task_type="system",
            executor="systemd",
            requires_database=False,
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


async def _probe_redis() -> tuple[bool, str | None]:
    """Check Redis used by strict distributed locks."""
    client = await _open_redis()
    if client is None:
        return False, "Redis 未配置，无法获取分布式锁"
    try:
        await asyncio.wait_for(client.ping(), timeout=2.0)
        return True, None
    except Exception as exc:
        return False, f"Redis 不可用，无法获取分布式锁：{type(exc).__name__}"
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def _probe_database() -> tuple[bool, str | None]:
    """Run a bounded SELECT 1 against the configured application database."""
    try:
        from sqlalchemy import text

        from app.core.database import async_session

        async with async_session() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=3.0)
        return True, None
    except Exception as exc:
        return False, f"数据库不可用：{type(exc).__name__}: {str(exc)[:160]}"


async def run_scheduler_heartbeat() -> None:
    """Publish scheduler liveness plus the prerequisites it can actually use."""
    while True:
        db_ok, db_note = await _probe_database()
        task_capabilities: dict[str, bool] = {}
        task_notes: dict[str, str] = {}
        for definition in _definitions():
            if definition.executor != "scheduler":
                continue
            local_ok, local_note = await _task_local_prerequisite(definition.task_id)
            task_capabilities[definition.task_id] = local_ok
            if local_note:
                task_notes[definition.task_id] = local_note

        client = await _open_redis()
        if client is not None:
            try:
                await client.hset(
                    _SCHEDULER_HEARTBEAT_KEY,
                    mapping={
                        "state": "active",
                        "pid": str(os.getpid()),
                        "updated_at": serialize_utc_datetime(utcnow()),
                        "database_available": "1" if db_ok else "0",
                        "database_note": db_note or "",
                        "task_capabilities": json.dumps(task_capabilities, ensure_ascii=False),
                        "task_notes": json.dumps(task_notes, ensure_ascii=False),
                        "registered_tasks": json.dumps(sorted(_SCHEDULER_REGISTERED_TASKS)),
                    },
                )
                await client.expire(_SCHEDULER_HEARTBEAT_KEY, _SCHEDULER_HEARTBEAT_TTL_SEC)
            except Exception:
                # Jobs themselves fail closed on Redis. Telemetry must not
                # crash the scheduler; the next heartbeat retries automatically.
                pass
            finally:
                try:
                    await client.aclose()
                except Exception:
                    pass
        await asyncio.sleep(_SCHEDULER_HEARTBEAT_INTERVAL_SEC)


async def _read_scheduler_heartbeat(redis_available: bool) -> SchedulerHealth:
    if not redis_available:
        return SchedulerHealth(False, "redis_unavailable")
    client = await _open_redis()
    if client is None:
        return SchedulerHealth(False, "redis_unavailable")
    try:
        row = await client.hgetall(_SCHEDULER_HEARTBEAT_KEY)
        if not row:
            return SchedulerHealth(False, "stopped")
        updated_at = _parse_datetime(row.get("updated_at"))
        if updated_at is None:
            return SchedulerHealth(False, "stale")
        age = (utcnow() - updated_at).total_seconds()
        if age > _SCHEDULER_HEARTBEAT_TTL_SEC:
            return SchedulerHealth(False, "stale")

        db_raw = row.get("database_available")
        database_available = None if db_raw not in ("0", "1") else db_raw == "1"
        try:
            task_capabilities = json.loads(row.get("task_capabilities") or "{}")
            if not isinstance(task_capabilities, dict):
                task_capabilities = {}
        except (TypeError, ValueError):
            task_capabilities = {}
        try:
            task_notes = json.loads(row.get("task_notes") or "{}")
            if not isinstance(task_notes, dict):
                task_notes = {}
        except (TypeError, ValueError):
            task_notes = {}

        try:
            registered_raw = json.loads(row.get("registered_tasks") or "[]")
            registered_tasks = (
                {str(item) for item in registered_raw}
                if isinstance(registered_raw, list)
                else set()
            )
        except (TypeError, ValueError):
            registered_tasks = set()

        return SchedulerHealth(
            True,
            "active",
            database_available=database_available,
            database_note=row.get("database_note") or None,
            task_capabilities={str(k): bool(v) for k, v in task_capabilities.items()},
            task_notes={str(k): str(v) for k, v in task_notes.items()},
            registered_tasks=registered_tasks,
        )
    except Exception:
        return SchedulerHealth(False, "unobservable")
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


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
        try:
            await client.aclose()
        except Exception:
            pass


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
        try:
            await client.aclose()
        except Exception:
            pass


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
    """Execute ``runner`` and persist cross-process run telemetry when possible."""
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
        outcome = raw if isinstance(raw, TaskRunOutcome) else TaskRunOutcome(
            status="success", message=_serialize_value(raw)
        )
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
        return normalize_to_naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _next_run_datetime(definition: ScheduledTaskDefinition, now: datetime) -> datetime | None:
    """Return the next deterministic UTC fire time for one catalogued task."""
    if not definition.enabled:
        return None

    if definition.daily_hour_utc is not None:
        candidate = now.replace(
            hour=definition.daily_hour_utc, minute=0, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if definition.cron_minute_utc is not None:
        minute = max(0, min(int(definition.cron_minute_utc), 59))
        hours = definition.cron_hours_utc
        if hours:
            normalized_hours = sorted({max(0, min(int(hour), 23)) for hour in hours})
            for day_offset in (0, 1):
                day = now + timedelta(days=day_offset)
                for hour in normalized_hours:
                    candidate = day.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    if candidate > now:
                        return candidate
            return None

        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        return candidate

    if definition.interval_seconds:
        return now + timedelta(seconds=definition.interval_seconds)
    return None


def _next_run_at(
    definition: ScheduledTaskDefinition,
    telemetry: dict[str, str],
    now: datetime,
) -> str | None:
    del telemetry  # manual runs must not shift deterministic scheduler slots
    candidate = _next_run_datetime(definition, now)
    return serialize_utc_datetime(candidate) if candidate is not None else None


def seconds_until_scheduled_task(task_id: str, now: datetime | None = None) -> float:
    """Seconds until the next real scheduler fire time for ``task_id``."""
    definition = get_scheduled_task_definition(task_id)
    if definition is None:
        raise KeyError(task_id)
    current = normalize_to_naive_utc(now or utcnow())
    candidate = _next_run_datetime(definition, current)
    if candidate is None:
        raise ValueError(f"Task {task_id} has no recurring schedule")
    return max(0.05, (candidate - current).total_seconds())


async def run_registered_periodic_task(task_id: str, label: str | None = None) -> None:
    """Run a deterministic scheduler loop and publish per-task liveness.

    ``main.py`` (single-process/local ``all`` role) and the standalone scheduler
    bootstrap both call this function. Keeping the sleep/execute/register logic
    here prevents the two process entry points from drifting apart.
    """
    definition = get_scheduled_task_definition(task_id)
    if definition is None:
        raise KeyError(task_id)
    if definition.executor != "scheduler":
        raise ValueError(f"Task {task_id} is not owned by the application scheduler")

    display_name = label or definition.name
    register_scheduler_task(task_id)
    try:
        while True:
            await asyncio.sleep(seconds_until_scheduled_task(task_id))
            try:
                outcome = await execute_scheduled_task(task_id, source="scheduler")
                if outcome.status == "failed":
                    logger.warning("%s task failed: %s", display_name, outcome.message)
                elif outcome.status == "skipped":
                    logger.info("%s task skipped: %s", display_name, outcome.message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("%s task failed (non-fatal): %s", display_name, exc)
    finally:
        unregister_scheduler_task(task_id)


async def _task_local_prerequisite(task_id: str) -> tuple[bool, str | None]:
    """Check inexpensive task-specific prerequisites without executing work."""
    try:
        if task_id == "staging_cleanup":
            from app.services.staging_storage import inspect_staging_cleanup_capability

            return await asyncio.to_thread(inspect_staging_cleanup_capability)
        if task_id == "export_cleanup":
            from app.services.export.cleanup import inspect_export_cleanup_capability

            return await asyncio.to_thread(inspect_export_cleanup_capability)
    except Exception as exc:
        return False, f"运行条件检查失败：{type(exc).__name__}: {str(exc)[:180]}"
    return True, None


async def _task_capability(
    definition: ScheduledTaskDefinition,
    *,
    redis_available: bool,
    database_available: bool,
    database_note: str | None,
    scheduler_health: SchedulerHealth,
    local_prerequisite: tuple[bool, str | None] | None = None,
) -> TaskCapability:
    if not definition.enabled:
        return TaskCapability(
            can_run_now=False,
            executor_available=(scheduler_health.available if definition.executor == "scheduler" else None),
            executor_state=(scheduler_health.state if definition.executor == "scheduler" else None),
            note="任务已在配置中停用",
        )

    local_ok, local_note = (
        local_prerequisite
        if local_prerequisite is not None
        else await _task_local_prerequisite(definition.task_id)
    )
    manual_db_ok = database_available or not definition.requires_database
    can_run_now = bool(definition.can_run_now and redis_available and local_ok and manual_db_ok)

    scheduler_local_ok = True
    scheduler_local_note: str | None = None
    if definition.executor == "scheduler":
        caps = scheduler_health.task_capabilities or {}
        notes = scheduler_health.task_notes or {}
        # A new scheduler heartbeat should explicitly report task capability.
        # Missing data means the scheduler is not fully observable, not healthy.
        if definition.task_id in caps:
            scheduler_local_ok = bool(caps[definition.task_id])
            scheduler_local_note = notes.get(definition.task_id)
        else:
            scheduler_local_ok = False
            scheduler_local_note = "scheduler 未上报该任务的运行条件"

    scheduler_db_ok = (
        not definition.requires_database
        or scheduler_health.database_available is True
    )
    scheduler_registered = (
        definition.task_id in (scheduler_health.registered_tasks or set())
    )
    executor_available = bool(
        scheduler_health.available
        and redis_available
        and scheduler_registered
        and scheduler_local_ok
        and scheduler_db_ok
    )
    executor_state = scheduler_health.state
    if scheduler_health.available and not scheduler_registered:
        executor_state = "loop_unavailable"
    elif scheduler_health.available and not scheduler_db_ok:
        executor_state = (
            "database_unobservable"
            if scheduler_health.database_available is None
            else "database_unavailable"
        )
    elif scheduler_health.available and not scheduler_local_ok:
        executor_state = "prerequisite_failed"

    notes_out: list[str] = []
    if not redis_available:
        notes_out.append("Redis 不可用，分布式锁无法工作")
    if definition.requires_database and not database_available:
        notes_out.append(database_note or "当前 Web 进程数据库不可用，不能手动执行")
    if not local_ok and local_note:
        notes_out.append(local_note)
    if definition.executor == "scheduler":
        if not scheduler_health.available:
            if scheduler_health.state == "stopped":
                notes_out.append("未检测到 scheduler 心跳，定时执行当前不可用")
            elif scheduler_health.state == "stale":
                notes_out.append("scheduler 心跳已过期，定时执行当前不可用")
            elif scheduler_health.state == "redis_unavailable":
                notes_out.append("无法通过 Redis 观测 scheduler，且定时任务锁不可用")
            else:
                notes_out.append("scheduler 状态不可观测")
        elif not scheduler_registered:
            notes_out.append("scheduler 进程在线，但该任务的周期执行循环未启动")
        elif not scheduler_db_ok:
            notes_out.append(
                scheduler_health.database_note
                or "scheduler 无法确认数据库连接，定时执行当前不可用"
            )
        elif not scheduler_local_ok:
            notes_out.append(scheduler_local_note or "scheduler 任务运行条件不满足")

    return TaskCapability(
        can_run_now=can_run_now,
        executor_available=(executor_available if definition.executor == "scheduler" else None),
        executor_state=(executor_state if definition.executor == "scheduler" else None),
        note="；".join(dict.fromkeys(notes_out)) or None,
    )


def _running_telemetry_is_stale(
    definition: ScheduledTaskDefinition,
    telemetry: dict[str, str],
    now: datetime,
) -> bool:
    if telemetry.get("state") != "running":
        return False
    started = _parse_datetime(telemetry.get("last_started_at"))
    if started is None:
        return True
    stale_after = 6 * 3600
    if definition.task_id == "postgres_backup":
        stale_after = max(stale_after, int(settings.POSTGRES_BACKUP_TIMEOUT_SEC) + 900)
    return (now - started).total_seconds() > stale_after


async def list_system_scheduled_tasks() -> list[dict]:
    definitions = _definitions()
    now = utcnow()
    result: list[dict] = []

    async def _inspect_backup_safe() -> tuple[dict | None, str | None]:
        try:
            from app.services.database_backup_service import inspect_database_backup

            return await inspect_database_backup(), None
        except Exception as exc:
            return None, (
                f"备份运行条件检查失败：{type(exc).__name__}: {str(exc)[:180]}"
            )

    # The task-center endpoint is operational telemetry, so degraded Redis, DB
    # or systemd must not make every probe wait serially for its timeout.  Run
    # independent checks concurrently and reuse task-local prerequisite results
    # rather than probing the same filesystem/backend twice per request.
    telemetry_coro = _read_all_telemetry([item.task_id for item in definitions])
    local_coro = asyncio.gather(
        *(_task_local_prerequisite(item.task_id) for item in definitions)
    )
    (
        telemetry_by_id,
        redis_probe,
        database_probe,
        backup_probe,
        local_rows,
    ) = await asyncio.gather(
        telemetry_coro,
        _probe_redis(),
        _probe_database(),
        _inspect_backup_safe(),
        local_coro,
    )
    redis_available, _redis_note = redis_probe
    database_available, database_note = database_probe
    backup_info, backup_inspect_error = backup_probe
    local_prerequisites = {
        definition.task_id: row
        for definition, row in zip(definitions, local_rows, strict=True)
    }
    scheduler_health = await _read_scheduler_heartbeat(redis_available)

    for definition in definitions:
        telemetry = telemetry_by_id.get(definition.task_id, {})
        state = telemetry.get("state")
        stale_running = _running_telemetry_is_stale(definition, telemetry, now)
        if stale_running:
            state = "stale"
        last_status = telemetry.get("last_status")
        definition_enabled = definition.enabled
        capability = await _task_capability(
            definition,
            redis_available=redis_available,
            database_available=database_available,
            database_note=database_note,
            scheduler_health=scheduler_health,
            local_prerequisite=local_prerequisites.get(definition.task_id),
        )
        can_run_now = capability.can_run_now
        next_run_at = (
            _next_run_at(definition, telemetry, now)
            if definition.executor != "scheduler" or capability.executor_available is True
            else None
        )
        extra: dict = {}

        if definition.task_id == "postgres_backup":
            next_run_at = None
            if backup_info is None:
                can_run_now = False
                extra = {
                    "executor_available": None,
                    "executor_state": "unobservable",
                    "next_run_label": "systemd 状态不可观测",
                    "note": backup_inspect_error or "PostgreSQL 备份状态暂不可观测",
                }
            else:
                definition_enabled = bool(backup_info.get("enabled"))
                can_run_now = bool(backup_info.get("can_run_now")) and redis_available
                latest = backup_info.get("latest_artifact") or {}

                artifact_at = _parse_datetime(str(latest.get("created_at") or ""))
                telemetry_at = _parse_datetime(telemetry.get("last_finished_at"))
                if artifact_at and (telemetry_at is None or artifact_at > telemetry_at):
                    telemetry = {
                        **telemetry,
                        "state": "idle",
                        "last_finished_at": str(latest.get("created_at")),
                        "last_status": "success",
                        "last_message": (
                            f"最近备份：{latest.get('name')}"
                            f"（{latest.get('size_bytes', 0)} bytes）"
                        ),
                        # The artifact proves a backup happened, but not which
                        # executor created it (host timer, script, or operator).
                        "last_source": "external_artifact",
                    }
                    last_status = "success"
                    state = "idle"
                    stale_running = False

                backup_note = str(backup_info.get("note") or "").strip()
                if not redis_available:
                    backup_note = "；".join(
                        part
                        for part in (backup_note, "Redis 不可用，无法获取手动备份分布式锁")
                        if part
                    )
                timer_active = backup_info.get("timer_active")
                extra = {
                    "executor_available": timer_active,
                    "executor_state": (
                        backup_info.get("timer_state")
                        if backup_info.get("timer_observable")
                        else "unobservable"
                    ),
                    "next_run_label": (
                        backup_info.get("next_run_label")
                        if timer_active is True
                        else (
                            "systemd timer 未激活"
                            if timer_active is False
                            else "systemd 状态不可观测"
                        )
                    ),
                    "note": backup_note or None,
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
        elif definition.executor == "scheduler":
            extra = {
                "executor_available": capability.executor_available,
                "executor_state": capability.executor_state,
                "next_run_label": (
                    None if capability.executor_available is True else "定时执行当前不可用"
                ),
                "note": capability.note,
            }

        if stale_running:
            stale_note = (
                "检测到过期的运行中遥测，上一执行进程可能异常退出；"
                "当前状态不再视为正在运行"
            )
            extra["note"] = "；".join(
                part
                for part in (str(extra.get("note") or "").strip(), stale_note)
                if part
            )

        if not definition_enabled:
            status: TaskStatus = "disabled"
        elif state == "running":
            status = "running"
        elif state == "stale":
            status = "unavailable"
        elif definition.executor == "scheduler" and capability.executor_available is False:
            status = "unavailable"
        elif definition.executor == "systemd" and extra.get("executor_available") is False:
            status = "unavailable"
        elif definition.executor == "systemd" and extra.get("executor_available") is None:
            status = "unobservable"
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
                "last_run_at": (
                    telemetry.get("last_finished_at")
                    or telemetry.get("last_started_at")
                    or None
                ),
                "last_status": last_status or None,
                "last_message": telemetry.get("last_message") or None,
                "last_duration_ms": (
                    int(telemetry["last_duration_ms"])
                    if telemetry.get("last_duration_ms", "").isdigit()
                    else None
                ),
                "last_source": telemetry.get("last_source") or None,
                "can_run_now": can_run_now,
                **extra,
            }
        )
    return result


async def _run_with_lock(
    task_id: str,
    source: str,
    lock_name: str,
    work: Callable[[], Awaitable[object]],
    *,
    ttl: int = 600,
) -> TaskRunOutcome:
    """Acquire the task lock before publishing a ``running`` telemetry state.

    A competing manual/scheduler invocation must not overwrite the telemetry of
    the instance that actually owns the distributed lock.  Therefore skipped
    lock attempts return immediately and only the lock owner enters
    ``record_system_task_execution``.
    """
    from app.core.distributed_lock import DistributedLock

    lock = DistributedLock(lock_name, instance_id="admin-system-task")
    try:
        async with lock.acquire_and_renew(
            ttl=ttl,
            renew_interval=max(30, min(120, ttl // 3)),
        ) as handle:
            if not handle.is_still_held():
                redis_ok, redis_note = await _probe_redis()
                if not redis_ok:
                    return TaskRunOutcome(
                        status="failed",
                        message=redis_note or "Redis 不可用，无法获取分布式锁",
                    )
                return TaskRunOutcome(status="skipped", message="已有实例正在执行，本次已跳过")

            async def locked_work() -> TaskRunOutcome:
                value = await work()
                if not handle.is_still_held():
                    return TaskRunOutcome(
                        status="failed",
                        message="执行期间分布式锁已丢失；任务为幂等操作，可在锁恢复后重试核查",
                    )
                if isinstance(value, TaskRunOutcome):
                    return value
                return TaskRunOutcome(status="success", message=_serialize_value(value))

            return await record_system_task_execution(
                task_id, locked_work, source=source
            )
    finally:
        await lock.close()


async def _run_refresh_token_cleanup(source: str) -> TaskRunOutcome:
    async def work():
        from app.core.database import async_session
        from app.services import token_service

        async with async_session() as db:
            deleted = await token_service.cleanup_expired_tokens(db)
        return f"清理 {deleted} 条过期 refresh token"

    return await _run_with_lock(
        "refresh_token_cleanup", source, "token:cleanup", work, ttl=300
    )


async def _run_staging_cleanup(source: str) -> TaskRunOutcome:
    async def work():
        from app.services.staging_storage import async_cleanup_orphans

        removed = await async_cleanup_orphans()
        return f"清理 {removed} 个过期/孤立 staging 条目"

    return await _run_with_lock(
        "staging_cleanup", source, "staging:cleanup", work, ttl=900
    )


async def _run_audit_cleanup(source: str) -> TaskRunOutcome:
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

    return await _run_with_lock(
        "audit_log_cleanup", source, "audit:cleanup", work
    )


async def _run_recommendation_metrics(source: str) -> TaskRunOutcome:
    async def work():
        from app.core.database import async_session
        from app.services.recommendation_log_service import cleanup_expired_recommendation_logs
        from app.services.recommendation_metrics_service import aggregate_recommendation_metrics_daily

        retention_days = max(7, settings.RECOMMENDATION_LOG_RETENTION_DAYS)
        # Recompute a short rolling window instead of only "yesterday". The
        # UPSERT aggregation is idempotent, so this repairs brief scheduler
        # downtime and also captures recommendations answered a little later.
        repair_days = min(7, retention_days)
        today = shanghai_today()
        aggregate_rows = 0
        failed_dates: list[str] = []
        async with async_session() as db:
            for offset in range(repair_days, 0, -1):
                target_date = today - timedelta(days=offset)
                try:
                    aggregate_result = await aggregate_recommendation_metrics_daily(
                        db, target_date=target_date
                    )
                    await db.commit()
                    aggregate_rows += int(aggregate_result.get("aggregated_rows", 0) or 0)
                except Exception:
                    failed_dates.append(str(target_date))
                    await db.rollback()

            # Source logs are the only material from which a failed daily
            # aggregation can be repaired. Never prune them in the same run
            # when any repair date failed, especially when retention is the
            # minimum seven days and the oldest repair day sits on the cutoff.
            deleted = 0
            if not failed_dates:
                deleted = await cleanup_expired_recommendation_logs(
                    db, retention_days=retention_days
                )

        message = (
            f"回补最近 {repair_days} 天，聚合 {aggregate_rows} 行，"
            f"清理 {deleted} 条推荐日志"
        )
        if failed_dates:
            return TaskRunOutcome(
                status="failed",
                message=(
                    f"{message}；失败日期：{', '.join(failed_dates)}；"
                    "为保留回补数据，本轮未执行推荐日志清理"
                ),
            )
        return message

    return await _run_with_lock(
        "recommendation_metrics_daily",
        source,
        "recommendation:metrics:daily",
        work,
    )


async def _run_export_cleanup(source: str) -> TaskRunOutcome:
    async def work():
        from app.core.database import async_session
        from app.services.export.cleanup import cleanup_expired

        async with async_session() as db:
            stats = await cleanup_expired(db)
        message = (
            f"过期任务 {stats.get('tasks_expired', 0)}，"
            f"删除文件 {stats.get('files_deleted', 0)}，"
            f"删除快照 {stats.get('snapshots_deleted', 0)}"
        )
        failures = (
            int(stats.get("files_delete_failed", 0))
            + int(stats.get("snapshots_delete_failed", 0))
            + int(stats.get("db_failures", 0))
        )
        if failures:
            details = [f"失败 {failures} 项"]
            if stats.get("limit_reached"):
                details.append("本轮达到处理上限，剩余任务将在下轮继续")
            return TaskRunOutcome(status="failed", message=f"{message}；{'；'.join(details)}")
        if stats.get("limit_reached"):
            message = f"{message}；本轮达到处理上限，剩余任务将在下轮继续"
        return TaskRunOutcome(status="success", message=message)

    return await _run_with_lock(
        "export_cleanup", source, "export:cleanup", work, ttl=1800
    )


async def _run_postgres_backup(source: str) -> TaskRunOutcome:
    from app.services.database_backup_service import run_postgres_backup

    async def work():
        backup_result = await run_postgres_backup()
        return backup_result.message

    return await _run_with_lock(
        "postgres_backup",
        source,
        "system:postgres-backup",
        work,
        ttl=max(1800, settings.POSTGRES_BACKUP_TIMEOUT_SEC + 300),
    )


_MANUAL_RUNNERS: dict[str, Callable[[str], Awaitable[TaskRunOutcome]]] = {
    "refresh_token_cleanup": _run_refresh_token_cleanup,
    "staging_cleanup": _run_staging_cleanup,
    "audit_log_cleanup": _run_audit_cleanup,
    "recommendation_metrics_daily": _run_recommendation_metrics,
    "export_cleanup": _run_export_cleanup,
    "postgres_backup": _run_postgres_backup,
}


async def execute_scheduled_task(task_id: str, *, source: str) -> TaskRunOutcome:
    """Execute one task through the same code path used by production scheduling.

    Capability checks run before lock acquisition.  Execution telemetry starts
    only after the distributed lock has been acquired, so a competing "run now"
    request cannot make a genuinely running scheduler job appear idle/skipped.
    """
    definition = get_scheduled_task_definition(task_id)
    if definition is None:
        raise KeyError(task_id)
    if not definition.enabled:
        return TaskRunOutcome(status="skipped", message="任务已在配置中停用")

    runner = _MANUAL_RUNNERS.get(task_id)
    if runner is None:
        return TaskRunOutcome(status="skipped", message="该任务不支持后台手动执行")

    if task_id == "postgres_backup":
        if source != "manual":
            return TaskRunOutcome(status="skipped", message="PostgreSQL 周期备份由 systemd 负责")
        from app.services.database_backup_service import inspect_database_backup

        info = await inspect_database_backup()
        if not info.get("enabled"):
            return TaskRunOutcome(
                status="skipped",
                message=info.get("note") or "当前环境不允许 PostgreSQL 备份",
            )
        if not info.get("can_run_now"):
            return TaskRunOutcome(
                status="skipped",
                message=info.get("note") or "当前没有可验证的 PostgreSQL 手动备份执行路径",
            )

    redis_ok, redis_note = await _probe_redis()
    local_ok, local_note = await _task_local_prerequisite(task_id)
    if not redis_ok:
        return TaskRunOutcome(
            status="failed",
            message=redis_note or "Redis 不可用，无法获取分布式锁",
        )
    if definition.requires_database:
        db_ok, db_note = await _probe_database()
        if not db_ok:
            return TaskRunOutcome(status="failed", message=db_note or "数据库不可用")
    if not local_ok:
        return TaskRunOutcome(status="failed", message=local_note or "任务运行条件不满足")
    return await runner(source)


async def run_scheduled_task_now(task_id: str) -> TaskRunOutcome:
    return await execute_scheduled_task(task_id, source="manual")
