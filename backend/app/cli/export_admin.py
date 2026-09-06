"""export_admin — CLI for export task management.

Usage:
    python -m app.cli.export_admin list pending
    python -m app.cli.export_admin list processing
    python -m app.cli.export_admin list zombie
    python -m app.cli.export_admin list failed
    python -m app.cli.export_admin metrics
    python -m app.cli.export_admin cleanup --dry-run
    python -m app.cli.export_admin cleanup --execute --confirm
    python -m app.cli.export_admin orphan-scan
    python -m app.cli.export_admin retry <task_id>
    python -m app.cli.export_admin recover-zombie <task_id>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("cli.export_admin")


def _parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="Export task admin CLI")
    sub = p.add_subparsers(dest="command", required=True)

    # list
    list_p = sub.add_parser("list", help="List tasks by status")
    list_p.add_argument("status", choices=["pending", "processing", "completed", "failed", "expired", "zombie"], help="Task status to list")

    # metrics
    sub.add_parser("metrics", help="Show export metrics")

    # cleanup
    clean_p = sub.add_parser("cleanup", help="Cleanup expired tasks")
    clean_p.add_argument("--dry-run", action="store_true", default=True, help="Report only (default)")
    clean_p.add_argument("--execute", action="store_true", help="Actually run cleanup")
    clean_p.add_argument("--confirm", action="store_true", help="Confirm destructive action")

    # orphan-scan
    sub.add_parser("orphan-scan", help="Scan for orphan files and missing files")

    # retry
    retry_p = sub.add_parser("retry", help="Retry a failed task")
    retry_p.add_argument("task_id", type=int)

    # recover-zombie
    rec_p = sub.add_parser("recover-zombie", help="Recover a zombie task")
    rec_p.add_argument("task_id", type=int)

    return p.parse_args(argv) if argv is not None else p.parse_args()


async def _list_tasks(status: str):
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus

    status_map = {
        "pending": ExportTaskStatus.PENDING,
        "processing": ExportTaskStatus.PROCESSING,
        "completed": ExportTaskStatus.COMPLETED,
        "failed": ExportTaskStatus.FAILED,
        "expired": ExportTaskStatus.EXPIRED,
        "zombie": None,  # special handling
    }
    target_status = status_map[status]

    async with async_session() as db:
        if status == "zombie":
            cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=900)
            from sqlalchemy import func as sa_func
            result = await db.execute(
                select(ExportTask).where(
                    ExportTask.status == ExportTaskStatus.PROCESSING,
                    ExportTask.processing_started_at.isnot(None),
                    sa_func.coalesce(ExportTask.heartbeat_at, ExportTask.processing_started_at) < cutoff,
                )
            )
        else:
            result = await db.execute(
                select(ExportTask).where(ExportTask.status == target_status)
                .order_by(ExportTask.created_at.desc())
                .limit(50)
            )
        tasks = result.scalars().all()

        if not tasks:
            print(f"No tasks with status '{status}'")
            return

        print(f"{'ID':<8} {'User':<8} {'Status':<12} {'Format':<6} {'Count':<6} {'Size':<8} {'Error':<30}")
        print("-" * 80)
        for t in tasks:
            err = (t.error_message or "")[:30]
            print(f"{t.id:<8} {t.user_id:<8} {t.status:<12} {t.file_format:<6} {t.total_count:<6} {t.file_size or 0:<8} {err:<30}")


async def _show_metrics():
    from app.services.export.export_metrics import get_metrics
    # Pretty print
    m = get_metrics()
    for k, v in m.items():
        if isinstance(v, float) and v == int(v):
            v = int(v)
        print(f"{k:50s} {v}")


async def _do_cleanup(dry_run: bool, confirmed: bool):
    if not confirmed and not dry_run:
        print("ERROR: --confirm required for --execute")
        sys.exit(1)

    from sqlalchemy import and_, func, or_, select

    from app.core.config import settings
    from app.core.database import async_session
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus
    from app.services.export.cleanup import cleanup_expired

    if dry_run:
        print("[DRY RUN] Would clean up expired tasks")
        async with async_session() as db:
            now = datetime.now(UTC).replace(tzinfo=None)
            retention_cutoff = now - timedelta(days=max(1, int(settings.EXPORT_RETENTION_DAYS)))
            result = await db.execute(
                select(ExportTask).where(
                    ExportTask.status.in_([ExportTaskStatus.COMPLETED, ExportTaskStatus.FAILED]),
                    or_(
                        and_(ExportTask.expires_at.isnot(None), ExportTask.expires_at < now),
                        and_(
                            ExportTask.expires_at.is_(None),
                            func.coalesce(
                                ExportTask.completed_at,
                                ExportTask.updated_at,
                                ExportTask.created_at,
                            ) < retention_cutoff,
                        ),
                    ),
                ).limit(50)
            )
            expired = result.scalars().all()
            print(f"Found {len(expired)} expired tasks:")
            for t in expired:
                print(f"  Task {t.id}: {t.status}, expires={t.expires_at}, key={t.file_key}")
    else:
        async with async_session() as db:
            stats = await cleanup_expired(db)
            print(f"Cleaned: {stats}")


async def _orphan_scan():
    """Scan for storage→DB orphans and DB→storage missing files."""
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus
    from app.services.export.export_metrics import inc_missing_files
    from app.services.storage_backend import get_export_storage

    storage = get_export_storage()

    # DB→Storage: completed tasks with file_key
    async with async_session() as db:
        result = await db.execute(
            select(ExportTask).where(
                ExportTask.status == ExportTaskStatus.COMPLETED,
                ExportTask.file_key.isnot(None),
            )
        )
        completed = result.scalars().all()

        missing = 0
        for t in completed:
            exists = await storage.exists(t.file_key)
            if not exists:
                print(f"MISSING: Task {t.id} completed but storage file '{t.file_key}' not found")
                missing += 1

        if missing:
            inc_missing_files(missing)
        else:
            print("All completed tasks have storage files present.")

    print(f"Scan complete: {missing} missing files")


async def _retry_task(task_id: int):
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus

    async with async_session() as db:
        result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
        t = result.scalar_one_or_none()
        if t is None:
            print(f"Task {task_id} not found")
            return
        if t.status != ExportTaskStatus.FAILED:
            print(f"Task {task_id} is not failed (status={t.status}), cannot retry")
            return

        # Create a new retry task
        from app.services.export.service import create_export_task

        config = {
            "range_type": t.range_type,
            "filters": t.filters,
            "selected_ids": t.selected_ids,
            "title": t.title,
            "show_date": t.show_date,
            "export_date": t.export_date,
            "sort_by": t.sort_by,
            "group_by": t.group_by,
            "answer_position": t.answer_position,
            "analysis_position": t.analysis_position,
            "space_style": t.space_style,
            "file_format": t.file_format,
        }
        new_task = await create_export_task(db, t.user_id, config)
        new_task.source_task_id = task_id
        await db.commit()
        await db.refresh(new_task)
        print(f"Created retry task {new_task.id} from source {task_id}")


async def _recover_zombie(task_id: int):
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus

    async with async_session() as db:
        result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
        t = result.scalar_one_or_none()
        if t is None:
            print(f"Task {task_id} not found")
            return
        if t.status != ExportTaskStatus.PROCESSING:
            print(f"Task {task_id} is not processing (status={t.status}), not a zombie")
            return

        from app.services.export.service import _apply_export_failure

        _apply_export_failure(t, "管理员恢复僵尸导出任务", "generation_failed")
        await db.commit()
        print(f"Task {task_id} recovered (processing → failed)")


async def main():
    args = _parse_args(sys.argv[1:] if len(sys.argv) > 1 else None)

    # Initialize app context
    from app.core.config import settings
    _ = settings  # ensure config loaded

    if args.command == "list":
        await _list_tasks(args.status)
    elif args.command == "metrics":
        await _show_metrics()
    elif args.command == "cleanup":
        await _do_cleanup(dry_run=not args.execute, confirmed=args.confirm)
    elif args.command == "orphan-scan":
        await _orphan_scan()
    elif args.command == "retry":
        await _retry_task(args.task_id)
    elif args.command == "recover-zombie":
        await _recover_zombie(args.task_id)


if __name__ == "__main__":
    asyncio.run(main())
