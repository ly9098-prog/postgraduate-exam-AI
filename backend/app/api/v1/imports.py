import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_app_permission
from app.features import question_pipeline as svc
from app.features.import_mode import ImportMode
from app.models.user import User
from app.schemas.import_review import (
    PipelineResumeResponse,
    PipelineStatusResponse,
    PipelineUploadResponse,
)
from app.schemas.question_import import (
    ImportBatchDetailResponse,
    ImportBatchResponse,
    QuestionImportResponse,
)
from app.services.import_pipeline_service import (
    get_pipeline_status as svc_get_pipeline_status,
)
from app.services.import_pipeline_service import (
    start_import_pipeline as svc_start_import_pipeline,
)
from app.services.streaming_upload_handler import stream_to_temp
from app.services.task_queue_worker import enqueue_resume_pipeline
from app.services.upload_validator import get_upload_validator

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
        import io

        from PIL import Image, UnidentifiedImageError
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
    from app.core.ocr_isolation import local_paddleocr_available

    return {
        "ocr_enabled": settings.OCR_ENABLED,
        "paddleocr_available": local_paddleocr_available(),
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


@router.post("/pipeline/upload", response_model=PipelineUploadResponse)
async def pipeline_upload(
    file: UploadFile,
    subject: str | None = None,
    subject_id: int | None = None,
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
    suffix = os.path.splitext(file.filename or "")[1] or ".bin"
    tmp = await stream_to_temp(file, suffix=suffix)
    try:
        result = await svc_start_import_pipeline(
            file_path=tmp.path,
            filename=file.filename or "",
            content_type=file.content_type,
            subject=subject,
            subject_id=subject_id,
            import_mode=import_mode.value if isinstance(import_mode, ImportMode) else import_mode,
            enable_ai_repair=enable_ai_repair,
            confidence_threshold=confidence_threshold,
            page_start=page_start,
            page_end=page_end,
            created_by=str(current_user.id) if current_user is not None else None,
        )
    except ValueError as exc:
        tmp.close()
        raise HTTPException(status_code=400, detail=str(exc))
    # On success, detach — the background worker takes ownership of the temp file
    tmp.detach()
    return result


@router.get("/pipelines/{pipeline_id}", response_model=PipelineStatusResponse)
async def pipeline_status(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """查询流水线执行状态和各阶段详情。"""
    try:
        return await svc_get_pipeline_status(pipeline_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


_RESUMABLE_PIPELINE_STATUSES = {"paused", "failed"}


def _validate_resume_pdf_sync(
    file_path: str,
    total_pages: int | None,
    validator: Any,
) -> tuple[int, str]:
    """Validate a re-uploaded PDF file in a thread (fitz + hashlib are sync).

    Returns (uploaded_pages, uploaded_sha256_hex).
    """
    import fitz

    with fitz.open(file_path) as doc:
        uploaded_pages = len(doc)
        validator.validate_pdf_pages(uploaded_pages)

    if total_pages is not None and uploaded_pages != total_pages:
        raise ValueError(
            f"PDF 页数不匹配（原始 {total_pages} 页，上传 {uploaded_pages} 页）",
        )

    uploaded_sha256 = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            uploaded_sha256.update(chunk)
    return uploaded_pages, uploaded_sha256.hexdigest()


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
    """手动恢复 paused/failed 的导入流水线。"""
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

    if pipeline_row.created_by is None:
        logger.warning(
            "legacy pipeline without created_by, allowing import:write to resume "
            "(pipeline_id=%s, requester=%s)",
            pipeline_id,
            getattr(current_user, "id", None),
        )
    else:
        requester_id = str(current_user.id) if current_user is not None else None
        if requester_id != pipeline_row.created_by:
            raise HTTPException(status_code=403, detail="not the pipeline creator")

    if pipeline_row.status not in _RESUMABLE_PIPELINE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"流水线当前状态为 {pipeline_row.status}，不可恢复",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="resume 仅支持 PDF 文件")

    suffix = os.path.splitext(file.filename)[1] or ".pdf"
    tmp = await stream_to_temp(file, suffix=suffix)

    try:
        if tmp.size == 0:
            raise ValueError("文件内容为空")

        validator = get_upload_validator()
        validator.validate_file(file.filename, tmp.size, file.content_type)

        # Run fitz + hashlib in a thread to avoid blocking the event loop
        uploaded_pages, uploaded_sha256_hex = await asyncio.to_thread(
            _validate_resume_pdf_sync,
            tmp.path,
            pipeline_row.total_pages,
            validator,
        )
        if pipeline_row.source_sha256 is None:
            logger.warning(
                "legacy pipeline without source_sha256, skipping content identity check "
                "(pipeline_id=%s, uploaded_sha256=%s)", pipeline_id, uploaded_sha256_hex,
            )
        elif uploaded_sha256_hex != pipeline_row.source_sha256:
            raise HTTPException(
                status_code=400,
                detail="上传文件内容与原始导入源不匹配（sha256 不一致）",
            )

        from app.features.pipeline_checkpoint import get_pending_chunks

        pending = await get_pending_chunks(db, pipeline_id)
        resumed_chunks = [c.chunk_index for c in pending]

        if not resumed_chunks:
            tmp.close()
            return PipelineResumeResponse(
                pipeline_id=pipeline_id, status=pipeline_row.status, resumed_chunks=[],
            )

        options = {
            "enable_ai_repair": enable_ai_repair,
            "confidence_threshold": confidence_threshold,
        }

        from app.core.log_context import get_log_context, log_event

        _resume_ctx = get_log_context()
        options["_trace_id"] = _resume_ctx.get("trace_id")
        options["_request_id"] = _resume_ctx.get("request_id")

        log_event(logger, "import.resume.accepted", pipeline_id=pipeline_id, resumed_chunks=resumed_chunks)

        # Stage the file to persistent storage before enqueuing
        from app.services.staging_storage import async_store_file
        _resume_staging = await async_store_file(
            tmp.path,
            original_name=f"resume_{pipeline_id}",
            mime="application/octet-stream",
        )

        result = await enqueue_resume_pipeline(
            pipeline_id=pipeline_id,
            staging_object_id=_resume_staging.object_id,
            subject=subject,
            subject_id=None,
            options=options,
        )
        if not result:
            tmp.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"任务队列已满，请稍后重试: {result.reason}",
            )

        # Detach — the background worker (run_resume_background) takes ownership
        tmp.detach()
        return PipelineResumeResponse(
            pipeline_id=pipeline_id, status="running", resumed_chunks=resumed_chunks,
        )
    except ValueError as exc:
        tmp.close()
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Math preview (app-side read-only utility)
# ---------------------------------------------------------------------------

@router.get("/math-preview/{import_id}")
async def math_preview(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:read")),
):
    """返回单题 segments 预览，供审核查看公式截图。"""
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
