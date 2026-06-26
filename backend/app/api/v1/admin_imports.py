import asyncio
import importlib.util
import logging
import os
import tempfile

import json

from fastapi import BackgroundTasks, APIRouter, Depends, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import paginated_response
from app.services.admin_import_service import (
    approve_import_batch,
    approve_low_risk_questions,
    approve_import_question,
    batch_complete_import_questions,
    complete_import_question,
    create_enrich_task,
    delete_import_batch,
    delete_import_question,
    get_enrich_status,
    get_import_batch_detail,
    list_import_batches,
    list_review_queue,
    reject_import_batch,
    reject_import_question,
    update_import_question,
)
from app.schemas.admin_imports import (
    AdminImportActionResponse,
    AdminImportBatchCompleteRequest,
    AdminImportBatchCompleteResponse,
    AdminImportBatchDetail,
    AdminImportBatchListItem,
    AdminImportCompleteResponse,
    AdminImportDeleteResponse,
    AdminImportEnrichResponse,
    AdminImportQuestionUpdateRequest,
    AdminImportRejectRequest,
    AdminImportTaskStatusResponse,
    BatchImageJobStatusResponse,
    BatchImageReparseResponse,
    BatchImageUploadResponse,
    TextImportRequest,
    TextImportResponse,
    TextImportResultItem,
    TextParseRequest,
    TextParseResponse,
)
from app.schemas.import_review import PipelineStatusResponse, PipelineUploadResponse
from app.schemas.question_publish import PublishResponse
from app.features.import_mode import ImportMode
from app.api.v1.imports import get_import_pipeline_status, start_import_pipeline_from_upload
from app.features.pipeline_orchestrator import (
    _get_stage_checkpoint,
    _set_pipeline_store,
    run_pipeline_background,
)
from app.features import question_publish_service as publish_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/v1/imports", tags=["admin-imports"])


