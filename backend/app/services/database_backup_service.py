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
    return any(lower.endswith(ext) for ext in _BACKUP_EXTENSIONS)


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


async def _run_command(*args: str, timeout: float, cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str]:
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
    """Return environment, systemd and artifact information for the task center."""
    artifacts = list_backup_artifacts(settings.POSTGRES_BACKUP_HISTORY_LIMIT)
    latest = artifacts[0] if artifacts else None

    timer = await _systemctl_show(
        settings.POSTGRES_BACKUP_TIMER_UNIT,
        ("LoadState", "ActiveState", "SubState", "NextElapseUSecRealtime", "LastTriggerUSec"),
    )
    service = await _systemctl_show(
        settings.POSTGRES_BACKUP_SERVICE_UNIT,
        ("LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus"),
    )
    timer_visible = bool(timer)
    script = resolve_backup_script()
    pg_dump = shutil.which("pg_dump")
    enabled = bool(settings.POSTGRES_BACKUP_ENABLED and is_postgresql_database())

    note: str | None = None
    if not is_postgresql_database():
        note = "当前 DATABASE_URL 不是 PostgreSQL；任务保留展示但不会执行备份。"
    elif not timer_visible:
        note = "当前进程无法读取宿主机 systemd；生产 timer 仍可独立运行。"
    elif timer.get("ActiveState") != "active":
        note = f"systemd timer 当前状态：{timer.get('ActiveState') or 'unknown'}"

    service_loaded = bool(service and service.get("LoadState") == "loaded")

    return {
        "enabled": enabled,
        "database_engine": "postgresql" if is_postgresql_database() else "non-postgresql",
        "backup_dir": str(_configured_backup_dir()),
        "backup_count": len(artifacts),
        "latest_artifact": latest,
        "script_available": bool(script),
        "script_path": str(script) if script else None,
        "pg_dump_available": bool(pg_dump),
        "systemd_observable": timer_visible,
        "timer_unit": settings.POSTGRES_BACKUP_TIMER_UNIT,
        "service_unit": settings.POSTGRES_BACKUP_SERVICE_UNIT,
        "timer_state": timer.get("ActiveState") if timer else None,
        "timer_sub_state": timer.get("SubState") if timer else None,
        "service_state": service.get("ActiveState") if service else None,
        "service_result": service.get("Result") if service else None,
        "service_loaded": service_loaded,
        "next_run_label": timer.get("NextElapseUSecRealtime") or None,
        "last_trigger_label": timer.get("LastTriggerUSec") or None,
        "can_run_now": enabled and bool(script or pg_dump or (timer_visible and service_loaded)),
        "note": note,
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
    before = {row["path"] for row in list_backup_artifacts(100)}
    code, stdout, stderr = await _run_command(
        systemctl,
        "start",
        settings.POSTGRES_BACKUP_SERVICE_UNIT,
        timeout=max(60, settings.POSTGRES_BACKUP_TIMEOUT_SEC),
    )
    if code != 0:
        detail = stderr or stdout or f"exit code {code}"
        raise RuntimeError(f"systemd 备份服务启动失败：{detail[:500]}")
    after = list_backup_artifacts(100)
    new_artifact = next((row for row in after if row["path"] not in before), after[0] if after else None)
    if new_artifact:
        return BackupRunResult(
            message=f"systemd 备份完成：{new_artifact['name']}（{new_artifact['size_bytes']} bytes）",
            artifact_name=new_artifact["name"],
            artifact_path=new_artifact["path"],
            artifact_size_bytes=new_artifact["size_bytes"],
        )
    return BackupRunResult(message="systemd 备份服务执行完成")


async def _run_repository_script(script: Path) -> BackupRunResult:
    before = {row["path"] for row in list_backup_artifacts(100)}
    code, stdout, stderr = await _run_command(
        sys.executable,
        str(script),
        timeout=max(60, settings.POSTGRES_BACKUP_TIMEOUT_SEC),
        cwd=_repo_root(),
        env=os.environ.copy(),
    )
    if code != 0:
        detail = stderr or stdout or f"exit code {code}"
        raise RuntimeError(f"PostgreSQL 备份脚本失败：{detail[:500]}")
    after = list_backup_artifacts(100)
    new_artifact = next((row for row in after if row["path"] not in before), after[0] if after else None)
    detail = stdout or "备份脚本执行成功"
    if new_artifact:
        return BackupRunResult(
            message=f"备份完成：{new_artifact['name']}（{new_artifact['size_bytes']} bytes）",
            artifact_name=new_artifact["name"],
            artifact_path=new_artifact["path"],
            artifact_size_bytes=new_artifact["size_bytes"],
        )
    return BackupRunResult(message=detail[:500])


async def _run_pg_dump_fallback() -> BackupRunResult:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("未找到 scripts/postgres_backup.py，且运行环境没有 pg_dump")
    backup_dir = _configured_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    env, database = _pg_env_and_database()
    timestamp = utcnow().strftime("%Y%m%d_%H%M%S")
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

    stat = artifact.stat()
    sidecar = artifact.with_name(f"{artifact.name}.meta.json")
    metadata = {
        "created_at": serialize_utc_datetime(utcnow()),
        "database": database,
        "method": "pg_dump_fallback",
        "size_bytes": int(stat.st_size),
    }
    try:
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
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

    raise RuntimeError("；".join(errors[-3:]) or "当前运行环境没有可用的 PostgreSQL 备份执行器")
