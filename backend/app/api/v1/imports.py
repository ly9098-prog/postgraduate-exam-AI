import hashlib
import importlib.util
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import get_db, async_session
from app.core.security import require_app_permission
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
from app.features.pipeline_orchestrator import (
    get_pipeline_status,
    run_excel_pipeline_background,
    run_import_pipeline,
    run_pipeline_background,
)
from app.schemas.import_review import (
    FixQuestionRequest,
    FixQuestionResponse,
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
    _: User = Depends(require_app_permission("import:read")),
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
    """审核单题：通过或拒绝"""
    if data.status == "rejected":
        await svc.reject_question(db, question_id, data.review_note)
        return {"status": "rejected"}

    try:
        result = await svc.approve_question(db, question_id, data.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    qi = result["qi"]
    return {
        "status": "duplicate" if result["is_duplicate"] else "approved",
        "id": qi.id,
        "question_id": result["question_id"],
        "is_duplicate": result["is_duplicate"],
    }


@router.post("/batches/{batch_id}/approve", response_model=dict)
async def approve_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """批量通过一个批次。skipped 题目会列出缺失字段，前端可据此提示用户去逐题审核。"""
    try:
        approved, skipped = await svc.batch_approve(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    skipped_details = [
        {"id": qid, "missing": fields} for qid, fields in skipped.items()
    ]
    return {
        "approved_count": approved,
        "skipped_count": len(skipped),
        "skipped": skipped_details,
    }


@router.post("/batches/{batch_id}/reject", response_model=dict)
async def reject_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """批量拒绝一个批次的所有待审核题目"""
    try:
        count = await svc.batch_reject(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"rejected_count": count}


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
    """人工修复题目字段（仅 pending 状态）"""
    try:
        result = await review_svc.fix_question(
            db, question_id, data.model_dump(exclude_none=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FixQuestionResponse(**result)


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
    try:
        from app.services.ocr_service import clean_ocr_text, ocr_image

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
            )

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
        await _fail_image_pipeline(pipeline_id, str(exc))


@router.post("/pipeline/upload", response_model=PipelineUploadResponse)
async def pipeline_upload(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    _: User = Depends(require_app_permission("import:write")),
):
    """统一导入入口：支持 Excel / PDF / TXT / 图片，异步返回 pipeline_id。

    通过 GET /api/v1/import/pipelines/{pipeline_id} 查询进度。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

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

    # --- Image branch ---
    if is_image:
        if file.content_type and file.content_type not in _IMAGE_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="图片 Content-Type 不支持")
        if not settings.OCR_ENABLED:
            raise HTTPException(status_code=400, detail="图片 OCR 功能未启用")
        if importlib.util.find_spec("paddleocr") is None:
            raise HTTPException(status_code=400, detail="OCR 依赖未安装：paddleocr")
        if len(content) > settings.IMAGE_IMPORT_MAX_BYTES:
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

        background_tasks.add_task(
            _run_image_pipeline_with_db,
            pipeline_id=pipeline_id,
            image_content=content,
            source_file=filename,
            subject=subject,
            options=options,
        )

        return PipelineUploadResponse(pipeline_id=pipeline_id, status="queued", source_type="image")

    # --- Excel branch ---
    if is_excel:
        pipeline_id = f"xl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        background_tasks.add_task(
            run_excel_pipeline_background,
            pipeline_id=pipeline_id,
            file_content=content,
            source_file=filename,
            import_excel_fn=svc.import_excel,
        )

        return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing", source_type="excel")

    # --- PDF / TXT branch ---
    source_type = "pdf" if is_pdf else "txt"
    pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
    }

    background_tasks.add_task(
        _run_pipeline_with_db,
        pipeline_id=pipeline_id,
        file_content=content,
        source_type=source_type,
        source_file=filename,
        subject=subject,
        options=options,
    )

    return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing", source_type=source_type)


async def _run_pipeline_with_db(
    pipeline_id: str,
    file_content: bytes,
    source_type: str,
    source_file: str,
    subject: str | None,
    options: dict,
) -> None:
    """后台任务包装器：创建独立 DB 会话并执行流水线。"""
    async with async_session() as db:
        await run_pipeline_background(
            pipeline_id=pipeline_id,
            file_content=file_content,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            options=options,
            db=db,
        )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineStatusResponse)
async def pipeline_status(
    pipeline_id: str,
    _: User = Depends(require_app_permission("import:read")),
):
    """查询流水线执行状态和各阶段详情。"""
    status = get_pipeline_status(pipeline_id)
    if status is None:
        status = await _get_image_pipeline_status(pipeline_id)
    if status is None:
        raise HTTPException(status_code=404, detail="流水线不存在")
    return PipelineStatusResponse(**status)


# ---------------------------------------------------------------------------
# Stage 10: Publish endpoints
# ---------------------------------------------------------------------------


@router.post("/review/publish", response_model=PublishResponse)
async def publish_questions(
    data: PublishRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """发布审核通过的题目到正式题库。question_ids 和 batch_id 二选一。"""
    try:
        return await publish_svc.publish_questions(
            db, question_ids=data.question_ids, batch_id=data.batch_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    """快捷操作：审核通过并发布，一步完成。"""
    try:
        return await publish_svc.approve_and_publish(db, question_ids=data.question_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
