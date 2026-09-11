"""PostgreSQL backup observability and manual-run integration for the admin task center.

The production deployment already owns the recurring backup schedule through
``systemd`` (``postgres-backup.timer`` -> ``postgres-backup.service``).  The
admin API does *not* create a second scheduler.  It only:

* inspects the timer/service when systemd is visible from the process,
* discovers recent backup artifacts from the configured backup directory,
* invokes the existing ``scripts/postgres_backup.py`` for an explicit admin
  "run now" request,
* falls back to a conservative ``pg_dump --format=custom`` execution when the
  repository backup script is not present but pg_dump is available.

This keeps a single production schedule while making the task visible and
operable from ``/system/tasks``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.time_utils import serialize_utc_datetime, utcnow

_BACKUP_EXTENSIONS = (".dump", ".backup", ".sql", ".sql.gz", ".dump.gz", ".tar")
_MAX_OUTPUT_LEN = 800


@dataclass(frozen=True)
class BackupRunResult:
    message: str
    artifact_name: str | None = None
    artifact_path: str | None = None
    artifact_size_bytes: int | None = None


def is_postgresql_database() -> bool:
    return settings.DATABASE_URL.lower().startswith(("postgresql://", "postgresql+"))


def _repo_root() -> Path:
    # backend/app/services/database_backup_service.py -> repository root
    return Path(__file__).resolve().parents[3]


def _configured_backup_dir() -> Path:
    raw = (settings.POSTGRES_BACKUP_DIR or os.environ.get("BACKUP_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_repo_root() / "backups" / "postgres").resolve()


def _backup_location_label() -> str:
    """Return a non-sensitive label suitable for admin API responses."""
    path = _configured_backup_dir()
    return path.name or "configured-backup-directory"


def _script_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = (settings.POSTGRES_BACKUP_SCRIPT or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    root = _repo_root()
    candidates.extend(
        [
            root / "scripts" / "postgres_backup.py",
            root / "backend" / "scripts" / "postgres_backup.py",
            Path.cwd() / "scripts" / "postgres_backup.py",
            Path.cwd().parent / "scripts" / "postgres_backup.py",
        ]
    )
    # Preserve order while removing duplicates.
    result: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        resolved = item.resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def resolve_backup_script() -> Path | None:
    return next((path for path in _script_candidates() if path.is_file()), None)


def _is_backup_artifact(path: Path) -> bool:
    if not path.is_file() or path.name.endswith(".meta.json"):
        return False
    lower = path.name.lower()
    if not any(lower.endswith(ext) for ext in _BACKUP_EXTENSIONS):
        return False
    try:
        # A zero-byte dump must never be treated as a successful backup.
        return path.stat().st_size > 0
    except OSError:
        return False


def _artifact_fingerprint() -> dict[str, tuple[int, int]]:
    """Snapshot visible non-empty backup artifacts as path -> (mtime_ns, size)."""
    result: dict[str, tuple[int, int]] = {}
    backup_dir = _configured_backup_dir()
    if not backup_dir.is_dir():
        return result
    try:
        for path in backup_dir.iterdir():
            if not _is_backup_artifact(path):
                continue
            stat = path.stat()
            result[str(path.resolve())] = (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return result
    return result


def _new_or_changed_artifact(
    before: dict[str, tuple[int, int]],
) -> dict[str, Any] | None:
    """Return the newest artifact created or materially changed since ``before``."""
    candidates: list[Path] = []
    backup_dir = _configured_backup_dir()
    if not backup_dir.is_dir():
        return None
    try:
        for path in backup_dir.iterdir():
            if not _is_backup_artifact(path):
                continue
            stat = path.stat()
            key = str(path.resolve())
            current = (int(stat.st_mtime_ns), int(stat.st_size))
            if before.get(key) != current:
                candidates.append(path)
        candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    except OSError:
        return None
    for path in candidates:
        try:
            return _artifact_row(path)
        except OSError:
            continue
    return None


def _inspect_backup_directory() -> tuple[bool, str | None]:
    """Check that this process can observe and verify backup artifacts."""
    backup_dir = _configured_backup_dir()
    if not backup_dir.is_dir():
        return False, "配置的备份目录不存在或当前进程不可见"
    required = os.R_OK | os.W_OK | os.X_OK
    if not os.access(backup_dir, required):
        return False, "配置的备份目录当前进程不可读写"
    return True, None


def _artifact_row(path: Path) -> dict[str, Any]:
    stat = path.stat()
    created = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    metadata: dict[str, Any] = {}
    sidecar = path.with_name(f"{path.name}.meta.json")
    if sidecar.is_file():
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            metadata = {}
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "created_at": metadata.get("created_at") or serialize_utc_datetime(created),
        "method": metadata.get("method") or "external",
        "database": metadata.get("database"),
    }


def count_backup_artifacts() -> int:
    """Count visible non-empty backup artifacts without history truncation."""
    backup_dir = _configured_backup_dir()
    if not backup_dir.is_dir():
        return 0
    try:
        return sum(1 for path in backup_dir.iterdir() if _is_backup_artifact(path))
    except OSError:
        return 0


def list_backup_artifacts(limit: int | None = None) -> list[dict[str, Any]]:
    backup_dir = _configured_backup_dir()
    if not backup_dir.is_dir():
        return []
    try:
        files = [path for path in backup_dir.iterdir() if _is_backup_artifact(path)]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    max_items = max(1, min(limit or settings.POSTGRES_BACKUP_HISTORY_LIMIT, 100))
    rows: list[dict[str, Any]] = []
    for path in files[:max_items]:
        try:
            rows.append(_artifact_row(path))
        except OSError:
            continue
    return rows


async def _run_command(
    *args: str,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError(f"命令执行超过 {int(timeout)} 秒，已终止")
    return (
        int(process.returncode or 0),
        stdout.decode("utf-8", errors="replace")[-_MAX_OUTPUT_LEN:].strip(),
        stderr.decode("utf-8", errors="replace")[-_MAX_OUTPUT_LEN:].strip(),
    )


async def _systemctl_show(unit: str, properties: tuple[str, ...]) -> dict[str, str]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {}
    args = [systemctl, "show", unit, "--no-pager"]
    for prop in properties:
        args.extend(["--property", prop])
    try:
        code, stdout, _ = await _run_command(*args, timeout=2.5)
    except (OSError, RuntimeError):
        return {}
    if code != 0:
        return {}
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value
    return values


async def inspect_database_backup() -> dict[str, Any]:
    """Return environment, executor and artifact health for the task center."""
    artifacts = list_backup_artifacts(settings.POSTGRES_BACKUP_HISTORY_LIMIT)
    artifact_count = count_backup_artifacts()
    latest = artifacts[0] if artifacts else None

    timer, service = await asyncio.gather(
        _systemctl_show(
            settings.POSTGRES_BACKUP_TIMER_UNIT,
            (
                "LoadState",
                "ActiveState",
                "SubState",
                "NextElapseUSecRealtime",
                "LastTriggerUSec",
            ),
        ),
        _systemctl_show(
            settings.POSTGRES_BACKUP_SERVICE_UNIT,
            ("LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus"),
        ),
    )
    timer_observable = bool(timer)
    systemd_observable = bool(timer or service)
    timer_loaded = bool(timer and timer.get("LoadState") == "loaded")
    service_loaded = bool(service and service.get("LoadState") == "loaded")
    timer_active: bool | None
    if not timer_observable:
        timer_active = None
    else:
        timer_active = bool(timer_loaded and timer.get("ActiveState") == "active")

    script = resolve_backup_script()
    pg_dump = shutil.which("pg_dump")
    postgres = is_postgresql_database()
    enabled = bool(settings.POSTGRES_BACKUP_ENABLED and postgres)
    backup_dir_ok, backup_dir_note = _inspect_backup_directory()

    notes: list[str] = []
    if not postgres:
        notes.append("当前 DATABASE_URL 不是 PostgreSQL；任务不会执行备份")
    if backup_dir_note:
        notes.append(backup_dir_note)
    if timer_active is None:
        notes.append("当前进程无法观测宿主机 systemd timer")
    elif timer_active is False:
        notes.append(
            f"systemd timer 未激活（{timer.get('LoadState') or 'unknown'}/{timer.get('ActiveState') or 'unknown'}）"
        )

    # Manual execution can use the deployment-owned oneshot service even when
    # the timer itself is inactive.  Every path still requires a visible,
    # writable backup directory so success can be verified by a real artifact.
    execution_path_available = bool(service_loaded or script or pg_dump)
    can_run_now = bool(enabled and backup_dir_ok and execution_path_available)
    if enabled and backup_dir_ok and not execution_path_available:
        notes.append("未检测到可执行的 systemd service、仓库备份脚本或 pg_dump")

    return {
        "enabled": enabled,
        "database_engine": "postgresql" if postgres else "non-postgresql",
        "backup_dir": _backup_location_label(),
        "backup_dir_available": backup_dir_ok,
        "backup_count": artifact_count,
        "latest_artifact": latest,
        "script_available": bool(script),
        "pg_dump_available": bool(pg_dump),
        "systemd_observable": systemd_observable,
        "timer_observable": timer_observable,
        "timer_active": timer_active,
        "timer_unit": settings.POSTGRES_BACKUP_TIMER_UNIT,
        "service_unit": settings.POSTGRES_BACKUP_SERVICE_UNIT,
        "timer_state": timer.get("ActiveState") if timer else None,
        "timer_sub_state": timer.get("SubState") if timer else None,
        "service_state": service.get("ActiveState") if service else None,
        "service_result": service.get("Result") if service else None,
        "service_loaded": service_loaded,
        "next_run_label": timer.get("NextElapseUSecRealtime") or None,
        "last_trigger_label": timer.get("LastTriggerUSec") or None,
        "can_run_now": can_run_now,
        "note": "；".join(dict.fromkeys(notes)) or None,
    }


def _pg_env_and_database() -> tuple[dict[str, str], str]:
    url = make_url(settings.DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("当前数据库不是 PostgreSQL")
    env = os.environ.copy()
    if url.host:
        env["PGHOST"] = url.host
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    database = url.database or "postgraduate"
    env["PGDATABASE"] = database
    sslmode = url.query.get("sslmode") if url.query else None
    if sslmode:
        env["PGSSLMODE"] = str(sslmode)
    return env, database


async def _run_systemd_service() -> BackupRunResult:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise RuntimeError("systemctl 不可用")
    before = _artifact_fingerprint()
    code, stdout, stderr = await _run_command(
        systemctl,
        "start",
        settings.POSTGRES_BACKUP_SERVICE_UNIT,
        timeout=max(60, settings.POSTGRES_BACKUP_TIMEOUT_SEC),
    )
    if code != 0:
        detail = stderr or stdout or f"exit code {code}"
        raise RuntimeError(f"systemd 备份服务启动失败：{detail[:500]}")

    service = await _systemctl_show(
        settings.POSTGRES_BACKUP_SERVICE_UNIT,
        ("LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus"),
    )
    result = (service.get("Result") or "").lower()
    status = service.get("ExecMainStatus")
    if result not in ("", "success") or status not in (None, "", "0"):
        raise RuntimeError(
            "systemd 备份服务执行失败："
            f"Result={result or 'unknown'}, ExecMainStatus={status or 'unknown'}"
        )

    artifact = _new_or_changed_artifact(before)
    if artifact is None:
        raise RuntimeError(
            "systemd service 已返回，但未发现本次新建或更新的非空备份文件；拒绝标记为成功"
        )
    return BackupRunResult(
        message=f"systemd 备份完成：{artifact['name']}（{artifact['size_bytes']} bytes）",
        artifact_name=artifact["name"],
        artifact_path=artifact["path"],
        artifact_size_bytes=artifact["size_bytes"],
    )


async def _run_repository_script(script: Path) -> BackupRunResult:
    before = _artifact_fingerprint()
    env = os.environ.copy()
    # The service may load configuration from a settings file rather than the
    # parent process environment. Pass the resolved values explicitly so the
    # repository script writes into the same directory that this service
    # observes and verifies, instead of silently succeeding elsewhere.
    env["BACKUP_DIR"] = str(_configured_backup_dir())
    env["DATABASE_URL"] = settings.DATABASE_URL
    code, stdout, stderr = await _run_command(
        sys.executable,
        str(script),
        timeout=max(60, settings.POSTGRES_BACKUP_TIMEOUT_SEC),
        cwd=_repo_root(),
        env=env,
    )
    if code != 0:
        detail = stderr or stdout or f"exit code {code}"
        raise RuntimeError(f"PostgreSQL 备份脚本失败：{detail[:500]}")
    artifact = _new_or_changed_artifact(before)
    if artifact is None:
        detail = (stdout or stderr or "脚本无输出")[:260]
        raise RuntimeError(f"备份脚本退出成功但未产生新的非空备份文件：{detail}")
    return BackupRunResult(
        message=f"备份完成：{artifact['name']}（{artifact['size_bytes']} bytes）",
        artifact_name=artifact["name"],
        artifact_path=artifact["path"],
        artifact_size_bytes=artifact["size_bytes"],
    )


async def _run_pg_dump_fallback() -> BackupRunResult:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("未找到 scripts/postgres_backup.py，且运行环境没有 pg_dump")
    backup_dir = _configured_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    env, database = _pg_env_and_database()
    timestamp = utcnow().strftime("%Y%m%d_%H%M%S_%f")
    artifact = backup_dir / f"{database}_{timestamp}.dump"
    code, stdout, stderr = await _run_command(
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(artifact),
        timeout=max(60, settings.POSTGRES_BACKUP_TIMEOUT_SEC),
        env=env,
    )
    if code != 0:
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass
        detail = stderr or stdout or f"exit code {code}"
        raise RuntimeError(f"pg_dump 备份失败：{detail[:500]}")

    try:
        stat = artifact.stat()
    except OSError as exc:
        raise RuntimeError(f"pg_dump 返回成功但备份文件不可读取：{exc}") from exc
    if stat.st_size <= 0:
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("pg_dump 返回成功但生成了空备份文件，拒绝标记为成功")
    sidecar = artifact.with_name(f"{artifact.name}.meta.json")
    metadata = {
        "created_at": serialize_utc_datetime(utcnow()),
        "database": database,
        "method": "pg_dump_fallback",
        "size_bytes": int(stat.st_size),
    }
    try:
        sidecar.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return BackupRunResult(
        message=f"备份完成：{artifact.name}（{stat.st_size} bytes）",
        artifact_name=artifact.name,
        artifact_path=str(artifact),
        artifact_size_bytes=int(stat.st_size),
    )


async def run_postgres_backup() -> BackupRunResult:
    if not settings.POSTGRES_BACKUP_ENABLED:
        raise RuntimeError("PostgreSQL 备份功能已通过配置停用")
    if not is_postgresql_database():
        raise RuntimeError("当前 DATABASE_URL 不是 PostgreSQL，拒绝执行数据库备份")

    info = await inspect_database_backup()
    errors: list[str] = []

    # Prefer the deployment-owned oneshot service when the backend can reach
    # host systemd.  This executes exactly the same production backup path.
    if info.get("systemd_observable") and info.get("service_loaded"):
        try:
            return await _run_systemd_service()
        except Exception as exc:
            errors.append(str(exc))

    script = resolve_backup_script()
    if script:
        try:
            return await _run_repository_script(script)
        except Exception as exc:
            errors.append(str(exc))

    try:
        return await _run_pg_dump_fallback()
    except Exception as exc:
        errors.append(str(exc))

    raise RuntimeError(
        "；".join(errors[-3:]) or "当前运行环境没有可用的 PostgreSQL 备份执行器"
    )
