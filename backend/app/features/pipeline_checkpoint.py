"""Import pipeline checkpoint 读写（P2-1）。

DB 为权威数据源，Redis 仅做进度快照缓存以加速 status 查询。
任何读路径都允许 Redis miss / 失败，回落 DB；写路径 DB 失败必须抛错，
Redis 失败仅打日志，不影响主流程。

提供给上层（orchestrator / status API / resume API）的接口：

- create_pipeline_record / update_pipeline_status
- create_chunk_records / update_chunk_status / mark_chunk_running
- get_pipeline_progress         返回 total/completed/failed/running 计数
- get_pending_chunks            for resume API：拿 failed + pending chunks
"""

from __future__ import annotations

import contextvars
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk

logger = logging.getLogger(__name__)

# ── Fencing context (set by worker before calling handlers) ──

_fencing_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "pipeline_fencing_ctx", default=None
)


def set_fencing_context(
    task_id: str,
    owner_token: str,
    generation: int,
) -> contextvars.Token:
    """Set fencing context for the current async task.

    Called by the worker before invoking business handlers.
    Returns a Token that should be passed to ``clear_fencing_context``.
    """
    return _fencing_ctx.set(
        {
            "task_id": task_id,
            "owner_token": owner_token,
            "generation": generation,
        }
    )


def clear_fencing_context(token: contextvars.Token) -> None:
    """Reset fencing context to its previous value."""
    _fencing_ctx.reset(token)


_CHECKPOINT_REDIS_PREFIX = "import:pipeline:checkpoint"
_CHECKPOINT_TTL = 86400  # 24h，与 _PIPELINE_STATUS_TTL 对齐


def _utcnow() -> datetime:
    """Naive UTC now, matching the pipeline DateTime columns."""
    return utcnow()


# ---------------------------------------------------------------------------
# Redis cache helpers（best-effort，失败不抛）
# ---------------------------------------------------------------------------


async def _cache_set(pipeline_id: str, snapshot: dict[str, Any]) -> None:
    try:
        from app.core.cache import cache

        await cache.set(
            f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}",
            snapshot,
            ttl=_CHECKPOINT_TTL,
        )
    except Exception:
        logger.debug("checkpoint cache set failed for %s", pipeline_id, exc_info=True)