def _raise_import_error(exc: ValueError) -> None:
    if str(exc) in {"导入批次不存在", "导入题目不存在", "AI任务不存在"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post("/upload", response_model=PipelineUploadResponse)
async def upload_import_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    import_mode: ImportMode = ImportMode.AUTO,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    page_start: int | None = None,
    page_end: int | None = None,
    current_admin=Depends(require_permissions("import:write")),
):
    return await start_import_pipeline_from_upload(
        file=file,
        background_tasks=background_tasks,
        subject=subject,
        import_mode=import_mode,
        enable_ai_repair=enable_ai_repair,
        confidence_threshold=confidence_threshold,
        page_start=page_start,
        page_end=page_end,
        created_by=f"admin:{current_admin.id}",
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineStatusResponse)
async def get_admin_pipeline_status(
    pipeline_id: str,
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_import_pipeline_status(pipeline_id, db)


_RESUMABLE_STATUSES = {"failed", "paused", "interrupted"}


@router.post("/pipelines/{pipeline_id}/resume")
async def admin_resume_pipeline(
    pipeline_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    enable_ai_repair: bool | None = None,
    enable_ocr_correction: bool | None = None,
    confidence_threshold: float | None = None,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """P3-3: 恢复失败的导入流水线。

    检查 checkpoint 后重新提交后台任务。仅允许 failed / interrupted 状态。
    需要重新上传原始文件。可通过可选参数覆盖原始流水线配置。

    P4-3: 自动检测 artifact 实现真断点恢复（从可恢复 stage 继续而非全部重跑）。
    """
    from datetime import datetime
    import tempfile

    from app.features.pipeline_orchestrator import _pipeline_store

    # 检查当前状态 — use pipeline_store directly for non-DB pipelines
    from app.features.pipeline_orchestrator import _get_pipeline_store as _get_ps
    status_data = await _get_ps(pipeline_id)
    if status_data is None:
        # check image pipeline store
        from app.api.v1.imports import _get_image_pipeline_status
        status_data = await _get_image_pipeline_status(pipeline_id)

    if status_data is None:
        raise HTTPException(status_code=404, detail="流水线不存在")

    current_status = status_data.get("status", "")
    if current_status not in _RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"流水线当前状态为 {current_status}，不可恢复（仅允许 {_RESUMABLE_STATUSES}）",
        )

    # 读取 checkpoint
    ckpt = await _get_stage_checkpoint(pipeline_id)
    if not ckpt:
        logger.warning("No stage checkpoint found for pipeline %s; will run full pipeline", pipeline_id)
    else:
        logger.info(
            "Pipeline %s resume with checkpoint: %d stages completed, failed_stage=%s",
            pipeline_id, len(ckpt.get("completed_stages") or []), ckpt.get("failed_stage"),
        )

    # P4-3: 检查 artifact 状态，记录哪些 stage 可通过 artifact 恢复
    artifact_stages: list[str] = []
    try:
        from app.features.pipeline_artifacts import list_artifacts
        artifact_stages = list_artifacts(pipeline_id)
        if artifact_stages:
            logger.info(
                "Pipeline %s has artifacts for stages: %s — will use true resume",
                pipeline_id, artifact_stages,
            )
    except Exception:
        pass

    # 保存上传文件
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    suffix = os.path.splitext(file.filename or "")[1] or ".bin"
    fd, tmp_path = tempfile.mkstemp(prefix=f"resume_admin_{pipeline_id}_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    del content

    # 从 checkpoint 恢复选项，允许调用方覆盖
    opts = dict(ckpt.get("options") or {}) if ckpt else {}
    if enable_ai_repair is not None:
        opts["enable_ai_repair"] = enable_ai_repair
    if enable_ocr_correction is not None:
        opts["enable_ocr_correction"] = enable_ocr_correction
    if confidence_threshold is not None:
        opts["confidence_threshold"] = confidence_threshold
    subject = ckpt.get("subject") if ckpt else None
    source_type = ckpt.get("source_type") or "pdf"
    source_file = ckpt.get("source_file") or file.filename or ""

    # 设置 pipeline store 为 processing
    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "current_stage": "extract",
        "stages": {},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    })

    # 后台任务
    async def _run_resume():
        try:
            from app.core.database import async_session
            from app.features.pipeline_orchestrator import (
                _pipeline_store as _ps,
                run_import_pipeline,
            )

            async def _progress(stages_dict, current_stage, errors):
                await _set_pipeline_store(pipeline_id, {
                    "pipeline_id": pipeline_id,
                    "status": "processing",
                    "source_type": source_type,
                    "current_stage": current_stage,
                    "stages": stages_dict,
                    "stats": {},
                    "errors": errors,
                    "started_at": _ps.get(pipeline_id, {}).get("started_at", ""),
                })

            async with async_session() as resume_db:
                result = await run_import_pipeline(
                    file_path=tmp_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    options=opts,
                    db=resume_db,
                    progress_callback=_progress,
                    pipeline_id=pipeline_id,
                    # P3-3: 传入 checkpoint 让 pipeline 跳过已完成 stage
                    resume_from_checkpoint=ckpt,
                )
                await _set_pipeline_store(pipeline_id, result)
        except Exception as exc:
            logger.exception("Admin resume pipeline %s failed", pipeline_id)
            await _set_pipeline_store(pipeline_id, {
                "pipeline_id": pipeline_id,
                "status": "failed",
                "source_type": source_type,
                "errors": [f"恢复导入失败: {exc}"],
                "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
                "finished_at": datetime.now().isoformat(),
            })
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    asyncio.create_task(_run_resume())

    failed_stage = (ckpt or {}).get("failed_stage")
    completed_stages = (ckpt or {}).get("completed_stages", [])
    return {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "resumed_chunks": [],
        "failed_stage": failed_stage,
        "completed_stages": len(completed_stages),
        # P4-3: artifact-based resume diagnostics
        "artifact_stages": artifact_stages,
        "true_resume": bool(artifact_stages),
    }


@router.get("/review-queue")
async def get_import_review_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = "pending",
    batch_id: str | None = None,
    subject: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    risk_level: str | None = Query(None, pattern="^(high|medium|low)$"),
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_review_queue(
        db, page, page_size, status, batch_id, subject, source_type, keyword,
        risk_level=risk_level,
    )
    return paginated_response(items, total, page, page_size)


