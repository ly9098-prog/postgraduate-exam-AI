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

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.export_task import ExportTask
from app.schemas.export_task import (
    ExportRangeType,
    ExportSortBy,
    ExportTaskStatus,
)
from app.services.export.data_builder import build_snapshot_data
from app.services.export.exporter_base import Exporter
from app.services.export.pdf_exporter import PdfExporter
from app.services.export.range_resolver import resolve_range
from app.services.export.snapshot_service import create_snapshot, load_snapshot
from app.services.export.sorter import sort_questions
from app.services.storage_backend import get_storage

logger = logging.getLogger(__name__)

# ── Limits ──
_MAX_EXPORT = 100
_MAX_FILENAME_BYTES = 200
_DEFAULT_FILENAME = "错题巩固练习.pdf"

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
    cleaned = cleaned.encode("utf-8", errors="ignore")[:_MAX_FILENAME_BYTES].decode("utf-8", errors="ignore")
    return cleaned


def _build_filename(title: str, date_str: str, ext: str = "pdf") -> str:
    """Build the export filename: {title}_{yyyyMMdd_HHmm}.{ext}"""
    safe_title = _sanitize_filename(title)
    ts = date_str.replace("-", "") if date_str else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return f"{safe_title}_{ts}.{ext}"


def _build_title(subjects: list[dict]) -> str:
    """Build the default title from the subject list.

    Rules:
    - 0 subjects: "错题巩固练习"
    - 1 subject: "{subject_name}错题巩固练习"
    - 2-3 subjects: "{name1、name2}错题巩固练习"
    - 4+ subjects: "{name1、name2、name3等}错题巩固练习"
    """
    names = [s.get("label", "") or s.get("name", "") for s in subjects if s.get("label") or s.get("name")]
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

    date_str = config.get("export_date", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_name = _build_filename(
        title,
        date_str.replace("-", ""),
        config.get("file_format", "pdf"),
    )

    task = ExportTask(
        user_id=user_id,
        status=ExportTaskStatus.PENDING,
        file_format=config.get("file_format", "pdf"),
        range_type=config.get("range_type", ExportRangeType.ALL),
        filters=config.get("filters"),
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
        generator_version=settings.GENERATOR_VERSION if hasattr(settings, "GENERATOR_VERSION") else "1.0",
    )
    db.add(task)
    await db.flush()
    logger.info("Export task %d created for user %d", task.id, user_id)
    return task


async def process_task(
    db: AsyncSession,
    task_id: int,
    exporter: Exporter | None = None,
) -> ExportTask:
    """Process an export task: resolve, build snapshot, generate, store.

    This is called by the background processor (not the web request handler).

    Returns the updated task.
    """
    # Load task with lock protection (re-select to get latest)
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise ValueError(f"Export task {task_id} not found")

    if task.status != ExportTaskStatus.PROCESSING:
        raise ValueError(f"Export task {task_id} is not in processing state (status={task.status})")

    exporter = exporter or PdfExporter()

    try:
        # 1. Resolve range
        wq_ids = await resolve_range(
            db, task.user_id,
            ExportRangeType(task.range_type),
            task.filters,
            task.selected_ids,
        )

        # 2. Sort (if random, uses deterministic seed)
        sorted_ids = await sort_questions(
            db, task.user_id, wq_ids,
            ExportSortBy(task.sort_by),
        )

        # 3. Build config dict for snapshot
        subjects = await _collect_subjects(db, sorted_ids)
        title = task.title or _build_title(subjects)

        config_for_snapshot = {
            "title": title,
            "file_name": task.file_name,
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
            db, task.user_id, sorted_ids, wq_order_map, config_for_snapshot,
        )

        snapshot_data["config"]["total_count"] = snapshot_data.get("total_count", 0)
        snapshot_data["config"]["skip_count"] = snapshot_data.get("skip_count", 0)

        # 5. Save snapshot
        snapshot_id = await create_snapshot(db, task.user_id, snapshot_data)
        task.snapshot_id = snapshot_id

        # 6. Update task counts before PDF generation (so we have them on failure)
        task.total_count = snapshot_data.get("total_count", 0)

        await db.flush()

        # 7. Generate PDF
        with tempfile.TemporaryDirectory(prefix=f"export_{task.id}_") as tmpdir:
            result = await exporter.export(snapshot_data, tmpdir)

            if not result.success or not result.file_bytes:
                task.status = ExportTaskStatus.FAILED
                task.error_message = (result.error_message or "PDF 生成失败")[:500]
                task.completed_at = datetime.now(timezone.utc)
                task.skip_count = result.skip_count
                task.skip_reasons = result.skip_reasons
                logger.warning("Export task %d failed: %s", task.id, task.error_message)
                await db.flush()
                return task

            # 8. Store the file
            from app.services.storage_backend import get_export_storage
            storage = get_export_storage()
            file_key = f"{task.id}/{task.file_name}"
            file_url = await storage.upload(file_key, result.file_bytes)

            task.status = ExportTaskStatus.COMPLETED
            task.file_key = file_key
            task.file_size = len(result.file_bytes)
            task.success_count = snapshot_data.get("total_count", 0) - (result.skip_count or 0)
            task.skip_count = result.skip_count
            task.skip_reasons = result.skip_reasons
            task.completed_at = datetime.now(timezone.utc)
            task.expires_at = datetime.now(timezone.utc) + dt.timedelta(days=7)

            logger.info(
                "Export task %d completed: %d questions, %d skipped, %d bytes",
                task.id, task.success_count, task.skip_count, task.file_size,
            )

    except ValueError as e:
        task.status = ExportTaskStatus.FAILED
        task.error_message = str(e)[:500]
        task.completed_at = datetime.now(timezone.utc)
        logger.warning("Export task %d failed (validation): %s", task.id, e)

    except Exception as e:
        task.status = ExportTaskStatus.FAILED
        task.error_message = f"导出失败: {str(e)[:200]}"
        task.completed_at = datetime.now(timezone.utc)
        logger.exception("Export task %d failed (unexpected)", task.id)

    await db.flush()
    return task


async def _collect_subjects(db: AsyncSession, wq_ids: list[int]) -> list[dict]:
    """Collect unique subjects from the resolved questions."""
    if not wq_ids:
        return []

    from app.models.question import Question
    from app.models.admin import Subject
    from app.models.wrong_question import WrongQuestion

    # Get distinct subject IDs from questions linked to these wrong-question IDs
    sq = (
        select(Question.subject_id)
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
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
