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
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

logger = logging.getLogger(__name__)

_MIN_CONCURRENCY = 1
_MAX_CONCURRENCY = 4


@dataclass
class BatchImageSource:
    """一张待处理图片：序号 + 原始文件名 + 落盘的临时文件路径。

    临时文件由编排器负责在处理完成后删除（PDF 拆页路径同样复用此结构）。
    """

    seq: int
    source_file: str
    temp_path: str


def _now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


def clamp_concurrency(value: int | None) -> int:
    default = max(_MIN_CONCURRENCY, min(_MAX_CONCURRENCY, settings.BATCH_IMAGE_DEFAULT_CONCURRENCY))
    if value is None:
        return default
    return max(_MIN_CONCURRENCY, min(_MAX_CONCURRENCY, value))


def new_job_id() -> str:
    return f"BIMG_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


async def create_batch_job(
    db: AsyncSession,
    *,
    job_id: str,
    sources: list[BatchImageSource],
    subject: str | None,
    concurrency: int,
    created_by: str | None,
    source_type: str = "image",
) -> ImportBatchJob:
    """落库一个批量任务 + 每张图片的 item 行（status=pending）。"""
    now = _now()
    job = ImportBatchJob(
        job_id=job_id,
        source_type=source_type,
        subject=subject,
        total=len(sources),
        concurrency=clamp_concurrency(concurrency),
        status="queued",
        created_by=created_by,
        started_at=now,
        updated_at=now,
    )
    db.add(job)
    for src in sources:
        db.add(
            ImportBatchJobItem(
                job_id=job_id,
                seq=src.seq,
                source_file=src.source_file,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
    await db.commit()
    return job


async def _update_item(item_id: int, **fields) -> None:
    """短事务更新单个 item，避免长时间持有连接。"""
    async with async_session() as db:
        item = await db.get(ImportBatchJobItem, item_id)
        if item is None:
            return
        for key, value in fields.items():
            setattr(item, key, value)
        item.updated_at = _now()
        await db.commit()


async def _set_job_status(job_id: str, status: str, error_message: str | None = None) -> None:
    async with async_session() as db:
        job = await db.get(ImportBatchJob, job_id)
        if job is None:
            return
        job.status = status
        if error_message is not None:
            job.error_message = error_message
        if status in {"completed", "failed"}:
            job.finished_at = _now()
        job.updated_at = _now()
        await db.commit()


async def _run_single_image(item_id: int, source_file: str, content: bytes, subject: str | None, options: dict) -> dict:
    """OCR → 清洗 → 现有 TXT 导入流水线。返回结果 dict（含 raw/cleaned 文本）。

    注意：OCR 同步且 GPU 串行，用 to_thread 避免阻塞事件循环。
    """
    from app.services.ocr_service import clean_ocr_text, ocr_image

    raw_ocr_text = await asyncio.to_thread(ocr_image, content)
    logger.info(
        "【OCR-1】PaddleOCR 原始结果 | file=%s chars=%d lines=%d\n%s",
        source_file, len(raw_ocr_text), raw_ocr_text.count("\n") + 1,
        raw_ocr_text[:2000],
    )

    cleaned_text = clean_ocr_text(raw_ocr_text)
    logger.info(
        "【OCR-2】clean_ocr_text 清洗结果 | file=%s chars=%d lines=%d%s\n%s",
        source_file, len(cleaned_text), cleaned_text.count("\n") + 1,
        " (未变化)" if cleaned_text == raw_ocr_text else "",
        cleaned_text[:2000],
    )

    # 先缓存 OCR 文本（即便后续解析失败，也能支持不重复 OCR 的重新解析）
    await _update_item(
        item_id,
        ocr_raw_text=raw_ocr_text,
        ocr_cleaned_text=cleaned_text,
    )

    if not cleaned_text.strip():
        raise ValueError("图片 OCR 未识别到可导入文本")

    async with async_session() as pdb:
        from app.features.pipeline_orchestrator import run_import_pipeline

        result = await run_import_pipeline(
            file_content=cleaned_text.encode("utf-8"),
            source_type="txt",
            source_file=source_file,
            subject=subject,
            options=options,
            db=pdb,
            page_images={1: content},
        )
    batch_id = result.get("batch_id")
    qcount = (result.get("stats") or {}).get("to_review", 0)
    stage_errors = result.get("errors", [])
    logger.info(
        "【OCR-9】流水线汇总 | file=%s status=%s batch=%s questions=%d errors=%s",
        source_file, result.get("status", "?"),
        batch_id or "❌", qcount,
        stage_errors[0] if stage_errors else "无",
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
) -> None:
    """单张图片 worker：失败隔离，绝不向上抛异常。"""
    async with sem:
        await _update_item(item_id, status="processing", started_at=_now())
        try:
            with open(src.temp_path, "rb") as fh:
                content = fh.read()

            result = await _run_single_image(item_id, src.source_file, content, subject, options)
            del content

            review_batch_id = result.get("batch_id") or None
            question_count = (result.get("stats") or {}).get("to_review", 0)
            pipeline_ok = result.get("status") == "completed"

            if pipeline_ok and review_batch_id:
                await _update_item(
                    item_id,
                    status="succeeded",
                    review_batch_id=review_batch_id,
                    pipeline_id=result.get("pipeline_id"),
                    question_count=question_count,
                    error_message=None,
                    finished_at=_now(),
                )
                logger.info(
                    "batch image item succeeded: item_id=%s file=%s batch_id=%s questions=%s",
                    item_id, src.source_file, review_batch_id, question_count,
                )
            else:
                errors = result.get("errors") or []
                reason = errors[0] if errors else "OCR 文本未生成待审核批次"
                await _update_item(
                    item_id,
                    status="failed",
                    pipeline_id=result.get("pipeline_id"),
                    question_count=question_count,
                    error_message=reason,
                    finished_at=_now(),
                )
                logger.warning(
                    "batch image item produced no review batch: item_id=%s file=%s reason=%s",
                    item_id, src.source_file, reason,
                )
        except Exception as exc:
            logger.exception(
                "batch image item failed: item_id=%s file=%s", item_id, src.source_file
            )
            await _update_item(
                item_id,
                status="failed",
                error_message=str(exc),
                finished_at=_now(),
            )
        finally:
            if src.temp_path and os.path.exists(src.temp_path):
                try:
                    os.unlink(src.temp_path)
                except OSError as exc:
                    logger.warning("delete batch tmp file failed: %s (%s)", src.temp_path, exc)


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
    """
    concurrency = clamp_concurrency(concurrency)
    logger.info(
        "batch image job started: job_id=%s total=%d concurrency=%d",
        job_id, len(sources), concurrency,
    )
    try:
        await _set_job_status(job_id, "running")

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
            )
            for src in sources
            if src.seq in seq_to_item
        ]
        await asyncio.gather(*tasks)

        await _set_job_status(job_id, "completed")
        logger.info("batch image job completed: job_id=%s", job_id)
    except Exception as exc:
        logger.exception("batch image job crashed: job_id=%s", job_id)
        await _set_job_status(job_id, "failed", error_message=str(exc))
    finally:
        # 兜底清理：worker 已逐个 unlink，这里清理可能残留的临时文件。
        for src in sources:
            if src.temp_path and os.path.exists(src.temp_path):
                try:
                    os.unlink(src.temp_path)
                except OSError:
                    pass


async def get_batch_job_status(db: AsyncSession, job_id: str) -> dict:
    """聚合任务进度（总数/已完成/处理中/等待中）+ 每张 item 明细。"""
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
        })

    done = counts["succeeded"] + counts["failed"]
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
        "current_seq": current_seq,
        "current_file": current_file,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else "",
        "items": items,
    }


async def reparse_item_from_cache(db: AsyncSession, item_id: int, subject: str | None = None) -> dict:
    """基于缓存的 OCR 文本重新跑导入流水线（不重复 OCR）。

    用于 AI 解析失败 / Prompt 调整后重新解析。复用 ocr_cleaned_text；
    若只有原始文本则现场清洗一次。
    """
    item = await db.get(ImportBatchJobItem, item_id)
    if item is None:
        raise ValueError("批量导题条目不存在")

    cleaned = item.ocr_cleaned_text
    if not cleaned and item.ocr_raw_text:
        from app.services.ocr_service import clean_ocr_text

        cleaned = clean_ocr_text(item.ocr_raw_text)
    if not cleaned or not cleaned.strip():
        raise ValueError("该条目没有可复用的 OCR 缓存文本")

    job = await db.get(ImportBatchJob, item.job_id)
    effective_subject = subject or (job.subject if job else None)

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

    item.status = "succeeded" if pipeline_ok else "failed"
    item.review_batch_id = review_batch_id
    item.pipeline_id = result.get("pipeline_id")
    item.question_count = question_count
    item.error_message = None if pipeline_ok else ((result.get("errors") or ["重新解析未生成待审核批次"])[0])
    item.finished_at = _now()
    item.updated_at = _now()
    await db.commit()

    return {
        "item_id": item.id,
        "status": item.status,
        "review_batch_id": review_batch_id,
        "question_count": question_count,
        "error_message": item.error_message,
    }
