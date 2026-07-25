"""Import pipeline service — shared business logic for import pipelines.

API Router 层只负责：鉴权、参数解析、调用 service、返回 response。
业务流程编排在 service 层完成，不依赖 FastAPI HTTP 对象 (UploadFile, Request, Depends)。
"""

import hashlib
import importlib.util
import logging
import os
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session
from app.core.log_context import bind_log_context, get_log_context, log_event
from app.core.resource_guard import resource_guard
from app.features.pipeline_coordinator_entry import run_pipeline
from app.features.pipeline_orchestrator import (
    _set_pipeline_store,
    resolve_pdf_page_range,
    resume_pipeline_background,
    run_pipeline_background,
)
from app.features.pipeline_orchestrator import (
    get_pipeline_status as _orchestrator_get_pipeline_status,
)
from app.schemas.import_review import (
    PdfPageRangeInfo,
    PipelineStatusResponse,
    PipelineUploadResponse,
)
from app.services.staging_storage import async_store_file
from app.services.upload_validator import get_upload_validator
from app.utils.sentry_utils import capture_exception, set_tag

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _sha256_of_file(path: str) -> str:
    """Compute SHA-256 of a file without loading it entirely into memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_PIPELINE_STORE_SIZE = 200
_IMAGE_PIPELINE_STATUS_TTL_SECONDS = 86400
_IMAGE_PIPELINE_REDIS_PREFIX = "import:image:pipeline"
_image_pipeline_store: dict[str, dict] = {}


def _image_pipeline_key(pipeline_id: str) -> str:
    return f"{_IMAGE_PIPELINE_REDIS_PREFIX}:{pipeline_id}"


def _prune_image_pipeline_store() -> None:
    if len(_image_pipeline_store) <= _MAX_IMAGE_PIPELINE_STORE_SIZE:
        return
    over_limit = len(_image_pipeline_store) - _MAX_IMAGE_PIPELINE_STORE_SIZE
    oldest_ids = sorted(
        _image_pipeline_store,
        key=lambda pid: _image_pipeline_store[pid].get("started_at", ""),
    )[:over_limit]
    for pipeline_id in oldest_ids:
        _image_pipeline_store.pop(pipeline_id, None)


async def _set_image_pipeline_status(image_pipeline_id: str, **updates) -> dict:
    updates.pop("pipeline_id", None)
    status = _image_pipeline_store.setdefault(
        image_pipeline_id,
        {
            "pipeline_id": image_pipeline_id,
            "status": "queued",
            "source_type": "image",
            "stages": {},
            "stats": {},
            "errors": [],
            "batch_id": "",
            "started_at": datetime.now().isoformat(),
        },
    )
    if "started_at" in updates and status.get("started_at"):
        updates = {k: v for k, v in updates.items() if k != "started_at"}
    status.update(updates)
    _prune_image_pipeline_store()
    try:
        await cache.set(
            _image_pipeline_key(image_pipeline_id),
            status,
            ttl=_IMAGE_PIPELINE_STATUS_TTL_SECONDS,
        )
    except Exception:
        logger.warning("image pipeline status cache write failed: pipeline_id=%s", image_pipeline_id)
    return status


async def _get_image_pipeline_status(pipeline_id: str) -> dict | None:
    try:
        cached = await cache.get(_image_pipeline_key(pipeline_id))
    except Exception:
        logger.warning("image pipeline status cache read failed: pipeline_id=%s", pipeline_id)
        cached = None
    if cached is not None:
        _image_pipeline_store[pipeline_id] = cached
        _prune_image_pipeline_store()
        return cached
    return _image_pipeline_store.get(pipeline_id)


def _validate_image_path(path: str) -> tuple[int, int, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ValueError("图片解析依赖不可用") from exc

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            image_format = (img.format or "").lower()
    except (UnidentifiedImageError, FileNotFoundError) as exc:
        raise ValueError("图片内容无法解析") from exc
    except Exception as exc:
        raise ValueError("图片内容校验失败") from exc

    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    return width, height, image_format


def _build_ocr_text_diagnostics(raw_ocr_text: str, cleaned_text: str) -> dict:
    raw_lines = [line for line in raw_ocr_text.splitlines() if line.strip()]
    cleaned_lines = [line for line in cleaned_text.splitlines() if line.strip()]
    return {
        "raw_text_length": len(raw_ocr_text),
        "cleaned_text_length": len(cleaned_text),
        "raw_line_count": len(raw_lines),
        "cleaned_line_count": len(cleaned_lines),
        "raw_text_preview": raw_ocr_text[:1000],
        "cleaned_text_preview": cleaned_text[:1000],
        "text_length_delta": len(raw_ocr_text) - len(cleaned_text),
        "line_count_delta": len(raw_lines) - len(cleaned_lines),
    }


def _build_ocr_runtime_diagnostics() -> dict:
    result: dict = {
        "ocr_enabled": settings.OCR_ENABLED,
    }
    try:
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
        profile = detect_deployment_profile()
        if profile == DeploymentProfile.CLOUD_API:
            result["paddleocr_available"] = False
        else:
            result["paddleocr_available"] = importlib.util.find_spec("paddleocr") is not None
    except Exception:
        result["paddleocr_available"] = False
    return result


# ImportPipeline uses the shared OCR executor service
from app.services.ocr_executor_service import ocr_executor


async def _run_ocr_in_thread(image_bytes: bytes) -> str:
    """Run ocr_image in the shared bounded executor.

    Uses a process-wide executor with semaphore, queue limit, and timeout.
    Raises TimeoutError if OCR exceeds OCR_TIMEOUT_SECONDS.
    """
    try:
        text = await ocr_executor.run_ocr(image_bytes, timeout=settings.OCR_TIMEOUT_SECONDS)
        return text
    except TimeoutError:
        raise
    except Exception as e:
        logger.error("OCR failed: %s", e)
        raise


def _classify_image_pipeline_result(result: dict, cleaned_text: str) -> str | None:
    if not cleaned_text.strip():
        return "ocr_empty_text"
    split = result.get("diagnostics", {}).get("split", {})
    if split.get("failure_reason") == "text_present_but_no_question_boundary":
        return "text_present_but_split_failed"
    schema_errors = result.get("diagnostics", {}).get("schema_errors", [])
    if any("missing_options" in item.get("errors", []) for item in schema_errors if isinstance(item, dict)):
        return "missing_options"
    if result.get("status") != "completed":
        return "pipeline_failed"
    return None


async def _fail_image_pipeline(pipeline_id: str, error: str) -> None:
    current = await _get_image_pipeline_status(pipeline_id) or {}
    errors = list(current.get("errors", []))
    errors.append(error)
    stages = dict(current.get("stages", {}))
    if stages:
        active_stage = next(
            (
                name
                for name, stage in reversed(list(stages.items()))
                if stage.get("status") in {"running", "pending"}
            ),
            None,
        )
        if active_stage:
            stages[active_stage] = {**stages[active_stage], "status": "failed", "error": error}
    await _set_image_pipeline_status(
        pipeline_id,
        status="failed",
        errors=errors,
        stages=stages,
        finished_at=datetime.now().isoformat(),
    )


async def _run_image_pipeline_with_db(
    pipeline_id: str,
    image_path: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> None:
    """图片后台任务：OCR → TXT bytes → 现有导入流水线。"""
    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
        source_type="image",
        source_file=source_file,
    )

    log_event(
        logger, "import.background.start",
        pipeline_id=pipeline_id, source_type="image",
        source_file=source_file,
    )

    set_tag("stage", "upload")
    set_tag("upload.filename", source_file)
    set_tag("upload.type", "image")
    try:
        from app.services.ocr_service import clean_ocr_text

        # Read image from disk for OCR processing
        with open(image_path, "rb") as _fh:
            image_content = _fh.read()

        set_tag("stage", "ocr")
        set_tag("ocr.engine", "PaddleOCR")

        logger.info("image OCR started: pipeline_id=%s file=%s", pipeline_id, source_file)
        runtime_diagnostics = _build_ocr_runtime_diagnostics()
        await _set_image_pipeline_status(
            pipeline_id,
            status="ocr_running",
            diagnostics={"ocr_runtime": runtime_diagnostics},
            stages={"upload": {"status": "completed"}, "ocr": {"status": "running"}},
        )
        raw_ocr_text = await _run_ocr_in_thread(image_content)
        raw_text = clean_ocr_text(raw_ocr_text)
        ocr_diagnostics = _build_ocr_text_diagnostics(raw_ocr_text, raw_text)
        if not raw_text:
            await _set_image_pipeline_status(
                pipeline_id,
                status="failed",
                stats={"ocr": ocr_diagnostics},
                diagnostics={
                    "ocr_runtime": runtime_diagnostics,
                    "failure_reason": "ocr_empty_text",
                },
                errors=["ocr_empty_text"],
                stages={
                    "upload": {"status": "completed"},
                    "ocr": {"status": "failed", "error": "ocr_empty_text"},
                },
            )
            raise ValueError("图片 OCR 未识别到可导入文本")
        logger.info(
            "image OCR completed: pipeline_id=%s raw_chars=%d cleaned_chars=%d raw_lines=%d cleaned_lines=%d",
            pipeline_id,
            ocr_diagnostics["raw_text_length"],
            ocr_diagnostics["cleaned_text_length"],
            ocr_diagnostics["raw_line_count"],
            ocr_diagnostics["cleaned_line_count"],
        )
        await _set_image_pipeline_status(
            pipeline_id,
            status="parsing",
            raw_text_preview=raw_text[:500],
            stats={"ocr": ocr_diagnostics},
            diagnostics={
                "ocr_runtime": runtime_diagnostics,
                "ocr_raw_text": raw_ocr_text[:1000],
                "ocr_cleaned_text": raw_text[:1000],
                "failure_reason": None,
            },
            stages={"upload": {"status": "completed"}, "ocr": {"status": "completed"}},
        )

        logger.info("image pipeline started: pipeline_id=%s", pipeline_id)
        async with async_session() as db:
            result = await run_pipeline(
                file_content=raw_text.encode("utf-8"),
                source_type="txt",
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                options=options,
                db=db,
                page_images={1: image_content},
            )
        del image_content

        status = "completed" if result.get("status") == "completed" else "failed"
        failure_reason = _classify_image_pipeline_result(result, raw_text)
        if status == "completed" and not result.get("batch_id"):
            status = "failed"
            failure_reason = failure_reason or "no_review_batch_created"
            result.setdefault("errors", []).append("OCR 文本未生成待审核批次")
        if result.get("batch_id"):
            logger.info(
                "image review created: pipeline_id=%s batch_id=%s count=%s",
                pipeline_id,
                result.get("batch_id"),
                result.get("stats", {}).get("to_review", 0),
            )
        logger.info("image pipeline completed: pipeline_id=%s status=%s", pipeline_id, status)
        result["pipeline_id"] = pipeline_id
        result["status"] = status
        result["raw_text_preview"] = raw_text[:500]
        result["finished_at"] = datetime.now().isoformat()
        result_stats = result.setdefault("stats", {})
        result_stats["ocr"] = ocr_diagnostics
        result["diagnostics"] = {
            **result.get("diagnostics", {}),
            "ocr_runtime": runtime_diagnostics,
            "ocr_raw_text": raw_ocr_text[:1000],
            "ocr_cleaned_text": raw_text[:1000],
            "failure_reason": failure_reason,
        }
        if status == "completed" and result.get("batch_id"):
            result["question_count"] = result.get("stats", {}).get("to_review", 0)
        current = await _get_image_pipeline_status(pipeline_id) or {}
        result.setdefault("started_at", current.get("started_at", datetime.now().isoformat()))
        await _set_image_pipeline_status(pipeline_id, **result)
        log_event(
            logger, "import.background.finish",
            pipeline_id=pipeline_id, source_type="image",
            source_file=source_file, status=status,
        )
    except Exception as exc:
        logger.exception("image pipeline failed: pipeline_id=%s file=%s", pipeline_id, source_file)
        log_event(
            logger, "import.background.error",
            level="error",
            pipeline_id=pipeline_id, source_type="image",
            source_file=source_file,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        capture_exception(exc, tags={"pipeline_id": pipeline_id, "source_file": source_file, "stage": "ocr"})
        await _fail_image_pipeline(pipeline_id, str(exc))
    finally:
        resource_guard.decrement_pipeline_count()
        if image_path and os.path.exists(image_path):
            try:
                os.unlink(image_path)
            except OSError as e:
                logger.warning("Failed to delete image tmp file %s: %s", image_path, e)


async def _run_pipeline_with_db(
    pipeline_id: str,
    file_path: str,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
) -> None:
    """后台任务包装器：创建独立 DB 会话并执行流水线。

    接收已写在磁盘上的临时文件路径，直接使用。完成后清理。
    """
    import traceback

    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
        source_type=source_type,
        source_file=source_file,
    )

    lgr = logging.getLogger("postgraduate-ai")
    log_event(
        lgr, "import.background.start",
        pipeline_id=pipeline_id, source_type=source_type,
        source_file=source_file,
    )

    try:
        source_sha256: str | None = None
        try:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    hasher.update(chunk)
            source_sha256 = hasher.hexdigest()
        except Exception:
            logger.exception(
                "compute source_sha256 failed for pipeline %s; resume identity check will be skipped",
                pipeline_id,
            )

        async with async_session() as db:
            await run_pipeline_background(
                pipeline_id=pipeline_id,
                file_path=file_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                options=options,
                db=db,
                created_by=created_by,
                source_sha256=source_sha256,
            )
        log_event(
            lgr, "import.background.finish",
            pipeline_id=pipeline_id, source_type=source_type,
            source_file=source_file,
        )
    except Exception as exc:
        logger.error(
            "Background task for pipeline %s crashed: %s\n%s",
            pipeline_id, exc, traceback.format_exc(),
        )
        log_event(
            lgr, "import.background.error",
            level="error",
            pipeline_id=pipeline_id, source_type=source_type,
            source_file=source_file,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        capture_exception(exc, tags={"pipeline_id": pipeline_id, "stage": "pipeline_background"})
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": source_type,
            "errors": [f"后台任务崩溃: {exc}"],
            "started_at": "",
            "finished_at": "",
        })
    finally:
        resource_guard.decrement_pipeline_count()
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning("Failed to delete pipeline tmp file %s: %s", file_path, e)


async def start_import_pipeline(
    *,
    file_path: str,
    filename: str,
    content_type: str | None,
    subject: str | None = None,
    subject_id: int | None = None,
    import_mode: str = "auto",
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    page_start: int | None = None,
    page_end: int | None = None,
    created_by: str | None = None,
) -> PipelineUploadResponse:
    """统一导入入口核心逻辑：支持 Excel / PDF / TXT / 图片，异步返回 pipeline_id。

    这是纯业务逻辑函数，不依赖 FastAPI HTTP 对象。
    Router 层需先通过 ``streaming_upload_handler.stream_to_temp()``
    将上传文件写入临时文件，再传入 file_path。
    """
    if not filename:
        raise ValueError("文件名不能为空")

    # System-level resource check
    ok, reason = resource_guard.can_accept_work()
    if not ok:
        from app.core.resource_guard import RESOURCE_PRESSURE, ResourceGuardError
        raise ResourceGuardError(RESOURCE_PRESSURE, reason)

    resource_guard.increment_pipeline_count()

    # Validate file exists and is non-empty
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError("文件内容为空")

    set_tag("stage", "upload")
    set_tag("upload.filename", filename or "unknown")
    set_tag("upload.type", "pipeline")

    lower_name = filename.lower()

    is_pdf = lower_name.endswith(".pdf")
    is_txt = lower_name.endswith(".txt")
    is_excel = lower_name.endswith((".xlsx", ".xls"))
    is_image = lower_name.endswith(_IMAGE_EXTENSIONS)

    if not is_pdf and not is_txt and not is_excel and not is_image:
        raise ValueError(
            "仅支持 .xlsx / .xls / .pdf / .txt / .jpg / .jpeg / .png / .webp 文件"
        )

    validator = get_upload_validator()
    validator.validate_file(filename, file_size, content_type)

    # Non-PDF files must not include page range params
    if (page_start is not None or page_end is not None) and not is_pdf:
        raise ValueError("page_start/page_end 仅适用于 PDF 文件")

    if is_image:
        if content_type and content_type not in _IMAGE_CONTENT_TYPES:
            raise ValueError("图片 Content-Type 不支持")
        if not settings.OCR_ENABLED:
            raise ValueError("图片 OCR 功能未启用")
        # 云端使用外部 OCR API，无需本地 PaddleOCR
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
        profile = detect_deployment_profile()
        if profile != DeploymentProfile.CLOUD_API and importlib.util.find_spec("paddleocr") is None:
            raise ValueError("OCR 依赖未安装：paddleocr")

        image_width, image_height, image_format = _validate_image_path(file_path)
        image_hash = _sha256_of_file(file_path)
        pipeline_id = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_hash[:8]}"

        # Stage the image to persistent storage before enqueuing
        staging_obj = await async_store_file(
            file_path,
            original_name=filename,
            mime=content_type or "image/png",
        )

        options = {
            "enable_ai_repair": enable_ai_repair,
            "confidence_threshold": confidence_threshold,
            "image_hash": image_hash,
        }

        _ctx = get_log_context()
        options["_trace_id"] = _ctx.get("trace_id")
        options["_request_id"] = _ctx.get("request_id")

        await _set_image_pipeline_status(
            pipeline_id,
            status="queued",
            stats={
                "image_bytes": file_size,
                "image_width": image_width,
                "image_height": image_height,
                "image_format": image_format,
                "staging_object_id": staging_obj.object_id,
            },
            stages={"upload": {"status": "completed"}, "ocr": {"status": "pending"}},
        )

        from app.services.task_queue_worker import enqueue_image_pipeline
        await enqueue_image_pipeline(
            pipeline_id=pipeline_id,
            image_path=file_path,
            staging_object_id=staging_obj.object_id,
            source_file=filename,
            subject=subject,
            subject_id=subject_id,
            options=options,
        )

        log_event(
            logger, "import.upload.accepted",
            pipeline_id=pipeline_id, source_type="image",
            source_file=filename, file_size=file_size,
            content_type=content_type or "-",
        )
        return PipelineUploadResponse(pipeline_id=pipeline_id, status="queued", source_type="image")

    if is_excel:
        pipeline_id = f"xl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        staging_obj = await async_store_file(file_path, original_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "parsing",
            "source_type": "excel",
            "source_file": filename,
            "stages": {"upload": {"status": "completed"}},
            "stats": {},
            "errors": [],
            "started_at": datetime.now().isoformat(),
            "staging_object_id": staging_obj.object_id,
        })

        from app.services.task_queue_worker import enqueue_excel_pipeline
        await enqueue_excel_pipeline(
            pipeline_id=pipeline_id,
            file_path=file_path,
            staging_object_id=staging_obj.object_id,
            source_file=filename,
        )

        return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing", source_type="excel")

    source_type = "pdf" if is_pdf else "txt"
    pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    page_range: PdfPageRangeInfo | None = None
    pdf_total_pages = 0

    if is_pdf:
        try:
            import fitz
            with fitz.open(file_path) as doc:
                pdf_total_pages = len(doc)
                validator.validate_pdf_pages(pdf_total_pages)
                page_range = resolve_pdf_page_range(
                    pdf_total_pages,
                    page_start=page_start,
                    page_end=page_end,
                )
        except ValueError:
            raise
        except Exception:
            logger.warning("PDF page count/range validation failed", exc_info=True)

        logger.info(
            "PDF upload accepted: filename=%s total_pages=%s page_start=%s page_end=%s selected=%s",
            filename, pdf_total_pages, page_start, page_end,
            page_range.selected_page_count if page_range else "N/A",
        )

    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
        "import_mode": import_mode,
    }
    if page_range:
        options["page_start"] = page_range.effective_start
        options["page_end"] = page_range.effective_end

    ctx = get_log_context()
    options["_trace_id"] = ctx.get("trace_id")
    options["_request_id"] = ctx.get("request_id")

    # Stage file to persistent storage before enqueuing task
    mime = content_type or ("application/pdf" if is_pdf else "text/plain")
    staging_obj = await async_store_file(file_path, original_name=filename, mime=mime)

    store_data: dict = {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "source_file": filename,
        "current_stage": "extract",
        "stages": {"upload": {"status": "completed"}},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
        "staging_object_id": staging_obj.object_id,
    }
    if page_range:
        store_data["page_range"] = page_range.model_dump()

    await _set_pipeline_store(pipeline_id, store_data)

    from app.services.task_queue_worker import enqueue_import_pipeline
    await enqueue_import_pipeline(
        pipeline_id=pipeline_id,
        file_path=file_path,
        staging_object_id=staging_obj.object_id,
        source_type=source_type,
        source_file=filename,
        subject=subject,
        subject_id=subject_id,
        options=options,
        created_by=created_by,
    )

    log_event(
        logger, "import.upload.accepted",
        pipeline_id=pipeline_id, source_type=source_type,
        source_file=filename, file_size=file_size,
        content_type=content_type or "-",
    )
    return PipelineUploadResponse(
        pipeline_id=pipeline_id, status="parsing",
        source_type=source_type, page_range=page_range,
    )


async def get_pipeline_status(pipeline_id: str, db: AsyncSession) -> PipelineStatusResponse:
    """查询流水线执行状态。"""
    status = await _orchestrator_get_pipeline_status(pipeline_id, db=db)
    if status is None:
        status = await _get_image_pipeline_status(pipeline_id)
    if status is None:
        raise ValueError("流水线不存在")
    return PipelineStatusResponse(**status)


async def run_resume_background(
    pipeline_id: str,
    file_path: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> None:
    """Background wrapper：单独 DB 会话跑 resume，结束后无条件清理 tmp 文件。"""
    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
    )
    try:
        async with async_session() as db:
            await resume_pipeline_background(
                pipeline_id=pipeline_id,
                file_path=file_path,
                subject=subject,
                subject_id=subject_id,
                options=options,
                db=db,
            )
    except Exception:
        logger.exception("resume pipeline %s failed", pipeline_id)
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning("Failed to delete resume tmp file %s: %s", file_path, e)
