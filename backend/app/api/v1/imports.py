from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.question_import import (
    ImportBatchDetailResponse,
    ImportBatchResponse,
    ImportQuestionUpdate,
    ImportUploadResponse,
    QuestionImportResponse,
)
from app.services import import_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/import")


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


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_file(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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
            batch_id, total = await svc.import_pdf(db, content, file.filename)
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
    _: User = Depends(get_current_user),
):
    """导入批次列表"""
    batches = await svc.list_batches(db)
    return {"items": [ImportBatchResponse(**b) for b in batches]}


@router.get("/batches/{batch_id}", response_model=ImportBatchDetailResponse)
async def batch_detail(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
):
    """审核单题：通过或拒绝"""
    if data.status == "rejected":
        await svc.reject_question(db, question_id, data.review_note)
        return {"status": "rejected"}

    try:
        q = await svc.approve_question(db, question_id, data.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "approved", "question_id": q.id}


@router.post("/batches/{batch_id}/approve", response_model=dict)
async def approve_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """批量通过一个批次"""
    try:
        count = await svc.batch_approve(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"approved_count": count}
