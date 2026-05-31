import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("import:write")),
):
    """上传文件（Excel / PDF），解析后进入暂存区"""
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


@router.post("/pipeline/upload", response_model=PipelineUploadResponse)
async def pipeline_upload(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str | None = None,
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    _: User = Depends(require_app_permission("import:write")),
):
    """异步导入流水线：上传文件即返回 pipeline_id，后台串联 Stage 1-7。

    通过 GET /api/v1/import/pipelines/{pipeline_id} 查询进度。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    is_pdf = file.filename.endswith(".pdf")
    is_txt = file.filename.endswith(".txt")

    if not is_pdf and not is_txt:
        raise HTTPException(status_code=400, detail="仅支持 .pdf / .txt 文件")

    source_type = "pdf" if is_pdf else "txt"
    content = await file.read()

    pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    options = {
        "enable_ai_repair": enable_ai_repair,
        "confidence_threshold": confidence_threshold,
    }

    # Create a DB session for the background task
    background_tasks.add_task(
        _run_pipeline_with_db,
        pipeline_id=pipeline_id,
        file_content=content,
        source_type=source_type,
        source_file=file.filename,
        subject=subject,
        options=options,
    )

    return PipelineUploadResponse(pipeline_id=pipeline_id, status="parsing")


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
