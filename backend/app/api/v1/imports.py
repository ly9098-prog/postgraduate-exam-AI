import asyncio
import hashlib
import importlib.util
import logging
import os
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import get_db, async_session
from app.core.security import get_current_user, require_app_permission
from app.models.user import User
from app.schemas.question_import import (
    ImportBatchDetailResponse,
    ImportBatchResponse,
    ImportQuestionUpdate,
    ImportUploadResponse,
    QuestionImportResponse,
)
from app.schemas.question_publish import (
    ApproveAndPublishRequest,
    ApproveAndPublishResponse,
    PublishHistoryResponse,
    PublishRequest,
    PublishResponse,
)
from app.features import question_pipeline as svc
from app.features import question_publish_service as publish_svc
from app.features import review_service as review_svc
from app.features.import_mode import ImportMode
from app.services.upload_validator import get_upload_validator
from app.features.pipeline_orchestrator import (
    _set_pipeline_store,
    get_pipeline_status,
    resume_pipeline_background,
    run_excel_pipeline_background,
    run_import_pipeline,
    run_pipeline_background,
)
from app.utils.sentry_utils import capture_exception, set_tag
from app.schemas.import_review import (
    FixQuestionRequest,
    FixQuestionResponse,
    PipelineResumeResponse,
    PipelineStatusResponse,
    PipelineUploadResponse,
    ReviewQueueResponse,
    SubmitReviewRequest,
    SubmitReviewResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/import")

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
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
        updates = {key: value for key, value in updates.items() if key != "started_at"}
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


def _validate_image_content(content: bytes) -> tuple[int, int, str]:
    try:
        from PIL import Image, UnidentifiedImageError
        import io
    except ImportError as exc:
        raise HTTPException(status_code=400, detail="图片解析依赖不可用") from exc

    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            image_format = (img.format or "").lower()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="图片内容无法解析") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="图片内容校验失败") from exc

    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="图片尺寸无效")
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
    return {
        "ocr_enabled": settings.OCR_ENABLED,
        "paddleocr_available": importlib.util.find_spec("paddleocr") is not None,
    }


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


@router.get("/template")
async def download_template(
    _: User = Depends(get_current_user),
):
    """下载 Excel 导入模板"""
    content = svc.generate_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=import_template.xlsx"},
    )


