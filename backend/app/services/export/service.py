"""ExportService — orchestrates the full export flow.

Responsibilities:
1. Validate export config and resolve question range
2. Sort and group questions
3. Build snapshot
4. Dispatch to appropriate Exporter
5. Store generated file
6. Update task record
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import tempfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import shanghai_now, shanghai_today, utcnow
from app.models.export_task import ExportTask
from app.schemas.export_task import (
    ExportErrorCode,
    ExportRangeType,
    ExportSortBy,
    ExportTaskStatus,
)
from app.services.export.data_builder import build_snapshot_data
from app.services.export.exceptions import ExportDomainError
from app.services.export.export_metrics import (
    inc_completed,
    inc_created,
    inc_failed,
    observe_file_size_bytes,
    observe_processing_seconds,
    observe_queue_wait_seconds,
)
from app.services.export.exporter_base import Exporter
from app.services.export.generation_token import GenerationToken
from app.services.export.pdf_exporter import PdfExporter
from app.services.export.range_resolver import resolve_range
from app.services.export.snapshot_service import create_snapshot, load_snapshot
from app.services.export.sorter import sort_questions

logger = logging.getLogger(__name__)


REEXPORTING_ERROR_CODE = "reexporting"
REEXPORT_FAILED_ERROR_CODE = "reexport_failed"


def _is_reexport_with_old_file(task: ExportTask) -> bool:
    """Return whether a replacement export can safely fall back to its old file."""
    return (
        task.error_code == REEXPORTING_ERROR_CODE
        and bool(task.file_key)
        and task.completed_at is not None
        and (task.expires_at is None or task.expires_at > utcnow())
    )


def _apply_export_failure(
    task: ExportTask,
    message: str,
    error_code: str,
) -> None:
    """Fail a normal task or restore the previous version of a re-export task."""
    safe_message = (message or "导出失败")[:420]
    if _is_reexport_with_old_file(task):
        task.status = ExportTaskStatus.COMPLETED
        task.error_code = REEXPORT_FAILED_ERROR_CODE
        task.error_message = f"重新导出失败：{safe_message}"[:500]
        # Keep file_key/file_size/completed_at/expires_at from the valid old version.
    else:
        task.status = ExportTaskStatus.FAILED
        task.error_code = error_code
        task.error_message = safe_message[:500]
        now = utcnow()
        task.completed_at = now
        # Failed exports still own a snapshot. Give them the same bounded
        # retention window as completed artifacts so snapshots cannot leak
        # forever when users never retry the failed task.
        task.expires_at = now + dt.timedelta(days=settings.EXPORT_RETENTION_DAYS)
    task.processing_started_at = None
    task.heartbeat_at = None


# ── Exporter registry ──
_EXPORTERS: dict[str, type[Exporter]] = {}


def register_exporter(format_name: str, exporter_cls: type[Exporter]) -> None:
    """Register an exporter class for a given format string."""
    _EXPORTERS[format_name] = exporter_cls


def get_exporter(format_name: str) -> Exporter:
    """Get an exporter instance for the given format."""
    cls = _EXPORTERS.get(format_name)
    if cls is None:
        raise ValueError(f"Unsupported export format: {format_name}")
    return cls()


# Register built-in exporters
from app.services.export.docx_exporter import DocxExporter

register_exporter("pdf", PdfExporter)
register_exporter("docx", DocxExporter)

# ── Limits (primary source: settings.EXPORT_MAX_QUESTIONS) ──
_MAX_FILENAME_BYTES = 200
_DEFAULT_FILENAME = "错题巩固练习"  # extension added by _build_filename

# ── File-name sanitisation ──
_INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_FILENAME_TRIM_RE = re.compile(r"^[\s.]+|[\s.]+$")


def _sanitize_filename(title: str) -> str:
    """Clean a title for use as a filename component."""
    cleaned = _INVALID_FILENAME_CHARS.sub("", title)
    cleaned = _FILENAME_TRIM_RE.sub("", cleaned)
    if not cleaned:
        cleaned = "错题巩固练习"
    # Limit byte length
    cleaned = cleaned.encode("utf-8", errors="ignore")[:_MAX_FILENAME_BYTES].decode(
        "utf-8", errors="ignore"
    )
    return cleaned


def _build_filename(title: str, date_str: str, ext: str = "pdf") -> str:
    """Build the export filename: {title}_{yyyyMMdd_HHmm}.{ext}"""
    safe_title = _sanitize_filename(title)
    ts = (
        date_str.replace("-", "")
        if date_str
        else shanghai_now().strftime("%Y%m%d_%H%M")
    )
    return f"{safe_title}_{ts}.{ext}"


def _build_title(subjects: list[dict]) -> str:
    """Build the default title from the subject list.

    Rules:
    - 0 subjects: "错题巩固练习"
    - 1 subject: "{subject_name}错题巩固练习"
    - 2-3 subjects: "{name1、name2}错题巩固练习"
    - 4+ subjects: "{name1、name2、name3等}错题巩固练习"
    """
    names = [
        s.get("label", "") or s.get("name", "")
        for s in subjects
        if s.get("label") or s.get("name")
    ]
    names = [n for n in names if n]

    if not names:
        return "错题巩固练习"

    if len(names) == 1:
        return f"{names[0]}错题巩固练习"

    if len(names) <= 3:
        return f"{'、'.join(names)}错题巩固练习"

    return f"{'、'.join(names[:3])}等错题巩固练习"


async def preview_count(
    db: AsyncSession,
    user_id: int,
    range_type: ExportRangeType,
    filters: dict | None = None,
    selected_ids: list[int] | None = None,
) -> int:
    """Preview how many questions will be exported for a given range."""
    ids = await resolve_range(db, user_id, range_type, filters, selected_ids)
    return len(ids)


async def create_export_task(
    db: AsyncSession,
    user_id: int,
    config: dict[str, Any],
) -> ExportTask:
    """Create a new export task (pending), ready for background processing.

    This does NOT validate the range — that happens in the processor.
    Basic sanity checks are performed here.
    """
    title = config.get("title", "错题巩固练习").strip()
    if not title:
        title = "错题巩固练习"

    date_str = config.get("export_date", "") or shanghai_today().strftime("%Y-%m-%d")
    file_name = _build_filename(
        title,
        date_str.replace("-", ""),
        config.get("file_format", "pdf"),
    )

    task_filters = dict(config.get("filters") or {})
    try:
        from app.core.log_context import get_log_context

        trace_id = get_log_context().get("trace_id")
        if trace_id not in (None, "", "-"):
            # Export tasks are processed by a scheduler process later. Persist
            # only the safe trace ID in the existing internal filters JSON so
            # no schema migration is required; range_resolver ignores unknown
            # keys and API responses never expose filters.
            task_filters["_trace_id"] = str(trace_id)
    except Exception:
        pass

    task = ExportTask(
        user_id=user_id,
        status=ExportTaskStatus.PENDING,
        file_format=config.get("file_format", "pdf"),
        range_type=config.get("range_type", ExportRangeType.ALL),
        filters=task_filters or None,
        selected_ids=config.get("selected_ids"),
        title=title,
        show_date=config.get("show_date", True),
        export_date=date_str,
        sort_by=config.get("sort_by", ExportSortBy.NEWEST),
        group_by=config.get("group_by", "none"),
        answer_position=config.get("answer_position", "none"),
        analysis_position=config.get("analysis_position", "none"),
        space_style=config.get("space_style", "standard"),
        total_count=0,
        file_name=file_name,
        idempotency_key=config.get("_idempotency_key"),
        generator_version=settings.GENERATOR_VERSION,
    )
    db.add(task)
    await db.flush()
    inc_created()
    logger.info("Export task %d created for user %d", task.id, user_id)
    return task


async def process_task(
    db: AsyncSession,
    task_id: int,
    exporter: Exporter | None = None,
    token: GenerationToken | None = None,
) -> ExportTask:
    """Process an export task: resolve, build snapshot, generate, store.

    If the task already has a ``snapshot_id`` (e.g. from re-export), the
    existing snapshot is loaded directly, skipping the resolve/sort/build
    steps. This ensures re-exported content reflects the original snapshot,
    not the current state of the user's wrong-question book.

    This is called by the background processor (not the web request handler).

    Returns the updated task.
    """
    # Lazy import to avoid circular dependency (processor.py imports process_task)
    from app.services.export.processor import validate_transition

    # Load task with lock protection (re-select to get latest)
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise ExportDomainError(
            status_code=404,
            error_code=ExportErrorCode.TASK_NOT_FOUND,
            message=f"Export task {task_id} not found",
        )

    if task.status != ExportTaskStatus.PROCESSING:
        raise ExportDomainError(
            status_code=400,
            error_code=ExportErrorCode.ACCESS_DENIED,
            message=f"Export task {task_id} is not in processing state (status={task.status})",
        )

    exporter = exporter or get_exporter(task.file_format)

    try:
        # Check if we already have a snapshot (re-export path)
        if task.snapshot_id:
            snapshot_data = await load_snapshot(db, task.snapshot_id, task.user_id)
            if snapshot_data is None:
                # Snapshot missing — fall through to rebuild
                logger.warning(
                    "Snapshot %s for task %d not found, rebuilding",
                    task.snapshot_id,
                    task.id,
                )
                task.snapshot_id = None
            else:
                logger.info(
                    "Reusing existing snapshot %s for task %d",
                    task.snapshot_id,
                    task.id,
                )

        if not task.snapshot_id:
            # 1. Resolve range
            wq_ids = await resolve_range(
                db,
                task.user_id,
                ExportRangeType(task.range_type),
                task.filters,
                task.selected_ids,
            )

            # 2. Sort (if random, uses deterministic seed)
            sorted_ids = await sort_questions(
                db,
                task.user_id,
                wq_ids,
                ExportSortBy(task.sort_by),
            )

            # 3. Build config dict for snapshot
            subjects = await _collect_subjects(db, sorted_ids)
            title = task.title or _build_title(subjects)

            config_for_snapshot = {
                "title": title,
                "file_name": task.file_name,
                "file_format": task.file_format,
                "show_date": task.show_date,
                "export_date": task.export_date,
                "sort_by": task.sort_by,
                "group_by": task.group_by,
                "answer_position": task.answer_position,
                "analysis_position": task.analysis_position,
                "space_style": task.space_style,
                "product_name": _get_product_name(),
                "total_count": len(sorted_ids),
                "skip_count": 0,
            }

            wq_order_map = {wq_id: idx for idx, wq_id in enumerate(sorted_ids)}

            # 4. Build snapshot data
            snapshot_data = await build_snapshot_data(
                db,
                task.user_id,
                sorted_ids,
                wq_order_map,
                config_for_snapshot,
            )

            snapshot_data["config"]["total_count"] = snapshot_data.get(
                "success_count",
                len(snapshot_data.get("questions", [])),
            )
            snapshot_data["config"]["skip_count"] = snapshot_data.get("skip_count", 0)
            snapshot_data["config"]["skip_reasons"] = snapshot_data.get("skip_reasons")

            # 5. Save snapshot
            snapshot_id = await create_snapshot(db, task.user_id, snapshot_data)
            task.snapshot_id = snapshot_id

        # 6. Update task counts
        task.total_count = snapshot_data.get(
            "total_count",
            len(snapshot_data.get("questions", [])),
        )

        await db.flush()

        # 7. Generate PDF
        with tempfile.TemporaryDirectory(prefix=f"export_{task.id}_") as tmpdir:
            result = await exporter.export(snapshot_data, tmpdir)

            if not result.success or not result.file_bytes:
                was_reexport = _is_reexport_with_old_file(task)
                target = (
                    ExportTaskStatus.COMPLETED
                    if was_reexport
                    else ExportTaskStatus.FAILED
                )
                validate_transition(ExportTaskStatus.PROCESSING, target, task.id)
                _apply_export_failure(
                    task,
                    result.error_message or "文件生成失败",
                    ExportErrorCode.GENERATION_FAILED.value,
                )
                if not was_reexport:
                    task.skip_count = result.skip_count
                    task.skip_reasons = result.skip_reasons
                logger.warning("Export task %d failed: %s", task.id, task.error_message)
                await db.flush()
                return task

            # 8. Check generation token before upload
            if token is not None and not token.is_active():
                raise ExportDomainError(
                    status_code=499,
                    error_code=ExportErrorCode.GENERATION_FAILED,
                    message="导出任务已超时，文件已丢弃",
                )

            # 9. Store the file
            from app.services.storage_backend import get_export_storage

            storage = get_export_storage()
            file_key = f"{task.id}/{task.file_name}"
            _file_url = await storage.upload(file_key, result.file_bytes)

            validate_transition(
                ExportTaskStatus.PROCESSING, ExportTaskStatus.COMPLETED, task.id
            )
            processing_started_at = task.processing_started_at
            task.status = ExportTaskStatus.COMPLETED
            task.file_key = file_key
            task.file_size = len(result.file_bytes)
            task.success_count = snapshot_data.get(
                "success_count",
                len(snapshot_data.get("questions", [])),
            )
            task.skip_count = result.skip_count
            task.skip_reasons = result.skip_reasons
            task.completed_at = utcnow()
            task.expires_at = utcnow() + dt.timedelta(
                days=settings.EXPORT_RETENTION_DAYS
            )
            task.error_code = None
            task.error_message = None
            task.processing_started_at = None
            task.heartbeat_at = None

            inc_completed()
            observe_file_size_bytes(len(result.file_bytes))
            if processing_started_at:
                observe_processing_seconds(
                    (task.completed_at - processing_started_at).total_seconds()
                )
            _record_queue_wait(task, processing_started_at)

            logger.info(
                "Export task %d completed: %d questions, %d skipped, %d bytes",
                task.id,
                task.success_count,
                task.skip_count,
                task.file_size,
            )

    except ExportDomainError as e:
        _apply_export_failure(task, e.message, e.error_code.value)
        inc_failed()
        logger.warning("Export task %d failed (domain): %s", task.id, e.message)

    except ValueError as e:
        _apply_export_failure(task, str(e), ExportErrorCode.GENERATION_FAILED.value)
        inc_failed()
        logger.warning("Export task %d failed (validation): %s", task.id, e)

    except Exception as e:
        _apply_export_failure(
            task,
            f"导出失败：{str(e)[:200]}",
            ExportErrorCode.SERVICE_UNAVAILABLE.value,
        )
        inc_failed()
        logger.exception("Export task %d failed (unexpected)", task.id)

    await db.flush()
    return task


def _record_queue_wait(
    task: ExportTask,
    processing_started_at: dt.datetime | None = None,
) -> None:
    """Record queue wait time from created_at to processing_started_at."""
    started_at = processing_started_at or task.processing_started_at
    if task.created_at and started_at:
        wait = (started_at - task.created_at).total_seconds()
        observe_queue_wait_seconds(max(0, wait))


async def _collect_subjects(db: AsyncSession, wq_ids: list[int]) -> list[dict]:
    """Collect unique subjects from the resolved questions."""
    if not wq_ids:
        return []

    from app.models.admin import QuestionVersion, Subject
    from app.models.wrong_question import WrongQuestion

    # Subject attribution follows the immutable revision bound to the wrong row.
    sq = (
        select(QuestionVersion.subject_id)
        .join(
            WrongQuestion,
            WrongQuestion.question_version_id == QuestionVersion.id,
        )
        .where(WrongQuestion.id.in_(wq_ids))
        .distinct()
        .subquery()
    )
    result = await db.execute(
        select(Subject.id, Subject.name).where(Subject.id.in_(select(sq.c.subject_id)))
    )
    return [{"id": s.id, "label": s.name} for s in result.fetchall()]


def _get_product_name() -> str:
    """Return the product name from config or settings."""
    # Try to read from a configurable source
    name = getattr(settings, "PRODUCT_NAME", None)
    if name:
        return name
    # Fallback to app name from PUBLIC_BASE_URL or env
    return "MemoGrad"


async def find_task_by_idempotency_key(
    db: AsyncSession,
    user_id: int,
    idempotency_key: str | None,
) -> ExportTask | None:
    """Find any task (any status) matching the given idempotency key.

    Used as a recovery path when the idempotency_key UNIQUE constraint
    prevents insertion (e.g. migration to drop it hasn't been applied).
    """
    if not idempotency_key:
        return None
    result = await db.execute(
        select(ExportTask)
        .where(
            ExportTask.user_id == user_id,
            ExportTask.idempotency_key == idempotency_key,
        )
        .order_by(ExportTask.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
