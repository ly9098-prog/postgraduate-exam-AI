"""批量导题编排器（多图片 → 复用现有单图 OCR/AI/审核流水线）。

设计约束（来自任务说明）：
- 不重构 OCR 核心逻辑、不改 PaddleOCR 配置、不换模型；
- 最大化复用现有 OCR(`ocr_image`/`clean_ocr_text`) 与导入流水线
  (`run_import_pipeline`，source_type="txt") 与待审核入库；
- 队列模式：并发 clamp 到 1~4（默认取 settings.BATCH_IMAGE_DEFAULT_CONCURRENCY，
  与本地 OCR profile max_workers 对齐），其余排队，避免 N 张图片同时 OCR
  撑爆内存/CPU/AI 限流；
- 单张失败只记录日志并继续，不终止整批；
- 缓存 OCR 原始文本，支持「不重复 OCR」的重新解析；
- 架构 source-agnostic：未来 PDF 拆页成图片数组后，直接复用
  `create_batch_job` + `run_batch_job`，不写第二套逻辑。

并发说明：PaddleOCR 推理被 `ocr_service._ocr_lock` 串行化（GPU 一次只跑一
张），因此真正并行的是各 worker 的 AI 解析（httpx 异步）。OCR 用
`asyncio.to_thread` 包裹，避免阻塞事件循环。

一致性（v2 新增）：
- State machine guard：阻止非法 status 迁移（如 completed→running）
- Trace event：append-only 事件流，与状态更新同 DB 事务
- Derived batch status：batch.status 由 items 状态派生
- Idempotency：(batch_import_id, image_import_id) 唯一约束防止重复提交
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.import_batch_job import (
    BatchJobTraceEvent,
    ImportBatchJob,
    ImportBatchJobItem,
)
from app.models.pipeline_enums import (
    guard_item_transition as _guard_item_transition,
    guard_job_transition as _guard_job_transition,
    TraceEventStatus,
    TraceStep,
)

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import bind_log_context, log_event
except ImportError:  # pragma: no cover
    def bind_log_context(**_kw): return []  # type: ignore[misc]
    def log_event(_lg, _ev, **_kw): pass  # type: ignore[misc]

_MIN_CONCURRENCY = 1
_MAX_CONCURRENCY = 4


# ================================================================
# Data structures
# ================================================================


@dataclass
class BatchImageSource:
    """一张待处理图片：序号 + 原始文件名 + 落盘的临时文件路径。

    临时文件由编排器负责在处理完成后删除（PDF 拆页路径同样复用此结构）。
    """

    seq: int
    source_file: str
    temp_path: str


@dataclass
class _TraceData:
    """Trace event payload — 与 item/job 状态更新同事务写入。"""

    step: str  # upload | waiting | ocr | pipeline | merge | done | error
    status: str  # running | success | failed
    message: str = ""
    duration_ms: int | None = None
    item_seq: int | None = None
    request_id: str | None = None
    image_import_id: str | None = None
    batch_import_id: str | None = None


# ================================================================
# Helpers
# ================================================================


def _now() -> datetime:
    """Return naive UTC datetime for DB storage (compatible with DateTime columns without timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clamp_concurrency(value: int | None) -> int:
    default = max(_MIN_CONCURRENCY, min(_MAX_CONCURRENCY, settings.BATCH_IMAGE_DEFAULT_CONCURRENCY))
    if value is None:
        return default
    return max(_MIN_CONCURRENCY, min(_MAX_CONCURRENCY, value))


def new_job_id() -> str:
    return f"BIMG_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


async def _append_trace_event(
    job_id: str,
    *,
    seq: int,
    step: str,
    status: str,
    message: str = "",
    item_seq: int | None = None,
    request_id: str | None = None,
    image_import_id: str | None = None,
    batch_import_id: str | None = None,
    duration_ms: int | None = None,
    db: AsyncSession,
) -> BatchJobTraceEvent:
    """追加 trace event 到已开启的事务中（不 commit，由调用方控制）。

    调用方必须确保 job 行已被 FOR UPDATE 锁定（next_event_seq 已递增）。
    """
    event = BatchJobTraceEvent(
        job_id=job_id,
        item_seq=item_seq,
        request_id=request_id,
        image_import_id=image_import_id,
        batch_import_id=batch_import_id,
        seq=seq,
        step=step,
        status=status,
        message=message[:512],
        duration_ms=duration_ms,
    )
    db.add(event)
    return event


# ================================================================
# 原子状态更新 + Trace Event（同事务）
# ================================================================


async def _update_item_with_trace(
    item_id: int,
    job_id: str,
    *,
    fields: dict,
    trace: _TraceData,
) -> None:
    """原子：item 字段更新 + trace event 追加。同事务、同行锁。"""
    async with async_session() as db:
        # 1. Lock job → 原子 seq + 防并发
        job = await db.get(ImportBatchJob, job_id, with_for_update=True)
        seq = job.next_event_seq
        job.next_event_seq += 1

        # 2. Update item + state guard
        item = await db.get(ImportBatchJobItem, item_id)
        if item is None:
            await db.rollback()
            return
        # Validate trace status is a valid trace event value (not a job status)
        from app.models.pipeline_enums import VALID_TRACE_STATUS
        if trace.status not in VALID_TRACE_STATUS:
            raise ValueError(
                f"Invalid trace event status: {trace.status!r}. "
                f"Allowed: {VALID_TRACE_STATUS}"
            )

        if "status" in fields:
            _guard_item_transition(item.status, fields["status"])
        for key, value in fields.items():
            setattr(item, key, value)
        item.updated_at = _now()

        # 3. Append trace event（同一 txn）
        await _append_trace_event(
            job_id,
            seq=seq,
            step=trace.step,
            status=trace.status,
            message=trace.message,
            item_seq=trace.item_seq or item.seq,
            request_id=trace.request_id or item.request_id,
            image_import_id=trace.image_import_id or item.image_import_id,
            batch_import_id=trace.batch_import_id or item.batch_import_id,
            duration_ms=trace.duration_ms,
            db=db,
        )

        await db.commit()


async def _batch_merge_commit(
    db: AsyncSession,
    job_id: str,
    merged_batch_id: str,
    old_batch_ids: list[str],
    items: list[ImportBatchJobItem],
    now: datetime,
) -> int:
    """原子：items 切换 batch + supersede 旧批次 + job 终态 + trace events。
    调用方负责 session.begin/commit，本函数只做 DB 操作。
    """
    from app.models.question_import import QuestionImport as QI

    job = await db.get(ImportBatchJob, job_id, with_for_update=True)
    if job is None:
        return 0

    superseded_count = 0
    for r in items:
        item = await db.get(ImportBatchJobItem, r.id)
        if item:
            item.review_batch_id = merged_batch_id
            item.question_count = 0
            item.updated_at = now

            seq = job.next_event_seq
            job.next_event_seq += 1
            await _append_trace_event(
                job_id,
                seq=seq,
                step="merge",
                status="success",
                message=f"合并至批次 {merged_batch_id}",
                item_seq=item.seq,
                db=db,
            )

    for old_id in old_batch_ids:
        if old_id and old_id != merged_batch_id:
            await db.execute(
                update(QI)
                .where(QI.batch_id == old_id)
                .values(
                    superseded_by_batch_id=merged_batch_id,
                    superseded_at=now,
                )
            )
            superseded_count += 1

    job.merge_status = "completed"
    job.merged_batch_id = merged_batch_id
    job.merge_finished_at = now
    return superseded_count


async def _set_job_status_with_trace(
    job_id: str,
    status: str,
    *,
    error_message: str | None = None,
    trace_message: str = "",
    trace_step: str | None = None,
) -> None:
    """原子：job status 更新 + trace event。同事务、同行锁。

    trace_step and trace_event status are DERIVED from the job status
    via pipeline_enums.map_job_status_to_trace(), NOT passed through
    directly. This prevents job status values (e.g. "completed") from
    leaking into trace event status fields.
    """
    from app.models.pipeline_enums import map_job_status_to_trace

    async with async_session() as db:
        job = await db.get(ImportBatchJob, job_id, with_for_update=True)
        if job is None:
            return
        _guard_job_transition(job.status, status)

        seq = job.next_event_seq
        job.next_event_seq += 1

        job.status = status
        if error_message is not None:
            job.error_message = error_message
        if status in {"completed", "completed_with_warnings", "failed"}:
            job.finished_at = _now()
        job.updated_at = _now()

        # Map job status -> trace step/status (NEVER write "completed" into trace.status)
        trace_step_resolved, trace_status = map_job_status_to_trace(status)
        step = trace_step or trace_step_resolved

        await _append_trace_event(
            job_id,
            seq=seq,
            step=step,
            status=trace_status,
            message=trace_message or error_message or status,
            db=db,
        )

        await db.commit()


# ================================================================
# Idempotency
# ================================================================


async def find_existing_job(
    db: AsyncSession, batch_import_id: str, image_import_id: str
) -> str | None:
    """查找已存在的 job_id（用于去重）。"""
    row = (
        await db.execute(
            select(ImportBatchJobItem.job_id).where(
                ImportBatchJobItem.batch_import_id == batch_import_id,
                ImportBatchJobItem.image_import_id == image_import_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row


async def _find_job_by_request_id(
    db: AsyncSession, request_id: str,
) -> str | None:
    """查找 request_id 对应的已有 job（job 级幂等）。"""
    if not request_id:
        return None
    row = (
        await db.execute(
            select(ImportBatchJob.job_id).where(
                ImportBatchJob.request_id == request_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row


# ================================================================
# Batch 创建
# ================================================================


async def create_batch_job(
    db: AsyncSession,
    *,
    job_id: str,
    sources: list[BatchImageSource],
    subject: str | None,
    concurrency: int,
    created_by: str | None,
    source_type: str = "image",
    batch_import_id: str | None = None,
    image_import_id: str | None = None,
    request_id: str | None = None,
    per_file_image_ids: list[str] | None = None,
    per_file_sha256: list[str] | None = None,
) -> ImportBatchJob:
    """落库一个批量任务 + 每张图片的 item 行（status=pending）。

    P0-4: idempotency via request_id (job-level), with per-file image_import_id
    and source_sha256 to avoid unique constraint conflicts.

    Supports two idempotency strategies:
    1. request_id-based: duplicate request_id returns existing job.
    2. (batch_import_id, image_import_id)-based: backward compat for single-image.
    """
    # P0-4: prefer request_id for job-level idempotency
    if request_id:
        existing = await _find_job_by_request_id(db, request_id)
        if existing:
            logger.info(
                "Duplicate batch submission: request_id=%s -> existing job=%s",
                request_id, existing,
            )
            stub = ImportBatchJob(
                job_id=existing,
                status="duplicate",
                total=0,
                concurrency=clamp_concurrency(concurrency),
            )
            return stub

    # Backward compat: single-image (batch_import_id, image_import_id) check
    if not request_id and batch_import_id and image_import_id and len(sources) <= 1:
        existing = await find_existing_job(db, batch_import_id, image_import_id)
        if existing:
            logger.info(
                "Duplicate batch image submission: batch=%s image=%s -> existing job=%s",
                batch_import_id, image_import_id, existing,
            )
            stub = ImportBatchJob(
                job_id=existing,
                status="duplicate",
                total=0,
                concurrency=clamp_concurrency(concurrency),
            )
            return stub

    now = _now()
    job = ImportBatchJob(
        job_id=job_id,
        source_type=source_type,
        subject=subject,
        total=len(sources),
        concurrency=clamp_concurrency(concurrency),
        status="queued",
        created_by=created_by,
        request_id=request_id,
        started_at=now,
        queued_at=now,
        updated_at=now,
    )
    db.add(job)

    for idx, src in enumerate(sources):
        per_image_id = (
            per_file_image_ids[idx]
            if per_file_image_ids and idx < len(per_file_image_ids)
            else image_import_id
        )
        per_sha256 = (
            per_file_sha256[idx]
            if per_file_sha256 and idx < len(per_file_sha256)
            else None
        )
        db.add(
            ImportBatchJobItem(
                job_id=job_id,
                seq=src.seq,
                source_file=src.source_file,
                source_sha256=per_sha256,
                status="pending",
                batch_import_id=batch_import_id,
                image_import_id=per_image_id,
                request_id=request_id,
                created_at=now,
                updated_at=now,
            )
        )

    # Append trace event for upload (need to flush to get seq)
    await db.flush()
    await _append_trace_event(
        job_id,
        seq=job.next_event_seq,
        step="upload",
        status="success",
        message=f"上传成功 ({len(sources)} 张)",
        request_id=request_id,
        image_import_id=image_import_id,
        batch_import_id=batch_import_id,
        db=db,
    )
    job.next_event_seq += 1

    # Lightweight AI model config pre-check — warn once per job, don't block
    try:
        from app.services.health_check_service import check_ai_model_config
        ai_check = await check_ai_model_config(db)
        if ai_check.severity in ("error", "warning"):
            await _append_trace_event(
                job_id,
                seq=job.next_event_seq,
                step=TraceStep.CONFIG.value,
                status=TraceEventStatus.WARNING.value,
                message=ai_check.message[:512],
                request_id=request_id,
                db=db,
            )
            job.next_event_seq += 1
    except Exception:
        logger.warning("AI model config pre-check failed (non-fatal)", exc_info=True)

    await db.commit()
    return job


# ================================================================
# 单图处理
# ================================================================


async def _merge_image_texts(
    job_id: str,
    subject: str | None,
    options: dict,
) -> dict:
    """Post-OCR merge: 将同批多张图片的 OCR 文本合并为连续文档再走一次导入流水线。

    只在全部图片成功且有 >=2 张产出 cleaned_text 时执行。
    失败时保留原始单图批次（不删除已有结果），保证数据不丢失。

    P0-4:
    - Merge idempotency: if merged_batch_id is already set, skip.
    - Old batches are marked superseded_by_batch_id + superseded_at instead of deleted.
    - Uses FOR UPDATE lock on job row to prevent concurrent merges.
    """
    now = _now()
    async with async_session() as db:
        # ── Idempotency guard: already merged? ──
        job = await db.get(ImportBatchJob, job_id, with_for_update=True)
        if job is None:
            return {"merged": False, "reason": "job not found"}
        if job.merge_status == "completed" and job.merged_batch_id:
            logger.info(
                "Merge already completed for job=%s batch=%s, skipping",
                job_id, job.merged_batch_id,
            )
            return {
                "merged": True,
                "batch_id": job.merged_batch_id,
                "reason": "already_merged",
            }
        job.merge_status = "running"
        job.merge_started_at = now
        await db.flush()

        rows = (
            await db.execute(
                select(ImportBatchJobItem)
                .where(
                    ImportBatchJobItem.job_id == job_id,
                    ImportBatchJobItem.status == "succeeded",
                    ImportBatchJobItem.ocr_cleaned_text.isnot(None),
                )
                .order_by(ImportBatchJobItem.seq)
            )
        ).scalars().all()

    if len(rows) < 2:
        msg = f"only {len(rows)} succeeded item(s)"
        async with async_session() as db:
            job = await db.get(ImportBatchJob, job_id)
            if job:
                job.merge_status = "skipped"
                job.merge_error = msg
                job.merge_finished_at = _now()
                await db.commit()
        logger.info("【MERGE-SKIP】job=%s %s", job_id, msg)
        return {"merged": False, "reason": msg}

    old_batch_ids = [r.review_batch_id for r in rows if r.review_batch_id]
    merged_text = "\n\n".join(r.ocr_cleaned_text for r in rows if r.ocr_cleaned_text)

    logger.info(
        "【MERGE-1】合并 %d 张图片 OCR 文本 | job=%s total_chars=%d",
        len(rows), job_id, len(merged_text),
    )
    log_event(
        logger, "batch_image.job.merge.start", "info",
        job_id=job_id, source_count=len(rows), total_chars=len(merged_text),
    )

    try:
        async with async_session() as pdb:
            from app.features.pipeline_orchestrator import run_import_pipeline

            merge_opts = dict(options)
            merge_opts["_merged_from_job"] = job_id
            merge_opts["skip_ocr_correction"] = True
            result = await run_import_pipeline(
                file_content=merged_text.encode("utf-8"),
                source_type="txt",
                source_file=f"batch_merged_{job_id}",
                subject=subject,
                options=merge_opts,
                db=pdb,
            )

        merged_batch_id = result.get("batch_id")
        qcount = (result.get("stats") or {}).get("to_review", 0)
        pipeline_ok = result.get("status") == "completed" and bool(merged_batch_id)

        if not pipeline_ok:
            errors = result.get("errors") or []
            reason = errors[0] if errors else "合并流水线未生成批次"
            async with async_session() as db:
                job = await db.get(ImportBatchJob, job_id)
                if job:
                    job.merge_status = "failed"
                    job.merge_error = reason
                    job.merge_finished_at = _now()
                    await db.commit()
            logger.warning("【MERGE-FAIL】job=%s reason=%s — 保留原始单图批次", job_id, reason)
            return {"merged": False, "reason": reason}

        logger.info(
            "【MERGE-2】合并流水线成功 | job=%s merged_batch=%s questions=%d",
            job_id, merged_batch_id, qcount,
        )

        async with async_session() as db:
            async with db.begin():
                superseded_count = await _batch_merge_commit(
                    db=db,
                    job_id=job_id,
                    merged_batch_id=merged_batch_id,
                    old_batch_ids=old_batch_ids,
                    items=rows,
                    now=now,
                )

        logger.info(
            "【MERGE-3】清理完成 | job=%s superseded_batches=%d",
            job_id, superseded_count,
        )
        log_event(
            logger, "batch_image.job.merge.finish", "info",
            job_id=job_id, merged_batch_id=merged_batch_id,
            question_count=qcount, superseded_batches=superseded_count,
        )
        return {
            "merged": True,
            "batch_id": merged_batch_id,
            "question_count": qcount,
            "source_count": len(rows),
            "superseded_batches": superseded_count,
        }
    except Exception:
        async with async_session() as db:
            job = await db.get(ImportBatchJob, job_id)
            if job:
                job.merge_status = "failed"
                job.merge_error = "exception during merge pipeline"
                job.merge_finished_at = _now()
                await db.commit()
        logger.exception("【MERGE-FAIL】合并流水线异常 | job=%s — 保留原始单图批次", job_id)
        return {"merged": False, "reason": "exception during merge pipeline"}


async def _run_vl_ocr(content: bytes, source_file: str) -> str:
    """使用 PaddleOCR-VL 远程 API 识别图片，返回原始文本。

    从 DB 模型配置中读取 api_key/api_base_url/model_name，
    通过 PaddleOCRVLClient 异步提交+轮询获取结果。
    """
    from app.services.model_config_resolver import resolve_active_model

    # 解析 DB 中的 PaddleOCR-VL 模型配置
    async with async_session() as db:
        resolved = await resolve_active_model(db, feature="ocr")
    if not resolved or not resolved.get("api_key"):
        raise ValueError(
            "PaddleOCR-VL 未配置：请在 AI 设置页面配置 paddleocr-vl 模型的 API Key"
        )

    api_token = resolved["api_key"]
    base_url = resolved.get("api_base_url", "https://paddleocr.aistudio-app.com")
    model = resolved.get("model_name", "PaddleOCR-VL-1.6")

    from app.features.ocr_vl.paddleocr_vl_client import PaddleOCRVLClient

    client = PaddleOCRVLClient(
        api_token=api_token,
        base_url=base_url,
        model=model,
    )

    vl_start = _now()
    logger.info("【OCR-VL】提交远程 OCR | file=%s model=%s", source_file, model)
    result = await client.ocr_image(image_bytes=content, filename=source_file)
    vl_duration = int((_now() - vl_start).total_seconds() * 1000)

    logger.info(
        "【OCR-VL】识别完成 | file=%s chars=%d conf=%.2f (%dms)\n%s",
        source_file, len(result.text), result.confidence, vl_duration,
        result.text[:2000],
    )
    return result.text


async def _run_single_image(
    item_id: int, source_file: str, content: bytes,
    subject: str | None, options: dict,
    job_id: str, seq: int,
) -> dict:
    """OCR → 清洗 → 现有 TXT 导入流水线。返回结果 dict（含 raw/cleaned 文本）。

    支持两种 OCR 模式：
    - local: 本地 PaddleOCR（默认）
    - api:   PaddleOCR-VL 远程 API（跳过本地 OCR + pipeline 纠错）
    """
    from app.services.ocr_service import clean_ocr_text, ocr_image

    ocr_mode = options.get("ocr_mode", "local")

    if ocr_mode == "api":
        # ── API 模式：使用 PaddleOCR-VL 替代本地 OCR ──
        raw_ocr_text = await _run_vl_ocr(content, source_file)
        skip_ocr_correction = True
    else:
        # ── 本地模式：本地 PaddleOCR ──
        ocr_start = _now()
        raw_ocr_text = await asyncio.to_thread(ocr_image, content)
        ocr_duration = int((_now() - ocr_start).total_seconds() * 1000)

        logger.info(
            "【OCR-1】PaddleOCR 原始结果 | file=%s chars=%d lines=%d\n%s",
            source_file, len(raw_ocr_text), raw_ocr_text.count("\n") + 1,
            raw_ocr_text[:2000],
        )

        # Trace: OCR done
        await _update_item_with_trace(
            item_id, job_id,
            fields={},
            trace=_TraceData(
                step="ocr", status="success",
                message=f"OCR 识别完成 ({ocr_duration}ms)",
                duration_ms=ocr_duration,
                item_seq=seq,
            ),
        )
        skip_ocr_correction = False

    cleaned_text = clean_ocr_text(raw_ocr_text)
    logger.info(
        "【OCR-2】clean_ocr_text 清洗结果 | file=%s chars=%d lines=%d%s\n%s",
        source_file, len(cleaned_text), cleaned_text.count("\n") + 1,
        " (未变化)" if cleaned_text == raw_ocr_text else "",
        cleaned_text[:2000],
    )

    # 先缓存 OCR 文本（即便后续解析失败，也能支持不重复 OCR 的重新解析）
    await _update_item_with_trace(
        item_id, job_id,
        fields={"ocr_raw_text": raw_ocr_text, "ocr_cleaned_text": cleaned_text},
        trace=_TraceData(
            step="ocr", status="success",
            message="OCR 文本已缓存",
            item_seq=seq,
        ),
    )

    if not cleaned_text.strip():
        raise ValueError("图片 OCR 未识别到可导入文本")

    async with async_session() as pdb:
        from app.features.pipeline_orchestrator import run_import_pipeline

        # API 模式：VL 已产出高质量文本，跳过 pipeline 的 ocr_correction 阶段
        pipeline_opts = {**options, "skip_ocr_correction": skip_ocr_correction, "_original_raw_text": raw_ocr_text}

        # Save image to temp file for VL_REBUILD fallback (needs disk path)
        import tempfile
        _tmp_img_path: str | None = None
        if content:
            try:
                ext = os.path.splitext(source_file)[1] or ".png"
                tmpf = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmpf.write(content)
                _tmp_img_path = tmpf.name
                tmpf.close()
            except Exception as exc:
                logger.warning("Failed to save temp image for VL_REBUILD: %s", exc)

        pipeline_start = _now()
        try:
            result = await run_import_pipeline(
                file_content=cleaned_text.encode("utf-8"),
                file_path=_tmp_img_path,
                source_type="image",
                source_file=source_file,
                subject=subject,
                options=pipeline_opts,
                db=pdb,
                page_images={1: content},
            )
        finally:
            # Clean up temp image file
            if _tmp_img_path:
                try:
                    os.unlink(_tmp_img_path)
                except Exception:
                    pass
        pipeline_duration = int((_now() - pipeline_start).total_seconds() * 1000)

    batch_id = result.get("batch_id")
    qcount = (result.get("stats") or {}).get("to_review", 0)
    stage_errors = result.get("errors", [])
    logger.info(
        "【OCR-9】流水线汇总 | file=%s status=%s batch=%s questions=%d errors=%s",
        source_file, result.get("status", "?"),
        batch_id or "❌", qcount,
        stage_errors[0] if stage_errors else "无",
    )

    # Trace: pipeline done
    await _update_item_with_trace(
        item_id, job_id,
        fields={},
        trace=_TraceData(
            step="pipeline", status="success",
            message=f"解析流水线完成 ({pipeline_duration}ms)",
            duration_ms=pipeline_duration,
            item_seq=seq,
        ),
    )

    result["_ocr_raw_text"] = raw_ocr_text
    result["_ocr_cleaned_text"] = cleaned_text
    return result


async def _process_source(
    sem: asyncio.Semaphore,
    *,
    item_id: int,
    src: BatchImageSource,
    subject: str | None,
    options: dict,
    job_id: str,
) -> None:
    """单张图片 worker：失败隔离，绝不向上抛异常。"""
    async with sem:
        await _update_item_with_trace(
            item_id, job_id,
            fields={"status": "processing", "started_at": _now()},
            trace=_TraceData(
                step="ocr", status="running",
                message=f"第 {src.seq} 张开始识别",
                item_seq=src.seq,
            ),
        )
        log_event(
            logger, "batch_image.item.start", "info",
            item_id=item_id, source_file=src.source_file, seq=src.seq,
        )

        proc_start = _now()

        try:
            with open(src.temp_path, "rb") as fh:
                content = fh.read()

            result = await _run_single_image(
                item_id, src.source_file, content, subject, options,
                job_id=job_id, seq=src.seq,
            )
            del content

            review_batch_id = result.get("batch_id") or None
            question_count = (result.get("stats") or {}).get("to_review", 0)
            pipeline_ok = result.get("status") == "completed"

            if pipeline_ok and review_batch_id:
                await _update_item_with_trace(
                    item_id, job_id,
                    fields={
                        "status": "succeeded",
                        "review_batch_id": review_batch_id,
                        "pipeline_id": result.get("pipeline_id"),
                        "question_count": question_count,
                        "error_message": None,
                        "finished_at": _now(),
                    },
                    trace=_TraceData(
                        step="done", status="success",
                        message=f"识别完成，生成 {question_count} 道题",
                        item_seq=src.seq,
                        duration_ms=int((_now() - proc_start).total_seconds() * 1000),
                    ),
                )
                logger.info(
                    "batch image item succeeded: item_id=%s file=%s batch_id=%s questions=%s",
                    item_id, src.source_file, review_batch_id, question_count,
                )
                log_event(
                    logger, "batch_image.item.finish", "info",
                    item_id=item_id, source_file=src.source_file,
                    review_batch_id=review_batch_id, question_count=question_count,
                    duration_ms=int((_now() - proc_start).total_seconds() * 1000),
                )
            else:
                errors = result.get("errors") or []
                reason = errors[0] if errors else "OCR 文本未生成待审核批次"
                await _update_item_with_trace(
                    item_id, job_id,
                    fields={
                        "status": "failed",
                        "pipeline_id": result.get("pipeline_id"),
                        "question_count": question_count,
                        "error_message": reason,
                        "finished_at": _now(),
                    },
                    trace=_TraceData(
                        step="error", status="failed",
                        message=reason,
                        item_seq=src.seq,
                    ),
                )
                logger.warning(
                    "batch image item produced no review batch: item_id=%s file=%s reason=%s",
                    item_id, src.source_file, reason,
                )
        except Exception as exc:
            logger.exception(
                "batch image item failed: item_id=%s file=%s", item_id, src.source_file
            )
            log_event(
                logger, "batch_image.item.error", "error",
                item_id=item_id, source_file=src.source_file,
                error_type=type(exc).__name__,
                error_message=str(exc)[:500],
            )
            await _update_item_with_trace(
                item_id, job_id,
                fields={
                    "status": "failed",
                    "error_message": str(exc),
                    "finished_at": _now(),
                },
                trace=_TraceData(
                    step="error", status="failed",
                    message=str(exc)[:512],
                    item_seq=src.seq,
                ),
            )
        finally:
            if src.temp_path and os.path.exists(src.temp_path):
                try:
                    os.unlink(src.temp_path)
                except OSError as exc:
                    logger.warning("delete batch tmp file failed: %s (%s)", src.temp_path, exc)


# ================================================================
# 后台批量执行
# ================================================================


async def run_batch_job(
    *,
    job_id: str,
    sources: list[BatchImageSource],
    subject: str | None,
    options: dict,
    concurrency: int,
) -> None:
    """后台编排：信号量限并发逐张处理，全部结束后标记任务完成。

    本函数被 BackgroundTasks 调度，独立于请求生命周期；任何未捕获异常都会
    把整个 job 标记为 failed，但单张图片的异常已在 worker 内被吞掉。

    P0-5 fix: job transitions to MERGING before merge, then to COMPLETED
    after merge succeeds. SSE receivers never see a terminal state before
    merge is actually done.
    """
    concurrency = clamp_concurrency(concurrency)
    logger.info(
        "batch image job started: job_id=%s total=%d concurrency=%d",
        job_id, len(sources), concurrency,
    )

    # Bind trace context for the entire batch job lifetime
    _trace_id = (options or {}).get("_trace_id")
    _request_id = (options or {}).get("_request_id")
    bind_ctx: dict = {"job_id": job_id}
    if _trace_id:
        bind_ctx["trace_id"] = _trace_id
    if _request_id:
        bind_ctx["request_id"] = _request_id
    bind_log_context(**bind_ctx)
    log_event(
        logger, "batch_image.job.start", "info",
        total=len(sources), concurrency=concurrency,
        subject=subject, ocr_mode=(options or {}).get("ocr_mode", "local"),
    )

    # Pre-resolve OCR model config once for the entire job (api mode only).
    # This avoids per-image resolution calls and ensures config is cached.
    ocr_mode = (options or {}).get("ocr_mode", "local")
    if ocr_mode == "api":
        from app.services.model_config_resolver import resolve_active_model
        async with async_session() as db:
            _resolved_ocr_config = await resolve_active_model(db, feature="ocr")
    try:
        await _set_job_status_with_trace(
            job_id, "running",
            trace_message=f"开始处理 ({len(sources)} 张)",
        )

        # 把 (seq -> item_id) 映射出来，worker 用 item_id 更新行。
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(ImportBatchJobItem.id, ImportBatchJobItem.seq).where(
                        ImportBatchJobItem.job_id == job_id
                    )
                )
            ).all()
        seq_to_item = {seq: item_id for item_id, seq in rows}

        sem = asyncio.Semaphore(concurrency)
        tasks = [
            _process_source(
                sem,
                item_id=seq_to_item[src.seq],
                src=src,
                subject=subject,
                options=options,
                job_id=job_id,
            )
            for src in sources
            if src.seq in seq_to_item
        ]
        await asyncio.gather(*tasks)

        # 派生 batch status：从 items 状态计算
        async with async_session() as db:
            statuses = (
                await db.execute(
                    select(ImportBatchJobItem.status).where(
                        ImportBatchJobItem.job_id == job_id
                    )
                )
            ).scalars().all()

        total = len(statuses)
        succeeded = sum(1 for s in statuses if s == "succeeded")
        failed = total - succeeded

        # ── P0-5: merge 前只设 MERGING，不设 COMPLETED ──
        if succeeded == total and len(sources) >= 2:
            # 全部成功 → 进入 merging 状态，执行跨图片合并
            await _set_job_status_with_trace(
                job_id, "merging",
                trace_message="图片全部处理完成，开始合并",
            )
            merge_result = await _merge_image_texts(
                job_id=job_id, subject=subject, options=options,
            )
            if merge_result.get("merged"):
                logger.info(
                    "batch image job merged: job_id=%s merged_batch=%s questions=%d",
                    job_id, merge_result.get("batch_id"), merge_result.get("question_count"),
                )
                await _set_job_status_with_trace(
                    job_id, "completed",
                    error_message=None,
                    trace_message=f"合并完成，共 {merge_result.get('question_count', 0)} 道题",
                )
            else:
                reason = merge_result.get("reason", "合并失败")
                logger.warning("batch image merge failed: job_id=%s reason=%s", job_id, reason)
                # merge 失败：job 仍为 completed（保留了原始单图批次），但带上 warning
                await _set_job_status_with_trace(
                    job_id, "completed",
                    error_message=f"合并未执行: {reason}",
                    trace_message=f"单图处理完成 (合并跳过: {reason})",
                )
        elif succeeded == total:
            # 单张图片：无合并必要，直接完成
            await _set_job_status_with_trace(
                job_id, "completed",
                error_message=None,
                trace_message="全部处理完成",
            )
        elif succeeded > 0:
            await _set_job_status_with_trace(
                job_id, "completed",
                error_message=f"部分失败: {failed}/{total}",
                trace_message=f"部分失败: {failed}/{total}",
            )
        else:
            await _set_job_status_with_trace(
                job_id, "failed",
                error_message=f"全部失败: {failed}/{total}",
                trace_message=f"全部失败: {failed}/{total}",
            )

        logger.info("batch image job completed: job_id=%s", job_id)
        _was_merged = "merge_result" in locals() and merge_result.get("merged", False)
        log_event(
            logger, "batch_image.job.finish", "info",
            job_id=job_id, succeeded=succeeded, failed=failed, total=total,
            merged=_was_merged,
        )
    except Exception as exc:
        logger.exception("batch image job crashed: job_id=%s", job_id)
        log_event(
            logger, "batch_image.job.error", "error",
            job_id=job_id, error_type=type(exc).__name__,
            error_message=str(exc)[:500],
        )
        await _set_job_status_with_trace(
            job_id, "failed",
            error_message=str(exc),
            trace_message=f"任务异常: {exc}",
        )
    finally:
        # 兜底清理：worker 已逐个 unlink，这里清理可能残留的临时文件。
        for src in sources:
            if src.temp_path and os.path.exists(src.temp_path):
                try:
                    os.unlink(src.temp_path)
                except OSError:
                    pass


# ================================================================
# 查询
# ================================================================


async def get_batch_job_status(db: AsyncSession, job_id: str) -> dict:
    """聚合任务进度（总数/已完成/处理中/等待中）+ 每张 item 明细 + trace events。"""
    job = await db.get(ImportBatchJob, job_id)
    if job is None:
        raise ValueError("批量导题任务不存在")

    rows = (
        await db.execute(
            select(ImportBatchJobItem)
            .where(ImportBatchJobItem.job_id == job_id)
            .order_by(ImportBatchJobItem.seq)
        )
    ).scalars().all()

    counts = {"pending": 0, "processing": 0, "succeeded": 0, "failed": 0}
    total_questions = 0
    current_file = ""
    current_seq = 0
    merged_batch_id = ""
    items: list[dict] = []
    for item in rows:
        counts[item.status] = counts.get(item.status, 0) + 1
        total_questions += item.question_count or 0
        if item.status == "processing" and not current_file:
            current_file = item.source_file or ""
            current_seq = item.seq
        items.append({
            "id": item.id,
            "seq": item.seq,
            "source_file": item.source_file,
            "status": item.status,
            "review_batch_id": item.review_batch_id,
            "question_count": item.question_count or 0,
            "error_message": item.error_message,
            "has_ocr_cache": bool(item.ocr_cleaned_text or item.ocr_raw_text),
            "batch_import_id": item.batch_import_id,
            "image_import_id": item.image_import_id,
            "request_id": item.request_id,
        })

    # 显式检测合并状态
    is_merged = False
    succeeded_items = [r for r in items if r["status"] == "succeeded" and r["review_batch_id"]]
    if len(succeeded_items) >= 2:
        candidate = succeeded_items[0]["review_batch_id"]
        if all(it["review_batch_id"] == candidate for it in succeeded_items):
            is_merged = True
            merged_batch_id = candidate
            from app.models.question_import import QuestionImport as QI
            q_count = await db.scalar(
                select(func.count()).select_from(QI).where(QI.batch_id == merged_batch_id)
            )
            total_questions = q_count or 0

    done = counts["succeeded"] + counts["failed"]
    partial_failure = counts["succeeded"] > 0 and counts["failed"] > 0

    # 读取 trace events
    events = (
        await db.execute(
            select(BatchJobTraceEvent)
            .where(BatchJobTraceEvent.job_id == job_id)
            .order_by(BatchJobTraceEvent.seq)
        )
    ).scalars().all()
    trace_events = [
        {
            "seq": e.seq,
            "item_seq": e.item_seq or 0,
            "request_id": e.request_id,
            "image_import_id": e.image_import_id,
            "batch_import_id": e.batch_import_id,
            "step": e.step,
            "status": e.status,
            "message": e.message,
            "duration_ms": e.duration_ms,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]

    return {
        "job_id": job.job_id,
        "status": job.status,
        "source_type": job.source_type,
        "subject": job.subject,
        "concurrency": job.concurrency,
        "total": job.total,
        "completed": done,
        "processing": counts["processing"],
        "pending": counts["pending"],
        "succeeded": counts["succeeded"],
        "failed": counts["failed"],
        "total_questions": total_questions,
        "is_merged": is_merged,
        "merged_batch_id": merged_batch_id,
        "partial_failure": partial_failure,
        "current_seq": current_seq,
        "current_file": current_file,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else "",
        "items": items,
        "trace_events": trace_events,
    }


# ================================================================
# SSE 轮询（增量 trace events + job 终态检测）
# ================================================================


async def poll_trace_events(
    db: AsyncSession, job_id: str, since_id: int = 0
) -> list[dict]:
    """返回 id > since_id 的增量 trace events（按 auto-increment id 排序）。"""
    rows = (
        await db.execute(
            select(BatchJobTraceEvent)
            .where(
                BatchJobTraceEvent.job_id == job_id,
                BatchJobTraceEvent.id > since_id,
            )
            .order_by(BatchJobTraceEvent.id)
        )
    ).scalars().all()
    return [
        {
            "id": e.id,
            "seq": e.id,  # seq == id for API consumers
            "item_seq": e.item_seq or 0,
            "step": e.step,
            "status": e.status,
            "message": e.message,
            "duration_ms": e.duration_ms,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


async def poll_job_summary(
    db: AsyncSession, job_id: str,
) -> dict | None:
    """简化的 job 终态摘要（用于 SSE done event）。"""
    job = await db.get(ImportBatchJob, job_id)
    if job is None:
        return None
    rows = (
        await db.execute(
            select(ImportBatchJobItem)
            .where(ImportBatchJobItem.job_id == job_id)
        )
    ).scalars().all()
    total_questions = sum(item.question_count or 0 for item in rows)
    succeeded = sum(1 for item in rows if item.status == "succeeded")
    failed = sum(1 for item in rows if item.status == "failed")
    return {
        "status": job.status,
        "total_questions": total_questions,
        "error_message": job.error_message,
        "succeeded": succeeded,
        "failed": failed,
    }


# ================================================================
# 重新解析
# ================================================================


async def reparse_item_from_cache(db: AsyncSession, item_id: int, subject: str | None = None) -> dict:
    """基于缓存的 OCR 文本重新跑导入流水线（不重复 OCR）。

    用于 AI 解析失败 / Prompt 调整后重新解析。复用 ocr_cleaned_text；
    若只有原始文本则现场清洗一次。

    P0-2 fix:
    1. Atomically transition item from succeeded/failed -> reprocessing.
    2. If transition fails (e.g. concurrent reparse already started), raise.
    3. After pipeline: if success, atomically switch review_batch_id;
       if failure, preserve previous_review_batch_id.
    """
    item = await db.get(ImportBatchJobItem, item_id)
    if item is None:
        raise ValueError("批量导题条目不存在")

    # ── Atomic: transition to reprocessing ──
    _guard_item_transition(item.status, "reprocessing")
    previous_batch_id = item.review_batch_id
    item.status = "reprocessing"
    item.reparse_attempt = (item.reparse_attempt or 0) + 1
    item.reparse_started_at = _now()
    item.previous_review_batch_id = previous_batch_id
    await db.flush()

    cleaned = item.ocr_cleaned_text
    if not cleaned and item.ocr_raw_text:
        from app.services.ocr_service import clean_ocr_text
        cleaned = clean_ocr_text(item.ocr_raw_text)
    if not cleaned or not cleaned.strip():
        item.status = "failed"
        item.reparse_finished_at = _now()
        await db.commit()
        raise ValueError("该条目没有可复用的 OCR 缓存文本")

    job = await db.get(ImportBatchJob, item.job_id)
    effective_subject = subject or (job.subject if job else None)

    # ── Run pipeline ──
    async with async_session() as pdb:
        from app.features.pipeline_orchestrator import run_import_pipeline
        result = await run_import_pipeline(
            file_content=cleaned.encode("utf-8"),
            source_type="txt",
            source_file=item.source_file or "reparse",
            subject=effective_subject,
            options={"enable_ai_repair": True, "confidence_threshold": 0.6},
            db=pdb,
        )

    review_batch_id = result.get("batch_id") or None
    question_count = (result.get("stats") or {}).get("to_review", 0)
    pipeline_ok = result.get("status") == "completed" and bool(review_batch_id)

    now = _now()
    if pipeline_ok:
        # ── Success: atomically switch to new batch ──
        await _update_item_with_trace(
            item.id, item.job_id,
            fields={
                "status": "succeeded",
                "review_batch_id": review_batch_id,
                "pipeline_id": result.get("pipeline_id"),
                "question_count": question_count,
                "error_message": None,
                "previous_review_batch_id": previous_batch_id,
                "reparse_finished_at": now,
            },
            trace=_TraceData(
                step="pipeline", status="success",
                message=f"重新解析完成，生成 {question_count} 道题",
                item_seq=item.seq,
                request_id=item.request_id,
                image_import_id=item.image_import_id,
                batch_import_id=item.batch_import_id,
            ),
        )
    else:
        # ── Failure: preserve previous batch, mark item failed ──
        error_msg = (result.get("errors") or ["重新解析未生成待审核批次"])[0]
        await _update_item_with_trace(
            item.id, item.job_id,
            fields={
                "status": "failed",
                "review_batch_id": previous_batch_id,  # restore previous
                "pipeline_id": result.get("pipeline_id"),
                "question_count": 0,
                "error_message": error_msg,
                "reparse_finished_at": now,
            },
            trace=_TraceData(
                step="pipeline", status="failed",
                message=error_msg,
                item_seq=item.seq,
                request_id=item.request_id,
                image_import_id=item.image_import_id,
                batch_import_id=item.batch_import_id,
            ),
        )

    return {
        "item_id": item.id,
        "status": item.status,
        "review_batch_id": review_batch_id if pipeline_ok else previous_batch_id,
        "question_count": question_count,
        "error_message": None if pipeline_ok else error_msg,
    }