async def _cache_get(pipeline_id: str) -> dict[str, Any] | None:
    try:
        from app.core.cache import cache

        return await cache.get(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
    except Exception:
        logger.debug("checkpoint cache get failed for %s", pipeline_id, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Pipeline 记录
# ---------------------------------------------------------------------------


async def create_pipeline_record(
    db: AsyncSession,
    *,
    pipeline_id: str,
    source_type: str,
    source_file: str | None,
    total_pages: int | None,
    chunk_size: int,
    created_by: str | None = None,
    source_sha256: str | None = None,
    watermark_snapshot: list | dict | None = None,
) -> ImportPipeline:
    """创建一条 pipeline 父记录。重复 pipeline_id 直接抛错（PK 冲突），
    上层应保证 ID 唯一（orchestrator 已用 timestamp + uuid）。

    P0-1 / P0-2: ``created_by`` 与 ``source_sha256`` 用于 resume endpoint
    校验创建者身份与上传文件是否一致。新调用方应同时传入两者；旧调用方
    （未升级链路 / 单 pass 路径）不传也能工作，写入 NULL。

    P0-3: ``watermark_snapshot`` 记录首次导入时实际生效的水印规则，resume
    时复用以避免规则漂移。NULL 表示老调用方 / 历史路径，resume 会回退到
    重新加载当前规则。
    """
    record = ImportPipeline(
        pipeline_id=pipeline_id,
        source_type=source_type,
        source_file=source_file,
        total_pages=total_pages,
        chunk_size=chunk_size,
        status="running",
        created_by=created_by,
        source_sha256=source_sha256,
        watermark_snapshot=watermark_snapshot,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def update_pipeline_status(
    db: AsyncSession,
    pipeline_id: str,
    *,
    status: str,
    error_message: str | None = None,
    finished: bool = False,
) -> None:
    values: dict[str, Any] = {"status": status}
    if error_message is not None:
        values["error_message"] = error_message
    if finished:
        values["finished_at"] = _utcnow()

    # Use fenced conditional UPDATE when a fencing context is active
    fence = _fencing_ctx.get()
    if fence is not None:
        from app.services.db_fencing import (
            FencingRejectedError,
            conditional_update_with_fencing,
        )

        ok = await conditional_update_with_fencing(
            db=db,
            model_class=ImportPipeline,
            record_id=pipeline_id,
            expected_task_id=fence["task_id"],
            expected_generation=fence["generation"],
            expected_owner_token=fence["owner_token"],
            **values,
        )
        if not ok:
            await db.rollback()
            raise FencingRejectedError(
                f"Pipeline status update rejected (fence lost): "
                f"pipeline_id={pipeline_id} task_id={fence['task_id']} gen={fence['generation']}"
            )
        await db.commit()
        return

    # No fencing context — plain UPDATE (e.g. called from API, not worker)
    await db.execute(
        update(ImportPipeline)
        .where(ImportPipeline.pipeline_id == pipeline_id)
        .values(**values)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Chunk 记录
# ---------------------------------------------------------------------------


async def create_chunk_records(
    db: AsyncSession,
    pipeline_id: str,
    page_ranges: list[tuple[int, int]],
) -> list[ImportPipelineChunk]:
    """批量创建所有 chunk，初始状态都是 pending。

    page_ranges: [(page_start, page_end), ...] 1-based 闭区间。
    """
    chunks = [
        ImportPipelineChunk(
            pipeline_id=pipeline_id,
            chunk_index=idx,
            page_start=start,
            page_end=end,
            status="pending",
        )
        for idx, (start, end) in enumerate(page_ranges)
    ]
    db.add_all(chunks)
    await db.commit()
    for chunk in chunks:
        await db.refresh(chunk)
    return chunks


async def mark_chunk_running(
    db: AsyncSession, pipeline_id: str, chunk_index: int
) -> None:
    await db.execute(
        update(ImportPipelineChunk)
        .where(
            ImportPipelineChunk.pipeline_id == pipeline_id,
            ImportPipelineChunk.chunk_index == chunk_index,
        )
        .values(status="running", started_at=_utcnow(), error_message=None)
    )
    await db.commit()


async def update_chunk_status(
    db: AsyncSession,
    pipeline_id: str,
    chunk_index: int,
    *,
    status: str,
    batch_id: str | None = None,
    question_count: int | None = None,
    error_message: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": status}
    if batch_id is not None:
        values["batch_id"] = batch_id
    if question_count is not None:
        values["question_count"] = question_count
    if error_message is not None:
        values["error_message"] = error_message
    if status in ("completed", "failed"):
        values["finished_at"] = _utcnow()

    # Fence via parent pipeline: if the pipeline has been reassigned to a new
    # worker, stale chunk updates must be rejected.
    fence = _fencing_ctx.get()
    if fence is not None:
        from app.services.db_fencing import (
            verify_fencing_or_raise,
        )

        # Verify the parent pipeline still belongs to this worker
        await verify_fencing_or_raise(
            db=db,
            model_class=ImportPipeline,
            record_id=pipeline_id,
        )

    await db.execute(
        update(ImportPipelineChunk)
        .where(
            ImportPipelineChunk.pipeline_id == pipeline_id,
            ImportPipelineChunk.chunk_index == chunk_index,
        )
        .values(**values)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# 查询：进度 / 待恢复 chunk
# ---------------------------------------------------------------------------


async def get_pipeline_progress(
    db: AsyncSession, pipeline_id: str, *, use_cache: bool = True
) -> dict[str, Any] | None:
    """返回 pipeline 的整体进度。

    {
        "pipeline_id": ...,
        "status": "running" | "completed" | "failed" | "paused",
        "total_chunks": int,
        "completed_chunks": int,
        "failed_chunks": int,
        "running_chunks": int,
        "pending_chunks": int,
        "question_count": int,    # 已完成 chunk 累计写入的题数
        "started_at": iso str,
        "finished_at": iso str | None,
        "failed_chunk_details": [{chunk_index, page_start, page_end, error_message}, ...],
    }

    缓存策略：DB 是权威源，只在 use_cache=True 且 Redis 命中时直接返回；
    Redis miss 时查 DB 并回写一份。状态接口频繁调用时可省去聚合查询。
    """
    if use_cache:
        cached = await _cache_get(pipeline_id)
        if cached:
            return cached

    pipeline_row = (
        await db.execute(
            select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
        )
    ).scalar_one_or_none()
    if pipeline_row is None:
        return None

    status_counts = dict(
        (
            await db.execute(
                select(
                    ImportPipelineChunk.status,
                    func.count(ImportPipelineChunk.id),
                )
                .where(ImportPipelineChunk.pipeline_id == pipeline_id)
                .group_by(ImportPipelineChunk.status)
            )
        ).all()
    )
    completed = int(status_counts.get("completed", 0))
    failed = int(status_counts.get("failed", 0))
    running = int(status_counts.get("running", 0))
    pending = int(status_counts.get("pending", 0))
    total = completed + failed + running + pending

    question_count = (
        await db.execute(
            select(
                func.coalesce(func.sum(ImportPipelineChunk.question_count), 0)
            ).where(
                ImportPipelineChunk.pipeline_id == pipeline_id,
                ImportPipelineChunk.status == "completed",
            )
        )
    ).scalar() or 0

    failed_rows = (
        (
            await db.execute(
                select(ImportPipelineChunk)
                .where(
                    ImportPipelineChunk.pipeline_id == pipeline_id,
                    ImportPipelineChunk.status == "failed",
                )
                .order_by(ImportPipelineChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )

    snapshot: dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "status": pipeline_row.status,
        "total_chunks": total,
        "completed_chunks": completed,
        "failed_chunks": failed,
        "running_chunks": running,
        "pending_chunks": pending,
        "question_count": int(question_count),
        "started_at": serialize_utc_datetime(pipeline_row.started_at)
        if pipeline_row.started_at
        else None,
        "finished_at": serialize_utc_datetime(pipeline_row.finished_at)
        if pipeline_row.finished_at
        else None,
        "failed_chunk_details": [
            {
                "chunk_index": c.chunk_index,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "error_message": c.error_message,
            }
            for c in failed_rows
        ],
    }

    await _cache_set(pipeline_id, snapshot)
    return snapshot


async def get_pending_chunks(
    db: AsyncSession, pipeline_id: str
) -> list[ImportPipelineChunk]:
    """返回 failed + pending 的 chunk，按 chunk_index 排序，供 resume 复跑。

    running 的 chunk 不返回——它要么真的还在跑，要么需要 admin 介入手动改成
    failed 后再恢复，避免并发同一 chunk。
    """
    rows = (
        (
            await db.execute(
                select(ImportPipelineChunk)
                .where(
                    ImportPipelineChunk.pipeline_id == pipeline_id,
                    ImportPipelineChunk.status.in_(("failed", "pending")),
                )
                .order_by(ImportPipelineChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def invalidate_progress_cache(pipeline_id: str) -> None:
    """chunk 状态写入 DB 后调用，清掉 Redis 缓存避免读到旧快照。"""
    try:
        from app.core.cache import cache

        await cache.delete(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
    except Exception:
        logger.debug(
            "checkpoint cache invalidate failed for %s", pipeline_id, exc_info=True
        )