@router.put("/questions/{import_id}")
async def update_import_question_item(
    import_id: int,
    data: AdminImportQuestionUpdateRequest,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await update_import_question(db, import_id, data)
        await db.commit()
        return item
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/questions/{import_id}/complete", response_model=AdminImportCompleteResponse)
async def complete_import_question_item(
    import_id: int,
    request: Request,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await complete_import_question(db, import_id, current_admin, request)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/questions/batch-complete", response_model=AdminImportBatchCompleteResponse)
async def batch_complete_import_questions_item(
    data: AdminImportBatchCompleteRequest,
    request: Request,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await batch_complete_import_questions(
            db, data.import_ids, data.fields, data.strategy, current_admin, request,
        )
        return result
    except ValueError as exc:
        _raise_import_error(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/questions/{import_id}/approve", response_model=AdminImportActionResponse)
async def approve_import_question_item(
    import_id: int,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await approve_import_question(db, import_id, current_admin.id)
        await db.commit()
        return AdminImportActionResponse(id=item.id, status=item.status, affected_count=1)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/questions/{import_id}/reject", response_model=AdminImportActionResponse)
async def reject_import_question_item(
    import_id: int,
    data: AdminImportRejectRequest | None = None,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await reject_import_question(db, import_id, current_admin.id, data.reason if data else None)
        await db.commit()
        return AdminImportActionResponse(id=item.id, status=item.status, affected_count=1)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/{batch_id}/approve", response_model=AdminImportActionResponse)
async def approve_import_batch_items(
    batch_id: str,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        count = await approve_import_batch(db, batch_id, current_admin.id)
        await db.commit()
        return AdminImportActionResponse(batch_id=batch_id, status="approved", affected_count=count)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/{batch_id}/approve-low-risk")
async def approve_low_risk_batch_items(
    batch_id: str,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await approve_low_risk_questions(db, batch_id, current_admin.id)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/{batch_id}/reject", response_model=AdminImportActionResponse)
async def reject_import_batch_items(
    batch_id: str,
    data: AdminImportRejectRequest | None = None,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        count = await reject_import_batch(db, batch_id, current_admin.id, data.reason if data else None)
        await db.commit()
        return AdminImportActionResponse(batch_id=batch_id, status="rejected", affected_count=count)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.post("/{batch_id}/publish", response_model=PublishResponse)
async def publish_import_batch_items(
    batch_id: str,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await publish_svc.publish_questions(db, batch_id=batch_id)
    except ValueError as exc:
        _raise_import_error(exc)


@router.delete("/questions/{import_id}", response_model=AdminImportDeleteResponse)
async def delete_import_question_item(
    import_id: int,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        count = await delete_import_question(db, import_id)
        await db.commit()
        return AdminImportDeleteResponse(id=import_id, deleted_count=count)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.delete("/{batch_id}", response_model=AdminImportDeleteResponse)
async def delete_import_batch_items(
    batch_id: str,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        count = await delete_import_batch(db, batch_id)
        await db.commit()
        return AdminImportDeleteResponse(batch_id=batch_id, deleted_count=count)
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)


@router.get("")
async def list_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    batches, total = await list_import_batches(db, page, page_size, status, source_type, keyword)
    return paginated_response([AdminImportBatchListItem.model_validate(item) for item in batches], total, page, page_size)


@router.get("/{batch_id}", response_model=AdminImportBatchDetail)
async def get_import_detail(
    batch_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_import_batch_detail(db, batch_id, page, page_size, status)
    except ValueError as exc:
        _raise_import_error(exc)


@router.post("/{batch_id}/enrich", response_model=AdminImportEnrichResponse)
async def create_import_enrich_task(
    batch_id: str,
    request: Request,
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await create_enrich_task(db, batch_id, current_admin, request)
        await db.commit()
        return task
    except ValueError as exc:
        await db.rollback()
        _raise_import_error(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/text-parse", response_model=TextParseResponse)
async def parse_text_questions(
    data: TextParseRequest,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """解析用户粘贴的文本，返回结构化题目预览。"""
    from app.features.text_question_parser import parse_text_questions_async

    result = await parse_text_questions_async(data.text, data.subject, db=db)
    return TextParseResponse(**result)


@router.post("/text-import", response_model=TextImportResponse)
async def import_text_questions(
    data: TextImportRequest,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """将解析后的文本题目写入 question_imports 暂存区。"""
    import uuid
    from datetime import datetime
    from app.features.question_pipeline import process_question_pipeline, _create_question_import

    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    items: list[TextImportResultItem] = []
    succeeded = 0
    failed = 0
    duplicates_filtered = 0

    for i, q in enumerate(data.questions):
        try:
            q_input = {
                "subject": q.subject or data.subject,
                "stem": q.stem,
                "options": q.options,
                "answer": q.answer or "",
                "analysis": q.analysis or "",
                "question_type": q.question_type or "",
                "knowledge_points": q.knowledge_points,
                "difficulty": q.difficulty,
            }

            result = process_question_pipeline(
                q_input,
                source_type="text",
                source={"file": "text_import", "page": 0},
            )

            if not result["is_valid"]:
                items.append(TextImportResultItem(
                    block_index=i,
                    status="fail",
                    error=f"校验失败: {', '.join(result['errors'])}",
                ))
                failed += 1
                continue

            async with db.begin_nested():
                qi = await _create_question_import(
                    db,
                    batch_id=batch_id,
                    source_type="text",
                    source_file="text_import",
                    raw_data=q.model_dump(),
                    result=result,
                    skip_existing=True,
                )
            if qi is None:
                items.append(TextImportResultItem(
                    block_index=i,
                    status="duplicate",
                    error="题库中已存在相同题目",
                ))
                duplicates_filtered += 1
                continue
            items.append(TextImportResultItem(
                block_index=i,
                import_id=qi.id,
                status="ok",
            ))
            succeeded += 1
        except Exception as exc:
            items.append(TextImportResultItem(
                block_index=i,
                status="fail",
                error=str(exc),
            ))
            failed += 1

    await db.commit()
    return TextImportResponse(
        batch_id=batch_id,
        items=items,
        total=len(data.questions),
        succeeded=succeeded,
        failed=failed,
        duplicates_filtered=duplicates_filtered,
    )


@router.get("/{batch_id}/status", response_model=AdminImportTaskStatusResponse)
async def get_import_enrich_status(
    batch_id: str,
    _=Depends(require_permissions("import:read")),
):
    try:
        return await get_enrich_status(batch_id)
    except ValueError as exc:
        _raise_import_error(exc)


# ---------------------------------------------------------------------------
# 批量图片导题（多图片 → 复用现有单图 OCR/AI/审核流水线）
# ---------------------------------------------------------------------------

_BATCH_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_BATCH_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _validate_batch_image(filename: str, content: bytes, content_type: str | None) -> str | None:
    """轻量校验单张图片，返回错误原因（None 表示通过）。

    重型 PIL 解码留给 worker（ocr_image 内部会做），避免上传阶段就因单张
    损坏图片拖慢/卡住整批；这里只做扩展名 / content-type / 大小 / 非空检查。
    """
    if not filename:
        return "文件名为空"
    if not filename.lower().endswith(_BATCH_IMAGE_EXTENSIONS):
        return "仅支持 .jpg / .jpeg / .png / .webp"
    if content_type and content_type not in _BATCH_IMAGE_CONTENT_TYPES:
        return f"Content-Type 不支持: {content_type}"
    if not content:
        return "图片内容为空"
    if settings.IMAGE_IMPORT_MAX_BYTES and len(content) > settings.IMAGE_IMPORT_MAX_BYTES:
        return "图片过大"
    return None


def _cleanup_temp_sources(sources: list) -> None:
    """Best-effort cleanup of temp files for duplicate request.

    Only cleans files created during this request; never touches existing job files.
    Failure is logged but not raised.
    """
    for src in sources:
        temp_path = src.temp_path if hasattr(src, "temp_path") else None
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError as exc:
                logger.warning("Failed to cleanup temp file %s: %s", temp_path, exc)


@router.post("/batch-image/upload", response_model=BatchImageUploadResponse)
async def batch_image_upload(
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    concurrency: int | None = None,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    ocr_mode: str = Query("local", alias="ocr_mode"),
    # Idempotency / trace identifiers
    batch_id: str | None = Query(None, description="前端生成的 batch 标识"),
    image_id: str | None = Query(None, description="前端生成的 image 标识（单图）。对多图，传 image_ids[] 或自动生成派生 ID"),
    image_ids: list[str] = Query([], alias="image_ids", description="各图片 image_import_id（可选，长度与 files 一致）"),
    request_id: str | None = Query(None, description="前端生成的 request 标识（幂等键）"),
    current_admin=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """批量上传图片，逐张走现有 OCR → AI 解析 → 待审核流水线（队列模式）。

    - 并发 2~4（默认取 settings.BATCH_IMAGE_DEFAULT_CONCURRENCY），其余排队；
    - 单张失败只记录、不终止整批；
    - 返回 job_id，通过 GET /imports/batch-image/{job_id} 查询进度。
    - 支持 idempotency：request_id 重复时返回已有 job_id。
    - image_id: 向后兼容的单图模式。多图时传 image_ids[]。
    """
    from app.features import batch_image_import_service as batch_svc

    if not files:
        raise HTTPException(status_code=400, detail="未上传任何图片")
    if len(files) > settings.BATCH_IMAGE_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {settings.BATCH_IMAGE_MAX_FILES} 张图片",
        )

    # P0-3: only validate dependencies matching the requested ocr_mode
    from app.features.ocr_mode import resolve_ocr_mode, validate_ocr_mode_dependencies
    try:
        resolved_mode = resolve_ocr_mode(ocr_mode)
        validate_ocr_mode_dependencies(resolved_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # P0-4: resolve per-image IDs
    if image_ids and len(image_ids) != len(files):
        raise HTTPException(
            status_code=422,
            detail=f"image_ids 长度 ({len(image_ids)}) 与 files 长度 ({len(files)}) 不一致",
        )
    use_image_ids = bool(image_ids)
    # Warn about deprecated single-image_id with multiple files
    if image_id and len(files) > 1 and not use_image_ids:
        logger.warning(
            "Deprecated: single image_id=%s used for %d files. "
            "Each file will get a derived ID (image_id:seq). "
            "Use image_ids[] for per-file IDs.",
            image_id, len(files),
        )

    import hashlib as _hashlib

    sources: list[batch_svc.BatchImageSource] = []
    sources_with_sha: list[tuple[batch_svc.BatchImageSource, str, str]] = []
    rejected_files: list[str] = []
    seq = 0
    try:
        for idx, upload in enumerate(files):
            filename = upload.filename or f"image_{seq + 1}"
            content = await upload.read()
            reason = _validate_batch_image(upload.filename or "", content, upload.content_type)
            if reason is not None:
                rejected_files.append(f"{filename}: {reason}")
                continue

            seq += 1
            # Compute source_sha256 for content-level dedup
            source_sha256 = _hashlib.sha256(content).hexdigest()

            suffix = os.path.splitext(filename)[1] or ".png"
            fd, tmp_path = tempfile.mkstemp(prefix="batch_img_", suffix=suffix)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(content)
            except Exception:
                try:
                    os.close(fd)
                except Exception:
                    pass
                raise
            del content

            # Resolve per-image image_import_id
            if use_image_ids:
                per_image_id = image_ids[idx]
            elif image_id and len(files) == 1:
                per_image_id = image_id
            elif image_id:
                # Multi-file with single image_id: derive stable ID
                per_image_id = f"{image_id}:{seq}"
            else:
                per_image_id = f"auto_{seq}"

            source_obj = batch_svc.BatchImageSource(
                seq=seq, source_file=filename, temp_path=tmp_path,
            )
            sources.append(source_obj)
            sources_with_sha.append((source_obj, source_sha256, per_image_id))
    except Exception:
        # Clean up temp files on error
        for src in sources:
            if os.path.exists(src.temp_path):
                try:
                    os.unlink(src.temp_path)
                except OSError:
                    pass
        raise

    if not sources:
        raise HTTPException(
            status_code=400,
            detail="没有可处理的图片" + (f"（{rejected_files[0]}）" if rejected_files else ""),
        )

    concurrency = batch_svc.clamp_concurrency(concurrency)
    job_id = batch_svc.new_job_id()
    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
        "ocr_mode": ocr_mode,
    }

    # P0-4: pass per-file image_import_id + source_sha256
    per_file_image_ids = [sid[2] for sid in sources_with_sha]
    per_file_sha256 = [sid[1] for sid in sources_with_sha]
    job = await batch_svc.create_batch_job(
        db,
        job_id=job_id,
        sources=sources,
        subject=subject,
        concurrency=concurrency,
        created_by=f"admin:{current_admin.id}",
        batch_import_id=batch_id,
        image_import_id=image_id,
        request_id=request_id,
        per_file_image_ids=per_file_image_ids,
        per_file_sha256=per_file_sha256,
    )

    # Idempotency: duplicate submission returns existing job_id
    is_duplicate = job.status == "duplicate"
    if is_duplicate:
        logger.info("Duplicate batch image upload, returning existing job_id=%s", job.job_id)
        # Cleanup temp files created during THIS request (not consumed by background task)
        _cleanup_temp_sources(sources)
        return BatchImageUploadResponse(
            job_id=job.job_id,
            status="queued",
            total=0,
            rejected=0,
            rejected_files=[],
            concurrency=concurrency,
            duplicate=True,
        )

    background_tasks.add_task(
        batch_svc.run_batch_job,
        job_id=job_id,
        sources=sources,
        subject=subject,
        options=options,
        concurrency=concurrency,
    )

    return BatchImageUploadResponse(
        job_id=job_id,
        status="queued",
        total=len(sources),
        rejected=len(rejected_files),
        rejected_files=rejected_files,
        concurrency=concurrency,
        duplicate=False,
    )


@router.get("/batch-image/{job_id}", response_model=BatchImageJobStatusResponse)
async def get_batch_image_job(
    job_id: str,
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    """查询批量导题任务进度（总数/已完成/处理中/等待中 + 每张明细）。"""
    from app.features import batch_image_import_service as batch_svc

    try:
        return await batch_svc.get_batch_job_status(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/batch-image/{job_id}/stream")
async def stream_batch_image_job(
    job_id: str,
    last_event_id_query: int = Query(0, alias="lastEventId"),
    since_seq: int = Query(0, alias="since_seq"),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
    _=Depends(require_permissions("import:read")),
):
    """SSE 流：增量推送 trace events（基于自增 id），job 终态时发送 done event 后关闭。

    参数解析优先级：lastEventId query > since_seq query > Last-Event-ID header > 0
    """
    from app.core.database import async_session
    from app.features import batch_image_import_service as batch_svc

    # Parse last_event_id with priority
    since_id = last_event_id_query
    if since_id == 0 and since_seq > 0:
        since_id = since_seq
    if since_id == 0 and last_event_id_header:
        try:
            since_id = int(last_event_id_header)
        except (ValueError, TypeError):
            since_id = 0

    async def event_generator():
        last_id = since_id
        summary_last_refreshed = 0.0
        import time as _time
        while True:
            async with async_session() as db:
                events = await batch_svc.poll_trace_events(
                    db, job_id, since_id=last_id
                )
                for ev in events:
                    last_id = ev["seq"]
                    yield f"id: {ev['seq']}\nevent: trace\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

                # ── 节流：summary 最多每 5 秒刷新一次 ──
                now_s = _time.time()
                if events or (now_s - summary_last_refreshed) >= 5.0:
                    summary_last_refreshed = now_s
                    summary = await batch_svc.poll_job_summary(db, job_id)
                    # Treat completed_with_warnings as terminal state too
                    if summary and summary["status"] in ("completed", "completed_with_warnings", "failed"):
                        yield f"event: done\ndata: {json.dumps(summary, ensure_ascii=False)}\n\n"
                        return

            if not events:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1.5)
            else:
                await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/batch-image/items/{item_id}/reparse", response_model=BatchImageReparseResponse)
async def reparse_batch_image_item(
    item_id: int,
    subject: str | None = None,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """基于缓存的 OCR 文本重新解析单张图片（不重复 OCR）。"""
    from app.features import batch_image_import_service as batch_svc

    try:
        return await batch_svc.reparse_item_from_cache(db, item_id, subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# P4-7: artifact / checkpoint / cache cleanup
# ---------------------------------------------------------------------------


@router.post("/pipelines/{pipeline_id}/cleanup")
async def admin_cleanup_pipeline_artifacts(
    pipeline_id: str,
    force: bool = False,
    _=Depends(require_permissions("import:write")),
):
    """清理指定 pipeline 的 artifact 文件。

    force=True 时跳过运行中检查，直接删除。
    """
    from app.features.pipeline_artifacts import cleanup_artifacts

    removed = cleanup_artifacts(pipeline_id, force=force)
    return {
        "pipeline_id": pipeline_id,
        "artifacts_removed": removed,
        "force": force,
    }


@router.post("/cleanup/expired")
async def admin_cleanup_expired_artifacts(
    completed_ttl: int = 86400,
    failed_ttl: int = 604800,
    _=Depends(require_permissions("import:write")),
):
    """清理所有过期 artifact。

    completed_ttl: completed pipeline artifact 保留秒数（默认 24h）
    failed_ttl: failed pipeline artifact 保留秒数（默认 7d）
    """
    from app.features.pipeline_artifacts import cleanup_expired

    results = cleanup_expired(
        completed_ttl=completed_ttl,
        failed_ttl=failed_ttl,
    )
    return {
        "cleaned": results,
        "total_pipelines": len(results),
        "completed_ttl": completed_ttl,
        "failed_ttl": failed_ttl,
    }


# ---------------------------------------------------------------------------
# P7-1: Pipelines list (API-level aggregation, no DB migration)
# ---------------------------------------------------------------------------


@router.get("/pipelines")
async def list_pipelines(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    source_type: str | None = None,
    sort_by: str = "started_at",
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    """列出所有 ImportPipeline 记录，合并内存中的 quality_report。

    不新增 DB migration；quality_report 仅对近期 pipeline 可用（内存 store 有上限）。
    历史 pipeline 返回基础字段。
    """
    from app.models.import_pipeline import ImportPipeline
    from sqlalchemy import select, func, desc

    # Whitelist sort_by to avoid getattr on arbitrary model attributes
    _ALLOWED_SORT = {"started_at", "finished_at", "status", "source_type", "total_pages", "pipeline_id"}
    if sort_by not in _ALLOWED_SORT:
        sort_by = "started_at"

    query = select(ImportPipeline)
    count_query = select(func.count(ImportPipeline.pipeline_id))

    if status:
        query = query.where(ImportPipeline.status == status)
        count_query = count_query.where(ImportPipeline.status == status)
    if source_type:
        query = query.where(ImportPipeline.source_type == source_type)
        count_query = count_query.where(ImportPipeline.source_type == source_type)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Default sort: newest first
    order = desc(getattr(ImportPipeline, sort_by, ImportPipeline.started_at))
    query = query.order_by(order).offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(query)).scalars().all()

    # Merge in-memory quality_report + alerts for recent pipelines
    from app.features.pipeline_orchestrator import (
        _pipeline_store,
        _get_pipeline_diagnostics,
    )

    items = []
    for row in rows:
        item = {
            "pipeline_id": row.pipeline_id,
            "source_type": row.source_type,
            "source_file": row.source_file,
            "status": row.status,
            "total_pages": row.total_pages,
            "error_message": row.error_message,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        # Merge quality_report from in-memory store if available
        store_data = _pipeline_store.get(row.pipeline_id)
        if store_data:
            qr = store_data.get("quality_report")
            if qr:
                item["quality_report"] = qr
            alerts = store_data.get("alerts")
            if alerts:
                item["alerts"] = alerts
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# P7-3: Maintenance — unified cleanup (artifacts + OCR cache, dry-run support)
# ---------------------------------------------------------------------------


@router.post("/maintenance/cleanup")
async def admin_maintenance_cleanup(
    request: dict,
    _=Depends(require_permissions("import:write")),
):
    """执行清理任务。

    请求:
        {
            "target": "all" | "artifacts" | "ocr_cache" | "db_rows",
            "dry_run": true
        }

    - artifacts: 清理过期 pipeline artifact 文件
    - ocr_cache: 清理过期 OCR 缓存条目
    - db_rows: 当前版本暂不实现（返回 not_implemented）

    dry_run=true 时只扫描不删除。
    真实删除（dry_run=false）需要先执行 dry-run 并确认。
    """
    from app.features.pipeline_artifacts import cleanup_expired as _cleanup_artifacts
    from app.services.ocr_cache_service import cleanup_expired_entries as _cleanup_ocr_cache

    target = (request or {}).get("target", "all")
    dry_run = (request or {}).get("dry_run", True)

    results: dict[str, dict] = {}

    if target in ("all", "artifacts"):
        try:
            art_result = _cleanup_artifacts(dry_run=dry_run)
            results["artifacts"] = {
                "scanned_count": art_result.get("scanned_count", 0),
                "deleted_count": art_result.get("deleted_count", 0),
                "freed_bytes": art_result.get("freed_bytes", 0),
                "skipped_running_count": art_result.get("skipped_running_count", 0),
            }
        except Exception as exc:
            results["artifacts"] = {"error": str(exc)}

    if target in ("all", "ocr_cache"):
        try:
            cache_result = _cleanup_ocr_cache(dry_run=dry_run)
            results["ocr_cache"] = {
                "scanned_count": cache_result.get("scanned_count", 0),
                "deleted_count": cache_result.get("deleted_count", 0),
                "freed_bytes": cache_result.get("freed_bytes", 0),
                "skipped_count": cache_result.get("skipped_count", 0),
            }
        except Exception as exc:
            results["ocr_cache"] = {"error": str(exc)}

    if target in ("all", "db_rows"):
        # P7 第一版不实现 DB rows 物理删除
        results["db_rows"] = {
            "status": "not_implemented",
            "note": "DB row cleanup 需要先 dry-run 再 confirm=true，当前版本暂不实现",
        }

    return {
        "dry_run": dry_run,
        "target": target,
        "targets": results,
    }


# ---------------------------------------------------------------------------
# P7-4: Failure case export
# ---------------------------------------------------------------------------


@router.post("/questions/{import_id}/export-case")
async def admin_export_failure_case(
    import_id: int,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """导出单道失败题为 acceptance case 模板。

    expected_template 所有字段为空，必须人工填写。
    不导出完整 PDF/图片，raw_data 截断至 2000 字符。
    """
    from app.features.ocr_case_exporter import export_failure_case
    from app.models.question_import import QuestionImport
    from sqlalchemy import select

    row = (await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="导入题目不存在")

    # Convert ORM to dict (safe fields only)
    q_import = {
        "id": row.id,
        "source_file": row.source_file,
        "source_page": None,
        "subject": row.subject,
        "question_type": row.question_type,
        "raw_data": row.raw_data or {},
        "stem": None,
        "options": None,
        "answer": None,
        "analysis": None,
        "risk_flags": row.risk_flags or [],
        "failure_types": [],
    }
    # Extract parsed content fields if available
    pc = row.parsed_content or {}
    if isinstance(pc, dict):
        q_import["stem"] = pc.get("stem")
        q_import["options"] = pc.get("options")
        q_import["answer"] = pc.get("answer")
        q_import["analysis"] = pc.get("analysis")

    case = export_failure_case(q_import)
    return case


@router.post("/batches/{batch_id}/export-failure-cases")
async def admin_export_batch_failure_cases(
    batch_id: str,
    failure_type: str | None = None,
    _=Depends(require_permissions("import:write")),
    db: AsyncSession = Depends(get_db),
):
    """批量导出批次内失败题为 acceptance case 模板。

    failure_type 可选：仅导出指定失败类型的题目。
    """
    from app.features.ocr_case_exporter import export_failure_cases_batch
    from app.models.question_import import QuestionImport
    from sqlalchemy import select

    rows = (await db.execute(
        select(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
        .order_by(QuestionImport.id)
    )).scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail="批次不存在或没有题目")

    items = []
    for row in rows:
        pc = row.parsed_content if isinstance(row.parsed_content, dict) else {}
        items.append({
            "id": row.id,
            "source_file": row.source_file,
            "source_page": None,
            "subject": row.subject,
            "question_type": row.question_type,
            "raw_data": row.raw_data or {},
            "stem": pc.get("stem"),
            "options": pc.get("options"),
            "answer": pc.get("answer"),
            "analysis": pc.get("analysis"),
            "risk_flags": row.risk_flags or [],
            "failure_types": [],
        })

    cases = export_failure_cases_batch(items, failure_type_filter=failure_type)
    return {
        "batch_id": batch_id,
        "total": len(items),
        "exported": len(cases),
        "cases": cases,
    }