@router.post("/upload", response_model=ImportUploadResponse, deprecated=True)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """上传文件（Excel / PDF），解析后进入暂存区。(deprecated: 请使用 /pipeline/upload)"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    is_excel = file.filename.endswith((".xlsx", ".xls"))
    is_pdf = file.filename.endswith(".pdf")

    if not is_excel and not is_pdf:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls / .pdf 文件")

    content = await file.read()
    try:
        if is_pdf:
            batch_id, total = await svc.import_pdf(db, content, file.filename, background_tasks)
            source_type = "pdf"
        else:
            batch_id, total = await svc.import_excel(db, content, file.filename)
            source_type = "excel"
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # PyMuPDF 损坏、编码异常、正则边界等都落到这里。
        # 必须返回 JSON，否则前端 JSON.parse 会直接炸（错误信息全丢）
        logger.exception("文件解析失败: %s", file.filename)
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败：{type(e).__name__}: {e}",
        )

    return ImportUploadResponse(
        batch_id=batch_id,
        total=total,
        source_type=source_type,
        source_file=file.filename,
    )


@router.get("/batches")
async def list_batches(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """导入批次列表"""
    batches = await svc.list_batches(db)
    return {"items": [ImportBatchResponse(**b) for b in batches]}


@router.get("/batches/{batch_id}", response_model=ImportBatchDetailResponse)
async def batch_detail(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """批次详情：该批次所有题目"""
    questions = await svc.get_batch_detail(db, batch_id)
    if not questions:
        raise HTTPException(status_code=404, detail="批次不存在")

    first = questions[0]
    return ImportBatchDetailResponse(
        batch_id=batch_id,
        source_type=first.source_type,
        source_file=first.source_file,
        questions=[QuestionImportResponse.model_validate(q) for q in questions],
    )


@router.put("/questions/{question_id}", response_model=dict)
async def review_question(
    question_id: int,
    data: ImportQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放导入审核能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台审核导入题目")


@router.post("/batches/{batch_id}/approve", response_model=dict)
async def approve_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放批量通过能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台审核导入题目")


@router.post("/batches/{batch_id}/reject", response_model=dict)
async def reject_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放批量拒绝能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台审核导入题目")


@router.post("/submit-review", response_model=SubmitReviewResponse)
async def submit_review(
    data: SubmitReviewRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """提交 Stage 5/6 标准化题目到审核队列"""
    questions = [q.model_dump() for q in data.questions]
    batch_meta = data.batch_meta.model_dump()
    result = await review_svc.submit_to_review(db, questions, batch_meta)
    return SubmitReviewResponse(**result)


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def review_queue(
    status: str | None = None,
    min_confidence: float | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """获取审核队列（低置信度优先）"""
    result = await review_svc.get_review_queue(
        db, status=status, min_confidence=min_confidence,
        page=page, page_size=page_size,
    )
    return ReviewQueueResponse(**result)


@router.put("/questions/{question_id}/fix", response_model=FixQuestionResponse)
async def fix_question(
    question_id: int,
    data: FixQuestionRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放题目修复能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台编辑导入题目")


# ---------------------------------------------------------------------------
# Stage 8: Pipeline Integration
# ---------------------------------------------------------------------------


@router.post("/image/upload", response_model=PipelineUploadResponse, deprecated=True)
async def image_upload(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    _: User = Depends(require_app_permission("import:write")),
):
    """图片导入：单图 OCR 后以 TXT 流水线进入现有审核队列。(deprecated: 请使用 /pipeline/upload)"""
    if not file.filename:
        logger.info("image upload validation failed: empty filename")
        raise HTTPException(status_code=400, detail="文件名不能为空")

    filename = file.filename
    lower_name = filename.lower()
    if not lower_name.endswith(_IMAGE_EXTENSIONS):
        logger.info("image upload validation failed: unsupported extension %s", filename)
        raise HTTPException(status_code=400, detail="仅支持 .jpg / .jpeg / .png / .webp 图片")

    if file.content_type and file.content_type not in _IMAGE_CONTENT_TYPES:
        logger.info(
            "image upload validation failed: unsupported content-type %s for %s",
            file.content_type,
            filename,
        )
        raise HTTPException(status_code=400, detail="图片 Content-Type 不支持")

    if not settings.OCR_ENABLED:
        logger.info(
            "image upload validation failed: OCR disabled filename=%s app_env=%s ocr_enabled=%s",
            filename,
            settings.APP_ENV,
            settings.OCR_ENABLED,
        )
        raise HTTPException(status_code=400, detail="图片 OCR 功能未启用")

    if importlib.util.find_spec("paddleocr") is None:
        logger.info("image upload validation failed: PaddleOCR dependency unavailable filename=%s", filename)
        raise HTTPException(status_code=400, detail="OCR 依赖未安装：paddleocr")

    content = await file.read()
    if not content:
        logger.info("image upload validation failed: empty content %s", filename)
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(content) > settings.IMAGE_IMPORT_MAX_BYTES:
        logger.info(
            "image upload validation failed: file too large %s bytes=%d",
            filename,
            len(content),
        )
        raise HTTPException(status_code=400, detail="图片过大，请压缩后重试")

    image_width, image_height, image_format = _validate_image_content(content)
    image_hash = hashlib.sha256(content).hexdigest()
    pipeline_id = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_hash[:8]}"
    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
        "image_hash": image_hash,
    }

    await _set_image_pipeline_status(
        pipeline_id,
        status="queued",
        stats={
            "image_bytes": len(content),
            "image_width": image_width,
            "image_height": image_height,
            "image_format": image_format,
        },
        stages={"upload": {"status": "completed"}, "ocr": {"status": "pending"}},
    )
    logger.info(
        "image upload received: pipeline_id=%s file=%s content_type=%s bytes=%d",
        pipeline_id,
        filename,
        file.content_type,
        len(content),
    )

    background_tasks.add_task(
        _run_image_pipeline_with_db,
        pipeline_id=pipeline_id,
        image_content=content,
        source_file=filename,
        subject=subject,
        options=options,
    )

    return PipelineUploadResponse(pipeline_id=pipeline_id, status="queued")


async def _run_image_pipeline_with_db(
    pipeline_id: str,
    image_content: bytes,
    source_file: str,
    subject: str | None,
    options: dict,
) -> None:
    """图片后台任务：OCR → TXT bytes → 现有导入流水线。"""
    set_tag("stage", "upload")
    set_tag("upload.filename", source_file)
    set_tag("upload.type", "image")
    try:
        from app.services.ocr_service import clean_ocr_text, ocr_image

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
        raw_ocr_text = ocr_image(image_content)
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
            result = await run_import_pipeline(
                file_content=raw_text.encode("utf-8"),
                source_type="txt",
                source_file=source_file,
                subject=subject,
                options=options,
                db=db,
                page_images={1: image_content},
            )
        # P0-1: image bytes have been consumed by pipeline (page_images dict
        # is popped after ocr_correction stage); release the local reference
        # so GC can reclaim memory before we continue with status/response.
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
    except Exception as exc:
        logger.exception("image pipeline failed: pipeline_id=%s file=%s", pipeline_id, source_file)
        capture_exception(exc, tags={"pipeline_id": pipeline_id, "source_file": source_file, "stage": "ocr"})
        await _fail_image_pipeline(pipeline_id, str(exc))


async def start_import_pipeline_from_upload(
    *,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    import_mode: ImportMode = ImportMode.AUTO,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    page_start: int | None = None,
    page_end: int | None = None,
    created_by: str | None = None,
) -> PipelineUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # Sentry upload stage tag
    set_tag("stage", "upload")
    set_tag("upload.filename", file.filename or "unknown")
    set_tag("upload.type", "pipeline")

    filename = file.filename
    lower_name = filename.lower()

    is_pdf = lower_name.endswith(".pdf")
    is_txt = lower_name.endswith(".txt")
    is_excel = lower_name.endswith((".xlsx", ".xls"))
    is_image = lower_name.endswith(_IMAGE_EXTENSIONS)

    if not is_pdf and not is_txt and not is_excel and not is_image:
        raise HTTPException(
            status_code=400,
            detail="仅支持 .xlsx / .xls / .pdf / .txt / .jpg / .jpeg / .png / .webp 文件",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    validator = get_upload_validator()
    validator.validate_file(filename, len(content), file.content_type)

    if page_start is not None and page_start < 1:
        raise HTTPException(status_code=400, detail="page_start 必须 >= 1")
    if page_end is not None and page_end < 1:
        raise HTTPException(status_code=400, detail="page_end 必须 >= 1")
    if page_end is not None and page_start is not None and page_end < page_start:
        raise HTTPException(status_code=400, detail="page_end 必须 >= page_start")

    if is_image:
        if file.content_type and file.content_type not in _IMAGE_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="图片 Content-Type 不支持")
        if not settings.OCR_ENABLED:
            raise HTTPException(status_code=400, detail="图片 OCR 功能未启用")
        if importlib.util.find_spec("paddleocr") is None:
            raise HTTPException(status_code=400, detail="OCR 依赖未安装：paddleocr")

        image_width, image_height, image_format = _validate_image_content(content)
        image_hash = hashlib.sha256(content).hexdigest()
        pipeline_id = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_hash[:8]}"
        options = {
            "enable_ai_repair": enable_ai_repair,
            "confidence_threshold": confidence_threshold,
            "image_hash": image_hash,
        }

        await _set_image_pipeline_status(
            pipeline_id,
            status="queued",
            stats={
                "image_bytes": len(content),
                "image_width": image_width,
                "image_height": image_height,
                "image_format": image_format,
            },
            stages={"upload": {"status": "completed"}, "ocr": {"status": "pending"}},
        )

        background_tasks.add_task(
            _run_image_pipeline_with_db,
            pipeline_id=pipeline_id,
            image_content=content,
            source_file=filename,
            subject=subject,
            options=options,
        )

        return PipelineUploadResponse(pipeline_id=pipeline_id, status="queued", source_type="image")

    if is_excel:
        pipeline_id = f"xl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "parsing",
            "source_type": "excel",
            "source_file": filename,
            "stages": {"upload": {"status": "completed"}},
            "stats": {},
            "errors": [],
            "started_at": datetime.now().isoformat(),
        })

        background_tasks.add_task(
            run_excel_pipeline_background,
            pipeline_id=pipeline_id,
            file_content=content,
            source_file=filename,
            import_excel_fn=svc.import_excel,
        )

        return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing", source_type="excel")

    source_type = "pdf" if is_pdf else "txt"
    pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    if is_pdf:
        try:
            import fitz
            with fitz.open(stream=content, filetype="pdf") as doc:
                validator.validate_pdf_pages(len(doc))
        except HTTPException:
            raise
        except Exception:
            pass

    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
        "import_mode": import_mode.value,
        "page_start": page_start,
        "page_end": page_end,
    }

    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "source_file": filename,
        "current_stage": "extract",
        "stages": {"upload": {"status": "completed"}},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    })

    asyncio.create_task(
        _run_pipeline_with_db(
            pipeline_id=pipeline_id,
            file_content=content,
            source_type=source_type,
            source_file=filename,
            subject=subject,
            options=options,
            created_by=created_by,
        )
    )

    return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing", source_type=source_type)


@router.post("/pipeline/upload", response_model=PipelineUploadResponse)
async def pipeline_upload(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    import_mode: ImportMode = ImportMode.AUTO,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    page_start: int | None = None,
    page_end: int | None = None,
    current_user: User = Depends(require_app_permission("import:write")),
):
    """统一导入入口：支持 Excel / PDF / TXT / 图片，异步返回 pipeline_id。

    import_mode: "auto" | "book" | "exam"
    通过 GET /api/v1/import/pipelines/{pipeline_id} 查询进度。
    """
    return await start_import_pipeline_from_upload(
        file=file,
        background_tasks=background_tasks,
        subject=subject,
        import_mode=import_mode,
        enable_ai_repair=enable_ai_repair,
        confidence_threshold=confidence_threshold,
        page_start=page_start,
        page_end=page_end,
        created_by=str(current_user.id) if current_user is not None else None,
    )


async def get_import_pipeline_status(pipeline_id: str, db: AsyncSession) -> PipelineStatusResponse:
    status = await get_pipeline_status(pipeline_id, db=db)
    if status is None:
        status = await _get_image_pipeline_status(pipeline_id)
    if status is None:
        raise HTTPException(status_code=404, detail="流水线不存在")
    return PipelineStatusResponse(**status)


async def _run_pipeline_with_db(
    pipeline_id: str,
    file_content: bytes,
    source_type: str,
    source_file: str,
    subject: str | None,
    options: dict,
    created_by: str | None = None,
) -> None:
    """后台任务包装器：创建独立 DB 会话并执行流水线。

    P0-1: 入口处把 file_content bytes 落盘到 tmp 文件，后台任务结束后删除；
    本函数局部变量持有 bytes 仅用于一次性写入文件，写完立即解除引用，
    避免大文件 (100~400 MB) 随整个 pipeline (~分钟级) 驻留内存。

    P0-1/P0-2 (security): ``created_by`` 用于记录创建者，``source_sha256``
    用文件落盘后流式计算（避免 bytes 重新加载进堆内存），一并落到
    ``import_pipelines`` 表，让 resume endpoint 能做创建者 + 文件身份校验。
    """
    import traceback
    logger = logging.getLogger("postgraduate-ai")
    logger.info("Background task started for pipeline %s", pipeline_id)

    tmp_path: str | None = None
    try:
        # 落盘到 tmp 文件
        suffix = os.path.splitext(source_file or "")[1] or ".bin"
        fd, tmp_path = tempfile.mkstemp(prefix=f"pipeline_{pipeline_id}_", suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(file_content)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise
        # 立即解除对 bytes 的引用，让 GC 回收
        del file_content

        # P0-2: 流式从 tmp 文件计算 sha256（仅 PDF chunked 路径会落到
        # import_pipelines 表，但 hash 计算成本低，在此统一算一次最简单；
        # 单 pass 路径不创建 pipeline 行，下游不会用到这个值）。
        source_sha256: str | None = None
        try:
            hasher = hashlib.sha256()
            with open(tmp_path, "rb") as fh:
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
                file_path=tmp_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                options=options,
                db=db,
                created_by=created_by,
                source_sha256=source_sha256,
            )
    except Exception as exc:
        logger.error(
            "Background task for pipeline %s crashed: %s\n%s",
            pipeline_id, exc, traceback.format_exc(),
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
        # 无论成功失败都删除 tmp 文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as e:
                logger.warning(
                    "Failed to delete pipeline tmp file %s: %s", tmp_path, e
                )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineStatusResponse)
async def pipeline_status(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """查询流水线执行状态和各阶段详情。

    P2-6: PDF 分块导入会带上 ``chunk_progress`` 字段（completed/failed/
    pending 计数 + failed_chunk_details）。图片 / Excel / 单 pass 路径
    不返回该字段，前端兼容缺失即可退化为旧逻辑。
    """
    return await get_import_pipeline_status(pipeline_id, db)


_RESUMABLE_PIPELINE_STATUSES = {"paused", "failed"}


async def _run_resume_with_db(
    pipeline_id: str,
    file_path: str,
    subject: str | None,
    options: dict,
) -> None:
    """Background wrapper：单独 DB 会话跑 resume，结束后无条件清理 tmp 文件。"""
    try:
        async with async_session() as db:
            await resume_pipeline_background(
                pipeline_id=pipeline_id,
                file_path=file_path,
                subject=subject,
                options=options,
                db=db,
            )
    except Exception:
        logger.exception("resume pipeline %s failed", pipeline_id)
        capture_exception(
            RuntimeError(f"resume pipeline {pipeline_id} failed"),
            tags={"pipeline_id": pipeline_id, "stage": "resume"},
        )
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning(
                    "Failed to delete resume tmp file %s: %s", file_path, e
                )


@router.post(
    "/pipelines/{pipeline_id}/resume",
    response_model=PipelineResumeResponse,
)
async def resume_pipeline(
    pipeline_id: str,
    file: UploadFile,
    subject: str | None = None,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_app_permission("import:write")),
):
    """P2-5: 手动恢复 paused/failed 的导入流水线。

    PDF 在首次导入结束后已被 unlink，因此 resume 必须重新上传同一个文件
    （v1 简化方案：服务器不持久化原始 PDF）。仅复跑 failed + pending
    chunk，已 completed 的 chunk 不动。

    P0-1 安全校验：仅 pipeline 创建者可 resume。历史记录（created_by IS NULL）
    保持向后兼容，import:write 持有者均可 resume，但会写一条 warning 日志。
    P0-2 安全校验：上传 PDF 字节 sha256 必须等于首次导入时记录的 source_sha256，
    否则返回 400，避免不同内容、相同页数的 PDF 替换原始上下文。
    """
    from sqlalchemy import select as sa_select

    from app.models.import_pipeline import ImportPipeline

    pipeline_row = (
        await db.execute(
            sa_select(ImportPipeline).where(
                ImportPipeline.pipeline_id == pipeline_id
            )
        )
    ).scalar_one_or_none()
    if pipeline_row is None:
        raise HTTPException(status_code=404, detail="流水线不存在")

    set_tag("stage", "upload")
    set_tag("upload.filename", file.filename or "unknown")
    set_tag("upload.type", "resume")

    # P0-1: 创建者鉴权。NULL 表示历史 pipeline，按旧行为放行（带 warning）。
    if pipeline_row.created_by is None:
        logger.warning(
            "legacy pipeline without created_by, allowing import:write to resume "
            "(pipeline_id=%s, requester=%s)",
            pipeline_id,
            getattr(current_user, "id", None),
        )
    else:
        requester_id = (
            str(current_user.id) if current_user is not None else None
        )
        if requester_id != pipeline_row.created_by:
            raise HTTPException(
                status_code=403, detail="not the pipeline creator"
            )

    if pipeline_row.status not in _RESUMABLE_PIPELINE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"流水线当前状态为 {pipeline_row.status}，不可恢复",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="resume 仅支持 PDF 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    validator = get_upload_validator()
    validator.validate_file(file.filename, len(content), file.content_type)

    try:
        import fitz
        with fitz.open(stream=content, filetype="pdf") as doc:
            uploaded_pages = len(doc)
            validator.validate_pdf_pages(uploaded_pages)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败：{exc}")

    if (
        pipeline_row.total_pages is not None
        and uploaded_pages != pipeline_row.total_pages
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"PDF 页数不匹配（原始 {pipeline_row.total_pages} 页，"
                f"上传 {uploaded_pages} 页），请确认是同一份文件"
            ),
        )

    # P0-2: 字节级身份校验。复用已读到内存的 content（resume 上限 ≤ 200MB，
    # 与全局 PDF 上传校验一致），避免再读一遍 file。
    uploaded_sha256 = hashlib.sha256(content).hexdigest()
    if pipeline_row.source_sha256 is None:
        logger.warning(
            "legacy pipeline without source_sha256, skipping content identity check "
            "(pipeline_id=%s, uploaded_sha256=%s)",
            pipeline_id,
            uploaded_sha256,
        )
    elif uploaded_sha256 != pipeline_row.source_sha256:
        raise HTTPException(
            status_code=400,
            detail="uploaded file content does not match original pipeline source",
        )

    # Snapshot pending chunks for the response. The background task may also
    # mark new chunks failed, but resumed_chunks reflects the entry-time view.
    from app.features.pipeline_checkpoint import get_pending_chunks

    pending = await get_pending_chunks(db, pipeline_id)
    resumed_chunks = [c.chunk_index for c in pending]

    if not resumed_chunks:
        return PipelineResumeResponse(
            pipeline_id=pipeline_id,
            status=pipeline_row.status,
            resumed_chunks=[],
        )

    # Persist re-uploaded PDF to a tmp path; background task unlinks in finally.
    suffix = os.path.splitext(file.filename)[1] or ".pdf"
    fd, tmp_path = tempfile.mkstemp(prefix=f"resume_{pipeline_id}_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    # P0-1: release PDF bytes after writing to tempfile
    del content

    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
    }

    asyncio.create_task(
        _run_resume_with_db(
            pipeline_id=pipeline_id,
            file_path=tmp_path,
            subject=subject,
            options=options,
        )
    )

    return PipelineResumeResponse(
        pipeline_id=pipeline_id,
        status="running",
        resumed_chunks=resumed_chunks,
    )


# ---------------------------------------------------------------------------
# Stage 10: Publish endpoints
# ---------------------------------------------------------------------------


@router.post("/review/publish", response_model=PublishResponse)
async def publish_questions(
    data: PublishRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放发布能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台发布导入题目")


@router.get("/review/publish-history", response_model=PublishHistoryResponse)
async def publish_history(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """查询发布历史（按 batch_id 聚合）。"""
    return await publish_svc.get_publish_history(
        db, page=page, page_size=page_size, status=status
    )


@router.post("/review/approve-and-publish", response_model=ApproveAndPublishResponse)
async def approve_and_publish(
    data: ApproveAndPublishRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """小程序端不再开放快捷审核发布能力。"""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请在 Admin 后台审核并发布导入题目")


# ---------------------------------------------------------------------------
# Stage 3: Math preview
# ---------------------------------------------------------------------------

@router.get("/math-preview/{import_id}")
async def math_preview(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """返回单题 segments 预览，供审核查看公式截图。"""
    from sqlalchemy import select as sa_select
    from app.models.question_import import QuestionImport

    result = await db.execute(
        sa_select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi = result.scalar_one_or_none()
    if qi is None:
        raise HTTPException(status_code=404, detail="导入记录不存在")

    content = qi.parsed_content or {}
    segments = content.get("segments", [])
    formula_count = sum(1 for s in segments if s.get("type") == "math_image")

    return {
        "import_id": import_id,
        "has_math": formula_count > 0,
        "formula_count": formula_count,
        "segments": segments,
        "original_text": content.get("text", ""),
    }
